"""Housekeeping board, cleaning tasks and inspection endpoints."""

import frappe

from hospitality_pms.services import housekeeping as service
from hospitality_pms.services.base import authorise_document, require_permission
from hospitality_pms.services.property import resolve_property

TASK_DOCTYPE = "Housekeeping Task"

TASK_FIELDS = (
	"name",
	"property",
	"task_status",
	"room",
	"room_type",
	"zone",
	"task_type",
	"priority",
	"scheduled_date",
	"source_stay",
	"due_in_reservation",
	"assigned_to",
	"assigned_on",
	"assigned_by",
	"started_on",
	"completed_on",
	"completed_by",
	"estimated_minutes",
	"actual_minutes",
	"housekeeping_credits",
	"requires_inspection",
	"inspected_by",
	"inspected_on",
	"inspection_passed",
	"inspection_notes",
	"minibar_checked",
	"damage_found",
	"damage_notes",
	"lost_and_found",
	"lost_and_found_notes",
	"maintenance_required",
	"maintenance_ticket",
	"notes",
)


def _allowed_transitions(status: str) -> list[str]:
	"""States reachable from `status`, straight from the service.

	Returned so a screen offers exactly what the domain permits instead of
	mirroring the transition table in JavaScript, where the two would
	eventually drift apart.
	"""
	return sorted(service.TRANSITIONS.get(status, set()))


@frappe.whitelist(methods=["GET"])
def board(property: str | None = None, scheduled_date: str | None = None) -> dict:
	"""The housekeeping board for a day."""
	require_permission(TASK_DOCTYPE, "read")
	property_name = resolve_property(property)

	return service.get_board(property_name, scheduled_date)


@frappe.whitelist(methods=["GET"])
def get_task(task: str) -> dict:
	"""One housekeeping task."""
	# `authorise_document` rather than `check_permission` alone (16.7.5). A User
	# Permission created without `apply_to_all_doctypes` restricts only the
	# DocTypes it names, so step 2 can legitimately pass for a record in a
	# property the caller may not operate in - and every one of these DocTypes
	# carries a required `property`, so the third check always fires.
	doc = authorise_document(TASK_DOCTYPE, task, "read")

	return {
		"task": {field: doc.get(field) for field in TASK_FIELDS},
		"allowed_transitions": _allowed_transitions(doc.task_status),
	}


@frappe.whitelist(methods=["POST"])
def create_task(
	property: str,
	room: str,
	task_type: str = "Departure Clean",
	priority: str = "Normal",
	scheduled_date: str | None = None,
	source_stay: str | None = None,
	due_in_reservation: str | None = None,
	requires_inspection: int | None = None,
	notes: str | None = None,
) -> dict:
	"""Raise a cleaning task for a room."""
	require_permission(TASK_DOCTYPE, "write")
	property_name = resolve_property(property)

	task = service.create_task(
		property_name,
		room,
		task_type=task_type,
		priority=priority,
		scheduled_date=scheduled_date,
		source_stay=source_stay,
		due_in_reservation=due_in_reservation,
		# None means "let the service decide from PMS Settings" - do not
		# collapse that to False by coercing unconditionally.
		requires_inspection=None if requires_inspection is None else bool(int(requires_inspection)),
		notes=notes,
	)

	return get_task(task)


@frappe.whitelist(methods=["POST"])
def assign(task: str, assignee: str) -> dict:
	"""Assign a task to a room attendant."""
	authorise_document(TASK_DOCTYPE, task, "write")

	service.assign(task, assignee)

	return get_task(task)


@frappe.whitelist(methods=["POST"])
def start(task: str) -> dict:
	"""Start cleaning."""
	authorise_document(TASK_DOCTYPE, task, "write")

	service.start(task)

	return get_task(task)


@frappe.whitelist(methods=["POST"])
def complete(
	task: str,
	minutes: int | None = None,
	minibar_checked: int = 0,
	damage_found: int = 0,
	damage_notes: str | None = None,
	lost_and_found: int = 0,
	lost_and_found_notes: str | None = None,
	maintenance_required: int = 0,
	maintenance_description: str | None = None,
) -> dict:
	"""Finish cleaning."""
	authorise_document(TASK_DOCTYPE, task, "write")

	service.complete(
		task,
		minutes=int(minutes or 0),
		minibar_checked=bool(int(minibar_checked or 0)),
		damage_found=bool(int(damage_found or 0)),
		damage_notes=damage_notes,
		lost_and_found=bool(int(lost_and_found or 0)),
		lost_and_found_notes=lost_and_found_notes,
		maintenance_required=bool(int(maintenance_required or 0)),
		maintenance_description=maintenance_description,
	)

	return get_task(task)


@frappe.whitelist(methods=["POST"])
def inspect(task: str, passed: int, notes: str | None = None, score: int | None = None) -> dict:
	"""Supervisor sign-off on a cleaned room."""
	authorise_document(TASK_DOCTYPE, task, "write")

	service.inspect(
		task,
		passed=bool(int(passed)),
		notes=notes,
		score=int(score) if score not in (None, "") else None,
	)

	return get_task(task)


@frappe.whitelist(methods=["POST"])
def set_do_not_disturb(task: str, refused: int = 0) -> dict:
	"""Record DND or a refused service against a task."""
	authorise_document(TASK_DOCTYPE, task, "write")

	service.set_do_not_disturb(task, refused=bool(int(refused or 0)))

	return get_task(task)
