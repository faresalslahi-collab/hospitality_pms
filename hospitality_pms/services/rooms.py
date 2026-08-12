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
from frappe.utils import getdate, now_datetime

from hospitality_pms.services.base import lock_and_find, lock_document, require_role
from hospitality_pms.services.exceptions import (
	InvalidStateTransitionError,
	RoomNotAssignableError,
	throw,
)

ROOM_DOCTYPE = "Hotel Room"
LOG_DOCTYPE = "Room Status Log"

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
#:
#: **Not the authority for whether somebody is in the room.** This is a
#: denormalised flag, and `active_stay_in_room` below is the authority; see the
#: section on physical occupancy. `Due Out` is deliberately still absent from
#: this set - a Due Out room is genuinely re-lettable *once its guest has left*,
#: and it is the Stay, not the flag, that knows whether they have.
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
# Physical occupancy: who is actually in the room
# ---------------------------------------------------------------------------
#
# Three records claim to know whether a room has a guest in it, and until
# HPMS-UAT-16.7.5-B01 the two that were asked were the two that can be wrong.
#
# `Hotel Room.occupancy_status` is a denormalised operational flag. It is what
# the rack renders and what housekeeping works from, and it is maintained by
# whichever service last touched the room. That makes it fast and makes it
# fallible: any path that moves a guest without moving the flag leaves it
# lying, and a *second* guest's checkout will happily set it `Vacant` while the
# first guest is still in the room. That is literally what happened to room 402.
#
# `Reservation Room` is the authoritative record of what was *sold*, and its
# overlap test is departure-exclusive - one guest leaves on the 12th, another
# arrives on the 12th - because that is correct for selling nights. It is not
# correct for asking who is in the bed, because a stay whose departure date is
# today does not overlap an assignment starting today, and the guest has not
# packed yet.
#
# `Stay` is the operational record of a guest in a room, and it is the only one
# of the three that is a statement about a physical body. It is therefore the
# authority for physical occupancy, and this is where that is expressed. The
# other two remain useful and remain checked; neither is trusted alone.


def active_stay_in_room(
	room: str,
	*,
	exclude_stay: str | None = None,
	property_name: str | None = None,
	current: bool = False,
) -> str | None:
	"""The active Stay physically occupying `room`, or None.

	The authoritative answer to "may another guest be put in this room". Named
	for what it returns rather than as a predicate because every caller that
	refuses wants to say *which* stay it refused for, and a bare boolean makes
	that message impossible.

	Active means both halves of `stays.ACTIVE_OCCUPANCY_STATES` and a null
	`checked_out_on`, and both halves are load-bearing. The status is the
	operational truth the desk works from; the timestamp is the one that cannot
	be reached by a workflow transition, so a stay that has been marked departed
	releases its room even if some path left its status behind. The estate audit
	found three stays on this bench whose status and timestamp disagree, so the
	two genuinely do come apart on real data.

	`exclude_stay` is the stay being moved. A room change must not find the
	guest it is moving and refuse to move them.

	`current` decides snapshot or current read, and carries exactly the meaning
	it carries in `availability` and `base`:

	* Left `False` - a plain read, for the pickers and boards that ask this
	  question constantly and must never take a row lock to answer it.
	* Set `True` - a locking read, for a caller that is about to *commit* a
	  guest into this room. Those callers hold the Hotel Room lock while they
	  decide, and **a lock serialises without refreshing**: under REPEATABLE
	  READ a plain read is answered from the view this transaction opened before
	  the rival committed, so the loser of the race still sees the room empty
	  (N1, `services/base.py`). `lock_and_find` is used rather than a plain
	  `get_all` for that reason, and because when it finds nothing it locks the
	  gap - so "no active stay" stays true until this transaction ends.

	Property scoped through `room`, which is unique per property by
	construction, and additionally on `property` when the caller already knows
	it. That is not redundancy for its own sake: the extra column is the one the
	Stay table is indexed on, and passing it keeps the guard cheap on a large
	estate.
	"""
	# Imported inside the function, not at module scope. `services.stays` imports
	# this module, so an eager import here would be circular. The state set lives
	# there because that is where the Stay state machine lives, and there must be
	# exactly one of it.
	from hospitality_pms.services.stays import ACTIVE_OCCUPANCY_STATES, STAY_DOCTYPE

	filters = {
		"room": room,
		"stay_status": ("in", ACTIVE_OCCUPANCY_STATES),
		"checked_out_on": ("is", "not set"),
	}

	if property_name:
		filters["property"] = property_name

	if exclude_stay:
		filters["name"] = ("!=", exclude_stay)

	if current:
		found = lock_and_find(STAY_DOCTYPE, filters, ["name"])

		return found["name"] if found else None

	return frappe.db.get_value(STAY_DOCTYPE, filters, "name")


def assert_room_unoccupied(
	room: str,
	*,
	exclude_stay: str | None = None,
	property_name: str | None = None,
	current: bool = True,
	label: str | None = None,
):
	"""Refuse to place a guest in a room another active Stay is occupying.

	The commit-time guard. Every mutation that can put a body in a physical room
	calls this, under that room's lock, and refuses on its own account - not
	because the picker filtered the room out, and not because the room's flag
	said something. A front-end that offers the wrong room is a usability
	defect; a mutation that accepts it is two guests behind one door.

	Defaults to `current=True`, unlike `active_stay_in_room`. The default is the
	safe one here because every caller of *this* function is by definition
	committing.
	"""
	occupant = active_stay_in_room(
		room, exclude_stay=exclude_stay, property_name=property_name, current=current
	)

	if not occupant:
		return

	label = label or frappe.db.get_value(ROOM_DOCTYPE, room, "room_number") or room

	# Says which stay, because the desk's next question is always "who is in it
	# then", and the answer sends them to the right record. Says nothing about
	# the guest: a room number and a stay id are operational facts, a guest name
	# is personal data and this refusal is reachable by roles that may not read
	# Guest.
	throw(
		_(
			"Room {0} is still occupied by stay {1}, which has not been checked out. "
			"Check that stay out, or choose another room."
		).format(label, occupant),
		exc=RoomNotAssignableError,
	)


def rooms_with_active_stays(property_name: str, *, exclude_stay: str | None = None) -> set[str]:
	"""Every room in the property an active Stay is physically occupying.

	The set form, for the pickers. `get_assignable_rooms` filters a whole room
	list, and asking `active_stay_in_room` per room would turn one query into one
	per room on every render (SAD section 13).

	Carries no date argument, deliberately. Physical occupancy is a fact about
	*now*, so there is no date on which this set is a different set. Whether it
	applies to a given assignment is a separate question, and it belongs to the
	caller: `availability.get_assignable_rooms` owns that rule and documents it.
	Pushing a date in here would invite two callers to answer it differently.

	A plain read on purpose: this feeds a list, and the authority that matters
	re-asks under the lock.
	"""
	from hospitality_pms.services.stays import ACTIVE_OCCUPANCY_STATES, STAY_DOCTYPE

	filters = {
		"property": property_name,
		"stay_status": ("in", ACTIVE_OCCUPANCY_STATES),
		"checked_out_on": ("is", "not set"),
		"room": ("is", "set"),
	}

	if exclude_stay:
		filters["name"] = ("!=", exclude_stay)

	return set(
		frappe.get_all(
			STAY_DOCTYPE,
			filters=filters,
			pluck="room",
			limit_page_length=0,
		)
	)


# ---------------------------------------------------------------------------
# Assignability
# ---------------------------------------------------------------------------


def occupancy_applies(room: str, arrival=None) -> bool:
	"""Whether "somebody is in it now" is a reason to refuse this assignment.

	It is, unless the assignment starts after today: a room occupied this
	morning is a perfectly good room to promise to next Tuesday's arrival.

	Public, and named without the underscore, because it is the single date rule
	shared by both occupancy authorities - the room's own flag here in
	`assert_assignable`, and the active-Stay check in
	`reservations.assign_room`. Two copies of "does today's occupant matter"
	would be two chances to answer it differently.
	"""
	if arrival is None:
		return True

	property_name = frappe.db.get_value(ROOM_DOCTYPE, room, "property")
	business_date = frappe.db.get_value("Property", property_name, "business_date")

	return getdate(arrival) <= getdate(business_date)


def assert_assignable(
	room: str,
	*,
	allow_unready_housekeeping: bool = False,
	state: dict | None = None,
	arrival=None,
):
	"""Raise unless the room can take a guest.

	`allow_unready_housekeeping` is the controlled Vacant Dirty override. It
	relaxes only the housekeeping dimension - never maintenance, inventory,
	occupancy or the active flag, none of which a front desk override may skip.

	`arrival` scopes the occupancy question to when the guest actually needs
	the room. Without it the check means "right now", which is correct for
	check-in and a room change and is the default. Pre-assigning a room for
	next Tuesday is a different question: today's occupant is irrelevant, and
	whether they will still be there on Tuesday is answered by their own
	inventory interval, not by a status field. A full house must still be able
	to pre-assign next week's arrivals.
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

	if occupancy_applies(room, arrival) and state.get("occupancy_status") in OCCUPIED_STATES:
		throw(
			_("Room {0} is already {1}.").format(label, _(state["occupancy_status"])),
			exc=RoomNotAssignableError,
		)

	if not allow_unready_housekeeping and state.get("housekeeping_status") not in READY_HOUSEKEEPING:
		throw(
			_("Room {0} is {1} and is not ready for a guest.").format(label, _(state["housekeeping_status"])),
			exc=RoomNotAssignableError,
		)


def is_assignable(room: str, *, allow_unready_housekeeping: bool = False, state: dict | None = None) -> bool:
	"""Non-raising form of `assert_assignable`, for filtering lists.

	Pass `state` when the caller already holds the room's four dimensions —
	a rack or a board reads every room at once, and re-fetching each one turns
	a single query into five hundred (SAD section 13).
	"""
	try:
		assert_assignable(room, allow_unready_housekeeping=allow_unready_housekeeping, state=state)
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
