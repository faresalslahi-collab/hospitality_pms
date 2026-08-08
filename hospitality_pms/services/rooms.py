"""Room status and assignability.

A room carries four independent status dimensions (SAS section 3.2). They are
independent on purpose: a room can be Occupied and Dirty and Operational and
Available all at once, and collapsing them into one status field is how PMS
implementations end up unable to answer "which occupied rooms still need
cleaning today".

Every transition goes through `set_status` so that it is locked, validated and
logged. Nothing else writes the status fields.
"""

from collections.abc import Iterable

import frappe
from frappe import _
from frappe.utils import now_datetime

from hospitality_pms.services.base import lock_document, require_role
from hospitality_pms.services.exceptions import (
	InvalidStateTransitionError,
	RoomNotAssignableError,
	throw,
)

ROOM_DOCTYPE = "Hotel Room"
LOG_DOCTYPE = "Hospitality Room Status Log"

# ---------------------------------------------------------------------------
# The four dimensions
# ---------------------------------------------------------------------------

OCCUPANCY = "Occupancy"
HOUSEKEEPING = "Housekeeping"
MAINTENANCE = "Maintenance"
INVENTORY = "Inventory"

DIMENSION_FIELD = {
	OCCUPANCY: "occupancy_status",
	HOUSEKEEPING: "housekeeping_status",
	MAINTENANCE: "maintenance_status",
	INVENTORY: "inventory_status",
}

#: Allowed transitions per dimension. A dimension not listing a source state
#: forbids every move out of it, so new states cannot silently become reachable.
TRANSITIONS = {
	OCCUPANCY: {
		"Vacant": {"Reserved", "Due In", "Occupied", "House Use"},
		"Reserved": {"Due In", "Occupied", "Vacant"},
		"Due In": {"Occupied", "Vacant", "Reserved"},
		"Occupied": {"Due Out", "Vacant", "House Use"},
		"Due Out": {"Vacant", "Occupied"},
		"House Use": {"Vacant", "Occupied"},
	},
	HOUSEKEEPING: {
		# Inspection Pending is reachable from Clean and Dirty, not only from
		# In Progress: an attendant finishing a re-clean after a failed
		# inspection completes from Dirty without pressing start again.
		"Clean": {"Dirty", "In Progress", "Inspection Pending", "DND", "Service Refused"},
		"Dirty": {"In Progress", "Inspection Pending", "DND", "Service Refused", "Clean"},
		"In Progress": {"Inspection Pending", "Clean", "Dirty", "DND", "Service Refused"},
		"Inspection Pending": {"Inspected", "In Progress", "Dirty"},
		# An inspected room can be cleaned again - turndown, deep clean, a
		# stayover service - so it is not a dead end.
		"Inspected": {"Clean", "Dirty", "In Progress", "Inspection Pending", "DND", "Service Refused"},
		"DND": {"Dirty", "In Progress", "Clean", "Service Refused"},
		"Service Refused": {"Dirty", "In Progress", "Clean", "DND"},
	},
	MAINTENANCE: {
		"Operational": {"Required", "Under Maintenance", "Out of Service", "Out of Order"},
		"Required": {"Under Maintenance", "Operational", "Out of Service", "Out of Order"},
		"Under Maintenance": {"Operational", "Out of Service", "Out of Order", "Required"},
		"Out of Service": {"Under Maintenance", "Operational", "Out of Order"},
		"Out of Order": {"Under Maintenance", "Out of Service", "Operational"},
	},
	INVENTORY: {
		"Available": {"Blocked", "Not Assignable", "Stop Sell"},
		"Blocked": {"Available", "Not Assignable", "Stop Sell"},
		"Not Assignable": {"Available", "Blocked", "Stop Sell"},
		"Stop Sell": {"Available", "Blocked", "Not Assignable"},
	},
}

#: Housekeeping states in which a room is physically ready for a new guest.
READY_HOUSEKEEPING = {"Clean", "Inspected"}

#: Maintenance states that make a room unusable. Out of Order is never
#: overridable; Out of Service and Under Maintenance are equally blocking for
#: assignment (SAS section 3.2).
BLOCKING_MAINTENANCE = {"Under Maintenance", "Out of Service", "Out of Order"}

#: Inventory states that take a room out of sale.
BLOCKING_INVENTORY = {"Blocked", "Not Assignable", "Stop Sell"}

#: Occupancy states meaning the room already has, or is committed to, a guest.
OCCUPIED_STATES = {"Occupied", "House Use"}


#: Who may move each dimension. A Room Attendant marks a room clean but must
#: never take it out of sale; a Revenue Manager stops sale but does not decide
#: a room is out of order. Gating per dimension avoids granting blanket write
#: access to Hotel Room just to let someone finish cleaning a room.
DIMENSION_ROLES = {
	OCCUPANCY: (
		"Front Office Manager",
		"Front Office Agent",
		"Night Auditor",
		"Hotel Manager",
		"General Manager",
		"Hospitality Administrator",
		"System Manager",
	),
	HOUSEKEEPING: (
		"Room Attendant",
		"Housekeeping Supervisor",
		"Housekeeping Manager",
		"Front Office Manager",
		"Front Office Agent",
		"Hotel Manager",
		"General Manager",
		"Hospitality Administrator",
		"System Manager",
	),
	MAINTENANCE: (
		"Maintenance Technician",
		"Maintenance Manager",
		"Hotel Manager",
		"General Manager",
		"Hospitality Administrator",
		"System Manager",
	),
	INVENTORY: (
		"Front Office Manager",
		"Reservation Manager",
		"Revenue Manager",
		"Housekeeping Manager",
		"Maintenance Manager",
		"Hotel Manager",
		"General Manager",
		"Hospitality Administrator",
		"System Manager",
	),
}

#: Statuses only a manager may set, whatever the dimension role allows. Taking
#: a room out of order removes sellable inventory and needs an accountable
#: decision (Roles Matrix section 4).
ELEVATED_STATUSES = {
	("Maintenance", "Out of Order"): ("Maintenance Manager", "Hotel Manager", "General Manager"),
	("Maintenance", "Out of Service"): ("Maintenance Manager", "Hotel Manager", "General Manager"),
}


def dimension_field(dimension: str) -> str:
	field = DIMENSION_FIELD.get(dimension)

	if not field:
		throw(_("{0} is not a room status dimension.").format(dimension))

	return field


# ---------------------------------------------------------------------------
# Reading state
# ---------------------------------------------------------------------------


def get_room_state(room: str) -> dict:
	"""All four dimensions plus the flags assignability depends on."""
	state = frappe.db.get_value(
		ROOM_DOCTYPE,
		room,
		[
			"name",
			"property",
			"room_number",
			"room_type",
			"is_active",
			"occupancy_status",
			"housekeeping_status",
			"maintenance_status",
			"inventory_status",
		],
		as_dict=True,
	)

	if not state:
		frappe.throw(_("Room {0} not found.").format(room), frappe.DoesNotExistError)

	return state


# ---------------------------------------------------------------------------
# Assignability
# ---------------------------------------------------------------------------


def assert_assignable(room: str, *, allow_unready_housekeeping: bool = False, state: dict | None = None):
	"""Raise unless the room can take a guest right now.

	`allow_unready_housekeeping` is the controlled Vacant Dirty override. It
	relaxes only the housekeeping dimension - never maintenance, inventory,
	occupancy or the active flag, none of which a front desk override may skip.
	"""
	state = state or get_room_state(room)
	label = state.get("room_number") or room

	if not state.get("is_active"):
		throw(_("Room {0} is not active and cannot be sold.").format(label), exc=RoomNotAssignableError)

	if state.get("maintenance_status") in BLOCKING_MAINTENANCE:
		throw(
			_("Room {0} is {1} and cannot be assigned.").format(label, _(state["maintenance_status"])),
			exc=RoomNotAssignableError,
		)

	if state.get("inventory_status") in BLOCKING_INVENTORY:
		throw(
			_("Room {0} is {1} and is not available for sale.").format(label, _(state["inventory_status"])),
			exc=RoomNotAssignableError,
		)

	if state.get("occupancy_status") in OCCUPIED_STATES:
		throw(
			_("Room {0} is already {1}.").format(label, _(state["occupancy_status"])),
			exc=RoomNotAssignableError,
		)

	if not allow_unready_housekeeping and state.get("housekeeping_status") not in READY_HOUSEKEEPING:
		throw(
			_("Room {0} is {1} and is not ready for a guest.").format(label, _(state["housekeeping_status"])),
			exc=RoomNotAssignableError,
		)


def is_assignable(room: str, *, allow_unready_housekeeping: bool = False) -> bool:
	"""Non-raising form of `assert_assignable`, for filtering lists."""
	try:
		assert_assignable(room, allow_unready_housekeeping=allow_unready_housekeeping)
	except RoomNotAssignableError:
		return False

	return True


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------


def set_status(
	room: str,
	dimension: str,
	to_status: str,
	*,
	reason: str | None = None,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
	force: bool = False,
) -> str:
	"""Move one status dimension and record it.

	The room row is locked for the rest of the transaction, so two concurrent
	check-ins cannot both read "Vacant" and both proceed.

	`force` skips the transition table for recovery paths (an administrator
	correcting bad data). It still locks, still validates the value, and still
	writes the log, so a forced change is never invisible.
	"""
	field = dimension_field(dimension)

	lock_document(ROOM_DOCTYPE, room)
	current = frappe.db.get_value(ROOM_DOCTYPE, room, field)

	if current == to_status:
		return to_status

	allowed_values = set(TRANSITIONS[dimension])
	if to_status not in allowed_values:
		throw(
			_("{0} is not a valid {1} status.").format(to_status, _(dimension)),
			exc=InvalidStateTransitionError,
		)

	if not force and to_status not in TRANSITIONS[dimension].get(current, set()):
		throw(
			_("Room {0} cannot move from {1} to {2}.").format(room, _(current or ""), _(to_status)),
			exc=InvalidStateTransitionError,
		)

	frappe.db.set_value(ROOM_DOCTYPE, room, field, to_status, update_modified=True)

	_log_transition(
		room=room,
		dimension=dimension,
		from_status=current,
		to_status=to_status,
		reason=reason,
		reference_doctype=reference_doctype,
		reference_name=reference_name,
	)

	return to_status


def set_statuses(room: str, changes: dict[str, str], *, reason: str | None = None, **kwargs) -> dict:
	"""Move several dimensions in one locked operation.

	Checkout, for example, sets Occupancy to Vacant and Housekeeping to Dirty
	together; doing them as two independent calls would leave a window where
	the room reads vacant and clean.
	"""
	lock_document(ROOM_DOCTYPE, room)

	applied = {}
	for dimension, to_status in changes.items():
		applied[dimension] = set_status(room, dimension, to_status, reason=reason, **kwargs)

	return applied


def _log_transition(
	room: str,
	dimension: str,
	from_status: str | None,
	to_status: str,
	reason: str | None,
	reference_doctype: str | None,
	reference_name: str | None,
):
	"""Append to the room status log.

	Inserted with `ignore_permissions` because the log records what the service
	did on the user's behalf; a Room Attendant may not write the log directly
	but their cleaning completion must still be recorded.
	"""
	property_name = frappe.db.get_value(ROOM_DOCTYPE, room, "property")

	frappe.get_doc(
		{
			"doctype": LOG_DOCTYPE,
			"property": property_name,
			"room": room,
			"dimension": dimension,
			"from_status": from_status,
			"to_status": to_status,
			"changed_by": frappe.session.user,
			"changed_at": now_datetime(),
			"reason": reason,
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
		}
	).insert(ignore_permissions=True)


# ---------------------------------------------------------------------------
# Common composite transitions
# ---------------------------------------------------------------------------


def mark_checked_out(room: str, *, reference_doctype=None, reference_name=None):
	"""Checkout leaves a room vacant and dirty in one step (SAS section 3.9)."""
	return set_statuses(
		room,
		{OCCUPANCY: "Vacant", HOUSEKEEPING: "Dirty"},
		reason=_("Guest checked out"),
		reference_doctype=reference_doctype,
		reference_name=reference_name,
	)


def mark_occupied(room: str, *, reference_doctype=None, reference_name=None):
	"""Check-in takes the room to Occupied."""
	return set_status(
		room,
		OCCUPANCY,
		"Occupied",
		reason=_("Guest checked in"),
		reference_doctype=reference_doctype,
		reference_name=reference_name,
	)


def require_dimension_role(dimension: str, to_status: str | None = None):
	"""Raise unless the session user may move this dimension.

	Called by the API layer. Services invoked from check-in, checkout and the
	Night Audit have already authorised their own operation, so they do not
	call this again.
	"""
	roles = DIMENSION_ROLES.get(dimension)

	if not roles:
		throw(_("{0} is not a room status dimension.").format(dimension))

	require_role(roles)

	elevated = ELEVATED_STATUSES.get((dimension, to_status))
	if elevated:
		require_role([*elevated, "Hospitality Administrator", "System Manager"])


def get_status_history(room: str, limit: int = 50) -> list[dict]:
	"""Recent transitions for a room, newest first."""
	return frappe.get_all(
		LOG_DOCTYPE,
		filters={"room": room},
		fields=[
			"dimension",
			"from_status",
			"to_status",
			"changed_by",
			"changed_at",
			"reason",
			"reference_doctype",
			"reference_name",
		],
		order_by="changed_at desc",
		limit=limit,
	)


def bulk_room_states(rooms: Iterable[str]) -> dict[str, dict]:
	"""State for many rooms in one query, for the room rack."""
	rooms = list(rooms)

	if not rooms:
		return {}

	records = frappe.get_all(
		ROOM_DOCTYPE,
		filters={"name": ("in", rooms)},
		fields=[
			"name",
			"property",
			"room_number",
			"room_type",
			"is_active",
			"occupancy_status",
			"housekeeping_status",
			"maintenance_status",
			"inventory_status",
		],
	)

	return {record["name"]: record for record in records}
