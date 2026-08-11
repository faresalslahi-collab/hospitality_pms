"""Guest folio endpoints.

Every mutating endpoint takes an operation key from the caller and refuses the
request without one (HPMS-DEC-031, P2-3).

The key identifies the *user action*, not the HTTP attempt. The client mints it
once when the operator submits, resends it unchanged on every retry of that
submission, and mints a new one only when the operator starts something else.
The server never invents one: a key generated per request is regenerated on
retry, which is precisely how a lost response became a second charge.
"""

import frappe
from frappe import _

from hospitality_pms.services import folio as service
from hospitality_pms.services.base import authorise_document, require_operation_key

FOLIO_DOCTYPE = "Guest Folio"


@frappe.whitelist(methods=["GET"])
def get_folio(folio: str) -> dict:
	"""One folio with its charges, payments and balance."""
	doc = authorise_document(FOLIO_DOCTYPE, folio, "read")

	return {
		"folio": {
			"name": doc.name,
			"folio_status": doc.folio_status,
			"folio_type": doc.folio_type,
			"guest": doc.guest,
			"guest_name": doc.guest_name,
			"stay": doc.stay,
			"reservation": doc.reservation,
			"room": doc.room,
			"currency": doc.currency,
			"total_charges": doc.total_charges,
			"total_taxes": doc.total_taxes,
			"total_payments": doc.total_payments,
			"total_adjustments": doc.total_adjustments,
			"balance": doc.balance,
			"billing_instructions": doc.billing_instructions,
		},
		"charges": [
			{
				"name": row.name,
				"charge_date": row.charge_date,
				"business_date": row.business_date,
				"charge_type": row.charge_type,
				"description": row.description,
				"quantity": row.quantity,
				"amount": row.amount,
				"tax_amount": row.tax_amount,
				"total_amount": row.total_amount,
				"payer": row.payer,
				"is_reversed": row.is_reversed,
				"reversal_of": row.reversal_of,
			}
			for row in doc.charges
		],
		"payments": [
			{
				"name": row.name,
				"payment_date": row.payment_date,
				"payment_type": row.payment_type,
				"payment_method": row.payment_method,
				"amount": row.amount,
				"reference": row.reference,
				"payer": row.payer,
			}
			for row in doc.payments
		],
		"allowed_transitions": sorted(service.TRANSITIONS.get(doc.folio_status, set())),
	}


@frappe.whitelist(methods=["POST"])
def post_charge(
	folio: str,
	charge_type: str,
	description: str,
	amount: float,
	idempotency_key: str,
	quantity: float = 1,
	tax_amount: float = 0,
	payer: str = "Guest",
) -> dict:
	"""Post a charge, once per operation key however many times it is sent."""
	authorise_document(FOLIO_DOCTYPE, folio, "write")

	return service.post_charge(
		folio,
		charge_type,
		description,
		float(amount),
		quantity=float(quantity or 1),
		tax_amount=float(tax_amount or 0),
		payer=payer,
		idempotency_key=require_operation_key(idempotency_key, "Posting a charge"),
	)


@frappe.whitelist(methods=["POST"])
def post_payment(
	folio: str,
	amount: float,
	payment_method: str,
	idempotency_key: str,
	payment_type: str = "Payment",
	reference: str | None = None,
	payer: str = "Guest",
) -> dict:
	authorise_document(FOLIO_DOCTYPE, folio, "write")

	return service.post_payment(
		folio,
		float(amount),
		payment_method,
		payment_type=payment_type,
		reference=reference,
		payer=payer,
		idempotency_key=require_operation_key(idempotency_key, "Recording a payment"),
	)


@frappe.whitelist(methods=["POST"])
def reverse_charge(folio: str, charge_row: str, reason: str) -> dict:
	"""Reverse a charge. Finance authority and a reason are enforced by the service."""
	authorise_document(FOLIO_DOCTYPE, folio, "write")

	service.reverse_charge(folio, charge_row, reason)

	return get_folio(folio)


@frappe.whitelist(methods=["POST"])
def post_adjustment(
	folio: str, amount: float, description: str, reason: str, idempotency_key: str, payer: str = "Guest"
) -> dict:
	authorise_document(FOLIO_DOCTYPE, folio, "write")

	service.post_adjustment(
		folio,
		float(amount),
		description,
		reason,
		payer=payer,
		idempotency_key=require_operation_key(idempotency_key, "Posting an adjustment"),
	)

	return get_folio(folio)


@frappe.whitelist(methods=["POST"])
def split_folio(folio: str, charge_rows: list | str, payer: str = "Company") -> dict:
	"""Move selected charges onto a new folio for company-pay separation."""
	authorise_document(FOLIO_DOCTYPE, folio, "write")

	rows = frappe.parse_json(charge_rows) if isinstance(charge_rows, str) else list(charge_rows)

	if not rows:
		frappe.throw(_("Select at least one charge to move."))

	target = service.split_folio(folio, rows, payer=payer)

	return {"source": get_folio(folio), "target": get_folio(target)}


@frappe.whitelist(methods=["POST"])
def transition(folio: str, target: str, reason: str | None = None) -> dict:
	authorise_document(FOLIO_DOCTYPE, folio, "write")

	service.transition(folio, target, reason=reason)

	return get_folio(folio)
