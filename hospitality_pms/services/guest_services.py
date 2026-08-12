"""Guest requests and complaints: SLA, escalation and service recovery.

The SLA timer is server managed (SAS section 3.15). A request carries a due
time from the moment it is raised, and breach is a fact the system records
rather than something a department decides after the event.
"""

import frappe
from frappe import _
from frappe.utils import add_to_date, flt, get_datetime, now_datetime

from hospitality_pms.services.base import assert_transition, lock_document, require_role
from hospitality_pms.services.exceptions import (
	HospitalityPMSError,
	PermissionDeniedError,
	throw,
)

REQUEST_DOCTYPE = "Guest Request"
LOG_DOCTYPE = "Guest Request Log"

#: Named here so `get_board` can ask whether its caller may be told which guest a
#: request belongs to. Not imported from `services.guests`, which would make this
#: module depend on guest identity handling to load.
GUEST_DOCTYPE = "Guest"

OPEN = "Open"
ASSIGNED = "Assigned"
IN_PROGRESS = "In Progress"
COMPLETED = "Completed"
CLOSED = "Closed"
ESCALATED = "Escalated"
CANCELLED = "Cancelled"
REOPENED = "Reopened"

#: From Workflow Matrix section 9.
TRANSITIONS = {
	OPEN: {ASSIGNED, IN_PROGRESS, ESCALATED, CANCELLED},
	ASSIGNED: {IN_PROGRESS, ESCALATED, CANCELLED, OPEN},
	IN_PROGRESS: {COMPLETED, ESCALATED, CANCELLED},
	ESCALATED: {IN_PROGRESS, ASSIGNED, COMPLETED, CANCELLED},
	COMPLETED: {CLOSED, REOPENED},
	REOPENED: {ASSIGNED, IN_PROGRESS, ESCALATED, CANCELLED},
	CLOSED: {REOPENED},
	CANCELLED: set(),
}

#: Default response targets in minutes. A hotel overrides these per request,
#: but an unset SLA would mean nothing is ever late, which is worse than a
#: default that is occasionally wrong.
DEFAULT_SLA_MINUTES = {
	"Urgent": 15,
	"High": 30,
	"Normal": 120,
	"Low": 480,
}

#: Compensation costs money, so it needs the same authority as a folio
#: adjustment (Roles Matrix section 4).
RECOVERY_ROLES = (
	"Front Office Manager",
	"Guest Relations Officer",
	"Hotel Manager",
	"General Manager",
	"Finance Manager",
	"Hospitality Administrator",
	"System Manager",
)


def _assert_context_belongs(
	property_name: str,
	*,
	stay: str | None = None,
	room: str | None = None,
	reservation: str | None = None,
):
	"""Prove the records a request points at belong to the property it is raised in.

	The caller authorises the *property* - `api.guest_services.create_request`
	calls `resolve_property` - but until 16.7.4 nothing authorised the records
	named alongside it, and the insert runs with `ignore_permissions=True`, which
	switches off even Frappe's own link permission check. So a user permitted in
	one property could raise a request there while attaching another property's
	stay, room or reservation, and every screen that renders a request would then
	display that record's context to a caller with no access to it. Recorded
	against 16.7.1 and still open until now.

	The guest is deliberately **not** checked: a Guest carries no property and is
	a global master record shared across the estate - the same person stays in
	Doha this year and Dubai next - so there is nothing to compare it against.
	That is the same reasoning `services.search` and the Guest 360 workspace use.
	"""
	for doctype, name in (("Stay", stay), ("Reservation", reservation), ("Hotel Room", room)):
		if not name:
			continue

		owner = frappe.db.get_value(doctype, name, "property")

		if not owner:
			throw(_("{0} {1} does not exist.").format(_(doctype), name), exc=HospitalityPMSError)

		if owner != property_name:
			throw(
				_("{0} {1} belongs to another property.").format(_(doctype), name),
				exc=PermissionDeniedError,
			)


def create_request(
	property_name: str,
	*,
	subject: str,
	description: str,
	category: str,
	request_type: str = "Request",
	priority: str = "Normal",
	guest: str | None = None,
	stay: str | None = None,
	room: str | None = None,
	reservation: str | None = None,
	department: str | None = None,
	sla_minutes: int | None = None,
) -> str:
	"""Raise a guest request or complaint, with its SLA clock started."""
	if not subject or not description:
		throw(_("A request needs a subject and a description."), exc=HospitalityPMSError)

	_assert_context_belongs(property_name, stay=stay, room=room, reservation=reservation)

	sla = int(sla_minutes or DEFAULT_SLA_MINUTES.get(priority, 120))
	raised_at = now_datetime()

	doc = frappe.get_doc(
		{
			"doctype": REQUEST_DOCTYPE,
			"property": property_name,
			"request_status": OPEN,
			"request_type": request_type,
			"category": category,
			"priority": priority,
			"subject": subject,
			"description": description,
			"guest": guest,
			"stay": stay,
			"room": room,
			"reservation": reservation,
			"department": department,
			"sla_minutes": sla,
			"due_by": add_to_date(raised_at, minutes=sla),
		}
	).insert(ignore_permissions=True)

	_log(doc.name, property_name, None, OPEN, note=_("Request raised"))

	return doc.name


def assign(request: str, assignee: str, *, department: str | None = None) -> str:
	"""Assign the request and record the first response."""
	lock_document(REQUEST_DOCTYPE, request)
	doc = frappe.get_doc(REQUEST_DOCTYPE, request)

	_transition(doc, ASSIGNED)

	values = {"assigned_to": assignee, "assigned_on": now_datetime()}

	# The first assignment is the response, which is what an SLA measures.
	if not doc.responded_on:
		values["responded_on"] = now_datetime()

	if department:
		values["department"] = department

	frappe.db.set_value(REQUEST_DOCTYPE, request, values, update_modified=True)

	return request


def start(request: str) -> str:
	lock_document(REQUEST_DOCTYPE, request)
	doc = frappe.get_doc(REQUEST_DOCTYPE, request)

	_transition(doc, IN_PROGRESS)

	if not doc.responded_on:
		frappe.db.set_value(REQUEST_DOCTYPE, request, "responded_on", now_datetime(), update_modified=False)

	return request


def complete(request: str, resolution: str, *, guest_satisfied: bool | None = None) -> dict:
	"""Complete a request and stamp whether the SLA held."""
	if not resolution or not resolution.strip():
		throw(_("A resolution is required to complete a request."), exc=HospitalityPMSError)

	lock_document(REQUEST_DOCTYPE, request)
	doc = frappe.get_doc(REQUEST_DOCTYPE, request)

	_transition(doc, COMPLETED)

	completed_on = now_datetime()
	breached = bool(doc.due_by and get_datetime(doc.due_by) < completed_on)

	frappe.db.set_value(
		REQUEST_DOCTYPE,
		request,
		{
			"resolution": resolution.strip(),
			"completed_on": completed_on,
			"is_breached": 1 if breached else 0,
			"guest_satisfied": 1 if guest_satisfied else 0,
		},
		update_modified=True,
	)

	return {"request": request, "breached": breached}


def escalate(request: str, *, escalate_to: str | None = None, reason: str | None = None) -> dict:
	"""Escalate a request, raising its level by one.

	Called by staff and by the scheduled SLA sweep. The level rises each time,
	so a request that keeps missing its target keeps climbing rather than
	sitting escalated at the same place forever.
	"""
	lock_document(REQUEST_DOCTYPE, request)
	doc = frappe.get_doc(REQUEST_DOCTYPE, request)

	if doc.request_status in (COMPLETED, CLOSED, CANCELLED):
		return {"request": request, "escalated": False, "reason": _("Already resolved.")}

	_transition(doc, ESCALATED)

	frappe.db.set_value(
		REQUEST_DOCTYPE,
		request,
		{
			"escalated_on": now_datetime(),
			"escalated_to": escalate_to,
			"escalation_reason": reason or _("SLA target passed"),
			"escalation_level": int(doc.escalation_level or 0) + 1,
		},
		update_modified=True,
	)

	return {"request": request, "escalated": True, "level": int(doc.escalation_level or 0) + 1}


def reopen(request: str, reason: str) -> str:
	"""Reopen a completed request the guest is not satisfied with."""
	if not reason or not reason.strip():
		throw(_("A reason is required to reopen a request."), exc=HospitalityPMSError)

	lock_document(REQUEST_DOCTYPE, request)
	doc = frappe.get_doc(REQUEST_DOCTYPE, request)

	_transition(doc, REOPENED)

	frappe.db.set_value(
		REQUEST_DOCTYPE,
		request,
		{"reopened_count": int(doc.reopened_count or 0) + 1, "guest_satisfied": 0},
		update_modified=True,
	)

	return request


def close(request: str) -> str:
	lock_document(REQUEST_DOCTYPE, request)
	doc = frappe.get_doc(REQUEST_DOCTYPE, request)

	_transition(doc, CLOSED)

	return request


def apply_service_recovery(
	request: str,
	recovery_type: str,
	*,
	amount: float = 0,
	reason: str,
	post_to_folio: bool = True,
) -> dict:
	"""Compensate a guest, and post it to their folio when it costs money.

	The folio charge goes through FolioService with a key derived from the
	request, so approving the same recovery twice does not discount the guest
	twice.
	"""
	require_role(RECOVERY_ROLES)

	if not reason or not reason.strip():
		throw(_("A reason is required for service recovery."), exc=HospitalityPMSError)

	lock_document(REQUEST_DOCTYPE, request)
	doc = frappe.get_doc(REQUEST_DOCTYPE, request)

	charge_row = None

	if post_to_folio and flt(amount) > 0:
		from hospitality_pms.services import folio as folio_service

		folio = None
		if doc.stay:
			folio = folio_service.get_folio_for_stay(doc.stay)

		if not folio:
			throw(
				_("This request has no folio to post the compensation to."),
				exc=HospitalityPMSError,
			)

		result = folio_service.post_charge(
			folio,
			"Discount",
			_("Service recovery for request {0}: {1}").format(request, recovery_type),
			flt(amount),
			idempotency_key=f"service-recovery:{request}",
		)
		charge_row = result["row"]

	frappe.db.set_value(
		REQUEST_DOCTYPE,
		request,
		{
			"requires_service_recovery": 1,
			"recovery_type": recovery_type,
			"recovery_amount": flt(amount),
			"recovery_approved_by": frappe.session.user,
			"recovery_folio_charge": charge_row,
		},
		update_modified=True,
	)

	_log(request, doc.property, doc.request_status, doc.request_status, note=_("Service recovery: {0}").format(reason.strip()))

	return {"request": request, "recovery_type": recovery_type, "folio_charge": charge_row}


def sweep_sla(property_name: str) -> dict:
	"""Escalate everything past its due time. Run by the scheduler.

	Idempotent in effect: a request already escalated at this level is skipped,
	so running the sweep every few minutes does not inflate escalation levels.
	"""
	now = now_datetime()

	overdue = frappe.get_all(
		REQUEST_DOCTYPE,
		filters={
			"property": property_name,
			"request_status": ("in", (OPEN, ASSIGNED, IN_PROGRESS, REOPENED)),
			"due_by": ("<", now),
		},
		fields=["name", "escalation_level"],
		limit_page_length=0,
	)

	escalated = []
	for row in overdue:
		result = escalate(row["name"], reason=_("SLA target passed"))
		if result.get("escalated"):
			escalated.append(row["name"])

	return {"property": property_name, "checked": len(overdue), "escalated": escalated}


def _transition(doc, target: str):
	if doc.request_status == target:
		return target

	assert_transition(doc.request_status, target, TRANSITIONS, _("Guest request"))

	previous = doc.request_status

	frappe.db.set_value(REQUEST_DOCTYPE, doc.name, "request_status", target, update_modified=False)
	doc.request_status = target

	_log(doc.name, doc.property, previous, target)

	return target


def _log(request: str, property_name: str, from_status: str | None, to_status: str, note: str | None = None):
	frappe.get_doc(
		{
			"doctype": LOG_DOCTYPE,
			"property": property_name,
			"guest_request": request,
			"from_status": from_status,
			"to_status": to_status,
			"changed_by": frappe.session.user,
			"changed_at": now_datetime(),
			"note": note,
		}
	).insert(ignore_permissions=True)


def get_board(property_name: str, *, include_closed: bool = False) -> dict:
	"""The guest services board."""
	filters = {"property": property_name}

	if not include_closed:
		filters["request_status"] = ("not in", (CLOSED, CANCELLED))

	requests = frappe.get_all(
		REQUEST_DOCTYPE,
		filters=filters,
		fields=[
			"name",
			"subject",
			"request_type",
			"request_status",
			"category",
			"priority",
			"room",
			"guest",
			"assigned_to",
			"due_by",
			"is_breached",
			"escalation_level",
		],
		order_by="priority desc, due_by asc",
		limit_page_length=0,
	)

	# The board carries a Guest identifier, and `frappe.get_all` above applies no
	# permission at all - not the DocType's, not permlevel, not user permissions.
	# Guest Request is read by every operational role in the estate and ten of them
	# cannot read Guest, so the board was handing a stable guest key to roles that
	# can resolve it nowhere (16.7.5-R1B; the same rule `kitchen.py` applies to the
	# guest, stay and folio on a room-service order).
	#
	# Popped, not blanked: an empty `guest` would read as "nobody's request".
	#
	# Asked once for the whole board rather than per row - the answer cannot differ
	# between rows of one response - and it adds no query, because
	# `frappe.has_permission` is answered from the request's cached role set.
	#
	# Done here rather than at the endpoint because this function *is* the board's
	# assembly, and `frappe.get_all`'s permission-free read is what needs covering.
	if not frappe.has_permission(GUEST_DOCTYPE, "read"):
		for row in requests:
			row.pop("guest", None)

	now = now_datetime()

	return {
		"property": property_name,
		"requests": requests,
		"summary": {
			"open": sum(1 for r in requests if r["request_status"] == OPEN),
			"in_progress": sum(1 for r in requests if r["request_status"] == IN_PROGRESS),
			"escalated": sum(1 for r in requests if r["request_status"] == ESCALATED),
			"overdue": sum(1 for r in requests if r["due_by"] and get_datetime(r["due_by"]) < now),
			"complaints": sum(1 for r in requests if r["request_type"] == "Complaint"),
		},
	}
