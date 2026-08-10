"""Housekeeping: cleaning tasks, inspection and room release.

The flow this implements is the one in SAS section 3.11:

    Checkout -> Vacant Dirty -> task -> In Progress -> Cleaning Complete
             -> Inspection (if required) -> Vacant Clean/Inspected -> Available

The task and the room's housekeeping dimension move together, always through
`RoomStatusService`, so the room rack and the housekeeping board can never
disagree about whether a room is clean.
"""

import frappe
from frappe import _
from frappe.utils import getdate, now_datetime

from hospitality_pms.services import rooms as room_service
from hospitality_pms.services.base import assert_transition, lock_document, require_role
from hospitality_pms.services.exceptions import HospitalityPMSError, throw
from hospitality_pms.services.property import get_business_date

TASK_DOCTYPE = "Housekeeping Task"
INSPECTION_DOCTYPE = "Room Inspection"

PENDING = "Pending"
ASSIGNED = "Assigned"
IN_PROGRESS = "In Progress"
INSPECTION_PENDING = "Inspection Pending"
COMPLETED = "Completed"
CANCELLED = "Cancelled"
SERVICE_REFUSED = "Service Refused"
DND = "DND"

#: Task state machine. Mirrors Workflow Matrix section 5.
TRANSITIONS = {
	PENDING: {ASSIGNED, IN_PROGRESS, CANCELLED, DND, SERVICE_REFUSED},
	ASSIGNED: {IN_PROGRESS, PENDING, CANCELLED, DND, SERVICE_REFUSED},
	IN_PROGRESS: {INSPECTION_PENDING, COMPLETED, DND, SERVICE_REFUSED, CANCELLED},
	INSPECTION_PENDING: {COMPLETED, IN_PROGRESS},
	DND: {PENDING, ASSIGNED, IN_PROGRESS, CANCELLED},
	SERVICE_REFUSED: {PENDING, ASSIGNED, IN_PROGRESS, CANCELLED},
	COMPLETED: set(),
	CANCELLED: set(),
}

#: Only a supervisor signs off an inspection - that is the point of having one.
INSPECTION_ROLES = (
	"Housekeeping Supervisor",
	"Housekeeping Manager",
	"Hotel Manager",
	"General Manager",
	"Hospitality Administrator",
	"System Manager",
)

ASSIGNMENT_ROLES = (
	"Housekeeping Supervisor",
	"Housekeeping Manager",
	"Front Office Manager",
	"Hotel Manager",
	"General Manager",
	"Hospitality Administrator",
	"System Manager",
)


def create_task(
	property_name: str,
	room: str,
	*,
	task_type: str = "Departure Clean",
	priority: str = "Normal",
	scheduled_date=None,
	source_stay: str | None = None,
	due_in_reservation: str | None = None,
	requires_inspection: bool | None = None,
	notes: str | None = None,
) -> str:
	"""Raise a cleaning task for a room.

	Returns the existing open task when one already covers this room, type and
	date, so a checkout retried twice does not queue the same room twice.
	"""
	scheduled_date = getdate(scheduled_date or get_business_date(property_name))

	existing = frappe.db.get_value(
		TASK_DOCTYPE,
		{
			"property": property_name,
			"room": room,
			"task_type": task_type,
			"scheduled_date": scheduled_date,
			"task_status": ("not in", (COMPLETED, CANCELLED)),
		},
		"name",
	)

	if existing:
		return existing

	room_details = frappe.db.get_value(
		"Hotel Room", room, ["room_type", "zone", "housekeeping_credits"], as_dict=True
	) or {}

	if requires_inspection is None:
		requires_inspection = bool(
			frappe.db.get_single_value("PMS Settings", "require_inspection_before_release")
		)

	doc = frappe.get_doc(
		{
			"doctype": TASK_DOCTYPE,
			"property": property_name,
			"room": room,
			"room_type": room_details.get("room_type"),
			"zone": room_details.get("zone"),
			"task_type": task_type,
			"priority": priority,
			"task_status": PENDING,
			"scheduled_date": scheduled_date,
			"source_stay": source_stay,
			"due_in_reservation": due_in_reservation,
			"requires_inspection": 1 if requires_inspection else 0,
			"housekeeping_credits": room_details.get("housekeeping_credits"),
			"notes": notes,
		}
	).insert(ignore_permissions=True)

	return doc.name


def assign(task: str, assignee: str) -> str:
	"""Assign a task to a room attendant."""
	require_role(ASSIGNMENT_ROLES)

	lock_document(TASK_DOCTYPE, task)
	doc = frappe.get_doc(TASK_DOCTYPE, task)

	_transition(doc, ASSIGNED)

	frappe.db.set_value(
		TASK_DOCTYPE,
		task,
		{"assigned_to": assignee, "assigned_on": now_datetime(), "assigned_by": frappe.session.user},
		update_modified=True,
	)

	return task


def start(task: str) -> str:
	"""Start cleaning. Moves the room's housekeeping dimension to In Progress."""
	lock_document(TASK_DOCTYPE, task)
	doc = frappe.get_doc(TASK_DOCTYPE, task)

	_transition(doc, IN_PROGRESS)

	frappe.db.set_value(TASK_DOCTYPE, task, "started_on", now_datetime(), update_modified=True)

	room_service.set_status(
		doc.room,
		room_service.HOUSEKEEPING,
		"In Progress",
		reason=_("Cleaning started"),
		reference_doctype=TASK_DOCTYPE,
		reference_name=task,
	)

	return task


def complete(
	task: str,
	*,
	minutes: int | None = None,
	minibar_checked: bool = False,
	damage_found: bool = False,
	damage_notes: str | None = None,
	lost_and_found: bool = False,
	lost_and_found_notes: str | None = None,
	maintenance_required: bool = False,
	maintenance_description: str | None = None,
) -> dict:
	"""Finish cleaning.

	Where inspection is required the room goes to Inspection Pending rather
	than Clean, because "the attendant says it is clean" and "a supervisor
	checked" are different facts and the room rack must show which one it has.
	"""
	lock_document(TASK_DOCTYPE, task)
	doc = frappe.get_doc(TASK_DOCTYPE, task)

	if damage_found and not (damage_notes or "").strip():
		throw(_("Describe the damage found."), exc=HospitalityPMSError)

	target = INSPECTION_PENDING if doc.requires_inspection else COMPLETED
	_transition(doc, target)

	frappe.db.set_value(
		TASK_DOCTYPE,
		task,
		{
			"completed_on": now_datetime(),
			"completed_by": frappe.session.user,
			# Frappe's Int columns are NOT NULL, so an unrecorded duration is
			# stored as zero rather than passed through as None.
			"actual_minutes": int(minutes or 0),
			"minibar_checked": 1 if minibar_checked else 0,
			"damage_found": 1 if damage_found else 0,
			"damage_notes": damage_notes,
			"lost_and_found": 1 if lost_and_found else 0,
			"lost_and_found_notes": lost_and_found_notes,
			"maintenance_required": 1 if maintenance_required else 0,
		},
		update_modified=True,
	)

	room_service.set_status(
		doc.room,
		room_service.HOUSEKEEPING,
		"Inspection Pending" if doc.requires_inspection else "Clean",
		reason=_("Cleaning complete"),
		reference_doctype=TASK_DOCTYPE,
		reference_name=task,
	)

	ticket = None
	if maintenance_required or damage_found:
		from hospitality_pms.services import maintenance as maintenance_service

		ticket = maintenance_service.create_ticket(
			doc.property,
			title=_("Issue found while cleaning room {0}").format(doc.room),
			description=maintenance_description or damage_notes or _("Raised by housekeeping."),
			room=doc.room,
			category="Other",
			priority="High" if damage_found else "Normal",
			source_housekeeping_task=task,
		)

		frappe.db.set_value(TASK_DOCTYPE, task, "maintenance_ticket", ticket, update_modified=False)

	return {"task": task, "task_status": target, "maintenance_ticket": ticket}


def inspect(task: str, *, passed: bool, notes: str | None = None, score: int | None = None) -> dict:
	"""Supervisor sign-off.

	A failed inspection sends the room back to Dirty and the task back to In
	Progress; it does not quietly pass.
	"""
	require_role(INSPECTION_ROLES)

	lock_document(TASK_DOCTYPE, task)
	doc = frappe.get_doc(TASK_DOCTYPE, task)

	if doc.task_status != INSPECTION_PENDING:
		throw(
			_("Task {0} is {1} and is not awaiting inspection.").format(task, _(doc.task_status)),
			exc=HospitalityPMSError,
		)

	if not passed and not (notes or "").strip():
		throw(_("A failed inspection needs a note saying what to redo."), exc=HospitalityPMSError)

	frappe.get_doc(
		{
			"doctype": INSPECTION_DOCTYPE,
			"property": doc.property,
			"room": doc.room,
			"housekeeping_task": task,
			"inspected_by": frappe.session.user,
			"inspected_on": now_datetime(),
			"result": "Passed" if passed else "Failed",
			"score": score,
			"notes": notes,
			"re_clean_required": 0 if passed else 1,
		}
	).insert(ignore_permissions=True)

	_transition(doc, COMPLETED if passed else IN_PROGRESS)

	frappe.db.set_value(
		TASK_DOCTYPE,
		task,
		{
			"inspected_by": frappe.session.user,
			"inspected_on": now_datetime(),
			"inspection_passed": 1 if passed else 0,
			"inspection_notes": notes,
		},
		update_modified=True,
	)

	room_service.set_status(
		doc.room,
		room_service.HOUSEKEEPING,
		"Inspected" if passed else "Dirty",
		reason=_("Inspection passed") if passed else _("Inspection failed: {0}").format(notes),
		reference_doctype=TASK_DOCTYPE,
		reference_name=task,
	)

	return {"task": task, "passed": passed}


def set_do_not_disturb(task: str, refused: bool = False) -> str:
	"""Record DND or a refused service, which is not a failure to clean."""
	lock_document(TASK_DOCTYPE, task)
	doc = frappe.get_doc(TASK_DOCTYPE, task)

	target = SERVICE_REFUSED if refused else DND
	_transition(doc, target)

	room_service.set_status(
		doc.room,
		room_service.HOUSEKEEPING,
		"Service Refused" if refused else "DND",
		reason=_("Reported by housekeeping"),
		reference_doctype=TASK_DOCTYPE,
		reference_name=task,
	)

	return target


def _transition(doc, target: str):
	assert_transition(doc.task_status, target, TRANSITIONS, _("Housekeeping task"))

	frappe.db.set_value(TASK_DOCTYPE, doc.name, "task_status", target, update_modified=True)
	doc.task_status = target

	return target


def get_board(property_name: str, scheduled_date=None) -> dict:
	"""The housekeeping board for a day.

	Rooms with an arriving guest are surfaced first: those are the ones that
	must be ready before the desk can check anyone in.
	"""
	# The property's business date, not the calendar's. A property that has not
	# yet run its night audit is still working yesterday, and a housekeeping
	# board that jumped to the wall clock would show a different day from the
	# dashboard tile that links to it - which is exactly what the other boards
	# avoid by resolving the business date the same way (SAS section 6).
	scheduled_date = getdate(scheduled_date or get_business_date(property_name))

	tasks = frappe.get_all(
		TASK_DOCTYPE,
		filters={"property": property_name, "scheduled_date": scheduled_date},
		fields=[
			"name",
			"room",
			"room_type",
			"zone",
			"task_type",
			"priority",
			"task_status",
			"assigned_to",
			"due_in_reservation",
			"requires_inspection",
			"housekeeping_credits",
			"damage_found",
			"maintenance_required",
		],
		order_by="priority desc, room asc",
		limit_page_length=0,
	)

	return {
		"property": property_name,
		"scheduled_date": str(scheduled_date),
		"tasks": tasks,
		"summary": {
			"total": len(tasks),
			"pending": sum(1 for t in tasks if t["task_status"] == PENDING),
			"in_progress": sum(1 for t in tasks if t["task_status"] == IN_PROGRESS),
			"awaiting_inspection": sum(1 for t in tasks if t["task_status"] == INSPECTION_PENDING),
			"completed": sum(1 for t in tasks if t["task_status"] == COMPLETED),
			"due_in": sum(1 for t in tasks if t["due_in_reservation"]),
		},
	}
