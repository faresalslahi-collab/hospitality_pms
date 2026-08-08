"""Night Audit: close the business date.

The Night Audit is the daily reconciliation that makes a PMS trustworthy. It
posts the day's room charges, resolves what the shift left open, checks that
the operational subledger agrees with ERPNext, and then moves the property's
business date forward.

The rule that matters most: **daily posting is idempotent** (SAS section 3.10).
Room charges post under `room-charge:{stay}:{business_date}`, so re-running an
audit for a date that already posted charges nothing again. That is what makes
the audit safe to retry after a crash, which is exactly when it is most likely
to be retried.

The business date only moves through `close`, and `close` is the only caller
permitted to set the property's business date at all (see PropertyService's
`BUSINESS_DATE_FLAG`).
"""

import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate, now_datetime

from hospitality_pms.services import folio as folio_service
from hospitality_pms.services import posting as posting_service
from hospitality_pms.services import reservations as reservation_service
from hospitality_pms.services import rooms as room_service
from hospitality_pms.services import stays as stay_service
from hospitality_pms.services.base import assert_transition, lock_document, require_role
from hospitality_pms.services.exceptions import NightAuditError, throw
from hospitality_pms.services.property import BUSINESS_DATE_FLAG, get_business_date, get_property

AUDIT_DOCTYPE = "Hospitality Night Audit"

OPEN = "Open"
REVIEWING = "Reviewing"
POSTING = "Posting"
READY_TO_CLOSE = "Ready to Close"
CLOSED = "Closed"

#: Night Audit state machine, from Workflow Matrix section 7.
TRANSITIONS = {
	OPEN: {REVIEWING},
	# Ready to Close is reachable straight from Reviewing: a day with nothing
	# left to post should not have to pass through Posting to be closable.
	REVIEWING: {POSTING, REVIEWING, READY_TO_CLOSE},
	POSTING: {READY_TO_CLOSE, REVIEWING},
	# An auditor who finds a missed charge at the last moment must be able to
	# go back and post it rather than close the day knowingly short.
	READY_TO_CLOSE: {CLOSED, REVIEWING, POSTING},
	CLOSED: {REVIEWING},
}

AUDITOR_ROLES = (
	"Night Auditor",
	"Hotel Manager",
	"General Manager",
	"Hospitality Administrator",
	"System Manager",
)

#: Reopening a closed business date is a manager exception (Workflow Matrix
#: section 7): it re-opens a day the hotel has already reported on.
REOPEN_ROLES = (
	"Hotel Manager",
	"General Manager",
	"Finance Manager",
	"Hospitality Administrator",
	"System Manager",
)

BLOCKING = "Blocking"


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def start(property_name: str, business_date=None) -> str:
	"""Open the audit for a business date.

	Returns the existing audit if one is already open for that date, so two
	auditors starting at once work on the same record instead of two.
	"""
	require_role(AUDITOR_ROLES)

	business_date = getdate(business_date or get_business_date(property_name))

	existing = frappe.db.get_value(
		AUDIT_DOCTYPE,
		{"property": property_name, "business_date": business_date},
		["name", "audit_status"],
		as_dict=True,
	)

	if existing:
		if existing["audit_status"] == CLOSED:
			throw(
				_("The business date {0} is already closed.").format(business_date),
				exc=NightAuditError,
			)
		return existing["name"]

	doc = frappe.get_doc(
		{
			"doctype": AUDIT_DOCTYPE,
			"property": property_name,
			"business_date": business_date,
			"next_business_date": add_days(business_date, 1),
			"audit_status": OPEN,
			"started_on": now_datetime(),
			"started_by": frappe.session.user,
		}
	).insert(ignore_permissions=True)

	return doc.name


def review(audit: str) -> dict:
	"""Gather the day's exceptions and figures.

	Read-and-record only: nothing is posted and no state is forced. Running
	review twice is safe and is expected while the auditor clears exceptions.
	"""
	require_role(AUDITOR_ROLES)

	lock_document(AUDIT_DOCTYPE, audit)
	doc = frappe.get_doc(AUDIT_DOCTYPE, audit)

	if doc.audit_status == CLOSED:
		throw(_("This audit is closed."), exc=NightAuditError)

	if doc.audit_status == OPEN:
		_transition(doc, REVIEWING)

	business_date = getdate(doc.business_date)

	# Exceptions are rebuilt each review so a resolved one disappears rather
	# than lingering as a stale blocker.
	doc.set("audit_exceptions", [])

	unresolved = reservation_service.get_unresolved_arrivals(doc.property, business_date)
	for row in unresolved:
		doc.append(
			"audit_exceptions",
			{
				"exception_type": "Unresolved Arrival",
				"reference_doctype": reservation_service.RESERVATION_DOCTYPE,
				"reference_name": row["name"],
				"description": _("{0} was due to arrive on {1} and has not checked in.").format(
					row["guest_name"] or row["name"], row["arrival_date"]
				),
				"severity": BLOCKING,
			},
		)

	overdue = frappe.get_all(
		stay_service.STAY_DOCTYPE,
		filters={
			"property": doc.property,
			"stay_status": ("in", (stay_service.IN_HOUSE, stay_service.DUE_OUT)),
			"departure_date": ("<=", business_date),
		},
		fields=["name", "guest_name", "room", "departure_date"],
	)
	for row in overdue:
		doc.append(
			"audit_exceptions",
			{
				"exception_type": "Unsettled Departure",
				"reference_doctype": stay_service.STAY_DOCTYPE,
				"reference_name": row["name"],
				"description": _("{0} in room {1} was due to depart on {2} and is still in house.").format(
					row["guest_name"], row["room"], row["departure_date"]
				),
				"severity": "Warning",
			},
		)

	failed = posting_service.get_failed_postings(doc.property, limit=50)
	for row in failed:
		doc.append(
			"audit_exceptions",
			{
				"exception_type": "Failed Posting",
				"reference_doctype": posting_service.POSTING_LOG,
				"reference_name": row["name"],
				"description": _("{0} posting failed after {1} attempt(s).").format(
					row["posting_type"], row["attempts"]
				),
				"severity": BLOCKING,
			},
		)

	_refresh_figures(doc, business_date)
	doc.save(ignore_permissions=True)

	return {
		"audit": audit,
		"business_date": str(business_date),
		"exceptions": len(doc.audit_exceptions),
		"blocking": sum(1 for row in doc.audit_exceptions if row.severity == BLOCKING and not row.is_resolved),
	}


def resolve_exception(audit: str, row_name: str, resolution: str) -> str:
	"""Mark one exception as dealt with, with a note saying how."""
	require_role(AUDITOR_ROLES)

	if not resolution or not resolution.strip():
		throw(_("A resolution note is required."), exc=NightAuditError)

	doc = frappe.get_doc(AUDIT_DOCTYPE, audit)
	row = next((line for line in doc.audit_exceptions if line.name == row_name), None)

	if not row:
		throw(_("Exception {0} does not belong to this audit.").format(row_name), exc=NightAuditError)

	row.is_resolved = 1
	row.resolution = resolution.strip()
	row.resolved_by = frappe.session.user
	row.resolved_on = now_datetime()

	doc.save(ignore_permissions=True)

	return row_name


def mark_no_shows(audit: str) -> list[str]:
	"""Turn unresolved arrivals into no-shows.

	Deliberately a separate, explicit step rather than part of review: a
	no-show applies a charge under the guest's policy, and the auditor should
	choose to do it.
	"""
	require_role(AUDITOR_ROLES)

	doc = frappe.get_doc(AUDIT_DOCTYPE, audit)
	marked = []

	for row in reservation_service.get_unresolved_arrivals(doc.property, doc.business_date):
		reservation_service.mark_no_show(row["name"], reason=_("Night Audit {0}").format(audit))
		marked.append(row["name"])

	frappe.db.set_value(AUDIT_DOCTYPE, audit, "no_shows", len(marked), update_modified=False)

	return marked


def post_room_charges(audit: str) -> dict:
	"""Post one night's room charge for every in-house stay.

	Idempotent per stay per business date. A stay departing on the business
	date does not consume that night, which is why the query lives in
	StayService alongside the same night arithmetic availability uses.
	"""
	require_role(AUDITOR_ROLES)

	lock_document(AUDIT_DOCTYPE, audit)
	doc = frappe.get_doc(AUDIT_DOCTYPE, audit)

	if doc.audit_status == CLOSED:
		throw(_("This audit is closed."), exc=NightAuditError)

	_transition(doc, POSTING)

	business_date = getdate(doc.business_date)
	posted = 0
	skipped = 0
	failed = []
	revenue = 0.0

	for stay in stay_service.get_stays_for_room_charge(doc.property, business_date):
		if not stay["folio"]:
			failed.append({"stay": stay["name"], "error": "no folio"})
			continue

		try:
			result = folio_service.post_charge(
				stay["folio"],
				"Room Charge",
				_("Room {0} on {1}").format(stay["room"], business_date),
				flt(stay["room_rate"]),
				idempotency_key=f"room-charge:{stay['name']}:{business_date}",
				business_date=business_date,
				charge_date=business_date,
				reference_doctype=stay_service.STAY_DOCTYPE,
				reference_name=stay["name"],
			)

			if result.get("duplicate"):
				skipped += 1
			else:
				posted += 1
				revenue += flt(result.get("total_amount") or result.get("amount"))
		except Exception as exc:  # noqa: BLE001
			failed.append({"stay": stay["name"], "error": str(exc)[:200]})

	frappe.db.set_value(
		AUDIT_DOCTYPE,
		audit,
		{
			"charges_posted": posted,
			"rooms_charged": posted + skipped,
			"postings_failed": len(failed),
			"room_revenue": flt(revenue, 2),
		},
		update_modified=True,
	)

	return {
		"audit": audit,
		"posted": posted,
		"already_posted": skipped,
		"failed": failed,
	}


def mark_due_outs(audit: str) -> list[str]:
	"""Flag tomorrow's departures so the morning shift sees them."""
	doc = frappe.get_doc(AUDIT_DOCTYPE, audit)

	return stay_service.mark_due_out(doc.property, add_days(getdate(doc.business_date), 1))


def reconcile(audit: str) -> dict:
	"""Check the subledger against ERPNext before allowing a close."""
	require_role(AUDITOR_ROLES)

	lock_document(AUDIT_DOCTYPE, audit)
	doc = frappe.get_doc(AUDIT_DOCTYPE, audit)

	_refresh_figures(doc, getdate(doc.business_date))

	variances = []
	for folio in frappe.get_all(
		folio_service.FOLIO_DOCTYPE,
		filters={"property": doc.property, "folio_status": ("in", (folio_service.SETTLED, folio_service.CLOSED))},
		pluck="name",
		limit=200,
	):
		result = posting_service.reconcile_folio(folio)
		if not result["is_reconciled"]:
			variances.append(result)

	for variance in variances:
		doc.append(
			"audit_exceptions",
			{
				"exception_type": "Unposted Charge",
				"reference_doctype": folio_service.FOLIO_DOCTYPE,
				"reference_name": variance["folio"],
				"description": _("Folio {0} differs from ERPNext by {1}.").format(
					variance["folio"], variance["charge_variance"]
				),
				"severity": BLOCKING,
			},
		)

	if not _blocking_exceptions(doc):
		_transition(doc, READY_TO_CLOSE)

	doc.save(ignore_permissions=True)

	return {
		"audit": audit,
		"variances": len(variances),
		"blocking": len(_blocking_exceptions(doc)),
		"audit_status": doc.audit_status,
	}


def close(audit: str) -> dict:
	"""Close the business date and roll the property forward.

	This is the only place the property's business date moves. It refuses while
	any blocking exception is unresolved, because closing over an unresolved
	exception is how a hotel loses a day's revenue quietly.
	"""
	require_role(AUDITOR_ROLES)

	lock_document(AUDIT_DOCTYPE, audit)
	doc = frappe.get_doc(AUDIT_DOCTYPE, audit)

	blocking = _blocking_exceptions(doc)
	if blocking:
		throw(
			_("{0} blocking exception(s) must be resolved before the business date can close.").format(
				len(blocking)
			),
			exc=NightAuditError,
		)

	if doc.audit_status != READY_TO_CLOSE:
		_transition(doc, READY_TO_CLOSE)

	business_date = getdate(doc.business_date)
	next_date = add_days(business_date, 1)

	property_doc = frappe.get_doc("Hospitality Property", doc.property)

	if getdate(property_doc.business_date) != business_date:
		throw(
			_("The property's business date is {0}, but this audit closes {1}.").format(
				property_doc.business_date, business_date
			),
			exc=NightAuditError,
		)

	property_doc.business_date = next_date
	frappe.flags[BUSINESS_DATE_FLAG] = True
	try:
		property_doc.save(ignore_permissions=True)
	finally:
		frappe.flags[BUSINESS_DATE_FLAG] = False

	_transition(doc, CLOSED)

	frappe.db.set_value(
		AUDIT_DOCTYPE,
		audit,
		{
			"closed_on": now_datetime(),
			"closed_by": frappe.session.user,
			"next_business_date": next_date,
		},
		update_modified=True,
	)

	return {
		"audit": audit,
		"closed_business_date": str(business_date),
		"new_business_date": str(next_date),
	}


def reopen(audit: str, reason: str) -> dict:
	"""Reopen a closed business date. Manager exception only."""
	require_role(REOPEN_ROLES)

	if not reason or not reason.strip():
		throw(_("A reason is required to reopen a closed business date."), exc=NightAuditError)

	lock_document(AUDIT_DOCTYPE, audit)
	doc = frappe.get_doc(AUDIT_DOCTYPE, audit)

	if doc.audit_status != CLOSED:
		throw(_("Audit {0} is not closed.").format(audit), exc=NightAuditError)

	property_doc = frappe.get_doc("Hospitality Property", doc.property)
	property_doc.business_date = getdate(doc.business_date)

	frappe.flags[BUSINESS_DATE_FLAG] = True
	try:
		property_doc.save(ignore_permissions=True)
	finally:
		frappe.flags[BUSINESS_DATE_FLAG] = False

	_transition(doc, REVIEWING)

	frappe.db.set_value(
		AUDIT_DOCTYPE,
		audit,
		{
			"reopened_on": now_datetime(),
			"reopened_by": frappe.session.user,
			"reopen_reason": reason.strip(),
		},
		update_modified=True,
	)

	return {"audit": audit, "business_date": str(doc.business_date), "reason": reason.strip()}


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _transition(doc, target: str):
	# Re-running a step that is already in progress is normal - an auditor
	# posts charges, fixes something, posts again - so staying put is a no-op
	# rather than an error.
	if doc.audit_status == target:
		return target

	assert_transition(doc.audit_status, target, TRANSITIONS, _("Night Audit"))

	# `update_modified=False` because the caller usually saves this same
	# in-memory document afterwards; bumping `modified` here would make that
	# save fail with a timestamp mismatch.
	frappe.db.set_value(AUDIT_DOCTYPE, doc.name, "audit_status", target, update_modified=False)
	doc.audit_status = target

	return target


def _blocking_exceptions(doc) -> list:
	return [row for row in doc.audit_exceptions if row.severity == BLOCKING and not row.is_resolved]


def _refresh_figures(doc, business_date):
	"""Recompute the day's operational and revenue statistics."""
	property_name = doc.property

	arrivals = reservation_service.get_arrivals(property_name, business_date)
	departures = reservation_service.get_departures(property_name, business_date)
	in_house = stay_service.get_in_house(property_name)

	sellable = frappe.db.count("Hotel Room", {"property": property_name, "is_active": 1})
	occupied = len(in_house)

	room_revenue = flt(doc.room_revenue)

	payments = frappe.db.sql(
		"""
		select coalesce(sum(p.amount), 0)
		from `tabHospitality Folio Payment` p
		inner join `tabHospitality Guest Folio` f on f.name = p.parent
		where f.property = %(property)s and p.business_date = %(date)s
		""",
		{"property": property_name, "date": business_date},
	)[0][0]

	outstanding = frappe.db.sql(
		"""
		select coalesce(sum(balance), 0)
		from `tabHospitality Guest Folio`
		where property = %(property)s and folio_status not in ('Settled', 'Closed')
		""",
		{"property": property_name},
	)[0][0]

	doc.arrivals_expected = len(arrivals)
	doc.arrivals_completed = frappe.db.count(
		stay_service.STAY_DOCTYPE,
		{"property": property_name, "arrival_date": business_date, "stay_status": ("!=", "Expected")},
	)
	doc.departures_expected = len(departures)
	doc.departures_completed = frappe.db.count(
		stay_service.STAY_DOCTYPE,
		{"property": property_name, "departure_date": business_date, "stay_status": "Checked Out"},
	)
	doc.in_house_rooms = occupied
	doc.payments_received = flt(payments, 2)
	doc.outstanding_balance = flt(outstanding, 2)
	doc.total_revenue = flt(room_revenue, 2)

	# The standard hospitality metrics. ADR is revenue per occupied room;
	# RevPAR is revenue per available room, which is why a hotel can have a
	# high ADR and poor RevPAR at the same time.
	doc.occupancy_percentage = flt((occupied / sellable * 100) if sellable else 0, 2)
	doc.adr = flt((room_revenue / occupied) if occupied else 0, 2)
	doc.revpar = flt((room_revenue / sellable) if sellable else 0, 2)


def run_full_audit(property_name: str, business_date=None) -> dict:
	"""Convenience path: review, post, reconcile.

	Stops short of closing on purpose. A human decides that the day is done -
	an automated close would defeat the exception list.
	"""
	audit = start(property_name, business_date)

	review(audit)
	posting = post_room_charges(audit)
	mark_due_outs(audit)
	reconciliation = reconcile(audit)

	return {
		"audit": audit,
		"posting": posting,
		"reconciliation": reconciliation,
		"audit_status": frappe.db.get_value(AUDIT_DOCTYPE, audit, "audit_status"),
	}
