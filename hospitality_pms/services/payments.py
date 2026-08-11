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
from hospitality_pms.integrations.payments.base import PaymentResult
from hospitality_pms.services import durability
from hospitality_pms.services import folio as folio_service
from hospitality_pms.services.base import lock_and_find, lock_and_read, lock_document
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

	# The provider call sits behind the durable ledger, so the record of having
	# contacted them survives the rollback that follows a failure. Before, the
	# Payment Transaction's Failed state and the queue row were both written in
	# this transaction and both vanished with it, leaving no evidence the
	# gateway had ever been asked for anything (P1-13).
	durable = durability.run_durably(
		property_name=folio_doc.property,
		integration_type="Payment",
		operation="initiate_payment",
		operation_key=idempotency_key,
		provider=config,
		reference_doctype=TRANSACTION_DOCTYPE,
		reference_name=transaction.name,
		payload={"folio": folio, "amount": amount, "transaction": transaction.name},
		call=lambda: adapter.initiate_payment(
			amount,
			folio_doc.currency,
			idempotency_key,
			reference=transaction.name,
			description=description or _("Folio {0}").format(folio),
			return_url=return_url,
			metadata={"folio": folio, "transaction": transaction.name},
		),
		reference_of=lambda result: result.provider_reference,
	)

	if not durable.performed:
		# Already initiated at the gateway under this key on an earlier attempt.
		return {
			"name": transaction.name,
			"transaction_status": "Pending",
			"payment_url": None,
			"provider_reference": durable.external_reference,
			"duplicate": True,
		}

	result = durable.result

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

	# The status was read by the lookup above, before the lock. A replayed
	# callback that waited behind the original would otherwise still see the
	# pre-lock status and apply the payment a second time, so the duplicate
	# guard is re-evaluated against the locked, current row (N1).
	transaction["transaction_status"] = lock_and_read(
		TRANSACTION_DOCTYPE, transaction["name"], "transaction_status"
	)["transaction_status"]

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
	"""Refund all or part of a captured transaction.

	The order of operations here is the whole of the fix for P1-12, and it is
	the reverse of what it was:

	    read current state under the lock
	    -> claim the funds, durably, in this transaction
	    -> only then call the provider

	It used to read the transaction *before* locking it, validate the
	refundable balance against that pre-lock snapshot, and call the provider
	before changing anything. Two concurrent refunds therefore both saw
	`refunded_amount = 0`, both believed the whole capture was available, and
	the provider refunded 200 against a 100 capture - with the loser's
	transaction then failing on an unrelated conflict, so the second 100 left
	the merchant account with no record here at all.

	Because the claim is written while the row lock is held, a second caller
	blocks at `lock_and_read` below, and by the time it is let through it reads
	the *claimed* balance and is refused before it can reach the provider.

	The other half of the problem has nothing to do with concurrency: the
	provider refunds, and the request then fails. Everything local rolls back -
	the claim, the balance, the failure record - and the next attempt sees a
	fully refundable transaction and refunds it again. That is closed by
	routing the provider call through the durable operation ledger, which is
	committed on a connection of its own and therefore still says "this refund
	reached the provider" after the rollback has taken everything else.
	"""
	if not reason or not reason.strip():
		throw(_("A reason is required to refund a payment."), exc=IntegrationError)

	amount = flt(amount)

	if amount <= 0:
		throw(_("A refund amount must be greater than zero."), exc=IntegrationError)

	key = idempotency_key or f"refund:{transaction}:{flt(amount, 2)}"

	# --- current state, under the lock ----------------------------------
	current = lock_and_read(
		TRANSACTION_DOCTYPE,
		transaction,
		["transaction_status", "amount", "refunded_amount", "property", "provider", "provider_reference", "folio"],
	)

	# --- has this operation already been performed? ---------------------
	# A locking read, so a claim another transaction committed while this one
	# waited is visible. A plain read here would answer from the pre-lock
	# snapshot and let the same key reach the provider twice.
	claimed = lock_and_find(
		TRANSACTION_DOCTYPE, {"idempotency_key": key}, ["name", "amount", "transaction_status"]
	)

	if claimed:
		return {
			"transaction": transaction,
			"refund_transaction": claimed["name"],
			"refunded_amount": flt(current["refunded_amount"]),
			"reason": reason.strip(),
			"duplicate": True,
		}

	if current["transaction_status"] not in SETTLED_STATES:
		throw(
			_("Transaction {0} is {1} and cannot be refunded.").format(
				transaction, _(current["transaction_status"])
			),
			exc=IntegrationError,
		)

	refundable = flt(current["amount"]) - flt(current["refunded_amount"])

	if amount > refundable + 0.005:
		throw(
			_("Refund amount must be between 0 and {0}.").format(flt(refundable, 2)),
			exc=IntegrationError,
		)

	# --- claim the funds before spending them ---------------------------
	refunded = flt(current["refunded_amount"]) + amount

	refund_transaction = _claim_refund(transaction, current, amount, key)

	frappe.db.set_value(
		TRANSACTION_DOCTYPE,
		transaction,
		{
			"refunded_amount": refunded,
			"transaction_status": "Refunded"
			if refunded >= flt(current["amount"]) - 0.005
			else "Partially Refunded",
		},
		update_modified=True,
	)

	# --- and only now, the provider, behind a durable record -------------
	adapter = get_provider(current["property"], current["provider"])

	durable = durability.run_durably(
		property_name=current["property"],
		integration_type="Payment",
		operation="refund_payment",
		operation_key=key,
		provider=current["provider"],
		reference_doctype=TRANSACTION_DOCTYPE,
		reference_name=transaction,
		payload={"transaction": transaction, "amount": amount, "reason": reason.strip()},
		call=lambda: adapter.refund(
			current["provider_reference"], amount, key, reason=reason.strip()
		),
		reference_of=lambda result: result.provider_reference,
	)

	if durable.performed:
		result = durable.result
	else:
		# The ledger says this refund already reached the provider on an
		# earlier attempt whose transaction then died. The money has moved;
		# what is missing is the local record of it. Rebuilding that - rather
		# than asking the provider again - is the whole point of the ledger.
		result = PaymentResult(
			success=True,
			status="Refunded",
			provider_reference=durable.external_reference,
			amount=amount,
			provider_status="recovered",
		)

	frappe.db.set_value(
		TRANSACTION_DOCTYPE,
		refund_transaction,
		{
			"transaction_status": result.status,
			"provider_reference": result.provider_reference,
			"provider_status": result.provider_status,
			"completed_on": now_datetime(),
			"response_payload": json.dumps(result.raw, default=str),
		},
		update_modified=True,
	)

	frappe.db.set_value(
		TRANSACTION_DOCTYPE, transaction, "provider_status", result.provider_status, update_modified=False
	)

	if current["folio"]:
		folio_service.post_payment(
			current["folio"],
			amount,
			"Online Gateway",
			payment_type="Refund",
			idempotency_key=f"gateway-refund:{key}",
			reference=transaction,
			provider_reference=result.provider_reference,
		)

	return {
		"transaction": transaction,
		"refund_transaction": refund_transaction,
		"refunded_amount": refunded,
		"reason": reason.strip(),
		"duplicate": False,
	}


def _claim_refund(transaction: str, current: dict, amount: float, key: str) -> str:
	"""Record the intent to refund, before the provider is asked to do it.

	A Payment Transaction of type Refund, which the model already provides for.
	Its `idempotency_key` column is unique, so the claim is enforced by the
	database and not only by the check above - two callers that somehow got
	past the lock could still not both create it.

	It is written before the provider call so that the row exists, and the
	funds are visibly spoken for, at the moment the external side effect
	happens rather than after it.
	"""
	doc = frappe.get_doc(
		{
			"doctype": TRANSACTION_DOCTYPE,
			"property": current["property"],
			"provider": current["provider"],
			"transaction_status": "Initiated",
			"transaction_type": "Refund",
			"idempotency_key": key,
			"folio": current["folio"],
			"amount": amount,
			"initiated_on": now_datetime(),
			"request_payload": json.dumps({"refund_of": transaction, "amount": amount}, default=str),
		}
	).insert(ignore_permissions=True)

	return doc.name


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
	"""Park work that needs a human, durably.

	The only caller left is the unmatched callback: a provider told us about a
	transaction this system has no record of, which nothing can safely retry
	its way out of. It is recorded for reconciliation rather than for retry.
	"""
	durability.begin_operation(
		property_name=property_name,
		integration_type="Payment",
		operation=operation,
		operation_key=f"{operation}:{idempotency_key}",
		payload=payload,
	)
	durability.flag_for_reconciliation(f"{operation}:{idempotency_key}", error=error)


def reconcile_operation(operation_key: str) -> dict:
	"""Establish what the provider actually did, and finish the job locally.

	The way out of `Needs Reconciliation`. An operation lands there when the
	answer was lost, and the one thing that must not happen next is issuing it
	again - so the provider is *asked*, never re-instructed.

	Three answers:

	* the provider has a record of it - the money moved, so the ledger is
	  resolved and local state is rebuilt to match;
	* the provider has no record - it never arrived, so the operation becomes
	  ordinarily retryable again;
	* the adapter cannot be asked - it stays where it is, waiting for someone
	  to look at the provider's dashboard. Guessing here is how a guest gets
	  refunded twice.
	"""
	record = durability.get_operation(operation_key)

	if not record:
		throw(_("No durable operation is recorded under {0}.").format(operation_key), exc=IntegrationError)

	if record["queue_status"] != durability.NEEDS_RECONCILIATION:
		return {"operation": operation_key, "status": record["queue_status"], "reconciled": False}

	adapter = get_provider(record["property"], record["provider"])

	if not adapter.supports_idempotent_replay:
		return {
			"operation": operation_key,
			"status": durability.NEEDS_RECONCILIATION,
			"reconciled": False,
			"reason": _("This provider cannot be queried; reconcile it by hand."),
		}

	outcome = adapter.get_operation_status(operation_key)

	if outcome is None:
		# It never reached them, so nothing happened and the ordinary retry
		# path is safe again.
		durability.fail_operation(
			operation_key,
			error=_("The provider has no record of this operation; it never arrived."),
			retry_in_minutes=0,
		)

		return {"operation": operation_key, "status": durability.RETRYING, "reconciled": True, "applied": False}

	durability.complete_operation(operation_key, external_reference=outcome.provider_reference)

	_rebuild_local_state(record)

	return {"operation": operation_key, "status": durability.RESOLVED, "reconciled": True, "applied": True}


def _rebuild_local_state(record: dict):
	"""Bring the PMS into line with an operation the provider did perform.

	Re-enters the ordinary service call. It cannot repeat the side effect: the
	ledger is Resolved by now, so `run_durably` reports the operation as
	already performed and the service takes its repair path instead of calling
	the provider.
	"""
	payload = durability.get_operation_payload(record)

	if record["operation"] == "refund_payment" and payload.get("transaction"):
		refund_payment(
			payload["transaction"],
			flt(payload.get("amount")),
			payload.get("reason") or _("Reconciled from provider"),
			idempotency_key=record["operation_key"],
		)


def retry_failed(property_name: str, limit: int = 20) -> list[dict]:
	"""Work the durable operation ledger. Called by the scheduler.

	Kept here as the scheduler's entry point; the dispatch itself lives in
	`services.retry`, which knows which operations may be re-run automatically
	and which must not.
	"""
	from hospitality_pms.services.retry import retry_due_operations

	return retry_due_operations(property_name, limit=limit)
