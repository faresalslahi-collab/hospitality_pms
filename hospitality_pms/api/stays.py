"""Check-in, in-house board and stay operations."""

import frappe

from hospitality_pms.services import front_office as front_office_service
from hospitality_pms.services import stays as service
from hospitality_pms.services.base import authorise_document, require_permission
from hospitality_pms.services.property import resolve_property

STAY_DOCTYPE = "Stay"


@frappe.whitelist(methods=["GET"])
def in_house(property: str | None = None) -> dict:
	"""The in-house board.

	Served by `front_office.get_in_house_board`, which assembles the row from the
	same bulk helpers the arrivals and departures boards use, so a room, a
	balance and a checkout blocker mean the same thing on all three screens.

	The response keeps the shape it has always had - `property`, `stays`,
	`summary`, and `summary` carrying `in_house`, `due_out`, `adults` and
	`children` - because the 16.7.0 frontend is built on it. `stays` is still the
	row list; the rows and the summary have grown, and nothing has been taken away.
	"""
	require_permission(STAY_DOCTYPE, "read")
	property_name = resolve_property(property)

	board = front_office_service.get_in_house_board(property_name)

	return {
		"property": board["property"],
		"business_date": board["business_date"],
		"currency": board["currency"],
		"stays": board["rows"],
		"summary": board["summary"],
	}


@frappe.whitelist(methods=["GET"])
def get_stay(stay: str) -> dict:
	"""One stay with its companions, notes and room history."""
	doc = authorise_document(STAY_DOCTYPE, stay, "read")

	return {
		"stay": {
			"name": doc.name,
			"stay_status": doc.stay_status,
			"guest": doc.guest,
			"guest_name": doc.guest_name,
			"room": doc.room,
			"room_type": doc.room_type,
			"arrival_date": doc.arrival_date,
			"departure_date": doc.departure_date,
			"nights": doc.nights,
			"adults": doc.adults,
			"children": doc.children,
			"folio": doc.folio,
			"reservation": doc.reservation,
			"room_rate": doc.room_rate,
			"currency": doc.currency,
			"readiness_override": doc.readiness_override,
		},
		"companions": [
			{"guest": row.guest, "guest_name": row.guest_name, "is_primary": row.is_primary}
			for row in doc.companions
		],
		"notes": [
			{
				"note_type": row.note_type,
				"note": row.note,
				"noted_by": row.noted_by,
				"noted_on": row.noted_on,
				"is_resolved": row.is_resolved,
			}
			for row in doc.stay_notes
		],
		"room_moves": [
			{
				"from_room": row.from_room,
				"to_room": row.to_room,
				"moved_on": row.moved_on,
				"reason": row.reason,
			}
			for row in doc.room_moves
		],
	}


@frappe.whitelist(methods=["POST"])
def check_in(
	reservation: str,
	room_line: str,
	room: str,
	allow_unready_room: int = 0,
	readiness_reason: str | None = None,
	billing_instructions: str | None = None,
) -> dict:
	"""Check a reservation room line into a room.

	Both permissions are asserted, matching `api.walk_in.create_walk_in`: a
	check-in edits the Reservation *and* creates a Stay, and a role that may do
	only the first has no authority to put a guest in a room. The service
	re-asserts `Stay.create` for callers that do not come through here.
	"""
	authorise_document("Reservation", reservation, "write")
	require_permission(STAY_DOCTYPE, "create")

	return service.check_in(
		reservation,
		room_line,
		room,
		allow_unready_room=bool(int(allow_unready_room or 0)),
		readiness_reason=readiness_reason,
		billing_instructions=billing_instructions,
	)


@frappe.whitelist(methods=["POST"])
def change_room(stay: str, new_room: str, reason: str, allow_unready: int = 0) -> dict:
	authorise_document(STAY_DOCTYPE, stay, "write")

	return service.change_room(
		stay, new_room, reason, allow_unready=bool(int(allow_unready or 0))
	)


@frappe.whitelist(methods=["POST"])
def extend_stay(
	stay: str, new_departure: str, allow_overbooking: int = 0, reason: str | None = None
) -> dict:
	"""Extend a stay. Overbooking, if requested, needs authority and a reason."""
	authorise_document(STAY_DOCTYPE, stay, "write")

	return service.extend_stay(
		stay,
		new_departure,
		allow_overbooking=bool(int(allow_overbooking or 0)),
		reason=reason,
	)


@frappe.whitelist(methods=["POST"])
def shorten_stay(stay: str, new_departure: str, reason: str) -> dict:
	authorise_document(STAY_DOCTYPE, stay, "write")

	return service.shorten_stay(stay, new_departure, reason)


@frappe.whitelist(methods=["POST"])
def add_note(stay: str, note: str, note_type: str = "Operational") -> dict:
	authorise_document(STAY_DOCTYPE, stay, "write")

	service.add_note(stay, note, note_type)

	return get_stay(stay)
