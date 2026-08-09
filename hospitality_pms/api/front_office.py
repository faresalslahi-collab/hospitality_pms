"""Front Office board endpoints for the operational frontend.

Read-only, every one of them. These four responses are what the dashboard, the
arrivals board, the departures board and the reservation calendar render; not
one of them changes anything. Check-in, checkout, room assignment and folio
posting keep going through their own services, which own the locking, the
audit trail and the right to say no (SAD section 6).

Each endpoint resolves the property through `resolve_property`, so a user who
asks for a property they cannot operate in is refused here rather than being
quietly served another property's day.
"""

import frappe

from hospitality_pms.services import front_office as service
from hospitality_pms.services.base import require_permission
from hospitality_pms.services.property import resolve_property

RESERVATION_DOCTYPE = "Reservation"
STAY_DOCTYPE = "Stay"
ROOM_DOCTYPE = "Hotel Room"


@frappe.whitelist(methods=["GET"])
def dashboard(property: str | None = None, on_date: str | None = None) -> dict:
	"""The whole front office dashboard in one request.

	One aggregate rather than a dozen small calls: this screen is open on every
	terminal for the length of a shift, and its request count is multiplied by
	every desk in the hotel (Frontend Standards section 6).
	"""
	require_permission(ROOM_DOCTYPE, "read")
	require_permission(STAY_DOCTYPE, "read")

	return service.get_dashboard(resolve_property(property), on_date)


@frappe.whitelist(methods=["GET"])
def arrivals(property: str | None = None, on_date: str | None = None) -> dict:
	"""The arrivals board: one row per room to be checked in today."""
	require_permission(RESERVATION_DOCTYPE, "read")

	return service.get_arrivals_board(resolve_property(property), on_date)


@frappe.whitelist(methods=["GET"])
def departures(property: str | None = None, on_date: str | None = None) -> dict:
	"""The departures board: one row per stay leaving today, and what blocks it."""
	require_permission(STAY_DOCTYPE, "read")

	return service.get_departures_board(resolve_property(property), on_date)


@frappe.whitelist(methods=["GET"])
def calendar(
	property: str | None = None,
	from_date: str | None = None,
	to_date: str | None = None,
	room_type: str | None = None,
	start: int = 0,
	limit: int = 25,
) -> dict:
	"""A page of rooms, across a bounded date window, with what occupies them."""
	require_permission(ROOM_DOCTYPE, "read")
	require_permission(RESERVATION_DOCTYPE, "read")

	return service.get_calendar(
		resolve_property(property),
		from_date=from_date,
		to_date=to_date,
		room_type=room_type,
		start=start,
		limit=limit,
	)
