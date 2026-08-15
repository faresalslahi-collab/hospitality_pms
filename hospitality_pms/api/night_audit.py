"""Night Audit endpoints: the daily business-date close.

Every mutating endpoint here only enforces the DocType-level permission; the
service itself holds the real authority (`AUDITOR_ROLES` / `REOPEN_ROLES` via
`require_role`, the transition table, the blocking-exception rule). This
module never re-derives any of that.
"""

import frappe
from frappe import _

from hospitality_pms.services import night_audit as service
from hospitality_pms.services.base import (
	authorise_document,
	may_read_doctype,
	require_permission,
)
from hospitality_pms.services.property import resolve_property

AUDIT_DOCTYPE = "Night Audit"

#: Named so `_serialize` can ask whether this caller may be told the audit's
#: folio-derived money. The audit stores it; Guest Folio owns it.
FOLIO_DOCTYPE = "Guest Folio"

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
	# Step completion evidence, for the progress rail.
	#
	# Read-only stamps the service already wrote (`review`, `post_room_charges`,
	# `reconcile`) plus the two added in 16.7.6 for the steps that move no status.
	# The screen shows a step as complete only where one of these says so — it
	# used to infer completion from `audit_status`, and because a status covers
	# more than one step it ticked steps that had never run.
	#
	# Disclosure: these are timestamps and actor names on a record the caller
	# already holds `Night Audit.read` for. They carry no folio money and are not
	# gated with `FOLIO_FIGURE_FIELDS`.
	"review_completed_on",
	"no_shows_completed_on",
	"posting_completed_on",
	"due_outs_completed_on",
	"reconciliation_completed_on",
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

#: Performance ratios the Night Audit computed and owns. Ungated beyond
#: `Night Audit.read`, deliberately: the Revenue Manager's job is ADR and RevPAR
#: and they hold no Guest Folio read, so the boundary for these was drawn at
#: Night Audit on purpose (HPMS-DEC-097).
PERFORMANCE_FIELDS = (
	"currency",
	"occupancy_percentage",
	"adr",
	"revpar",
)

#: Absolute money totals. These are Guest Folio aggregates that the audit happens
#: to store, not performance metrics, and they are gated accordingly
#: (16.7.5-R1B).
#:
#: `outstanding_balance` is the reason this split exists. `_refresh_figures`
#: computes it as `sum(balance) from tabGuest Folio where folio_status not in
#: ('Settled','Closed')` - with no date filter, so it is a near-current snapshot of
#: the hotel's open receivables rather than a historical figure. The Command Center
#: was fixed to withhold exactly that number from a caller who may not read Guest
#: Folio, and this endpoint published the same one, plus `payments_received`, to
#: all twenty-three Night Audit readers. Closing one and leaving the other open
#: closes nothing.
FOLIO_FIGURE_FIELDS = (
	"room_revenue",
	"total_revenue",
	"payments_received",
	"outstanding_balance",
)


def _may_read_folio() -> bool:
	"""Whether this caller may be told the audit's folio-derived money.

	Asked once per request. The audit stores these totals; Guest Folio owns them.
	"""
	return frappe.has_permission(FOLIO_DOCTYPE, "read")


def _audit_fields_for_caller() -> list[str]:
	"""`AUDIT_FIELDS` minus the money, for a caller who may not read Guest Folio.

	Used by **both** readers of the audit record, which is the point. The first
	version of this fix gated `_serialize` and left `history` selecting the full
	field list two functions above it - and `history` takes a `limit` of up to a
	hundred audits, so it was the larger disclosure of the two. One field list,
	one question, both callers.
	"""
	if _may_read_folio():
		return list(AUDIT_FIELDS)

	return [field for field in AUDIT_FIELDS if field not in FOLIO_FIGURE_FIELDS]


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
		fields=_audit_fields_for_caller(),
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


def _exception_reference(row) -> dict:
	"""The record an audit exception points at - if the caller may read it.

	An exception's `reference` is polymorphic: a `Financial Posting Log` for a
	failed posting, a `Guest Folio` for a reconciliation variance, a `Stay` or a
	`Reservation` for an arrivals or departures anomaly. Night Audit is read by
	all twenty-three operational roles; `Financial Posting Log` by eight and
	`Guest Folio` by thirteen. So this key was handing fifteen roles the name of a
	posting log they cannot open, and ten of them the name of a folio
	(16.7.5-R1B).

	Gated per row against the DocType the row itself names, which is the shape
	`api/folio.py`'s `_charge_source` already uses for the same polymorphic
	problem. Asked per row rather than once because the DocType varies by row -
	the one case where per-row is not a mistake.

	Omitted rather than nulled. `None` already means "this exception points at
	nothing", which several exception types legitimately do, so returning it for a
	refusal would make the two indistinguishable. The screen reads neither: the
	Night Audit page renders `severity`, `type`, `is_resolved` and `description`
	and never touches `reference`, so nothing visible changes for anybody.
	"""
	if not (row.reference_doctype and row.reference_name):
		return {"reference": None}

	# `reference_doctype` is stored data, not code, and this bench has renamed
	# DocTypes before (`patches/v1_0/rename_doctypes_to_commercial_names.py`). A
	# historical row naming a DocType that no longer exists would take
	# `frappe.has_permission` into `get_meta`, which raises - and this function is
	# on the path of every Night Audit endpoint, so one stale row would have
	# turned the whole screen into a 500 for everybody, including the auditor
	# trying to close the day. An unknown DocType is treated as a refusal.
	#
	# `services.base.may_read_doctype` so this and `api/checkout.py` cannot answer
	# the same question differently. Memoised there: asked per row, over a handful
	# of distinct doctypes.
	if not may_read_doctype(row.reference_doctype):
		return {}

	return {"reference": {"doctype": row.reference_doctype, "name": row.reference_name}}


def _serialize(doc) -> dict:
	audit = {field: doc.get(field) for field in AUDIT_FIELDS}

	# The audit's money is Guest Folio's, whatever record it is stored on.
	may_read_folio = _may_read_folio()

	figures = {field: audit[field] for field in PERFORMANCE_FIELDS}

	if may_read_folio:
		figures.update({field: audit[field] for field in FOLIO_FIGURE_FIELDS})

	exceptions = [
		{
			"name": row.name,
			"type": row.exception_type,
			"severity": row.severity,
			"description": row.description,
			"is_resolved": bool(row.is_resolved),
			**_exception_reference(row),
		}
		for row in doc.audit_exceptions
	]

	blocking_count = sum(
		1 for row in doc.audit_exceptions if row.severity == service.BLOCKING and not row.is_resolved
	)

	return {
		"audit": {
			field: value
			for field, value in audit.items()
			if may_read_folio or field not in FOLIO_FIGURE_FIELDS
		},
		"exceptions": exceptions,
		"counts": {field: audit[field] for field in COUNT_FIELDS},
		"figures": figures,
		"blocking_count": blocking_count,
	}
