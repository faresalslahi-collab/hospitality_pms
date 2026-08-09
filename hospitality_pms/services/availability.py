"""Availability: what can actually be sold, per night, per room type.

This is the authoritative availability decision (SAS section 3.5). The frontend
may show an optimistic view, but nothing is ever held or confirmed on the
strength of a client-side calculation.

Nights, not days
----------------
A stay from the 10th to the 12th consumes the nights of the 10th and the 11th.
The departure date is never consumed. Every function here works in nights, and
`nights_between` is the single place that rule is expressed.

What consumes inventory
-----------------------
1. Rooms that are not sellable at all - inactive, out of order, out of service,
   under maintenance, or with a blocking inventory status.
2. Room blocks covering the night - either a specific room, or a quantity of a
   room type (maintenance, group holds, house use).
3. Confirmed and in-house reservations. Reservations arrive in HPMS-0.9.0;
   until then `_sold_by_night` returns nothing and the arithmetic still holds.

Overbooking is added back on top, and only up to the property's configured
limit (SAS section 3.5).
"""

from collections import defaultdict
from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import add_days, getdate

from hospitality_pms.services.base import lock_documents
from hospitality_pms.services.exceptions import AvailabilityError, throw
from hospitality_pms.services.property import get_property
from hospitality_pms.services.rooms import BLOCKING_INVENTORY, BLOCKING_MAINTENANCE

ROOM_DOCTYPE = "Hotel Room"
ROOM_TYPE_DOCTYPE = "Room Type"
BLOCK_DOCTYPE = "Room Block"
RESERVATION_ROOM_DOCTYPE = "Reservation Room"

#: Reservation states that hold inventory. Used from HPMS-0.9.0 onward.
HOLDING_RESERVATION_STATES = ("Confirmed", "Guaranteed", "Checked In")


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------


def nights_between(arrival, departure) -> list:
	"""The nights a stay consumes: arrival inclusive, departure exclusive."""
	arrival = getdate(arrival)
	departure = getdate(departure)

	if departure <= arrival:
		throw(
			_("Departure {0} must be after arrival {1}.").format(departure, arrival),
			exc=AvailabilityError,
		)

	nights = []
	current = arrival

	while current < departure:
		nights.append(current)
		current += timedelta(days=1)

	return nights


# ---------------------------------------------------------------------------
# Inventory components
# ---------------------------------------------------------------------------


def _physical_rooms(property_name: str, room_type: str | None = None) -> list[dict]:
	"""Active rooms and their current blocking state."""
	filters = {"property": property_name, "is_active": 1}
	if room_type:
		filters["room_type"] = room_type

	return frappe.get_all(
		ROOM_DOCTYPE,
		filters=filters,
		fields=["name", "room_type", "maintenance_status", "inventory_status", "occupancy_status"],
		limit_page_length=0,
	)


def _is_sellable(room: dict) -> bool:
	"""Whether a room is sellable at all, ignoring dates.

	Housekeeping status is deliberately not consulted: a dirty room is still
	sellable inventory, it just needs cleaning before the guest walks in.
	Treating dirty as unavailable would collapse availability every morning.
	"""
	return (
		room.get("maintenance_status") not in BLOCKING_MAINTENANCE
		and room.get("inventory_status") not in BLOCKING_INVENTORY
	)


def _blocks(property_name: str, arrival, departure, room_type: str | None = None) -> list[dict]:
	"""Submitted, active room blocks overlapping the stay's nights."""
	last_night = add_days(getdate(departure), -1)

	filters = {
		"property": property_name,
		"docstatus": 1,
		"status": "Active",
		"from_date": ("<=", last_night),
		"to_date": (">=", getdate(arrival)),
	}

	blocks = frappe.get_all(
		BLOCK_DOCTYPE,
		filters=filters,
		fields=["name", "room", "room_type", "rooms_blocked", "from_date", "to_date", "block_type"],
		limit_page_length=0,
	)

	if room_type:
		blocks = [b for b in blocks if not b["room_type"] or b["room_type"] == room_type]

	return blocks


def _blocked_by_night(blocks: list[dict], nights: list, rooms_by_name: dict) -> tuple[dict, dict]:
	"""Split blocks into specific-room and quantity effects, per night.

	Specific-room blocks are tracked as a set of room names so they cannot be
	double counted against a room that is already unsellable. Type-level blocks
	are plain quantities.
	"""
	rooms_blocked = defaultdict(set)
	quantity_blocked = defaultdict(lambda: defaultdict(int))

	for block in blocks:
		block_from = getdate(block["from_date"])
		block_to = getdate(block["to_date"])

		for night in nights:
			if not (block_from <= night <= block_to):
				continue

			if block["room"]:
				rooms_blocked[night].add(block["room"])
			elif block["room_type"]:
				quantity_blocked[night][block["room_type"]] += max(int(block["rooms_blocked"] or 1), 1)

	return rooms_blocked, quantity_blocked


def _sold_by_night(
	property_name: str,
	nights: list,
	room_type: str | None = None,
	exclude_reservation: str | None = None,
) -> dict:
	"""Rooms already committed to reservations, per night, per room type.

	Returns an empty result until the reservation build lands, so availability
	is correct at every stage rather than importing a DocType that does not
	exist yet.
	"""
	if not frappe.db.table_exists(RESERVATION_ROOM_DOCTYPE):
		return defaultdict(lambda: defaultdict(int))

	filters = {
		"property": property_name,
		"reservation_status": ("in", HOLDING_RESERVATION_STATES),
		"arrival_date": ("<=", nights[-1]),
		"departure_date": (">", nights[0]),
	}

	if room_type:
		filters["room_type"] = room_type

	if exclude_reservation:
		filters["parent"] = ("!=", exclude_reservation)

	rows = frappe.get_all(
		RESERVATION_ROOM_DOCTYPE,
		filters=filters,
		fields=["room_type", "arrival_date", "departure_date", "rooms"],
		limit_page_length=0,
	)

	sold = defaultdict(lambda: defaultdict(int))

	for row in rows:
		for night in nights_between(row["arrival_date"], row["departure_date"]):
			if night in nights:
				sold[night][row["room_type"]] += int(row.get("rooms") or 1)

	return sold


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_availability(
	property_name: str,
	arrival,
	departure,
	room_type: str | None = None,
	exclude_reservation: str | None = None,
) -> dict:
	"""Availability per night, per room type.

	Returns a structure the search screen and the room rack both render from:

	    {
	      "nights": [...],
	      "room_types": {
	         "DLX": {
	            "physical": 40,
	            "by_night": {date: {"sellable": .., "blocked": .., "sold": .., "available": ..}},
	            "min_available": 12,
	         }
	      }
	    }

	`min_available` is what a booking decision uses: a stay is only sellable if
	every one of its nights has room.
	"""
	nights = nights_between(arrival, departure)
	rooms = _physical_rooms(property_name, room_type)
	rooms_by_name = {room["name"]: room for room in rooms}

	blocks = _blocks(property_name, arrival, departure, room_type)
	rooms_blocked, quantity_blocked = _blocked_by_night(blocks, nights, rooms_by_name)
	sold = _sold_by_night(property_name, nights, room_type, exclude_reservation)

	overbooking = int(get_property(property_name).overbooking_limit or 0)

	by_type: dict[str, dict] = {}

	for room in rooms:
		by_type.setdefault(
			room["room_type"],
			{"physical": 0, "sellable_rooms": set(), "by_night": {}, "min_available": None},
		)
		by_type[room["room_type"]]["physical"] += 1

		if _is_sellable(room):
			by_type[room["room_type"]]["sellable_rooms"].add(room["name"])

	for type_name, bucket in by_type.items():
		for night in nights:
			# A room blocked for this night is removed from the sellable set,
			# which keeps a block on an already out-of-order room from being
			# counted twice.
			sellable = bucket["sellable_rooms"] - rooms_blocked.get(night, set())

			blocked_count = len(bucket["sellable_rooms"]) - len(sellable)
			quantity = quantity_blocked.get(night, {}).get(type_name, 0)
			sold_count = sold.get(night, {}).get(type_name, 0)

			available = len(sellable) - quantity - sold_count

			bucket["by_night"][str(night)] = {
				"sellable": len(sellable),
				"blocked": blocked_count + quantity,
				"sold": sold_count,
				"available": max(available, 0),
				"available_with_overbooking": max(available + overbooking, 0),
			}

			current_min = bucket["min_available"]
			bucket["min_available"] = available if current_min is None else min(current_min, available)

		bucket["min_available"] = max(bucket["min_available"] or 0, 0)
		bucket["overbooking_limit"] = overbooking
		# The set is an implementation detail; do not ship it to the client.
		del bucket["sellable_rooms"]

	return {
		"property": property_name,
		"arrival": str(getdate(arrival)),
		"departure": str(getdate(departure)),
		"nights": [str(night) for night in nights],
		"room_types": by_type,
	}


def check_availability(
	property_name: str,
	room_type: str,
	arrival,
	departure,
	rooms: int = 1,
	*,
	allow_overbooking: bool = False,
	exclude_reservation: str | None = None,
) -> dict:
	"""Raise unless `rooms` of `room_type` can be sold for every night.

	Callers that are about to commit inventory must hold the room-type row
	first - see `lock_room_type`. Checking without locking is fine for a
	search, never for a confirmation.
	"""
	rooms = max(int(rooms or 1), 1)

	availability = get_availability(
		property_name, arrival, departure, room_type, exclude_reservation=exclude_reservation
	)

	bucket = availability["room_types"].get(room_type)

	if not bucket:
		throw(
			_("Room type {0} has no active rooms in property {1}.").format(room_type, property_name),
			exc=AvailabilityError,
		)

	limit_key = "available_with_overbooking" if allow_overbooking else "available"
	overbooking = bucket.get("overbooking_limit", 0)

	for night, figures in bucket["by_night"].items():
		if figures[limit_key] < rooms:
			throw(
				_("Only {0} room(s) of type {1} are available on {2}; {3} requested.").format(
					figures[limit_key], room_type, night, rooms
				),
				exc=AvailabilityError,
			)

	return {
		"room_type": room_type,
		"rooms": rooms,
		"min_available": bucket["min_available"],
		"overbooking_limit": overbooking,
	}


def lock_room_type(property_name: str, room_types) -> list[str]:
	"""Serialise inventory decisions for one or more room types.

	Two agents confirming the last room at the same moment must not both read
	"1 available". Locking the Room Type rows makes the read-check-write
	sequence atomic for the rest of the transaction; sorting the keys keeps
	concurrent multi-type bookings from deadlocking (HPMS-DEC-053).
	"""
	if isinstance(room_types, str):
		room_types = [room_types]

	return lock_documents(ROOM_TYPE_DOCTYPE, room_types)


def get_assignable_rooms(
	property_name: str,
	room_type: str | None,
	arrival,
	departure,
	*,
	allow_unready_housekeeping: bool = False,
) -> list[dict]:
	"""Specific rooms that can be assigned for the whole stay.

	Used by room assignment at confirmation and check-in. A room is offered
	only if it is sellable, unblocked for every night, and - unless overridden
	- physically ready.
	"""
	from hospitality_pms.services.rooms import READY_HOUSEKEEPING

	nights = nights_between(arrival, departure)
	rooms = _physical_rooms(property_name, room_type)

	blocks = _blocks(property_name, arrival, departure, room_type)
	rooms_blocked, _quantity = _blocked_by_night(blocks, nights, {r["name"]: r for r in rooms})

	blocked_any_night = set()
	for night in nights:
		blocked_any_night |= rooms_blocked.get(night, set())

	candidates = []

	for room in rooms:
		if not _is_sellable(room) or room["name"] in blocked_any_night:
			continue

		details = frappe.db.get_value(
			ROOM_DOCTYPE,
			room["name"],
			["name", "room_number", "room_type", "floor", "housekeeping_status", "is_accessible", "is_smoking"],
			as_dict=True,
		)

		details["ready"] = details["housekeeping_status"] in READY_HOUSEKEEPING

		if not details["ready"] and not allow_unready_housekeeping:
			continue

		candidates.append(details)

	return sorted(candidates, key=lambda row: row["room_number"] or "")
