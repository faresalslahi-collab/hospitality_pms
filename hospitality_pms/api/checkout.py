"""Checkout, ERP posting and reconciliation endpoints."""

import frappe

from hospitality_pms.services import checkout as service
from hospitality_pms.services import posting as posting_service
from hospitality_pms.services.base import require_permission, require_role
from hospitality_pms.services.property import resolve_property

STAY_DOCTYPE = "Hospitality Stay"
FOLIO_DOCTYPE = "Hospitality Guest Folio"

RECONCILIATION_ROLES = (
	"Finance Manager",
	"Accounts User",
	"Night Auditor",
	"Hotel Manager",
	"General Manager",
	"Hospitality Administrator",
	"System Manager",
)


@frappe.whitelist(methods=["GET"])
def summary(stay: str) -> dict:
	"""What the guest owes and anything blocking departure."""
	require_permission(STAY_DOCTYPE, "read")

	return service.get_checkout_summary(stay)


@frappe.whitelist(methods=["POST"])
def check_out(
	stay: str,
	post_to_erp: int = 1,
	allow_open_balance: int = 0,
	reason: str | None = None,
) -> dict:
	"""Settle, post and release the room."""
	require_permission(STAY_DOCTYPE, "write")

	return service.check_out(
		stay,
		post_to_erp=bool(int(post_to_erp or 0)),
		allow_open_balance=bool(int(allow_open_balance or 0)),
		reason=reason,
	)


@frappe.whitelist(methods=["POST"])
def reverse_checkout(stay: str, reason: str) -> dict:
	"""Undo a checkout. Requires front office and finance authority."""
	require_permission(STAY_DOCTYPE, "write")

	return service.reverse_checkout(stay, reason)


@frappe.whitelist(methods=["GET"])
def reconciliation(property: str | None = None) -> dict:
	"""Failed postings and folios that do not agree with ERPNext."""
	require_role(RECONCILIATION_ROLES)
	property_name = resolve_property(property)

	failed = posting_service.get_failed_postings(property_name)

	# Folios that closed with charges never posted are the ones finance most
	# needs to see: the guest has gone and the revenue is not in the ledger.
	unposted = frappe.db.sql(
		"""
		select distinct f.name, f.guest_name, f.folio_status, f.total_charges, f.balance
		from `tabHospitality Guest Folio` f
		inner join `tabHospitality Folio Charge` c on c.parent = f.name
		where f.property = %(property)s
		  and f.folio_status in ('Settled', 'Closed')
		  and ifnull(c.is_posted_to_erp, 0) = 0
		order by f.modified desc
		limit 100
		""",
		{"property": property_name},
		as_dict=True,
	)

	return {
		"property": property_name,
		"failed_postings": failed,
		"closed_folios_with_unposted_charges": unposted,
	}


@frappe.whitelist(methods=["GET"])
def reconcile_folio(folio: str) -> dict:
	"""Compare one folio against what actually reached ERPNext."""
	require_role(RECONCILIATION_ROLES)

	return posting_service.reconcile_folio(folio)


@frappe.whitelist(methods=["POST"])
def retry_posting(log: str) -> dict:
	"""Retry a failed posting under its original idempotency key."""
	require_role(RECONCILIATION_ROLES)

	return posting_service.retry_posting(log)


@frappe.whitelist(methods=["POST"])
def post_folio(folio: str) -> dict:
	"""Post a folio's invoice and payments without checking the guest out.

	Used by the Night Audit and by finance catching up a folio that failed to
	post at checkout.
	"""
	require_role(RECONCILIATION_ROLES)
	require_permission(FOLIO_DOCTYPE, "write")

	return service._post_to_erp(folio)
