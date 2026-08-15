"""Maintenance: tickets, out-of-service control and verified room release.

The part that touches money is out-of-service control. Taking a room out of
order removes sellable inventory, so it raises a real Room Block rather than
just setting a flag - which means availability, the room rack and revenue all
see the same thing. Releasing it back requires verification by a manager
(Workflow Matrix section 6).
"""

import frappe
from frappe import _
from frappe.utils import add_days, getdate, now_datetime, nowdate

from hospitality_pms.services import rooms as room_service
from hospitality_pms.services.base import (
	assert_transition,
	lock_and_find,
	lock_and_get_doc,
	lock_document,
	require_role,
)
from hospitality_pms.services.exceptions import HospitalityPMSError, throw
from hospitality_pms.services.property import get_business_date

TICKET_DOCTYPE = "Maintenance Ticket"
BLOCK_DOCTYPE = "Room Block"

OPEN = "Open"
IN_PROGRESS = "In Progress"
VERIFICATION = "Verification"
COMPLETED = "Completed"
CANCELLED = "Cancelled"

#: Ticket state machine, from Workflow Matrix section 6.
TRANSITIONS = {
	OPEN: {IN_PROGRESS, CANCELLED},
	IN_PROGRESS: {VERIFICATION, OPEN, CANCELLED},
	VERIFICATION: {COMPLETED, IN_PROGRESS},
	COMPLETED: set(),
	CANCELLED: set(),
}

#: Taking a room out of service, and releasing it again, are manager decisions.
OOS_ROLES = (
	"Maintenance Manager",
	"Hotel Manager",
	"General Manager",
	"Hospitality Administrator",
	"System Manager",
)

ASSIGNMENT_ROLES = (
	"Maintenance Manager",
	"Hotel Manager",
	"General Manager",
	"Hospitality Administrator",
	"System Manager",
)


def create_ticket(
	property_name: str,
	*,
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
) -> str:
	"""Raise a maintenance ticket."""
	if not title or not description:
		throw(_("A maintenance ticket needs a title and a description."), exc=HospitalityPMSError)

	previous = None
	if room:
		# A room with a recent closed ticket in the same category is very
		# likely the same fault coming back, which is worth flagging.
		previous = frappe.db.get_value(
			TICKET_DOCTYPE,
			{
				"room": room,
				"category": category,
				"ticket_status": COMPLETED,
				"completed_on": (">=", add_days(nowdate(), -30)),
			},
			"name",
		)

	doc = frappe.get_doc(
		{
			"doctype": TICKET_DOCTYPE,
			"property": property_name,
			"ticket_type": ticket_type,
			"ticket_status": OPEN,
			"priority": priority,
			"category": category,
			"title": title,
			"description": description,
			"room": room,
			"zone": zone,
			"area": area,
			"asset": asset,
			"reported_by": frappe.session.user,
			"reported_on": now_datetime(),
			"source_housekeeping_task": source_housekeeping_task,
			"is_repeat_defect": 1 if previous else 0,
			"previous_ticket": previous,
		}
	).insert(ignore_permissions=True)

	return doc.name


def assign(ticket: str, technician: str) -> str:
	require_role(ASSIGNMENT_ROLES)

	lock_document(TICKET_DOCTYPE, ticket)

	frappe.db.set_value(
		TICKET_DOCTYPE,
		ticket,
		{"assigned_to": technician, "assigned_on": now_datetime()},
		update_modified=True,
	)

	return ticket


def start_work(ticket: str) -> str:
	lock_document(TICKET_DOCTYPE, ticket)
	doc = frappe.get_doc(TICKET_DOCTYPE, ticket)

	_transition(doc, IN_PROGRESS)

	frappe.db.set_value(TICKET_DOCTYPE, ticket, "started_on", now_datetime(), update_modified=True)

	if doc.room:
		_take_room_under_repair(doc.room, ticket)

	return ticket


def _take_room_under_repair(room: str, ticket: str):
	"""Reflect that a technician now has this room open.

	Two things were wrong with moving the room to `Required` here (UAT-005).

	`Required` means *this room needs work*, not *work is happening*, and it is
	not in `BLOCKING_MAINTENANCE` - so starting a repair on a healthy room left
	it sellable while somebody had it apart. `Under Maintenance` is the state
	the room model already has for exactly this, and it does block the sale.

	And a room that has already been taken Out of Order or Out of Service is
	left alone. `Out of Order` has no transition to `Required`, which is why the
	natural order - find the fault, pull the room out of sale, then start work -
	failed outright. Those states are also a deliberate severity judgement by
	someone holding the maintenance role; starting work is not new information
	about how bad the room is, so it must not quietly downgrade it. Both states
	already block the sale, which is what starting work needs to guarantee.
	"""
	current = frappe.db.get_value(room_service.ROOM_DOCTYPE, room, "maintenance_status")

	if current in room_service.BLOCKING_MAINTENANCE:
		return

	room_service.set_status(
		room,
		room_service.MAINTENANCE,
		"Under Maintenance",
		reason=_("Maintenance ticket {0} started").format(ticket),
		reference_doctype=TICKET_DOCTYPE,
		reference_name=ticket,
	)


def log_work(ticket: str, work_done: str, *, minutes: int | None = None, parts: str | None = None) -> str:
	"""Append to the ticket's work log."""
	if not work_done or not work_done.strip():
		throw(_("Describe the work done."), exc=HospitalityPMSError)

	doc = frappe.get_doc(TICKET_DOCTYPE, ticket)
	doc.append(
		"work_logs",
		{
			"logged_on": now_datetime(),
			"logged_by": frappe.session.user,
			"work_done": work_done.strip(),
			"minutes_spent": minutes,
			"parts_used": parts,
		},
	)
	doc.save(ignore_permissions=True)

	return ticket


def take_out_of_service(ticket: str, status: str, reason: str, *, until_date=None) -> dict:
	"""Remove a room from sale for maintenance.

	Raises a submitted Room Block so the availability engine, the room rack and
	revenue reporting all agree the room is gone. Setting the maintenance
	dimension alone would leave availability still selling it.
	"""
	require_role(OOS_ROLES)

	if status not in ("Out of Service", "Out of Order"):
		throw(_("Status must be Out of Service or Out of Order."), exc=HospitalityPMSError)

	if not reason or not reason.strip():
		throw(_("A reason is required to take a room out of service."), exc=HospitalityPMSError)

	# Locked and read in one operation. `lock_document` serialises but does not
	# refresh: a plain `get_doc` after it is answered from the snapshot this
	# transaction opened *before* it started waiting, so a retry that queued
	# behind a winner read `room_block` as empty, raised a second submitted
	# Active Room Block for the same room, and overwrote the ticket's reference
	# with the newer one - orphaning the first. `verify_and_release` then
	# releases only the block the ticket names, leaving the orphan holding the
	# room out of sale for good (N1).
	doc = lock_and_get_doc(TICKET_DOCTYPE, ticket)

	if not doc.room:
		throw(_("Ticket {0} is not against a room.").format(ticket), exc=HospitalityPMSError)

	# Idempotent under a double-click or a retried request: a ticket already
	# covered by its own submitted, Active Room Block does not get a second one.
	# `lock_and_get_doc` read `room_block` currently under the lock, but the
	# block it names must be read currently too - a plain read of it would be
	# answered from this transaction's pre-lock snapshot, which predates the
	# winner *inserting* that block, so the block would look absent and the guard
	# would fall through and raise a second one. `lock_and_find` reads it with a
	# locking read, so the winner's just-committed block is visible.
	if doc.room_block:
		existing = lock_and_find(
			BLOCK_DOCTYPE, {"name": doc.room_block}, ["docstatus", "status", "room"]
		)

		if existing and existing.docstatus == 1 and existing.status == "Active" and existing.room == doc.room:
			return {
				"ticket": ticket,
				"room": doc.room,
				"status": doc.out_of_service_status or status,
				"room_block": doc.room_block,
			}

	business_date = get_business_date(doc.property)
	until_date = getdate(until_date or add_days(business_date, 7))

	block = frappe.get_doc(
		{
			"doctype": BLOCK_DOCTYPE,
			"property": doc.property,
			"block_type": "Out of Order" if status == "Out of Order" else "Maintenance",
			"room": doc.room,
			"from_date": business_date,
			"to_date": until_date,
			"reason": reason.strip(),
			"reference_doctype": TICKET_DOCTYPE,
			"reference_name": ticket,
		}
	)
	block.flags.ignore_permissions = True
	block.insert()
	block.submit()

	room_service.set_status(
		doc.room,
		room_service.MAINTENANCE,
		status,
		reason=reason.strip(),
		reference_doctype=TICKET_DOCTYPE,
		reference_name=ticket,
	)

	frappe.db.set_value(
		TICKET_DOCTYPE,
		ticket,
		{
			"takes_room_out_of_service": 1,
			"out_of_service_status": status,
			"room_block": block.name,
		},
		update_modified=True,
	)

	return {"ticket": ticket, "room": doc.room, "status": status, "room_block": block.name}


def complete_work(ticket: str, *, notes: str | None = None) -> str:
	"""Technician finishes. The room is not released yet - verification first."""
	lock_document(TICKET_DOCTYPE, ticket)
	doc = frappe.get_doc(TICKET_DOCTYPE, ticket)

	_transition(doc, VERIFICATION)

	frappe.db.set_value(
		TICKET_DOCTYPE,
		ticket,
		{"completed_on": now_datetime(), "completed_by": frappe.session.user},
		update_modified=True,
	)

	if notes:
		log_work(ticket, notes)

	return ticket


def verify_and_release(ticket: str, *, passed: bool, notes: str | None = None) -> dict:
	"""Verify the work and, if it passed, return the room to sale.

	Releasing cancels the Room Block and returns the maintenance dimension to
	Operational. A failed verification sends the ticket back to In Progress and
	the room stays out of sale, which is the whole point of the step.
	"""
	require_role(OOS_ROLES)

	if not passed and not (notes or "").strip():
		throw(_("A failed verification needs a note saying what is still wrong."), exc=HospitalityPMSError)

	lock_document(TICKET_DOCTYPE, ticket)
	doc = frappe.get_doc(TICKET_DOCTYPE, ticket)

	if doc.ticket_status != VERIFICATION:
		throw(
			_("Ticket {0} is {1} and is not awaiting verification.").format(ticket, _(doc.ticket_status)),
			exc=HospitalityPMSError,
		)

	if not passed:
		_transition(doc, IN_PROGRESS)
		log_work(ticket, _("Verification failed: {0}").format(notes))
		return {"ticket": ticket, "passed": False, "room_released": False}

	_transition(doc, COMPLETED)

	released = False
	if doc.room_block and frappe.db.exists(BLOCK_DOCTYPE, doc.room_block):
		block = frappe.get_doc(BLOCK_DOCTYPE, doc.room_block)
		if block.docstatus == 1 and block.status == "Active":
			block.flags.ignore_permissions = True
			block.release()
			released = True

	if doc.room:
		room_service.set_status(
			doc.room,
			room_service.MAINTENANCE,
			"Operational",
			reason=_("Verified and released after ticket {0}").format(ticket),
			reference_doctype=TICKET_DOCTYPE,
			reference_name=ticket,
		)

	frappe.db.set_value(
		TICKET_DOCTYPE,
		ticket,
		{
			"verified_by": frappe.session.user,
			"verified_on": now_datetime(),
			"verification_notes": notes,
			"released_on": now_datetime() if released else None,
			"released_by": frappe.session.user if released else None,
		},
		update_modified=True,
	)

	return {"ticket": ticket, "passed": True, "room_released": released}


def _transition(doc, target: str):
	assert_transition(doc.ticket_status, target, TRANSITIONS, _("Maintenance ticket"))

	frappe.db.set_value(TICKET_DOCTYPE, doc.name, "ticket_status", target, update_modified=True)
	doc.ticket_status = target

	return target


def get_board(property_name: str, *, include_completed: bool = False) -> dict:
	"""The maintenance board."""
	filters = {"property": property_name}

	if not include_completed:
		filters["ticket_status"] = ("not in", (COMPLETED, CANCELLED))

	tickets = frappe.get_all(
		TICKET_DOCTYPE,
		filters=filters,
		fields=[
			"name",
			"title",
			"ticket_type",
			"ticket_status",
			"priority",
			"category",
			"room",
			"area",
			"assigned_to",
			"reported_on",
			"takes_room_out_of_service",
			"out_of_service_status",
			"is_repeat_defect",
		],
		order_by="priority desc, reported_on asc",
		limit_page_length=0,
	)

	return {
		"property": property_name,
		"tickets": tickets,
		"summary": {
			"open": sum(1 for t in tickets if t["ticket_status"] == OPEN),
			"in_progress": sum(1 for t in tickets if t["ticket_status"] == IN_PROGRESS),
			"awaiting_verification": sum(1 for t in tickets if t["ticket_status"] == VERIFICATION),
			"rooms_out_of_service": sum(1 for t in tickets if t["takes_room_out_of_service"]),
			"repeat_defects": sum(1 for t in tickets if t["is_repeat_defect"]),
		},
	}
