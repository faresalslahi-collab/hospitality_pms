"""Room inventory and Room Rack endpoints.

The rack is the front desk's main visual: every room, its four status
dimensions, and what is wrong with it. It is read constantly, so it is served
as one purpose-built response rather than a page of small requests
(Frontend Standards section 6).
"""

import frappe
from frappe import _

from hospitality_pms.services.base import authorise_document, require_permission
from hospitality_pms.services.property import resolve_property
from hospitality_pms.services.rooms import (
	BLOCKING_INVENTORY,
	BLOCKING_MAINTENANCE,
	OCCUPIED_STATES,
	READY_HOUSEKEEPING,
	get_status_history,
	is_assignable_now,
	rooms_with_active_stays,
)

ROOM_DOCTYPE = "Hotel Room"
ROOM_TYPE_DOCTYPE = "Room Type"
LOG_DOCTYPE = "Room Status Log"

RACK_FIELDS = (
	"name",
	"room_number",
	"room_type",
	"building",
	"wing",
	"floor",
	"zone",
	"is_active",
	"occupancy_status",
	"housekeeping_status",
	"maintenance_status",
	"inventory_status",
	"is_smoking",
	"is_accessible",
	"view_type",
	"housekeeping_credits",
)


@frappe.whitelist(methods=["GET"])
def get_room_rack(property: str | None = None, room_type: str | None = None) -> dict:
	"""Current state of every room in a property, grouped by room type."""
	require_permission(ROOM_DOCTYPE, "read")
	property_name = resolve_property(property)

	filters = {"property": property_name}
	if room_type:
		filters["room_type"] = room_type

	rooms = frappe.get_all(
		ROOM_DOCTYPE,
		filters=filters,
		fields=list(RACK_FIELDS),
		order_by="room_type asc, room_number asc",
		limit_page_length=0,
	)

	types = frappe.get_all(
		ROOM_TYPE_DOCTYPE,
		filters={"property": property_name, "is_active": 1},
		fields=["name", "room_type_name", "display_order", "base_occupancy", "max_occupancy"],
		order_by="display_order asc, room_type_name asc",
		limit_page_length=0,
	)

	grouped = {room_type_row["name"]: {**room_type_row, "rooms": []} for room_type_row in types}
	floors = _floor_labels(property_name)

	# Who is physically in a room, for the whole property, in **one** query.
	#
	# The rack used to derive its badge from `occupancy_status` alone, and R1A left
	# it that way on purpose: every path that *places* a guest had been made to
	# check active Stay occupancy, so a stale flag could no longer cause double
	# occupancy. What it could still do was advertise a room the desk cannot have -
	# room 402 and the five Due Out rooms the estate audit found all read as
	# assignable here while a guest was in them.
	#
	# Read once, outside the loop, and passed into each row. Asking per room would
	# turn the rack into one query per room on a screen that is open all shift on
	# every terminal (Frontend Standards section 6, SAD section 13).
	occupied_now = rooms_with_active_stays(property_name)

	for room in rooms:
		# The row already carries every dimension assignability depends on, so
		# this stays one query for the whole rack rather than one per room.
		room["assignable"] = is_assignable_now(
			room["name"], state=room, occupied_rooms=occupied_now
		)
		room["blocking_reason"] = _blocking_reason(room, occupied_rooms=occupied_now)

		# `floor` is a link, and its name is a code the property chose - which
		# is not necessarily anything a guest or a housekeeper would recognise.
		# The rack sends the floor's own name and level alongside it so the
		# screens can label and order by what the floor is called and where it
		# is in the building, rather than by how its code happens to sort.
		floor = floors.get(room.get("floor")) or {}
		room["floor_name"] = floor.get("floor_name") or room.get("floor")
		room["floor_level"] = floor.get("floor_level")

		bucket = grouped.setdefault(
			room["room_type"],
			{"name": room["room_type"], "room_type_name": room["room_type"], "rooms": []},
		)
		bucket["rooms"].append(room)

	return {
		"property": property_name,
		"room_types": list(grouped.values()),
		"summary": summarise(rooms),
	}


def _floor_labels(property_name: str) -> dict[str, dict]:
	"""Every floor in the property, keyed by the value a room stores."""
	return {
		row["name"]: row
		for row in frappe.get_all(
			"Floor",
			filters={"property": property_name},
			fields=["name", "floor_name", "floor_level"],
			limit_page_length=0,
		)
	}


def _blocking_reason(room: dict, *, occupied_rooms: set[str] | None = None) -> str | None:
	"""Why this room cannot take a guest, in the order the desk cares about."""
	if not room.get("is_active"):
		return _("Inactive")

	if room.get("maintenance_status") in BLOCKING_MAINTENANCE:
		return _(room["maintenance_status"])

	if room.get("inventory_status") in BLOCKING_INVENTORY:
		return _(room["inventory_status"])

	if room.get("occupancy_status") in OCCUPIED_STATES:
		return _(room["occupancy_status"])

	# A guest who is in the room even though the flag does not say so. Reported
	# as Occupied, which is what the desk needs to read off the rack, and
	# deliberately *not* as "the flag is wrong": the rack is an operational
	# screen, not a data-quality report, and the stale flag is a known estate
	# item carried forward for a separate decision. Named without the stay id -
	# the rack is open to fourteen roles and a stay id is Stay's to disclose,
	# not Hotel Room's.
	if occupied_rooms is not None and room.get("name") in occupied_rooms:
		return _("Occupied")

	if room.get("housekeeping_status") not in READY_HOUSEKEEPING:
		return _(room["housekeeping_status"])

	return None


def summarise(rooms: list[dict]) -> dict:
	"""Counts the front office dashboard needs, computed once here."""
	summary = {
		"total": len(rooms),
		"occupied": 0,
		"vacant": 0,
		"ready": 0,
		"dirty": 0,
		"out_of_order": 0,
		"blocked": 0,
		"assignable": 0,
	}

	for room in rooms:
		if room.get("occupancy_status") in OCCUPIED_STATES:
			summary["occupied"] += 1
		elif room.get("occupancy_status") == "Vacant":
			summary["vacant"] += 1

		if room.get("housekeeping_status") in READY_HOUSEKEEPING:
			summary["ready"] += 1
		elif room.get("housekeeping_status") == "Dirty":
			summary["dirty"] += 1

		if room.get("maintenance_status") == "Out of Order":
			summary["out_of_order"] += 1

		if room.get("inventory_status") in BLOCKING_INVENTORY:
			summary["blocked"] += 1

		if room.get("assignable"):
			summary["assignable"] += 1

	return summary


@frappe.whitelist(methods=["GET"])
def get_room(room: str) -> dict:
	"""One room, with its recent status history if the caller may read the log."""
	# `authorise_document` rather than `require_permission` + `check_permission`
	# (16.7.5-R1B). The two-step form this used is the pattern the app declared
	# insufficient: a User Permission created without `apply_to_all_doctypes`
	# restricts only the DocTypes it names, so `check_permission` can legitimately
	# pass for a room in a property the caller may not operate in. Hotel Room
	# carries a required `property`, so the third check always fires - and it is
	# resolved from the record, never from the request, so naming another
	# property's room is not a way in.
	doc = authorise_document(ROOM_DOCTYPE, room, "read")

	payload = {
		"room": {field: doc.get(field) for field in RACK_FIELDS},
		"assignable": is_assignable_now(
			room, state={"property": doc.property, **{f: doc.get(f) for f in RACK_FIELDS}}
		),
	}

	# The status log is a different DocType with a deliberately narrower reader
	# set, and this endpoint used to hand it over on Hotel Room read alone.
	#
	# `Room Status Log` is described in `setup/permissions.py` as a technical
	# record "hidden from ordinary operational users", and it is read by nine
	# roles where Hotel Room is read by twenty-three. The fourteen in between -
	# among them Room Attendant, Kitchen User and Accounts User - were receiving
	# `changed_by`, `reason` and `reference_doctype`/`reference_name` for every
	# transition, and `reason` is free text a manager writes when taking a room
	# out of order.
	#
	# The key is **omitted**, not set to `[]`. An empty list is a claim that this
	# room has no history, which is a different statement from "you may not be
	# told its history", and the frontend already distinguishes them: the room
	# dialog renders on `detail.data?.history?.length`, so an absent key degrades
	# to no history section rather than to a false "nothing ever happened here".
	#
	# Gated here at the controller boundary rather than inside
	# `rooms.get_status_history`, for the reason `authorise_document` records: the
	# same service is reachable from paths that do not act for a session user.
	if frappe.has_permission(LOG_DOCTYPE, "read"):
		payload["history"] = get_status_history(room, limit=20)

	return payload


@frappe.whitelist(methods=["POST"])
def set_room_status(
	room: str,
	dimension: str,
	status: str,
	reason: str | None = None,
) -> dict:
	"""Change one status dimension from the operational frontend.

	Authorisation is per dimension rather than blanket write access on the
	room: a Room Attendant must be able to finish cleaning a room without
	being able to rename it or take it out of sale.
	"""
	from hospitality_pms.services.rooms import require_dimension_role, set_status

	# `authorise_document` for the same reason as `get_room` (16.7.5-R1B), and it
	# matters more here because this one writes.
	#
	# `require_dimension_role` below is a global role test with no property
	# dimension at all, so before this line the only property-aware check on a
	# *mutation* was whatever the document check happened to catch. A Housekeeping
	# Manager restricted to property A could mark a room clean in property B - and
	# `set_status` writes a Room Status Log row with `ignore_permissions=True`, so
	# the foreign property gained an audit entry naming an operator who has no
	# business in it.
	#
	# Still `read` and not `write`: status changes are deliberately not gated on
	# Hotel Room write, because a Room Attendant must be able to finish cleaning a
	# room without being able to rename it or take it out of sale. The write
	# authority is `require_dimension_role`, per dimension. What was missing was
	# the property, not the verb.
	authorise_document(ROOM_DOCTYPE, room, "read")
	require_dimension_role(dimension, status)

	set_status(room, dimension, status, reason=reason)

	return get_room(room)
