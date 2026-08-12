"""Maintenance board, tickets and out-of-service control endpoints."""

import frappe

from hospitality_pms.services import maintenance as service
from hospitality_pms.services.base import authorise_document, require_permission
from hospitality_pms.services.property import resolve_property

TICKET_DOCTYPE = "Maintenance Ticket"

TICKET_FIELDS = (
	"name",
	"property",
	"ticket_status",
	"ticket_type",
	"priority",
	"category",
	"room",
	"zone",
	"area",
	"asset",
	"title",
	"description",
	"reported_by",
	"reported_on",
	"source_housekeeping_task",
	"assigned_to",
	"assigned_on",
	"takes_room_out_of_service",
	"out_of_service_status",
	"room_block",
	"started_on",
	"completed_on",
	"completed_by",
	"verified_by",
	"verified_on",
	"released_on",
	"released_by",
	"verification_notes",
	"is_repeat_defect",
	"previous_ticket",
	"estimated_cost",
	"actual_cost",
	"currency",
)


def _allowed_transitions(status: str) -> list[str]:
	"""States reachable from `status`, straight from the service.

	Returned so a screen offers exactly what the domain permits instead of
	mirroring the transition table in JavaScript, where the two would
	eventually drift apart.
	"""
	return sorted(service.TRANSITIONS.get(status, set()))


@frappe.whitelist(methods=["GET"])
def board(property: str | None = None, include_completed: int = 0) -> dict:
	"""The maintenance board."""
	require_permission(TICKET_DOCTYPE, "read")
	property_name = resolve_property(property)

	return service.get_board(property_name, include_completed=bool(int(include_completed or 0)))


@frappe.whitelist(methods=["GET"])
def get_ticket(ticket: str) -> dict:
	"""One maintenance ticket with its work log."""
	# `authorise_document` rather than `check_permission` alone (16.7.5). A User
	# Permission created without `apply_to_all_doctypes` restricts only the
	# DocTypes it names, so step 2 can legitimately pass for a record in a
	# property the caller may not operate in - and every one of these DocTypes
	# carries a required `property`, so the third check always fires.
	doc = authorise_document(TICKET_DOCTYPE, ticket, "read")

	return {
		"ticket": {field: doc.get(field) for field in TICKET_FIELDS},
		"work_logs": [
			{
				"logged_on": row.logged_on,
				"logged_by": row.logged_by,
				"work_done": row.work_done,
				"minutes_spent": row.minutes_spent,
				"parts_used": row.parts_used,
			}
			for row in doc.work_logs
		],
		"allowed_transitions": _allowed_transitions(doc.ticket_status),
	}


@frappe.whitelist(methods=["POST"])
def create_ticket(
	property: str,
	title: str,
	description: str,
	category: str = "Other",
	priority: str = "Normal",
	ticket_type: str = "Corrective",
	room: str | None = None,
	zone: str | None = None,
	area: str | None = None,
	asset: str | None = None,
	source_housekeeping_task: str | None = None,
) -> dict:
	"""Raise a maintenance ticket."""
	require_permission(TICKET_DOCTYPE, "write")
	property_name = resolve_property(property)

	ticket = service.create_ticket(
		property_name,
		title=title,
		description=description,
		category=category,
		priority=priority,
		ticket_type=ticket_type,
		room=room,
		zone=zone,
		area=area,
		asset=asset,
		source_housekeeping_task=source_housekeeping_task,
	)

	return get_ticket(ticket)


@frappe.whitelist(methods=["POST"])
def assign(ticket: str, technician: str) -> dict:
	"""Assign a ticket to a technician."""
	authorise_document(TICKET_DOCTYPE, ticket, "write")

	service.assign(ticket, technician)

	return get_ticket(ticket)


@frappe.whitelist(methods=["POST"])
def start_work(ticket: str) -> dict:
	"""Start work on a ticket."""
	authorise_document(TICKET_DOCTYPE, ticket, "write")

	service.start_work(ticket)

	return get_ticket(ticket)


@frappe.whitelist(methods=["POST"])
def log_work(ticket: str, work_done: str, minutes: int | None = None, parts: str | None = None) -> dict:
	"""Append an entry to a ticket's work log."""
	authorise_document(TICKET_DOCTYPE, ticket, "write")

	service.log_work(
		ticket,
		work_done,
		minutes=int(minutes) if minutes not in (None, "") else None,
		parts=parts,
	)

	return get_ticket(ticket)


@frappe.whitelist(methods=["POST"])
def take_out_of_service(ticket: str, status: str, reason: str, until_date: str | None = None) -> dict:
	"""Remove a room from sale for maintenance."""
	authorise_document(TICKET_DOCTYPE, ticket, "write")

	service.take_out_of_service(ticket, status, reason, until_date=until_date)

	return get_ticket(ticket)


@frappe.whitelist(methods=["POST"])
def complete_work(ticket: str, notes: str | None = None) -> dict:
	"""Technician finishes work; the room still awaits verification."""
	authorise_document(TICKET_DOCTYPE, ticket, "write")

	service.complete_work(ticket, notes=notes)

	return get_ticket(ticket)


@frappe.whitelist(methods=["POST"])
def verify_and_release(ticket: str, passed: int, notes: str | None = None) -> dict:
	"""Verify completed work and, if it passed, release the room back to sale."""
	authorise_document(TICKET_DOCTYPE, ticket, "write")

	service.verify_and_release(ticket, passed=bool(int(passed)), notes=notes)

	return get_ticket(ticket)
