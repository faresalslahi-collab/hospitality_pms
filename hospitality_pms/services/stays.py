"""Check-in, stay management and the in-house board.

Check-in is the moment a booking becomes a physical guest in a physical room.
It touches four things that must all move together or not at all: the
reservation status, the room's occupancy, a new Stay record and a new Folio.
Everything here runs inside the caller's transaction so a failure half way
cannot leave a guest checked in with no folio to charge.
"""

import json

import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate, now_datetime

from hospitality_pms.services import folio as folio_service
from hospitality_pms.services import reservations as reservation_service
from hospitality_pms.services import rooms as room_service
from hospitality_pms.services.availability import (
	authorise_overbooking,
	check_availability,
	lock_room_type,
	nights_between,
	overbooking_evidence,
)
from hospitality_pms.services.base import (
	STAY_ORCHESTRATION,
	assert_transition,
	lock_and_get_doc,
	lock_document,
	require_permission,
	require_role,
	service_context,
)
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
	# Editing a booking and physically checking a guest in are different
	# authorities. A Reservation Agent holds `Reservation.write` and, by the
	# approved matrix, no `Stay.create` - and used to be able to check a guest
	# in anyway, because this gate consulted only the first of the two. Both
	# are required, and both are asserted before any state is touched.
	require_permission(STAY_DOCTYPE, "create")

	# Locked and read together: `_assert_reservation_ready` below decides on
	# `reservation_status`, and reading it from a pre-lock snapshot would let a
	# reservation cancelled a moment ago still be checked in (N1).
	reservation_doc = lock_and_get_doc(reservation_service.RESERVATION_DOCTYPE, reservation)
	reservation_doc.check_permission("write")

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

	# Every precondition above has now passed, so this is the one moment at
	# which a Stay may legitimately come into existence. The context is opened
	# around the insert alone: an unrelated save later in this request must not
	# inherit the authority (P1-2).
	stay = _insert_stay(
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
	)

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

	# Any deposit already taken on the reservation moves onto the folio, so the
	# guest is not asked to pay it twice - but only this room's share of it.
	# The key carries the room line for the same reason: idempotency is scoped
	# per folio, so one key for the whole booking was unique on three different
	# folios and let the deposit through three times (P1-6).
	deposit = reservation_service.deposit_share(reservation_doc, room_line)
	if deposit > 0:
		folio_service.post_payment(
			folio,
			deposit,
			"Bank Transfer",
			payment_type="Deposit",
			idempotency_key=f"reservation-deposit:{reservation}:{room_line}",
			reference=reservation,
		)

	return {"stay": stay.name, "folio": folio, "room": room}


def _insert_stay(values: dict):
	"""Create the Stay, inside the orchestration context that authorises it.

	The single place in the application where a Stay is created. `Stay`'s
	controller refuses an insert outside this context, so anything that needs
	to create a stay in future has to come through here - and therefore through
	the preconditions that make a stay safe to create.
	"""
	with service_context(STAY_ORCHESTRATION):
		return frappe.get_doc(values).insert(ignore_permissions=True)


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

	# Current under lock: the status guard below decides whether the guest is
	# still in the room at all, and a pre-lock read of it could move a guest
	# who checked out while this request waited (N1).
	doc = lock_and_get_doc(STAY_DOCTYPE, stay)
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


def extend_stay(
	stay: str, new_departure, *, allow_overbooking: bool = False, reason: str | None = None
) -> dict:
	"""Extend a stay, and extend the inventory it holds with it.

	The two used to come apart. Only the Stay's own departure date moved, and
	`Reservation Room` - which is what availability counts, what confirmation
	reduces and what the room-clash check reads - kept the original date. So a
	guest extended to the 15th and the property cheerfully reported its only
	room free from the 12th, sold it to somebody else, and had two guests for
	one room (P1-5).

	Both dates move here, in one transaction, behind the inventory lock chain
	documented in `services.reservations`.
	"""
	# Authorised before anything is read or locked, so an override nobody may
	# make costs nothing (Wave 1, P1-3).
	overbooking_reason = authorise_overbooking(reason) if allow_overbooking else None

	new_departure = getdate(new_departure)

	# Plain reads, used only to decide what to lock.
	target = frappe.db.get_value(
		STAY_DOCTYPE,
		stay,
		["property", "reservation", "reservation_room_line", "room_type", "room"],
		as_dict=True,
	)

	if not target:
		throw(_("Stay {0} not found.").format(stay), exc=HospitalityPMSError)

	doc, line = _lock_stay_chain(stay, target)
	doc.check_permission("write")

	if doc.stay_status not in (IN_HOUSE, DUE_OUT):
		throw(
			_("Only an in-house stay can be extended; this stay is {0}.").format(_(doc.stay_status)),
			exc=InvalidStateTransitionError,
		)

	current_departure = getdate(line["departure_date"] if line else doc.departure_date)

	if new_departure <= current_departure:
		throw(_("The new departure must be after the current departure of {0}.").format(current_departure))

	# Only the added nights are checked; the nights already in house are the
	# guest's by right.
	check = check_availability(
		doc.property,
		doc.room_type,
		current_departure,
		new_departure,
		rooms=1,
		allow_overbooking=allow_overbooking,
	)

	# Room-type capacity and this particular room are different questions, and
	# an overbooking override answers only the first. Selling one more room of a
	# type the house does not have is a management decision; putting two guests
	# in room 101 is not something any override makes true.
	reservation_service._assert_room_free(
		doc.room, current_departure, new_departure, exclude_line=target["reservation_room_line"]
	)

	if line:
		reservation_service.set_line_interval(line["name"], departure=new_departure)

	doc.departure_date = new_departure
	doc.nights = len(nights_between(doc.arrival_date, new_departure))

	# Appended *before* the save. It used to be appended after, so every
	# extension the hotel ever made left no record of itself at all (N3).
	_log_note(
		doc,
		_("Stay extended from {0} to {1}{2}").format(
			current_departure,
			new_departure,
			_(" (overbooking override: {0})").format(overbooking_reason) if overbooking_reason else "",
		),
	)

	# The save runs inside the orchestration context because the Stay
	# controller refuses a date moved by a bare document edit; this function
	# is the supported route, and the context is what says so.
	with service_context(STAY_ORCHESTRATION):
		doc.save(ignore_permissions=True)

	# Due Out means "leaving today"; a guest who has just extended is not.
	# Written through the transition service because the Stay controller
	# refuses a status edited on the document itself.
	if doc.stay_status == DUE_OUT:
		transition(stay, IN_HOUSE, reason=_("Stay extended"))

	if overbooking_reason:
		_log_overbooking_override(doc, [check], overbooking_reason, new_departure)

	return {"stay": stay, "departure_date": str(new_departure), "nights": doc.nights}


def _lock_stay_chain(stay: str, target: dict):
	"""Take the inventory locks in the one documented order, then load the Stay.

	Reservation, its room line, the room type, the physical room, and finally
	the Stay itself. One order for every caller, so two operations touching the
	same booking queue behind each other instead of deadlocking.
	"""
	if target.get("reservation"):
		lock_document(reservation_service.RESERVATION_DOCTYPE, target["reservation"])

	line = None
	if target.get("reservation_room_line"):
		line = reservation_service.lock_inventory_line(target["reservation_room_line"])

	if target.get("room_type"):
		lock_room_type(target["property"], target["room_type"])

	if target.get("room"):
		lock_document("Hotel Room", target["room"])

	return lock_and_get_doc(STAY_DOCTYPE, stay), line


def shorten_stay(stay: str, new_departure, reason: str) -> dict:
	"""Shorten a stay, and release the nights the guest is no longer taking.

	The mirror of the extension defect: only the Stay moved, so a guest who
	left four days early left four nights unsellable behind them (P2-5).

	Money already posted is left exactly as it is. A night the guest slept and
	was charged for is history; reversing it because the booking got shorter
	would be the system deciding a refund on its own.
	"""
	if not reason or not reason.strip():
		throw(_("A reason is required to shorten a stay."))

	new_departure = getdate(new_departure)

	target = frappe.db.get_value(
		STAY_DOCTYPE,
		stay,
		["property", "reservation", "reservation_room_line", "room_type", "room"],
		as_dict=True,
	)

	if not target:
		throw(_("Stay {0} not found.").format(stay), exc=HospitalityPMSError)

	doc, line = _lock_stay_chain(stay, target)
	doc.check_permission("write")

	current_departure = getdate(line["departure_date"] if line else doc.departure_date)

	if new_departure <= getdate(doc.arrival_date):
		throw(_("The departure must be after the arrival date."))

	if new_departure >= current_departure:
		throw(_("The new departure must be before the current departure."))

	business_date = get_business_date(doc.property)
	if new_departure < getdate(business_date):
		throw(_("A stay cannot be shortened to a date before the business date."))

	if line:
		reservation_service.set_line_interval(line["name"], departure=new_departure)

	doc.departure_date = new_departure
	doc.nights = len(nights_between(doc.arrival_date, new_departure))

	_log_note(
		doc,
		_("Stay shortened from {0} to {1}: {2}").format(
			current_departure, new_departure, reason.strip()
		),
	)

	with service_context(STAY_ORCHESTRATION):
		doc.save(ignore_permissions=True)

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


def _log_overbooking_override(doc, checks: list[dict], reason: str, new_departure):
	"""Record an oversell made through a stay extension.

	Written to the Reservation Log rather than to a new DocType, because that
	is where the booking's history already lives and where an auditor looking
	for "was this room oversold" will look. The stay's own note table is not
	used: notes appended after `doc.save()` are never persisted (N3), which is
	a separate defect and not one to build an audit trail on top of.

	`from_status` and `to_status` are both the reservation's current status -
	an override changes no reservation state - which is the same shape
	`reservations.assign_room` already writes.
	"""
	if not doc.reservation:
		return

	status = frappe.db.get_value(reservation_service.RESERVATION_DOCTYPE, doc.reservation, "reservation_status")

	frappe.get_doc(
		{
			"doctype": reservation_service.RESERVATION_LOG_DOCTYPE,
			"property": doc.property,
			"reservation": doc.reservation,
			"from_status": status,
			"to_status": status,
			"changed_by": frappe.session.user,
			"changed_at": now_datetime(),
			"reason": reason,
			"details": json.dumps(
				{
					**overbooking_evidence(checks, reason),
					"action": "Stay extended",
					"stay": doc.name,
					"room": doc.room,
					"new_departure": str(new_departure),
					"business_date": str(get_business_date(doc.property)),
				},
				default=str,
			),
		}
	).insert(ignore_permissions=True)


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
	# The transition is asserted against the status read by the lock, not one
	# this transaction saw beforehand (N1).
	doc = lock_and_get_doc(STAY_DOCTYPE, stay)

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
