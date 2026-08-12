"""Checkout, ERP posting and reconciliation endpoints."""

import frappe

from hospitality_pms.services import checkout as service
from hospitality_pms.services import finance_messages
from hospitality_pms.services import posting as posting_service
from hospitality_pms.services.base import authorise_document, require_role
from hospitality_pms.services.property import resolve_property

STAY_DOCTYPE = "Stay"
FOLIO_DOCTYPE = "Guest Folio"

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
	authorise_document(STAY_DOCTYPE, stay, "read")

	return service.get_checkout_summary(stay)


@frappe.whitelist(methods=["POST"])
def check_out(
	stay: str,
	post_to_erp: int = 1,
	allow_open_balance: int = 0,
	reason: str | None = None,
) -> dict:
	"""Settle, post and release the room."""
	authorise_document(STAY_DOCTYPE, stay, "write")

	return service.check_out(
		stay,
		post_to_erp=bool(int(post_to_erp or 0)),
		allow_open_balance=bool(int(allow_open_balance or 0)),
		reason=reason,
	)


@frappe.whitelist(methods=["POST"])
def reverse_checkout(stay: str, reason: str) -> dict:
	"""Undo a checkout. Requires front office and finance authority."""
	authorise_document(STAY_DOCTYPE, stay, "write")

	return service.reverse_checkout(stay, reason)


@frappe.whitelist(methods=["GET"])
def reconciliation(property: str | None = None) -> dict:
	"""Failed postings and folios that do not agree with ERPNext."""
	require_role(RECONCILIATION_ROLES)
	property_name = resolve_property(property)

	# Projected, never published raw. `get_failed_postings` returns the
	# `Financial Posting Log`'s `error_message` and the durable ledger's
	# `last_error` - both truncated `str(exc)` - and this endpoint used to hand
	# them to a browser. Its own shape is fixed by its test and by what Night
	# Audit reads, so it is projected here rather than narrowed there.
	failed = finance_messages.safe_failed_postings(
		posting_service.get_failed_postings(property_name)
	)

	unposted = posting_service.closed_folios_with_unposted_charges(property_name)

	return {
		"property": property_name,
		"failed_postings": failed,
		"closed_folios_with_unposted_charges": unposted,
	}


@frappe.whitelist(methods=["GET"])
def reconcile_folio(folio: str) -> dict:
	"""Compare one folio against what actually reached ERPNext."""
	require_role(RECONCILIATION_ROLES)
	authorise_document(FOLIO_DOCTYPE, folio, "read")

	return posting_service.reconcile_folio(folio)


@frappe.whitelist(methods=["POST"])
def retry_posting(log: str) -> dict:
	"""Retry a failed posting under its original idempotency key."""
	require_role(RECONCILIATION_ROLES)
	authorise_document(posting_service.POSTING_LOG, log, "read")

	return posting_service.retry_posting(log)


@frappe.whitelist(methods=["POST"])
def post_folio(folio: str) -> dict:
	"""Post a folio's invoice and payments without checking the guest out.

	Used by the Night Audit and by finance catching up a folio that failed to
	post at checkout.
	"""
	require_role(RECONCILIATION_ROLES)
	authorise_document(FOLIO_DOCTYPE, folio, "write")

	return service._post_to_erp(folio)
