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

from hospitality_pms.services.availability import (
	authorise_overbooking,
	check_availability,
	check_demand,
	lock_room_type,
	nights_between,
	overbooking_evidence,
)
from hospitality_pms.services.base import (
	assert_transition,
	lock_and_find,
	lock_and_get_doc,
	lock_and_read,
	lock_document,
	require_role,
)
from hospitality_pms.services.exceptions import (
	InvalidStateTransitionError,
	HospitalityPMSError,
	throw,
)
from hospitality_pms.services.property import get_business_date
from hospitality_pms.services.rates import get_cancellation_charge, get_rate_breakdown
from hospitality_pms.services.rooms import assert_assignable

RESERVATION_DOCTYPE = "Reservation"
RESERVATION_LOG_DOCTYPE = "Reservation Log"

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
	"""Apply a state change: validate against **current** state, write, propagate, log.

	The status is re-read here under the row lock rather than taken from
	`doc.reservation_status`, and that is the whole defence against P1-4.

	A caller's document is loaded at the top of its operation. By the time the
	operation reaches this point it may have waited behind another transaction
	that changed the very status this transition is legal or illegal against -
	and under REPEATABLE READ the caller's copy still shows the pre-wait value
	(N1). Evaluating the state machine against that copy is what let two
	concurrent confirms both see `Draft`, and what let a confirm overwrite a
	cancellation that had already committed.

	Reading it with `lock_and_read` makes this function the single point where
	every reservation state change is decided, for every caller, against the
	state that is actually in the database.
	"""
	previous = lock_and_read(RESERVATION_DOCTYPE, doc.name, "reservation_status")["reservation_status"]

	assert_transition(previous, target, TRANSITIONS, _("Reservation"))

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
	# Locked first, then read from that same locking read, so every guard below
	# - the room lines, the availability check, the credit draw - is evaluated
	# against the reservation as it stands now rather than as it stood when
	# this request started (N1). Permission is checked on the locked document:
	# an unauthorised caller is refused a moment later and its lock goes with
	# the rolled-back transaction.
	doc = lock_and_get_doc(RESERVATION_DOCTYPE, reservation)
	doc.check_permission("write")

	# Refuse an illegal transition before any inventory or credit is touched.
	# _transition re-asserts this under the lock as well; doing it here too
	# means the loser of a race never draws corporate credit it will have to
	# roll back.
	assert_transition(doc.reservation_status, CONFIRMED, TRANSITIONS, _("Reservation"))

	if not doc.rooms:
		throw(_("A reservation must have at least one room line before it can be confirmed."))

	# Selling past capacity is authorised before any inventory is locked, so an
	# override nobody may make costs nothing and blocks nobody (P1-3).
	overbooking_reason = authorise_overbooking(reason) if allow_overbooking else None

	# A quantity is how a booking is asked for; it is not how three rooms are
	# run. Normalised here, while the reservation is still editable and before
	# any inventory is committed, so everything downstream - assignment,
	# check-in, the Stay, the folio, the deposit - has one row per real room
	# (P1-6).
	if normalise_room_lines(doc):
		doc.save(ignore_permissions=True)

	# Lock every room type this reservation touches before reading availability.
	lock_room_type(doc.property, [line.room_type for line in doc.rooms])

	# Summed per night across the whole booking. Asking once per row would ask
	# for one room three times, which a house with one room left would grant.
	checks = check_demand(
		doc.property,
		doc.rooms,
		allow_overbooking=allow_overbooking,
		exclude_reservation=reservation,
	)

	# A corporate booking draws on the account's credit. This runs inside the
	# same locked transaction as the availability check, so the credit movement
	# and the booking decision commit together or not at all.
	_consume_corporate_credit(doc)

	details = {"rooms": [{"room_type": line.room_type, "rooms": line.rooms} for line in doc.rooms]}

	if overbooking_reason:
		# Recorded on the transition itself rather than in a log of its own, so
		# an auditor reading the reservation's history sees the oversell in the
		# same place as the decision it belonged to.
		details.update(overbooking_evidence(checks, overbooking_reason))
		details["business_date"] = str(get_business_date(doc.property))

	_transition(doc, CONFIRMED, reason=reason, details=details)

	frappe.db.set_value(
		RESERVATION_DOCTYPE,
		reservation,
		{"confirmed_on": now_datetime(), "confirmed_by": frappe.session.user},
		update_modified=False,
	)

	return CONFIRMED


def guarantee(reservation: str, guarantee_type: str, *, reason: str | None = None) -> str:
	"""Move a confirmed reservation to guaranteed once its guarantee is in place."""
	if not guarantee_type or guarantee_type == "None":
		throw(_("A guarantee type is required to guarantee a reservation."))

	doc = lock_and_get_doc(RESERVATION_DOCTYPE, reservation)
	doc.check_permission("write")

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

	doc = lock_and_get_doc(RESERVATION_DOCTYPE, reservation)
	doc.check_permission("write")

	# Refused here as well as inside _transition, so a cancellation that has
	# already lost the race never releases credit it never consumed.
	assert_transition(doc.reservation_status, CANCELLED, TRANSITIONS, _("Reservation"))

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

	# Releasing before the transition so a failure here aborts the cancellation
	# rather than leaving the booking cancelled with its credit still consumed.
	_release_corporate_credit(doc, charge)

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

	doc = lock_and_get_doc(RESERVATION_DOCTYPE, reservation)

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
		{
			"no_show_on": now_datetime(),
			"cancellation_charge": charge,
			# A no-show ends a booking just as a cancellation does, so it records
			# who and why in the same fields. Without this the actor and reason
			# existed only in the reservation log, which reporting cannot read
			# without crossing that log's own permission boundary.
			"cancelled_by": frappe.session.user,
			"cancellation_reason": reason or _("Recorded as a no-show"),
		},
		update_modified=False,
	)

	return {"status": NO_SHOW, "no_show_charge": charge}



def deposit_allocation(doc) -> dict[str, float]:
	"""Split one deposit across the rooms that will carry it.

	A deposit belongs to a booking, and a booking is now one row per physical
	room, each of which opens its own folio at check-in. Crediting the whole
	deposit to each of those folios credited a 300 deposit three times (P1-6).

	The split is proportional to what each room is worth, so the guest who
	booked a suite and a single does not see the deposit halved between them,
	and it is computed the same way every time it is asked for: the shares are
	rounded down to currency precision and the last row takes the remainder, so
	the parts add back up to the deposit exactly rather than to 99.99.

	A pure function of what is stored. Nothing here decides *when* a share is
	posted; that is check-in's business, one room at a time.
	"""
	deposit = flt(doc.deposit_received)
	lines = list(doc.rooms)

	if deposit <= 0 or not lines:
		return {line.name: 0.0 for line in lines}

	precision = frappe.get_precision("Folio Payment", "amount") or 2
	weights = [flt(line.total_amount) for line in lines]
	basis = sum(weights)

	if basis <= 0:
		# Nothing priced yet - an equal split is the only defensible answer.
		weights = [1.0] * len(lines)
		basis = float(len(lines))

	allocation: dict[str, float] = {}
	running = 0.0

	for line, weight in zip(lines[:-1], weights[:-1], strict=True):
		share = flt(deposit * weight / basis, precision)
		allocation[line.name] = share
		running += share

	# The last row absorbs the rounding remainder, which is what makes the
	# aggregate exact rather than approximately right.
	allocation[lines[-1].name] = flt(deposit - running, precision)

	return allocation


def deposit_credited(reservation: str) -> float:
	"""What the folios of this booking have already been credited."""
	return flt(
		frappe.db.sql(
			"""
			select coalesce(sum(payment.amount), 0)
			from `tabFolio Payment` payment
			inner join `tabGuest Folio` folio on folio.name = payment.parent
			where folio.reservation = %s and payment.payment_type = %s
			""",
			(reservation, DEPOSIT_PAYMENT_TYPE),
		)[0][0]
	)


def deposit_share(doc, room_line: str) -> float:
	"""One room's share of the deposit, capped by what is left to credit.

	The allocation alone would already sum to the deposit, but it is derived
	from line values that can move after a room has been checked in - a stay
	shortened on Tuesday re-prices its row. The cap makes the invariant hold
	regardless: the folios of one booking can never be credited more than the
	deposit that was actually received.

	Read under the reservation lock the caller already holds, so two rooms
	arriving at once cannot both see the same room left in the budget.
	"""
	share = flt(deposit_allocation(doc).get(room_line, 0))

	if share <= 0:
		return 0.0

	remaining = flt(doc.deposit_received) - deposit_credited(doc.name)

	return max(min(share, remaining), 0.0)


def normalise_room_lines(doc) -> bool:
	"""Turn a booked quantity into one operational row per physical room.

	A `Reservation Room` row is the unit everything operational hangs off: it
	holds one assigned room, produces one Stay, opens one Folio and takes one
	share of the deposit. A row saying `rooms = 3` can do exactly one of each,
	which is why the second and third rooms of a three-room booking could never
	be checked in, and why the whole booking was marked Checked In as soon as
	the first guest arrived (P1-6).

	Splitting rather than teaching check-in to consume a row three times: the
	quantity was the wrong representation to run a hotel from, and every
	downstream fix would have had to know about it.

	Returns whether anything changed, so the caller only saves when it must.
	Idempotent - a booking already at one room per row is left alone.

	Pricing is untouched by design. `price_reservation` computes a line's total
	as the per-room total multiplied by its quantity, so three rows of one come
	to exactly what one row of three did; the re-price on save proves it rather
	than assuming it.
	"""
	extra = []
	changed = False

	for line in doc.rooms:
		quantity = max(int(line.rooms or 1), 1)

		if quantity == 1:
			continue

		changed = True
		line.rooms = 1

		for _copy in range(quantity - 1):
			values = {
				field: line.get(field)
				for field in (
					"room_type",
					"arrival_date",
					"departure_date",
					"property",
					"reservation_status",
					"rate_plan",
					"adults",
					"children",
					"extra_beds",
					"room_rate",
					"special_requests",
				)
			}
			# Deliberately not copied: a physical room belongs to one row, and
			# duplicating an assignment would promise one room to two guests.
			extra.append({**values, "rooms": 1, "assigned_room": None})

	for values in extra:
		doc.append("rooms", values)

	return changed


def _corporate_account(doc) -> str | None:
	"""The corporate account a reservation bills to, if it resolves to a real one.

	`corporate_account` is a Data field rather than a Link, so a typo or a
	stale name is possible. An unresolvable value is ignored rather than
	blocking the booking: refusing to sell a room because a reference is stale
	would be a worse failure than not tracking the credit.
	"""
	name = (doc.get("corporate_account") or "").strip()

	if not name or not frappe.db.exists("Corporate Account", name):
		return None

	return name


def _consume_corporate_credit(doc):
	"""Draw the reservation's value against its corporate account's credit."""
	account = _corporate_account(doc)

	if not account:
		return

	from hospitality_pms.services.corporate import consume_credit

	consume_credit(account, flt(doc.total_amount), reservation=doc.name)


def _release_corporate_credit(doc, charge: float = 0.0):
	"""Return credit when a booking is cancelled.

	Only the amount that will not now be billed is released: a cancellation
	charge is still owed by the account, so it stays consumed.

	Nothing is released for a booking that never consumed anything. Credit is
	drawn at confirmation, so a Draft, Tentative or Waitlisted reservation is
	not holding any - and releasing against it wrote a `Credit released`
	movement for money that was never taken, leaving the ledger showing a
	release with no matching consumption.
	"""
	if doc.reservation_status not in HOLDING_STATES:
		return

	account = _corporate_account(doc)

	if not account:
		return

	from hospitality_pms.services.corporate import release_credit

	releasable = max(flt(doc.total_amount) - flt(charge), 0.0)

	if releasable <= 0:
		return

	release_credit(account, releasable, reason=_("Reservation {0} cancelled").format(doc.name))


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

	_assert_room_free(room, line.arrival_date, line.departure_date, exclude_line=room_line)
	assert_assignable(room, allow_unready_housekeeping=allow_unready, arrival=line.arrival_date)

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


def _assert_room_free(room: str, arrival, departure, exclude_line: str | None = None):
	"""Refuse a room already promised to an overlapping stay.

	Overlap is `arrival < other.departure AND departure > other.arrival`,
	which correctly allows a same-day turnover: one guest departs on the 12th
	and another arrives on the 12th.

	Scoped to the *line*, not the reservation. Excluding the whole reservation
	was safe only while a booking held one row; once a three-room booking is
	three rows, excluding the parent would let two of its own rooms be given
	the same physical room and nobody would notice until both guests arrived.

	`Reservation Room` is the authoritative interval - a checked-in guest is
	still counted here, because check-in does not move a booking out of the
	holding states.
	"""
	filters = {
		"assigned_room": room,
		"reservation_status": ("in", HOLDING_STATES),
		"arrival_date": ("<", getdate(departure)),
		"departure_date": (">", getdate(arrival)),
	}

	if exclude_line:
		filters["name"] = ("!=", exclude_line)

	# A **current** read, not a snapshot read. `lock_document` on the room
	# serialises two agents clicking the same room, but locking does not
	# refresh what this transaction can see: a plain `get_all` is answered
	# from the snapshot opened before the rival committed its assignment, so
	# both agents find the room free and both take it. This is the N1 pattern
	# Wave 1 established, applied to the assignment interval.
	clash = lock_and_find("Reservation Room", filters, ["parent", "name"])

	if clash:
		throw(
			_("Room {0} is already assigned to reservation {1} for these dates.").format(
				room, clash["parent"]
			),
			exc=HospitalityPMSError,
		)


# ---------------------------------------------------------------------------
# The inventory chain
# ---------------------------------------------------------------------------
#
# `Reservation Room` is the single authoritative record of what is sold. It is
# what `availability._sold_by_night` counts, what `_assert_room_free` checks and
# what confirmation reduces. A Stay is the operational face of one of those
# rows, never a second inventory holder - counting both would count a
# checked-in guest twice.
#
# Everything that changes an interval therefore locks the same chain in the same
# order. One order, so two operations touching overlapping rows queue rather
# than deadlock:
#
#     1. Reservation        the aggregate whose dates are recalculated
#     2. Reservation Room   the interval itself
#     3. Room Type          the type-level capacity check
#     4. Hotel Room         the physical room
#     5. Stay               the operational record
#
# Reading a row to decide *what* to lock is fine; every value a decision is made
# from is read back from the locking read (Wave 1, N1).

RESERVATION_ROOM_DOCTYPE = "Reservation Room"
DEPOSIT_PAYMENT_TYPE = "Deposit"


def lock_inventory_line(room_line: str) -> dict:
	"""Lock one Reservation Room row and return its current interval."""
	return lock_and_read(
		RESERVATION_ROOM_DOCTYPE,
		room_line,
		["name", "parent", "room_type", "rooms", "arrival_date", "departure_date", "assigned_room"],
	)


def set_line_interval(room_line: str, *, arrival=None, departure=None):
	"""Move an inventory interval, and keep the reservation's own dates true.

	The only supported way to change what a booking holds. A Stay's departure
	date on its own is a display value; this is the row availability counts.
	"""
	values = {}

	if arrival:
		values["arrival_date"] = getdate(arrival)

	if departure:
		values["departure_date"] = getdate(departure)

	if not values:
		return

	current = frappe.db.get_value(
		RESERVATION_ROOM_DOCTYPE, room_line, ["parent", "arrival_date", "departure_date"], as_dict=True
	)

	values["nights"] = len(
		nights_between(
			values.get("arrival_date", current["arrival_date"]),
			values.get("departure_date", current["departure_date"]),
		)
	)

	frappe.db.set_value(RESERVATION_ROOM_DOCTYPE, room_line, values, update_modified=False)

	refresh_header_dates(current["parent"])


def refresh_header_dates(reservation: str):
	"""Recompute the reservation's own dates from the rooms it holds.

	The header is a summary of its children, not a copy of one of them. Setting
	it from whichever room was just changed would shorten a whole booking
	because one guest of three left early.
	"""
	span = frappe.db.sql(
		"""
		select min(arrival_date) as arrival, max(departure_date) as departure
		from `tabReservation Room`
		where parent = %s
		""",
		reservation,
		as_dict=True,
	)[0]

	if not span["arrival"] or not span["departure"]:
		return

	frappe.db.set_value(
		RESERVATION_DOCTYPE,
		reservation,
		{
			"arrival_date": getdate(span["arrival"]),
			"departure_date": getdate(span["departure"]),
			"nights": len(nights_between(span["arrival"], span["departure"])),
		},
		update_modified=False,
	)


# ---------------------------------------------------------------------------
# Queries# ---------------------------------------------------------------------------
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
