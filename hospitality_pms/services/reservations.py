"""Reservation lifecycle, pricing and inventory holding.

The rule this module exists to guarantee: **a reservation may only reach a
holding state if, at that exact moment and under a lock, the inventory is
there.** Everything else here supports that.

Concurrency
-----------
Two agents selling the last room at the same instant must not both succeed.
Confirmation locks the Room Type rows first, then re-reads availability, then
writes. Because the lock is held for the rest of the transaction, the second
agent's read happens after the first agent's write and correctly sees zero.

Snapshots
---------
The rate breakdown is stored on the reservation. Re-pricing a confirmed
reservation from today's rate grid would silently change what the guest owes.
"""

import json

import frappe
from frappe import _
from frappe.utils import flt, getdate, now_datetime, nowdate

from hospitality_pms.services.availability import check_availability, lock_room_type, nights_between
from hospitality_pms.services.base import assert_transition, lock_document, require_role
from hospitality_pms.services.exceptions import (
	InvalidStateTransitionError,
	HospitalityPMSError,
	throw,
)
from hospitality_pms.services.property import get_business_date
from hospitality_pms.services.rates import get_cancellation_charge, get_rate_breakdown
from hospitality_pms.services.rooms import assert_assignable

RESERVATION_DOCTYPE = "Hotel Reservation"
RESERVATION_LOG_DOCTYPE = "Hospitality Reservation Log"

DRAFT = "Draft"
TENTATIVE = "Tentative"
CONFIRMED = "Confirmed"
GUARANTEED = "Guaranteed"
WAITLISTED = "Waitlisted"
CHECKED_IN = "Checked In"
CHECKED_OUT = "Checked Out"
CLOSED = "Closed"
CANCELLED = "Cancelled"
NO_SHOW = "No Show"

#: The reservation state machine, from Workflow Matrix section 2.
TRANSITIONS = {
	DRAFT: {TENTATIVE, CONFIRMED, CANCELLED},
	TENTATIVE: {CONFIRMED, WAITLISTED, CANCELLED},
	WAITLISTED: {TENTATIVE, CONFIRMED, CANCELLED},
	CONFIRMED: {GUARANTEED, CHECKED_IN, CANCELLED, NO_SHOW},
	GUARANTEED: {CHECKED_IN, CANCELLED, NO_SHOW},
	CHECKED_IN: {CHECKED_OUT},
	CHECKED_OUT: {CLOSED},
	CLOSED: set(),
	CANCELLED: set(),
	NO_SHOW: {CANCELLED},
}

#: States that consume inventory. Kept in step with the availability engine's
#: HOLDING_RESERVATION_STATES - if these two ever disagree, availability is
#: wrong, so they are asserted equal at import time below.
HOLDING_STATES = (CONFIRMED, GUARANTEED, CHECKED_IN)

#: Cancelling inside the policy window, or after arrival, needs a manager.
CANCEL_OVERRIDE_ROLES = (
	"Front Office Manager",
	"Reservation Manager",
	"Hotel Manager",
	"General Manager",
	"Hospitality Administrator",
	"System Manager",
)

NO_SHOW_ROLES = (
	"Night Auditor",
	"Front Office Manager",
	"Hotel Manager",
	"General Manager",
	"Hospitality Administrator",
	"System Manager",
)


def _assert_states_agree():
	from hospitality_pms.services import availability

	if set(availability.HOLDING_RESERVATION_STATES) != set(HOLDING_STATES):
		raise RuntimeError(
			"Reservation holding states and availability holding states disagree; "
			"availability would be computed against the wrong reservations."
		)


_assert_states_agree()


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------


def price_reservation(doc, *, check_restrictions: bool = True) -> dict:
	"""Resolve and attach the rate snapshot for every room line.

	Called on validate for a reservation that is still editable. Once a
	reservation holds inventory its lines are not re-priced automatically.
	"""
	totals = {"room_charges_total": 0.0, "total_rooms": 0, "total_adults": 0, "total_children": 0}

	# The snapshot is one flat table on the reservation: Frappe has no
	# grandchild tables, so it cannot hang off the room line itself. Each row
	# carries `room_line` to say which line it belongs to.
	doc.set("rate_lines", [])

	for line in doc.rooms:
		breakdown = get_rate_breakdown(
			doc.property,
			line.room_type,
			line.arrival_date or doc.arrival_date,
			line.departure_date or doc.departure_date,
			rate_plan=line.rate_plan or doc.rate_plan,
			adults=line.adults,
			children=line.children,
			extra_beds=line.extra_beds,
			rooms=line.rooms,
			check_restrictions=check_restrictions,
		)

		line.rate_plan = breakdown["rate_plan"]
		line.nights = breakdown["nights"]
		line.room_rate = breakdown["average_nightly_rate"]
		line.total_amount = breakdown["total_amount"]

		for rate_line in breakdown["lines"]:
			doc.append("rate_lines", {**rate_line, "room_line": line.name})

		totals["room_charges_total"] += breakdown["total_amount"]
		totals["total_rooms"] += int(line.rooms or 1)
		totals["total_adults"] += int(line.adults or 0) * int(line.rooms or 1)
		totals["total_children"] += int(line.children or 0) * int(line.rooms or 1)

	doc.room_charges_total = flt(totals["room_charges_total"], 2)
	doc.total_amount = flt(totals["room_charges_total"], 2)
	doc.total_rooms = totals["total_rooms"]
	doc.total_adults = totals["total_adults"]
	doc.total_children = totals["total_children"]

	return totals


def sync_room_lines(doc):
	"""Keep the denormalised fields on Reservation Room in step with the parent.

	Availability filters Reservation Room directly, without joining to the
	reservation, so `property`, `reservation_status` and the dates have to be
	correct on every line or the engine will miscount.
	"""
	for line in doc.rooms:
		line.property = doc.property
		line.reservation_status = doc.reservation_status
		line.arrival_date = line.arrival_date or doc.arrival_date
		line.departure_date = line.departure_date or doc.departure_date
		line.nights = len(nights_between(line.arrival_date, line.departure_date))
		line.rooms = max(int(line.rooms or 1), 1)


def _propagate_status(reservation: str, status: str):
	"""Push a status change down to the room lines already in the database."""
	for line in frappe.get_all("Reservation Room", filters={"parent": reservation}, pluck="name"):
		frappe.db.set_value("Reservation Room", line, "reservation_status", status, update_modified=False)



def _first_night_amount(doc) -> float:
	"""The net rate of the earliest night in the snapshot.

	Read from the stored snapshot, not recomputed, so a first-night charge uses
	the rate the guest was actually sold.
	"""
	if not doc.rate_lines:
		return 0.0

	earliest = min(doc.rate_lines, key=lambda row: getdate(row.rate_date))

	return flt(earliest.net_rate)


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------


def _transition(doc, target: str, *, reason: str | None = None, details: dict | None = None):
	"""Apply a state change: validate, write, propagate, log."""
	assert_transition(doc.reservation_status, target, TRANSITIONS, _("Reservation"))

	previous = doc.reservation_status

	frappe.db.set_value(RESERVATION_DOCTYPE, doc.name, "reservation_status", target, update_modified=True)
	doc.reservation_status = target

	_propagate_status(doc.name, target)

	frappe.get_doc(
		{
			"doctype": RESERVATION_LOG_DOCTYPE,
			"property": doc.property,
			"reservation": doc.name,
			"from_status": previous,
			"to_status": target,
			"changed_by": frappe.session.user,
			"changed_at": now_datetime(),
			"reason": reason,
			"details": json.dumps(details, default=str) if details else None,
		}
	).insert(ignore_permissions=True)

	return target


def confirm(reservation: str, *, allow_overbooking: bool = False, reason: str | None = None) -> str:
	"""Confirm a reservation, holding inventory for every night.

	This is the point where inventory is actually committed, so it is the point
	that has to be race-safe.
	"""
	doc = frappe.get_doc(RESERVATION_DOCTYPE, reservation)
	doc.check_permission("write")

	lock_document(RESERVATION_DOCTYPE, reservation)

	if not doc.rooms:
		throw(_("A reservation must have at least one room line before it can be confirmed."))

	# Lock every room type this reservation touches before reading availability.
	lock_room_type(doc.property, [line.room_type for line in doc.rooms])

	for line in doc.rooms:
		check_availability(
			doc.property,
			line.room_type,
			line.arrival_date,
			line.departure_date,
			rooms=line.rooms,
			allow_overbooking=allow_overbooking,
			exclude_reservation=reservation,
		)

	_transition(
		doc,
		CONFIRMED,
		reason=reason,
		details={"rooms": [{"room_type": line.room_type, "rooms": line.rooms} for line in doc.rooms]},
	)

	frappe.db.set_value(
		RESERVATION_DOCTYPE,
		reservation,
		{"confirmed_on": now_datetime(), "confirmed_by": frappe.session.user},
		update_modified=False,
	)

	return CONFIRMED


def guarantee(reservation: str, guarantee_type: str, *, reason: str | None = None) -> str:
	"""Move a confirmed reservation to guaranteed once its guarantee is in place."""
	doc = frappe.get_doc(RESERVATION_DOCTYPE, reservation)
	doc.check_permission("write")

	if not guarantee_type or guarantee_type == "None":
		throw(_("A guarantee type is required to guarantee a reservation."))

	lock_document(RESERVATION_DOCTYPE, reservation)

	frappe.db.set_value(
		RESERVATION_DOCTYPE,
		reservation,
		{"guarantee_type": guarantee_type, "guaranteed_on": now_datetime()},
		update_modified=False,
	)

	return _transition(doc, GUARANTEED, reason=reason, details={"guarantee_type": guarantee_type})


def make_tentative(reservation: str, *, reason: str | None = None) -> str:
	doc = frappe.get_doc(RESERVATION_DOCTYPE, reservation)
	doc.check_permission("write")

	return _transition(doc, TENTATIVE, reason=reason)


def waitlist(reservation: str, *, reason: str | None = None) -> str:
	doc = frappe.get_doc(RESERVATION_DOCTYPE, reservation)
	doc.check_permission("write")

	return _transition(doc, WAITLISTED, reason=reason)


def cancel(reservation: str, reason: str, *, waive_charge: bool = False) -> dict:
	"""Cancel a reservation and compute what the policy charges.

	A cancellation inside the free window, or after arrival, is a policy
	exception and needs a manager (Roles Matrix section 3).
	"""
	if not reason or not reason.strip():
		throw(_("A reason is required to cancel a reservation."))

	doc = frappe.get_doc(RESERVATION_DOCTYPE, reservation)
	doc.check_permission("write")

	lock_document(RESERVATION_DOCTYPE, reservation)

	first_night = _first_night_amount(doc)

	charge = get_cancellation_charge(
		flt(doc.total_amount),
		doc.cancellation_policy,
		doc.arrival_date,
		first_night_amount=first_night,
	)

	if charge and waive_charge:
		require_role(CANCEL_OVERRIDE_ROLES)
		charge = 0.0

	if getdate(doc.arrival_date) < getdate(get_business_date(doc.property)):
		# Cancelling a reservation whose arrival has already passed is an
		# exception, not routine housekeeping.
		require_role(CANCEL_OVERRIDE_ROLES)

	_transition(doc, CANCELLED, reason=reason, details={"cancellation_charge": charge})

	frappe.db.set_value(
		RESERVATION_DOCTYPE,
		reservation,
		{
			"cancelled_on": now_datetime(),
			"cancelled_by": frappe.session.user,
			"cancellation_reason": reason.strip(),
			"cancellation_charge": charge,
		},
		update_modified=False,
	)

	return {"status": CANCELLED, "cancellation_charge": charge}


def mark_no_show(reservation: str, *, reason: str | None = None) -> dict:
	"""Record a no-show, which the Night Audit normally raises.

	Only allowed once the arrival date has passed relative to the property's
	business date - a guest cannot be a no-show on a day that has not ended.
	"""
	require_role(NO_SHOW_ROLES)

	doc = frappe.get_doc(RESERVATION_DOCTYPE, reservation)
	lock_document(RESERVATION_DOCTYPE, reservation)

	business_date = get_business_date(doc.property)

	if getdate(doc.arrival_date) > getdate(business_date):
		throw(
			_("Reservation {0} arrives on {1}, which is after the business date {2}.").format(
				reservation, getdate(doc.arrival_date), getdate(business_date)
			),
			exc=InvalidStateTransitionError,
		)

	first_night = _first_night_amount(doc)

	charge = get_cancellation_charge(
		flt(doc.total_amount),
		doc.no_show_policy,
		doc.arrival_date,
		first_night_amount=first_night,
	)

	_transition(doc, NO_SHOW, reason=reason, details={"no_show_charge": charge})

	frappe.db.set_value(
		RESERVATION_DOCTYPE,
		reservation,
		{"no_show_on": now_datetime(), "cancellation_charge": charge},
		update_modified=False,
	)

	return {"status": NO_SHOW, "no_show_charge": charge}


# ---------------------------------------------------------------------------
# Room assignment
# ---------------------------------------------------------------------------


def assign_room(reservation: str, room_line: str, room: str, *, allow_unready: bool = False) -> str:
	"""Assign a specific room to a reservation line.

	Locks the room so two reservations cannot be given the same room, and
	re-checks assignability under that lock.
	"""
	doc = frappe.get_doc(RESERVATION_DOCTYPE, reservation)
	doc.check_permission("write")

	line = next((row for row in doc.rooms if row.name == room_line), None)
	if not line:
		throw(_("Room line {0} does not belong to reservation {1}.").format(room_line, reservation))

	lock_document("Hotel Room", room)

	room_property, room_type = frappe.db.get_value("Hotel Room", room, ["property", "room_type"])

	if room_property != doc.property:
		throw(_("Room {0} belongs to another property.").format(room))

	if room_type != line.room_type:
		throw(
			_("Room {0} is a {1}, but this line is for {2}.").format(room, room_type, line.room_type),
		)

	_assert_room_free(room, line.arrival_date, line.departure_date, reservation)
	assert_assignable(room, allow_unready_housekeeping=allow_unready)

	frappe.db.set_value("Reservation Room", room_line, "assigned_room", room, update_modified=False)

	frappe.get_doc(
		{
			"doctype": RESERVATION_LOG_DOCTYPE,
			"property": doc.property,
			"reservation": reservation,
			"from_status": doc.reservation_status,
			"to_status": doc.reservation_status,
			"changed_by": frappe.session.user,
			"changed_at": now_datetime(),
			"reason": _("Room {0} assigned").format(room),
			"details": json.dumps({"room": room, "room_line": room_line}),
		}
	).insert(ignore_permissions=True)

	return room


def _assert_room_free(room: str, arrival, departure, exclude_reservation: str | None = None):
	"""Refuse a room already promised to an overlapping stay.

	Overlap is `arrival < other.departure AND departure > other.arrival`,
	which correctly allows a same-day turnover: one guest departs on the 12th
	and another arrives on the 12th.
	"""
	filters = {
		"assigned_room": room,
		"reservation_status": ("in", HOLDING_STATES),
		"arrival_date": ("<", getdate(departure)),
		"departure_date": (">", getdate(arrival)),
	}

	if exclude_reservation:
		filters["parent"] = ("!=", exclude_reservation)

	clash = frappe.get_all("Reservation Room", filters=filters, fields=["parent"], limit=1)

	if clash:
		throw(
			_("Room {0} is already assigned to reservation {1} for these dates.").format(
				room, clash[0]["parent"]
			),
			exc=HospitalityPMSError,
		)


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


def get_arrivals(property_name: str, on_date=None) -> list[dict]:
	"""Reservations due to arrive on a date."""
	return frappe.get_all(
		RESERVATION_DOCTYPE,
		filters={
			"property": property_name,
			"arrival_date": getdate(on_date or nowdate()),
			"reservation_status": ("in", (CONFIRMED, GUARANTEED)),
		},
		fields=[
			"name",
			"guest",
			"guest_name",
			"arrival_date",
			"departure_date",
			"total_rooms",
			"total_adults",
			"reservation_status",
			"total_amount",
			"deposit_received",
		],
		order_by="guest_name asc",
		limit_page_length=0,
	)


def get_departures(property_name: str, on_date=None) -> list[dict]:
	"""Reservations due to depart on a date."""
	return frappe.get_all(
		RESERVATION_DOCTYPE,
		filters={
			"property": property_name,
			"departure_date": getdate(on_date or nowdate()),
			"reservation_status": CHECKED_IN,
		},
		fields=[
			"name",
			"guest",
			"guest_name",
			"arrival_date",
			"departure_date",
			"total_rooms",
			"reservation_status",
			"total_amount",
		],
		order_by="guest_name asc",
		limit_page_length=0,
	)


def get_unresolved_arrivals(property_name: str, business_date=None) -> list[dict]:
	"""Arrivals that never checked in, for the Night Audit exception list."""
	business_date = getdate(business_date or get_business_date(property_name))

	return frappe.get_all(
		RESERVATION_DOCTYPE,
		filters={
			"property": property_name,
			"arrival_date": ("<=", business_date),
			"reservation_status": ("in", (CONFIRMED, GUARANTEED)),
		},
		fields=["name", "guest_name", "arrival_date", "total_rooms", "reservation_status", "guarantee_type"],
		order_by="arrival_date asc",
		limit_page_length=0,
	)


def find_by_external_reference(property_name: str, external_reference: str) -> str | None:
	"""Duplicate protection for channel imports (SAS section 3.4)."""
	if not external_reference:
		return None

	return frappe.db.get_value(
		RESERVATION_DOCTYPE,
		{
			"property": property_name,
			"external_reference": external_reference,
			"reservation_status": ("not in", (CANCELLED,)),
		},
		"name",
	)
