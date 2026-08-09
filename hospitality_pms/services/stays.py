"""Check-in, stay management and the in-house board.

Check-in is the moment a booking becomes a physical guest in a physical room.
It touches four things that must all move together or not at all: the
reservation status, the room's occupancy, a new Stay record and a new Folio.
Everything here runs inside the caller's transaction so a failure half way
cannot leave a guest checked in with no folio to charge.
"""

import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate, now_datetime

from hospitality_pms.services import folio as folio_service
from hospitality_pms.services import reservations as reservation_service
from hospitality_pms.services import rooms as room_service
from hospitality_pms.services.availability import check_availability, nights_between
from hospitality_pms.services.base import assert_transition, lock_document, require_role
from hospitality_pms.services.exceptions import (
	HospitalityPMSError,
	InvalidStateTransitionError,
	throw,
)
from hospitality_pms.services.guests import assert_not_blacklisted
from hospitality_pms.services.property import get_business_date, get_property

STAY_DOCTYPE = "Stay"

EXPECTED = "Expected"
IN_HOUSE = "In House"
DUE_OUT = "Due Out"
CHECKED_OUT = "Checked Out"
CLOSED = "Closed"

#: Stay state machine, from Workflow Matrix section 3.
TRANSITIONS = {
	EXPECTED: {IN_HOUSE},
	IN_HOUSE: {DUE_OUT, CHECKED_OUT},
	DUE_OUT: {CHECKED_OUT, IN_HOUSE},
	CHECKED_OUT: {CLOSED, IN_HOUSE},
	CLOSED: set(),
}

#: Checking a guest into a room that is not clean is a manager decision, and
#: the reason is recorded on the stay (SAS section 3.2).
READINESS_OVERRIDE_ROLES = (
	"Front Office Manager",
	"Hotel Manager",
	"General Manager",
	"Hospitality Administrator",
	"System Manager",
)

#: Reversing a checkout re-opens settled money, so it needs both front office
#: and finance authority (Workflow Matrix section 3).
CHECKOUT_REVERSAL_ROLES = (
	"Front Office Manager",
	"Finance Manager",
	"Hotel Manager",
	"General Manager",
	"Hospitality Administrator",
	"System Manager",
)


# ---------------------------------------------------------------------------
# Check-in
# ---------------------------------------------------------------------------


def check_in(
	reservation: str,
	room_line: str,
	room: str,
	*,
	allow_unready_room: bool = False,
	readiness_reason: str | None = None,
	skip_id_check: bool = False,
	companions: list[dict] | None = None,
	billing_instructions: str | None = None,
) -> dict:
	"""Check a reservation's room line into a specific room.

	Returns the stay and folio it created. Safe to call twice: the second call
	finds the line already checked in and refuses rather than creating a second
	stay for the same guest.
	"""
	reservation_doc = frappe.get_doc(reservation_service.RESERVATION_DOCTYPE, reservation)
	reservation_doc.check_permission("write")

	lock_document(reservation_service.RESERVATION_DOCTYPE, reservation)
	lock_document("Hotel Room", room)

	line = next((row for row in reservation_doc.rooms if row.name == room_line), None)
	if not line:
		throw(_("Room line {0} does not belong to reservation {1}.").format(room_line, reservation))

	if frappe.db.exists(STAY_DOCTYPE, {"reservation_room_line": room_line, "stay_status": ("!=", CLOSED)}):
		throw(
			_("This room line is already checked in."),
			exc=InvalidStateTransitionError,
		)

	_assert_reservation_ready(reservation_doc)
	_assert_arrival_is_due(reservation_doc)

	if reservation_doc.guest:
		assert_not_blacklisted(reservation_doc.guest)

	if not skip_id_check:
		_assert_identity_captured(reservation_doc.property, reservation_doc.guest)

	_assert_deposit_satisfied(reservation_doc)

	# Room readiness. The override relaxes housekeeping only, and is recorded.
	if allow_unready_room:
		require_role(READINESS_OVERRIDE_ROLES)

		if not readiness_reason or not readiness_reason.strip():
			throw(_("A reason is required to check in to a room that is not ready."))

		if not get_property(reservation_doc.property).allow_vacant_dirty_check_in:
			throw(
				_("This property does not permit check-in to a room that is not ready."),
				exc=HospitalityPMSError,
			)

	room_service.assert_assignable(room, allow_unready_housekeeping=allow_unready_room)

	# Assigning through the reservation service re-checks the clash rules.
	if line.assigned_room != room:
		reservation_service.assign_room(reservation, room_line, room, allow_unready=allow_unready_room)

	stay = frappe.get_doc(
		{
			"doctype": STAY_DOCTYPE,
			"property": reservation_doc.property,
			"stay_status": EXPECTED,
			"reservation": reservation,
			"reservation_room_line": room_line,
			"guest": reservation_doc.guest,
			"room": room,
			"room_type": line.room_type,
			"arrival_date": line.arrival_date,
			"departure_date": line.departure_date,
			"nights": len(nights_between(line.arrival_date, line.departure_date)),
			"adults": line.adults,
			"children": line.children,
			"extra_beds": line.extra_beds,
			"rate_plan": line.rate_plan,
			"room_rate": line.room_rate,
			"readiness_override": 1 if allow_unready_room else 0,
			"readiness_override_reason": readiness_reason,
			"special_requests": line.special_requests or reservation_doc.special_requests,
		}
	).insert(ignore_permissions=True)

	for companion in companions or []:
		stay.append("companions", companion)

	if companions:
		stay.save(ignore_permissions=True)

	folio = folio_service.open_folio(
		reservation_doc.property,
		reservation_doc.guest,
		stay=stay.name,
		reservation=reservation,
		room=room,
		billing_instructions=billing_instructions or reservation_doc.internal_notes,
	)

	frappe.db.set_value(
		STAY_DOCTYPE,
		stay.name,
		{
			"folio": folio,
			"stay_status": IN_HOUSE,
			"checked_in_on": now_datetime(),
			"checked_in_by": frappe.session.user,
		},
		update_modified=True,
	)

	room_service.mark_occupied(
		room, reference_doctype=STAY_DOCTYPE, reference_name=stay.name
	)

	# The reservation follows only once every one of its lines is in house;
	# a multi-room booking is not checked in until the whole party arrives.
	if _all_lines_checked_in(reservation):
		reservation_service._transition(
			reservation_doc,
			reservation_service.CHECKED_IN,
			reason=_("Guest checked in"),
			details={"stay": stay.name, "room": room},
		)
		frappe.db.set_value(
			reservation_service.RESERVATION_DOCTYPE,
			reservation,
			"checked_in_on",
			now_datetime(),
			update_modified=False,
		)

	# Any deposit already taken on the reservation moves onto the folio, so
	# the guest is not asked to pay it twice.
	deposit = flt(reservation_doc.deposit_received)
	if deposit > 0:
		folio_service.post_payment(
			folio,
			deposit,
			"Bank Transfer",
			payment_type="Deposit",
			idempotency_key=f"reservation-deposit:{reservation}",
			reference=reservation,
		)

	return {"stay": stay.name, "folio": folio, "room": room}


def _assert_reservation_ready(doc):
	if doc.reservation_status not in (reservation_service.CONFIRMED, reservation_service.GUARANTEED):
		throw(
			_("Reservation {0} is {1} and cannot be checked in.").format(doc.name, _(doc.reservation_status)),
			exc=InvalidStateTransitionError,
		)


def _assert_arrival_is_due(doc):
	"""A guest cannot check in before the business date reaches their arrival."""
	business_date = get_business_date(doc.property)

	if getdate(doc.arrival_date) > getdate(business_date):
		throw(
			_("Reservation {0} arrives on {1}; the business date is {2}.").format(
				doc.name, getdate(doc.arrival_date), getdate(business_date)
			),
			exc=InvalidStateTransitionError,
		)


def _assert_identity_captured(property_name: str, guest: str | None):
	"""Refuse check-in without an identification document when required."""
	if not get_property(property_name).require_id_at_check_in:
		return

	if not guest:
		throw(_("A guest record is required to check in."))

	has_id = frappe.db.exists(
		"Guest Identification",
		{"parent": guest, "parenttype": "Guest"},
	)

	if not has_id:
		throw(
			_("This property requires guest identification before check-in."),
			exc=HospitalityPMSError,
		)


def _assert_deposit_satisfied(doc):
	"""Refuse check-in when a required deposit has not been received."""
	required = flt(doc.deposit_required)

	if required <= 0:
		return

	if flt(doc.deposit_received) + 0.005 < required:
		throw(
			_("A deposit of {0} is required; {1} has been received.").format(
				required, flt(doc.deposit_received)
			),
			exc=HospitalityPMSError,
		)


def _all_lines_checked_in(reservation: str) -> bool:
	lines = frappe.get_all("Reservation Room", filters={"parent": reservation}, pluck="name")

	checked_in = frappe.get_all(
		STAY_DOCTYPE,
		filters={
			"reservation": reservation,
			"stay_status": ("in", (IN_HOUSE, DUE_OUT, CHECKED_OUT)),
		},
		pluck="reservation_room_line",
	)

	return set(lines).issubset(set(filter(None, checked_in)))


# ---------------------------------------------------------------------------
# Stay operations
# ---------------------------------------------------------------------------


def change_room(stay: str, new_room: str, reason: str, *, allow_unready: bool = False) -> dict:
	"""Move an in-house guest to another room.

	Both rooms are locked, in a deterministic order, so two simultaneous moves
	cannot cross over each other.
	"""
	if not reason or not reason.strip():
		throw(_("A reason is required to change room."))

	doc = frappe.get_doc(STAY_DOCTYPE, stay)
	doc.check_permission("write")

	if doc.stay_status not in (IN_HOUSE, DUE_OUT):
		throw(
			_("Only an in-house stay can change room; this stay is {0}.").format(_(doc.stay_status)),
			exc=InvalidStateTransitionError,
		)

	if new_room == doc.room:
		throw(_("The guest is already in room {0}.").format(new_room))

	for room in sorted([doc.room, new_room]):
		lock_document("Hotel Room", room)

	room_service.assert_assignable(new_room, allow_unready_housekeeping=allow_unready)

	new_property, new_type = frappe.db.get_value("Hotel Room", new_room, ["property", "room_type"])
	if new_property != doc.property:
		throw(_("Room {0} belongs to another property.").format(new_room))

	previous_room = doc.room

	# The vacated room becomes dirty; the new room becomes occupied.
	room_service.set_statuses(
		previous_room,
		{room_service.OCCUPANCY: "Vacant", room_service.HOUSEKEEPING: "Dirty"},
		reason=_("Guest moved to room {0}").format(new_room),
		reference_doctype=STAY_DOCTYPE,
		reference_name=stay,
	)
	room_service.mark_occupied(new_room, reference_doctype=STAY_DOCTYPE, reference_name=stay)

	doc.append(
		"room_moves",
		{
			"from_room": previous_room,
			"to_room": new_room,
			"moved_on": now_datetime(),
			"moved_by": frappe.session.user,
			"reason": reason.strip(),
		},
	)
	doc.room = new_room
	doc.room_type = new_type
	doc.save(ignore_permissions=True)

	if doc.folio:
		frappe.db.set_value(folio_service.FOLIO_DOCTYPE, doc.folio, "room", new_room, update_modified=False)

	return {"stay": stay, "from_room": previous_room, "to_room": new_room}


def extend_stay(stay: str, new_departure, *, allow_overbooking: bool = False) -> dict:
	"""Extend a stay, but only if the room type is free for the extra nights."""
	doc = frappe.get_doc(STAY_DOCTYPE, stay)
	doc.check_permission("write")

	if doc.stay_status not in (IN_HOUSE, DUE_OUT):
		throw(
			_("Only an in-house stay can be extended; this stay is {0}.").format(_(doc.stay_status)),
			exc=InvalidStateTransitionError,
		)

	new_departure = getdate(new_departure)
	current_departure = getdate(doc.departure_date)

	if new_departure <= current_departure:
		throw(_("The new departure must be after the current departure of {0}.").format(current_departure))

	lock_document(STAY_DOCTYPE, stay)

	# Only the added nights are checked; the nights already in house are the
	# guest's by right.
	check_availability(
		doc.property,
		doc.room_type,
		current_departure,
		new_departure,
		rooms=1,
		allow_overbooking=allow_overbooking,
	)

	# The specific room must also be free for the extra nights.
	reservation_service._assert_room_free(doc.room, current_departure, new_departure, doc.reservation)

	doc.departure_date = new_departure
	doc.nights = len(nights_between(doc.arrival_date, new_departure))

	if doc.stay_status == DUE_OUT:
		doc.stay_status = IN_HOUSE

	doc.save(ignore_permissions=True)

	_log_note(doc, _("Stay extended to {0}").format(new_departure))

	return {"stay": stay, "departure_date": str(new_departure), "nights": doc.nights}


def shorten_stay(stay: str, new_departure, reason: str) -> dict:
	"""Shorten a stay. Releases the nights the guest is no longer taking."""
	if not reason or not reason.strip():
		throw(_("A reason is required to shorten a stay."))

	doc = frappe.get_doc(STAY_DOCTYPE, stay)
	doc.check_permission("write")

	new_departure = getdate(new_departure)

	if new_departure <= getdate(doc.arrival_date):
		throw(_("The departure must be after the arrival date."))

	if new_departure >= getdate(doc.departure_date):
		throw(_("The new departure must be before the current departure."))

	business_date = get_business_date(doc.property)
	if new_departure < getdate(business_date):
		throw(_("A stay cannot be shortened to a date before the business date."))

	lock_document(STAY_DOCTYPE, stay)

	doc.departure_date = new_departure
	doc.nights = len(nights_between(doc.arrival_date, new_departure))
	doc.save(ignore_permissions=True)

	_log_note(doc, _("Stay shortened to {0}: {1}").format(new_departure, reason.strip()))

	return {"stay": stay, "departure_date": str(new_departure), "nights": doc.nights}


def add_companion(stay: str, companion: dict) -> str:
	doc = frappe.get_doc(STAY_DOCTYPE, stay)
	doc.check_permission("write")

	doc.append("companions", companion)
	doc.save(ignore_permissions=True)

	return stay


def add_note(stay: str, note: str, note_type: str = "Operational") -> str:
	"""Record an operational note on the stay, for shift handover."""
	doc = frappe.get_doc(STAY_DOCTYPE, stay)
	doc.check_permission("write")

	_log_note(doc, note, note_type)
	doc.save(ignore_permissions=True)

	return stay


def _log_note(doc, note: str, note_type: str = "Operational"):
	doc.append(
		"stay_notes",
		{
			"note_type": note_type,
			"note": note,
			"noted_by": frappe.session.user,
			"noted_on": now_datetime(),
		},
	)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


def transition(stay: str, target: str, *, reason: str | None = None) -> str:
	"""Move a stay's state against the approved machine."""
	lock_document(STAY_DOCTYPE, stay)

	doc = frappe.get_doc(STAY_DOCTYPE, stay)

	if doc.stay_status == CHECKED_OUT and target == IN_HOUSE:
		require_role(CHECKOUT_REVERSAL_ROLES)

		if not reason or not reason.strip():
			throw(_("A reason is required to reverse a checkout."))

	assert_transition(doc.stay_status, target, TRANSITIONS, _("Stay"))

	frappe.db.set_value(STAY_DOCTYPE, stay, "stay_status", target, update_modified=True)

	return target


def mark_due_out(property_name: str, business_date=None) -> list[str]:
	"""Flag in-house stays departing on the business date.

	Run by the Night Audit so the morning shift sees who is leaving.
	"""
	business_date = getdate(business_date or get_business_date(property_name))

	due = frappe.get_all(
		STAY_DOCTYPE,
		filters={
			"property": property_name,
			"stay_status": IN_HOUSE,
			"departure_date": ("<=", business_date),
		},
		pluck="name",
	)

	for stay in due:
		frappe.db.set_value(STAY_DOCTYPE, stay, "stay_status", DUE_OUT, update_modified=True)
		room = frappe.db.get_value(STAY_DOCTYPE, stay, "room")
		if room:
			room_service.set_status(
				room,
				room_service.OCCUPANCY,
				"Due Out",
				reason=_("Departing on {0}").format(business_date),
				reference_doctype=STAY_DOCTYPE,
				reference_name=stay,
			)

	return due


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


def get_in_house(property_name: str) -> list[dict]:
	"""The in-house board."""
	return frappe.get_all(
		STAY_DOCTYPE,
		filters={"property": property_name, "stay_status": ("in", (IN_HOUSE, DUE_OUT))},
		fields=[
			"name",
			"guest",
			"guest_name",
			"room",
			"room_type",
			"arrival_date",
			"departure_date",
			"nights",
			"adults",
			"children",
			"stay_status",
			"folio",
			"room_rate",
		],
		order_by="room asc",
		limit_page_length=0,
	)


def get_stays_for_room_charge(property_name: str, business_date) -> list[dict]:
	"""In-house stays that owe a room charge for a business date.

	A guest departing on the business date does not consume that night, so the
	filter is `departure_date > business_date` - the same night arithmetic the
	availability engine uses.
	"""
	business_date = getdate(business_date)

	return frappe.get_all(
		STAY_DOCTYPE,
		filters={
			"property": property_name,
			"stay_status": ("in", (IN_HOUSE, DUE_OUT)),
			"arrival_date": ("<=", business_date),
			"departure_date": (">", business_date),
		},
		fields=["name", "folio", "room", "room_type", "room_rate", "rate_plan", "guest", "adults", "children"],
		limit_page_length=0,
	)
