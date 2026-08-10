"""Room inventory and Room Rack endpoints.

The rack is the front desk's main visual: every room, its four status
dimensions, and what is wrong with it. It is read constantly, so it is served
as one purpose-built response rather than a page of small requests
(Frontend Standards section 6).
"""

import frappe
from frappe import _

from hospitality_pms.services.base import require_permission
from hospitality_pms.services.property import resolve_property
from hospitality_pms.services.rooms import (
	BLOCKING_INVENTORY,
	BLOCKING_MAINTENANCE,
	OCCUPIED_STATES,
	READY_HOUSEKEEPING,
	get_status_history,
	is_assignable,
)

ROOM_DOCTYPE = "Hotel Room"
ROOM_TYPE_DOCTYPE = "Room Type"

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

	for room in rooms:
		# The row already carries every dimension assignability depends on, so
		# this stays one query for the whole rack rather than one per room.
		room["assignable"] = is_assignable(room["name"], state=room)
		room["blocking_reason"] = _blocking_reason(room)

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


def _blocking_reason(room: dict) -> str | None:
	"""Why this room cannot take a guest, in the order the desk cares about."""
	if not room.get("is_active"):
		return _("Inactive")

	if room.get("maintenance_status") in BLOCKING_MAINTENANCE:
		return _(room["maintenance_status"])

	if room.get("inventory_status") in BLOCKING_INVENTORY:
		return _(room["inventory_status"])

	if room.get("occupancy_status") in OCCUPIED_STATES:
		return _(room["occupancy_status"])

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
	"""One room with its recent status history."""
	require_permission(ROOM_DOCTYPE, "read")

	doc = frappe.get_doc(ROOM_DOCTYPE, room)
	doc.check_permission("read")

	return {
		"room": {field: doc.get(field) for field in RACK_FIELDS},
		"assignable": is_assignable(room),
		"history": get_status_history(room, limit=20),
	}


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

	require_permission(ROOM_DOCTYPE, "read", doc=frappe.get_doc(ROOM_DOCTYPE, room))
	require_dimension_role(dimension, status)

	set_status(room, dimension, status, reason=reason)

	return get_room(room)
