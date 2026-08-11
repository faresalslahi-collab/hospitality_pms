"""Night Audit endpoints: the daily business-date close.

Every mutating endpoint here only enforces the DocType-level permission; the
service itself holds the real authority (`AUDITOR_ROLES` / `REOPEN_ROLES` via
`require_role`, the transition table, the blocking-exception rule). This
module never re-derives any of that.
"""

import frappe
from frappe import _

from hospitality_pms.services import night_audit as service
from hospitality_pms.services.base import authorise_document, require_permission
from hospitality_pms.services.property import resolve_property

AUDIT_DOCTYPE = "Night Audit"

AUDIT_FIELDS = (
	"name",
	"property",
	"audit_status",
	"business_date",
	"next_business_date",
	"arrivals_expected",
	"arrivals_completed",
	"no_shows",
	"departures_expected",
	"departures_completed",
	"in_house_rooms",
	"rooms_charged",
	"charges_posted",
	"postings_failed",
	"room_revenue",
	"total_revenue",
	"payments_received",
	"outstanding_balance",
	"currency",
	"occupancy_percentage",
	"adr",
	"revpar",
	"started_on",
	"started_by",
	"closed_on",
	"closed_by",
	"reopened_on",
	"reopened_by",
	"reopen_reason",
	"notes",
)

#: Which of `AUDIT_FIELDS` the night audit screen treats as operational counts
#: versus revenue figures, so it does not have to know the split itself.
COUNT_FIELDS = (
	"arrivals_expected",
	"arrivals_completed",
	"no_shows",
	"departures_expected",
	"departures_completed",
	"in_house_rooms",
	"rooms_charged",
	"charges_posted",
	"postings_failed",
)

FIGURE_FIELDS = (
	"room_revenue",
	"total_revenue",
	"payments_received",
	"outstanding_balance",
	"currency",
	"occupancy_percentage",
	"adr",
	"revpar",
)


@frappe.whitelist(methods=["GET"])
def get_current(property: str | None = None) -> dict:
	"""The open audit for this property, or its most recently closed one.

	What the night audit screen loads. `blocking_count` is surfaced directly so
	the screen can disable Close without re-deriving the blocking-severity rule
	that `close()` itself enforces.
	"""
	require_permission(AUDIT_DOCTYPE, "read")
	property_name = resolve_property(property)

	audit_name = _current_audit_name(property_name)
	if not audit_name:
		return {
			"property": property_name,
			"audit": None,
			"exceptions": [],
			"counts": {},
			"figures": {},
			"blocking_count": 0,
		}

	return {"property": property_name, **_get_detail(audit_name)}


@frappe.whitelist(methods=["GET"])
def history(property: str | None = None, limit: int = 10) -> dict:
	"""Recent audits for the property, most recent business date first."""
	require_permission(AUDIT_DOCTYPE, "read")
	property_name = resolve_property(property)

	limit = min(int(limit or 10), 100)

	records = frappe.get_list(
		AUDIT_DOCTYPE,
		filters={"property": property_name},
		fields=list(AUDIT_FIELDS),
		order_by="business_date desc",
		limit_page_length=limit,
	)

	return {"property": property_name, "audits": records}


@frappe.whitelist(methods=["POST"])
def start(property: str | None = None, business_date: str | None = None) -> dict:
	"""Open (or resume) the audit for a business date."""
	require_permission(AUDIT_DOCTYPE, "write")
	property_name = resolve_property(property)

	audit_name = service.start(property_name, business_date)

	return {"result": audit_name, **_get_detail(audit_name)}


@frappe.whitelist(methods=["POST"])
def review(audit: str) -> dict:
	"""Rebuild the day's exceptions and figures."""
	authorise_document(AUDIT_DOCTYPE, audit, "write")

	result = service.review(audit)

	return {"result": result, **_get_detail(audit)}


@frappe.whitelist(methods=["POST"])
def resolve_exception(audit: str, row_name: str, resolution: str) -> dict:
	"""Mark one exception row as dealt with."""
	authorise_document(AUDIT_DOCTYPE, audit, "write")

	result = service.resolve_exception(audit, row_name, resolution)

	return {"result": result, **_get_detail(audit)}


@frappe.whitelist(methods=["POST"])
def mark_no_shows(audit: str) -> dict:
	"""Turn today's unresolved arrivals into no-shows."""
	authorise_document(AUDIT_DOCTYPE, audit, "write")

	result = service.mark_no_shows(audit)

	return {"result": result, **_get_detail(audit)}


@frappe.whitelist(methods=["POST"])
def post_room_charges(audit: str) -> dict:
	"""Post one night's room charge for every in-house stay."""
	authorise_document(AUDIT_DOCTYPE, audit, "write")

	result = service.post_room_charges(audit)

	return {"result": result, **_get_detail(audit)}


@frappe.whitelist(methods=["POST"])
def mark_due_outs(audit: str) -> dict:
	"""Flag tomorrow's departures for the morning shift."""
	authorise_document(AUDIT_DOCTYPE, audit, "write")

	result = service.mark_due_outs(audit)

	return {"result": result, **_get_detail(audit)}


@frappe.whitelist(methods=["POST"])
def reconcile(audit: str) -> dict:
	"""Check the subledger against ERPNext before a close is possible."""
	authorise_document(AUDIT_DOCTYPE, audit, "write")

	result = service.reconcile(audit)

	return {"result": result, **_get_detail(audit)}


@frappe.whitelist(methods=["POST"])
def close(audit: str) -> dict:
	"""Close the business date and roll the property forward."""
	authorise_document(AUDIT_DOCTYPE, audit, "write")

	result = service.close(audit)

	return {"result": result, **_get_detail(audit)}


@frappe.whitelist(methods=["POST"])
def reopen(audit: str, reason: str) -> dict:
	"""Reopen a closed business date. Manager exception only (service-enforced)."""
	authorise_document(AUDIT_DOCTYPE, audit, "write")

	result = service.reopen(audit, reason)

	return {"result": result, **_get_detail(audit)}


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _current_audit_name(property_name: str) -> str | None:
	# Prefer whatever is not yet closed - that is the audit the screen should
	# be working on. Fall back to the latest closed one so the screen still has
	# something to show a property that closed its day and moved on.
	open_audit = frappe.db.get_value(
		AUDIT_DOCTYPE,
		{"property": property_name, "audit_status": ("!=", service.CLOSED)},
		"name",
		order_by="business_date desc",
	)
	if open_audit:
		return open_audit

	return frappe.db.get_value(
		AUDIT_DOCTYPE,
		{"property": property_name},
		"name",
		order_by="business_date desc",
	)


def _get_detail(audit_name: str) -> dict:
	doc = frappe.get_doc(AUDIT_DOCTYPE, audit_name)
	doc.check_permission("read")

	return _serialize(doc)


def _serialize(doc) -> dict:
	audit = {field: doc.get(field) for field in AUDIT_FIELDS}

	exceptions = [
		{
			"name": row.name,
			"type": row.exception_type,
			"severity": row.severity,
			"description": row.description,
			"is_resolved": bool(row.is_resolved),
			"reference": {"doctype": row.reference_doctype, "name": row.reference_name}
			if row.reference_doctype and row.reference_name
			else None,
		}
		for row in doc.audit_exceptions
	]

	blocking_count = sum(
		1 for row in doc.audit_exceptions if row.severity == service.BLOCKING and not row.is_resolved
	)

	return {
		"audit": audit,
		"exceptions": exceptions,
		"counts": {field: audit[field] for field in COUNT_FIELDS},
		"figures": {field: audit[field] for field in FIGURE_FIELDS},
		"blocking_count": blocking_count,
	}
