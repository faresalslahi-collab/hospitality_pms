"""Payment endpoints, including the provider webhook.

The webhook is the only guest-facing entry point in the app. It is deliberately
narrow: it verifies the provider's signature before reading anything, and it
never trusts an amount or a status that has not been signed.
"""

import frappe
from frappe import _

from hospitality_pms.services import payments as service
from hospitality_pms.services.base import (
	authorise_document,
	require_operation_key,
	require_role,
)

FOLIO_DOCTYPE = "Guest Folio"
TRANSACTION_DOCTYPE = "Payment Transaction"

REFUND_ROLES = (
	"Finance Manager",
	"Front Office Manager",
	"Hotel Manager",
	"General Manager",
	"Hospitality Administrator",
	"System Manager",
)


@frappe.whitelist(methods=["POST"])
def initiate(
	folio: str,
	amount: float,
	idempotency_key: str,
	provider: str | None = None,
	description: str | None = None,
	return_url: str | None = None,
) -> dict:
	"""Start a gateway payment against a folio.

	The operation key is the caller's, and required: a key minted here would be
	new on every retry, which for a gateway payment means charging the guest's
	card a second time (P2-3).
	"""
	authorise_document(FOLIO_DOCTYPE, folio, "write")

	return service.initiate_payment(
		folio,
		float(amount),
		idempotency_key=require_operation_key(idempotency_key, "Starting a payment"),
		provider=provider,
		description=description,
		return_url=return_url,
	)


@frappe.whitelist(methods=["GET"])
def get_transaction(transaction: str) -> dict:
	doc = authorise_document(TRANSACTION_DOCTYPE, transaction, "read")

	return {
		"name": doc.name,
		"transaction_status": doc.transaction_status,
		"transaction_type": doc.transaction_type,
		"amount": doc.amount,
		"refunded_amount": doc.refunded_amount,
		"currency": doc.currency,
		"provider_reference": doc.provider_reference,
		"payment_url": doc.payment_url,
		"folio": doc.folio,
		"failure_reason": doc.failure_reason,
	}


@frappe.whitelist(methods=["POST"])
def sync_status(transaction: str) -> dict:
	"""Ask the provider what happened. The reconciliation path for a lost callback."""
	authorise_document(TRANSACTION_DOCTYPE, transaction, "write")

	return service.sync_status(transaction)


@frappe.whitelist(methods=["POST"])
def refund(transaction: str, amount: float, reason: str) -> dict:
	require_role(REFUND_ROLES)
	authorise_document(TRANSACTION_DOCTYPE, transaction, "write")

	return service.refund_payment(transaction, float(amount), reason)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def webhook(property: str, provider: str) -> dict:
	"""Inbound provider callback.

	`allow_guest` because the gateway has no Frappe session. Authentication is
	the provider's signature over the payload, checked by the adapter before
	any field is read - see `PaymentProvider.verify_callback`. An unsigned or
	mis-signed callback raises and nothing is written.
	"""
	# The raw bytes are what the provider signed. They must reach the adapter
	# unmodified: re-encoding the parsed dict changes key order and separators,
	# and every signature check would fail.
	raw_body = frappe.request.get_data() or b""
	payload = frappe.request.get_json(silent=True) or {}
	headers = dict(frappe.request.headers or {})

	if not payload:
		frappe.throw(_("Empty callback payload."), frappe.ValidationError)

	# Guest context cannot resolve a property, so it is named in the URL the
	# provider was configured with and validated here.
	if not frappe.db.exists("Property", property):
		frappe.throw(_("Unknown property."), frappe.DoesNotExistError)

	return service.handle_callback(property, provider, payload, headers, raw_body)
