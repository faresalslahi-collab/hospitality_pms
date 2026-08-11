"""Availability endpoints.

Read-only. Nothing here holds inventory - a hold is created by confirming a
reservation, which re-checks availability under a lock (HPMS-0.9.0).
"""

import frappe

from hospitality_pms.services.availability import (
	check_availability,
	get_assignable_rooms,
	get_availability,
)
from hospitality_pms.services.base import require_permission
from hospitality_pms.services.exceptions import AvailabilityError
from hospitality_pms.services.property import resolve_property

ROOM_DOCTYPE = "Hotel Room"


@frappe.whitelist(methods=["GET"])
def search(
	arrival: str,
	departure: str,
	property: str | None = None,
	room_type: str | None = None,
	rooms: int = 1,
	adults: int = 2,
	children: int = 0,
) -> dict:
	"""Availability search for the reservation and front desk screens.

	Returns every room type with its per-night figures, plus a `bookable` flag
	per type so the screen does not have to re-derive the rule that a stay
	needs every night available.
	"""
	require_permission(ROOM_DOCTYPE, "read")
	property_name = resolve_property(property)

	rooms = max(int(rooms or 1), 1)
	adults = max(int(adults or 1), 1)
	children = max(int(children or 0), 0)

	availability = get_availability(property_name, arrival, departure, room_type)

	occupancy = _room_type_occupancy(property_name)

	for type_name, bucket in availability["room_types"].items():
		limits = occupancy.get(type_name, {})
		fits = _fits_occupancy(limits, adults, children)

		bucket.update(limits)
		bucket["requested_rooms"] = rooms
		bucket["fits_occupancy"] = fits
		bucket["bookable"] = bool(fits and bucket["min_available"] >= rooms)

	return availability


def _room_type_occupancy(property_name: str) -> dict[str, dict]:
	rows = frappe.get_all(
		"Room Type",
		filters={"property": property_name, "is_active": 1},
		fields=[
			"name",
			"room_type_name",
			"base_occupancy",
			"max_occupancy",
			"max_adults",
			"max_children",
			"max_extra_beds",
			"base_rate",
			"currency",
			"display_order",
		],
		limit_page_length=0,
	)

	return {row["name"]: row for row in rows}


def _fits_occupancy(limits: dict, adults: int, children: int) -> bool:
	"""Whether the party fits this room type.

	Extra beds are counted as capacity, since that is what they are for.
	"""
	if not limits:
		return False

	max_occupancy = int(limits.get("max_occupancy") or 0) + int(limits.get("max_extra_beds") or 0)

	if adults > int(limits.get("max_adults") or 0):
		return False

	if children > int(limits.get("max_children") or 0) + int(limits.get("max_extra_beds") or 0):
		return False

	return (adults + children) <= max_occupancy


@frappe.whitelist(methods=["GET"])
def check(
	room_type: str,
	arrival: str,
	departure: str,
	property: str | None = None,
	rooms: int = 1,
	allow_overbooking: int = 0,
) -> dict:
	"""Answer whether a specific request can be sold, with the reason if not."""
	require_permission(ROOM_DOCTYPE, "read")
	property_name = resolve_property(property)

	try:
		result = check_availability(
			property_name,
			room_type,
			arrival,
			departure,
			rooms=rooms,
			allow_overbooking=bool(int(allow_overbooking or 0)),
		)
	except AvailabilityError as exc:
		return {"available": False, "reason": frappe.utils.strip_html(str(exc))}

	return {"available": True, **result}


@frappe.whitelist(methods=["GET"])
def assignable_rooms(
	arrival: str,
	departure: str,
	room_type: str | None = None,
	property: str | None = None,
	include_unready: int = 0,
	exclude_line: str | None = None,
) -> list[dict]:
	"""Specific rooms that can be assigned for the whole stay.

	`exclude_line` is the reservation room line being assigned, so a line
	re-picking a room is not shown a list that omits the room it already has.
	"""
	require_permission(ROOM_DOCTYPE, "read")
	property_name = resolve_property(property)

	return get_assignable_rooms(
		property_name,
		room_type,
		arrival,
		departure,
		allow_unready_housekeeping=bool(int(include_unready or 0)),
		exclude_line=exclude_line,
	)
