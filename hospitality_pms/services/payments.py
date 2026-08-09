"""Payment orchestration across providers.

The provider adapters know how to talk to Fatora or Stripe. This module knows
what a payment *means*: which folio it belongs to, when it becomes money the
hotel has received, and how to make sure a replayed callback does not credit
the guest twice.

Callback safety
---------------
Gateways retry callbacks. They deliver out of order. They occasionally deliver
a callback for a transaction the hotel never saw succeed. All three are handled
the same way: the transaction is looked up by the provider's own reference,
the folio payment is posted under a key derived from the transaction, and
`FolioService.post_payment` refuses the second attempt.
"""

import json

import frappe
from frappe import _
from frappe.utils import flt, now_datetime

from hospitality_pms.integrations.payments import get_provider, get_provider_config
from hospitality_pms.services import folio as folio_service
from hospitality_pms.services.base import lock_document
from hospitality_pms.services.exceptions import IntegrationError, throw

TRANSACTION_DOCTYPE = "Payment Transaction"
FAILURE_QUEUE = "PMS Integration Failure Queue"

#: Transaction states in which the money is the hotel's and belongs on the folio.
SETTLED_STATES = ("Captured",)

#: States from which nothing further will happen.
TERMINAL_STATES = ("Captured", "Failed", "Cancelled", "Refunded")


def initiate_payment(
	folio: str,
	amount: float,
	*,
	idempotency_key: str,
	provider: str | None = None,
	description: str | None = None,
	return_url: str | None = None,
) -> dict:
	"""Start a payment against a folio.

	Returns the transaction and, for hosted-checkout providers, the URL the
	guest is sent to. Replaying the same key returns the original transaction
	rather than charging the guest again.
	"""
	if not idempotency_key:
		throw(_("An idempotency key is required to initiate a payment."), exc=IntegrationError)

	amount = flt(amount)
	if amount <= 0:
		throw(_("A payment amount must be greater than zero."), exc=IntegrationError)

	existing = frappe.db.get_value(
		TRANSACTION_DOCTYPE,
		{"idempotency_key": idempotency_key},
		["name", "transaction_status", "payment_url", "provider_reference"],
		as_dict=True,
	)

	if existing:
		return {**existing, "duplicate": True}

	folio_doc = frappe.get_doc(folio_service.FOLIO_DOCTYPE, folio)
	config = get_provider_config(folio_doc.property, provider)

	transaction = frappe.get_doc(
		{
			"doctype": TRANSACTION_DOCTYPE,
			"property": folio_doc.property,
			"provider": config,
			"transaction_status": "Initiated",
			"transaction_type": "Payment",
			"idempotency_key": idempotency_key,
			"folio": folio,
			"reservation": folio_doc.reservation,
			"guest": folio_doc.guest,
			"amount": amount,
			"initiated_on": now_datetime(),
		}
	).insert(ignore_permissions=True)

	adapter = get_provider(folio_doc.property, config)

	try:
		result = adapter.initiate_payment(
			amount,
			folio_doc.currency,
			idempotency_key,
			reference=transaction.name,
			description=description or _("Folio {0}").format(folio),
			return_url=return_url,
			metadata={"folio": folio, "transaction": transaction.name},
		)
	except Exception as exc:  # noqa: BLE001
		_fail_transaction(transaction.name, str(exc))
		_queue_failure(
			folio_doc.property,
			"initiate_payment",
			idempotency_key,
			{"folio": folio, "amount": amount, "transaction": transaction.name},
			str(exc),
		)
		raise

	frappe.db.set_value(
		TRANSACTION_DOCTYPE,
		transaction.name,
		{
			"transaction_status": result.status,
			"provider_reference": result.provider_reference,
			"provider_status": result.provider_status,
			"payment_url": result.payment_url,
			"request_payload": json.dumps({"amount": amount, "currency": folio_doc.currency}, default=str),
			"response_payload": json.dumps(result.raw, default=str),
		},
		update_modified=True,
	)

	# A provider that captures immediately (a manual desk payment) is money in
	# hand, so it lands on the folio now rather than waiting for a callback.
	if result.status in SETTLED_STATES:
		_apply_to_folio(transaction.name)

	return {
		"name": transaction.name,
		"transaction_status": result.status,
		"payment_url": result.payment_url,
		"provider_reference": result.provider_reference,
		"duplicate": False,
	}


def handle_callback(
	property_name: str, provider: str, payload: dict, headers: dict, raw_body: bytes | None = None
) -> dict:
	"""Process an inbound provider callback.

	The signature is verified before anything is read from the payload. An
	unverified callback is refused outright: accepting one would let anyone
	mark a folio as paid.
	"""
	adapter = get_provider(property_name, provider)

	normalised = adapter.verify_callback(payload, headers, raw_body)

	reference = normalised.get("provider_reference")
	if not reference:
		throw(_("The callback carried no provider reference."), exc=IntegrationError)

	transaction = frappe.db.get_value(
		TRANSACTION_DOCTYPE,
		{"provider_reference": reference},
		["name", "transaction_status", "folio", "amount"],
		as_dict=True,
	)

	if not transaction:
		# A callback for a transaction this system never created is not an
		# error to swallow: it is queued so someone reconciles it.
		_queue_failure(
			property_name,
			"unmatched_callback",
			normalised.get("idempotency_key") or reference,
			normalised,
			"No matching payment transaction",
		)
		return {"matched": False, "provider_reference": reference}

	lock_document(TRANSACTION_DOCTYPE, transaction["name"])

	if transaction["transaction_status"] in TERMINAL_STATES:
		# A replayed callback for a transaction already in its final state.
		return {
			"matched": True,
			"transaction": transaction["name"],
			"transaction_status": transaction["transaction_status"],
			"duplicate": True,
		}

	status = normalised.get("status") or "Pending"

	frappe.db.set_value(
		TRANSACTION_DOCTYPE,
		transaction["name"],
		{
			"transaction_status": status,
			"provider_status": normalised.get("provider_status"),
			"response_payload": json.dumps(normalised, default=str),
			"completed_on": now_datetime() if status in TERMINAL_STATES else None,
			"failure_reason": normalised.get("failure_reason"),
		},
		update_modified=True,
	)

	applied = None
	if status in SETTLED_STATES:
		applied = _apply_to_folio(transaction["name"])

	return {
		"matched": True,
		"transaction": transaction["name"],
		"transaction_status": status,
		"folio_payment": applied,
		"duplicate": False,
	}


def _apply_to_folio(transaction: str) -> str | None:
	"""Post a captured transaction onto its folio, exactly once.

	The folio key is derived from the transaction name, so however many times
	this is reached - immediate capture, callback, status sync - the guest is
	credited once.
	"""
	doc = frappe.get_doc(TRANSACTION_DOCTYPE, transaction)

	if not doc.folio:
		return None

	result = folio_service.post_payment(
		doc.folio,
		flt(doc.amount),
		"Online Gateway",
		payment_type="Refund" if doc.transaction_type == "Refund" else "Payment",
		idempotency_key=f"gateway:{transaction}",
		reference=doc.name,
		provider_reference=doc.provider_reference,
	)

	frappe.db.set_value(
		TRANSACTION_DOCTYPE,
		transaction,
		{"folio_payment_row": result["row"], "completed_on": now_datetime()},
		update_modified=False,
	)

	return result["row"]


def sync_status(transaction: str) -> dict:
	"""Ask the provider what really happened.

	The reconciliation path for a lost callback. The provider is the authority
	on its own transaction, so whatever it says wins.
	"""
	doc = frappe.get_doc(TRANSACTION_DOCTYPE, transaction)

	if not doc.provider_reference:
		throw(_("Transaction {0} has no provider reference to query.").format(transaction), exc=IntegrationError)

	adapter = get_provider(doc.property, doc.provider)
	result = adapter.get_status(doc.provider_reference)

	lock_document(TRANSACTION_DOCTYPE, transaction)

	frappe.db.set_value(
		TRANSACTION_DOCTYPE,
		transaction,
		{
			"transaction_status": result.status,
			"provider_status": result.provider_status,
			"response_payload": json.dumps(result.raw, default=str),
		},
		update_modified=True,
	)

	applied = None
	if result.status in SETTLED_STATES:
		applied = _apply_to_folio(transaction)

	return {"transaction": transaction, "transaction_status": result.status, "folio_payment": applied}


def refund_payment(transaction: str, amount: float, reason: str, *, idempotency_key: str | None = None) -> dict:
	"""Refund all or part of a captured transaction."""
	if not reason or not reason.strip():
		throw(_("A reason is required to refund a payment."), exc=IntegrationError)

	doc = frappe.get_doc(TRANSACTION_DOCTYPE, transaction)

	if doc.transaction_status not in SETTLED_STATES:
		throw(
			_("Transaction {0} is {1} and cannot be refunded.").format(transaction, _(doc.transaction_status)),
			exc=IntegrationError,
		)

	amount = flt(amount)
	refundable = flt(doc.amount) - flt(doc.refunded_amount)

	if amount <= 0 or amount > refundable + 0.005:
		throw(
			_("Refund amount must be between 0 and {0}.").format(flt(refundable, 2)),
			exc=IntegrationError,
		)

	key = idempotency_key or f"refund:{transaction}:{flt(amount, 2)}"

	lock_document(TRANSACTION_DOCTYPE, transaction)

	adapter = get_provider(doc.property, doc.provider)
	result = adapter.refund(doc.provider_reference, amount, key, reason=reason.strip())

	refunded = flt(doc.refunded_amount) + amount

	frappe.db.set_value(
		TRANSACTION_DOCTYPE,
		transaction,
		{
			"refunded_amount": refunded,
			"transaction_status": "Refunded" if refunded >= flt(doc.amount) - 0.005 else "Partially Refunded",
			"provider_status": result.provider_status,
		},
		update_modified=True,
	)

	if doc.folio:
		folio_service.post_payment(
			doc.folio,
			amount,
			"Online Gateway",
			payment_type="Refund",
			idempotency_key=f"gateway-refund:{key}",
			reference=transaction,
			provider_reference=result.provider_reference,
		)

	return {"transaction": transaction, "refunded_amount": refunded, "reason": reason.strip()}


# ---------------------------------------------------------------------------
# Failure queue
# ---------------------------------------------------------------------------


def _fail_transaction(transaction: str, error: str):
	frappe.db.set_value(
		TRANSACTION_DOCTYPE,
		transaction,
		{"transaction_status": "Failed", "failure_reason": error[:500], "completed_on": now_datetime()},
		update_modified=True,
	)


def _queue_failure(
	property_name: str, operation: str, idempotency_key: str, payload: dict, error: str
):
	"""Park failed integration work for retry rather than losing it.

	Written in its own transaction-independent way: the caller usually re-raises
	straight after, and the queue entry has to survive that.
	"""
	frappe.get_doc(
		{
			"doctype": FAILURE_QUEUE,
			"property": property_name,
			"integration_type": "Payment",
			"operation": operation,
			"idempotency_key": idempotency_key,
			"payload": json.dumps(payload, default=str),
			"queue_status": "Pending",
			"attempts": 0,
			"last_error": error[:2000],
			"next_attempt_on": frappe.utils.add_to_date(now_datetime(), minutes=5),
		}
	).insert(ignore_permissions=True)


def retry_failed(property_name: str, limit: int = 20) -> list[dict]:
	"""Work the failure queue. Called by the scheduler."""
	due = frappe.get_all(
		FAILURE_QUEUE,
		filters={
			"property": property_name,
			"queue_status": ("in", ("Pending", "Retrying")),
			"next_attempt_on": ("<=", now_datetime()),
		},
		fields=["name", "operation", "idempotency_key", "payload", "attempts", "max_attempts"],
		limit=limit,
	)

	results = []

	for entry in due:
		attempts = int(entry["attempts"] or 0) + 1

		if attempts > int(entry["max_attempts"] or 5):
			frappe.db.set_value(FAILURE_QUEUE, entry["name"], "queue_status", "Abandoned")
			results.append({"entry": entry["name"], "status": "Abandoned"})
			continue

		# Backoff grows with each attempt so a provider outage is not hammered.
		frappe.db.set_value(
			FAILURE_QUEUE,
			entry["name"],
			{
				"attempts": attempts,
				"queue_status": "Retrying",
				"next_attempt_on": frappe.utils.add_to_date(now_datetime(), minutes=5 * (2 ** (attempts - 1))),
			},
			update_modified=True,
		)

		results.append({"entry": entry["name"], "status": "Retrying", "attempts": attempts})

	return results
