"""Guest folio endpoints.

Every mutating endpoint takes an idempotency key from the caller, or derives a
deterministic one, so a retried request cannot post twice (HPMS-DEC-031).
"""

import frappe
from frappe import _

from hospitality_pms.services import folio as service
from hospitality_pms.services.base import require_permission

FOLIO_DOCTYPE = "Hospitality Guest Folio"


@frappe.whitelist(methods=["GET"])
def get_folio(folio: str) -> dict:
	"""One folio with its charges, payments and balance."""
	require_permission(FOLIO_DOCTYPE, "read")

	doc = frappe.get_doc(FOLIO_DOCTYPE, folio)
	doc.check_permission("read")

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
	quantity: float = 1,
	tax_amount: float = 0,
	payer: str = "Guest",
	idempotency_key: str | None = None,
) -> dict:
	"""Post a charge.

	When the caller supplies no key one is generated, which makes a retry of
	this exact HTTP request post twice. Clients that can retry must send their
	own stable key.
	"""
	require_permission(FOLIO_DOCTYPE, "write")

	return service.post_charge(
		folio,
		charge_type,
		description,
		float(amount),
		quantity=float(quantity or 1),
		tax_amount=float(tax_amount or 0),
		payer=payer,
		idempotency_key=idempotency_key or f"manual:{folio}:{frappe.generate_hash(length=12)}",
	)


@frappe.whitelist(methods=["POST"])
def post_payment(
	folio: str,
	amount: float,
	payment_method: str,
	payment_type: str = "Payment",
	reference: str | None = None,
	payer: str = "Guest",
	idempotency_key: str | None = None,
) -> dict:
	require_permission(FOLIO_DOCTYPE, "write")

	return service.post_payment(
		folio,
		float(amount),
		payment_method,
		payment_type=payment_type,
		reference=reference,
		payer=payer,
		idempotency_key=idempotency_key or f"manual:{folio}:{frappe.generate_hash(length=12)}",
	)


@frappe.whitelist(methods=["POST"])
def reverse_charge(folio: str, charge_row: str, reason: str) -> dict:
	"""Reverse a charge. Finance authority and a reason are enforced by the service."""
	require_permission(FOLIO_DOCTYPE, "write")

	service.reverse_charge(folio, charge_row, reason)

	return get_folio(folio)


@frappe.whitelist(methods=["POST"])
def post_adjustment(folio: str, amount: float, description: str, reason: str, payer: str = "Guest") -> dict:
	require_permission(FOLIO_DOCTYPE, "write")

	service.post_adjustment(folio, float(amount), description, reason, payer=payer)

	return get_folio(folio)


@frappe.whitelist(methods=["POST"])
def split_folio(folio: str, charge_rows: list | str, payer: str = "Company") -> dict:
	"""Move selected charges onto a new folio for company-pay separation."""
	require_permission(FOLIO_DOCTYPE, "write")

	rows = frappe.parse_json(charge_rows) if isinstance(charge_rows, str) else list(charge_rows)

	if not rows:
		frappe.throw(_("Select at least one charge to move."))

	target = service.split_folio(folio, rows, payer=payer)

	return {"source": get_folio(folio), "target": get_folio(target)}


@frappe.whitelist(methods=["POST"])
def transition(folio: str, target: str, reason: str | None = None) -> dict:
	require_permission(FOLIO_DOCTYPE, "write")

	service.transition(folio, target, reason=reason)

	return get_folio(folio)
