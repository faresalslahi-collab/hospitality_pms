"""Read models for the Front Office boards.

Nothing here changes state. These are the queries behind the dashboard, the
arrivals and departures boards and the reservation calendar — the four screens
a front desk keeps open all shift, on a property with 500 rooms and six figures
of reservations a year.

Two rules shape every function below.

*Bulk, never per row.* Each board is a fixed handful of queries whose count does
not grow with the number of rows returned. A board that issued one query per
reservation would be fine in a demo and unusable at the desk.

*Borrow the rule, never restate it.* Whether a room can take a guest comes from
`rooms.is_assignable`; whether a guest may leave comes from
`checkout.get_departure_blockers`; the day's revenue metrics come from the
Night Audit that computed them. Where an authoritative answer does not exist
yet, these functions say so rather than estimating one.
"""

import frappe
from frappe.utils import add_days, cint, flt, getdate

from hospitality_pms.services import checkout as checkout_service
from hospitality_pms.services import folio as folio_service
from hospitality_pms.services import guest_services as guest_service
from hospitality_pms.services import guests as guest_identity_service
from hospitality_pms.services import housekeeping as housekeeping_service
from hospitality_pms.services import maintenance as maintenance_service
from hospitality_pms.services import reservations as reservation_service
from hospitality_pms.services import rooms as room_service
from hospitality_pms.services import stays as stay_service
from hospitality_pms.services.property import (
	get_business_date,
	get_property,
	resolve_operational_date,
)

ROOM_DOCTYPE = "Hotel Room"
ROOM_TYPE_DOCTYPE = "Room Type"
RESERVATION_ROOM_DOCTYPE = "Reservation Room"
ROOM_BLOCK_DOCTYPE = "Room Block"
GUEST_DOCTYPE = "Guest"
NIGHT_AUDIT_DOCTYPE = "Night Audit"

#: Room fields every board reads. The same set the rack uses, so a room reads
#: identically on the dashboard, the arrivals board and the rack itself
#: (Frontend Standards section 2).
ROOM_STATE_FIELDS = (
	"name",
	"room_number",
	"room_type",
	"floor",
	"is_active",
	"occupancy_status",
	"housekeeping_status",
	"maintenance_status",
	"inventory_status",
)

#: Reservation statuses that put a booking on the arrivals board. Checked In is
#: included on purpose: an arrivals board that drops guests the moment they
#: check in cannot be reconciled against the day's expected arrivals.
ARRIVAL_STATES = (
	reservation_service.CONFIRMED,
	reservation_service.GUARANTEED,
	reservation_service.CHECKED_IN,
)

#: Stay statuses that put a guest on the departures board, including the ones
#: that already left today, for the same reason.
DEPARTURE_STATES = (stay_service.IN_HOUSE, stay_service.DUE_OUT, stay_service.CHECKED_OUT)

#: Stay statuses that mean "this guest is in the house right now". The same pair
#: `stays.get_in_house` selects on, and the pair the dashboard's in-house tiles
#: are counted from: a guest who has checked out is no longer in the house, and a
#: guest still Expected is not in it yet.
IN_HOUSE_STATES = (stay_service.IN_HOUSE, stay_service.DUE_OUT)

#: Reservations that hold inventory, and so count as demand on the calendar.
CALENDAR_RESERVATION_STATES = (*reservation_service.HOLDING_STATES, reservation_service.TENTATIVE)

#: Reservations that draw their own bar against a room. Checked In is excluded
#: because that room already carries a stay bar, and a room showing two bars for
#: one guest reads as a double booking. Tentative is included because
#: `assign_room` permits it, and a held room that drew no bar would look free.
CALENDAR_BAR_STATES = (
	reservation_service.TENTATIVE,
	reservation_service.CONFIRMED,
	reservation_service.GUARANTEED,
)

#: The calendar never renders an unbounded window, whatever the caller asks for.
MAX_CALENDAR_DAYS = 31
MAX_CALENDAR_ROOMS = 100


# ---------------------------------------------------------------------------
# Shared building blocks
# ---------------------------------------------------------------------------


def resolve_business_date(property_name: str, on_date=None):
	"""The date a board is about.

	Kept as the name the front office boards already call, delegating to the
	one shared implementation. Wave 6 found the same rule written twice with
	different answers - the boards resolved the business date and the legacy
	reservation endpoints reached for `nowdate()` - so there is now one.
	"""
	return resolve_operational_date(property_name, on_date)


def get_room_states(property_name: str, rooms: list[str] | None = None) -> dict[str, dict]:
	"""Every room's four dimensions, keyed by room name, in two queries.

	`assignable` answers "may the desk give this room away right now", which is a
	question about the guest in it and not only about the room's own flags. R1A
	made active Stay occupancy authoritative for every path that *places* a
	guest and deliberately left this board reading the flag alone, so a room
	whose `occupancy_status` had gone stale was still shown as assignable -
	nobody could be checked into it, but the desk was being offered it. R1B
	derives the display from the same authority the mutations use.

	Two queries, not one per room: the rooms, and one bulk read of which rooms an
	active Stay physically occupies.
	"""
	filters = {"property": property_name}
	if rooms is not None:
		if not rooms:
			return {}
		filters["name"] = ("in", list(rooms))

	records = frappe.get_all(
		ROOM_DOCTYPE,
		filters=filters,
		fields=list(ROOM_STATE_FIELDS),
		order_by="room_number asc",
		limit_page_length=0,
	)

	occupied_now = room_service.rooms_with_active_stays(property_name)

	for row in records:
		row["assignable"] = room_service.is_assignable_now(
			row["name"], state=row, occupied_rooms=occupied_now
		)
		row["ready"] = bool(row.get("housekeeping_status") in room_service.READY_HOUSEKEEPING)

	return {row["name"]: row for row in records}


def get_guest_flags(guests: list[str]) -> dict[str, dict]:
	"""Guest standing for a set of guests, in one query, filtered by clearance.

	The desk needs to know before the guest reaches the counter, and it is the
	same handful of fields on every board. `vip_status` and `guest_type` are
	permlevel 0 and travel unconditionally.

	`is_blacklisted` does not. It is permlevel 2 with a deliberately narrow
	reader set (`setup.permissions.BLACKLIST_READERS`), and this is a
	`frappe.get_all`, which applies neither DocType permission nor permlevel
	filtering. The boards gate on their own DocType - arrivals on
	`Reservation.read`, whose readers are OPERATIONAL + AUDITOR - so until 16.7.1
	housekeeping, maintenance, kitchen, revenue, corporate sales, finance and
	accounts all received a permlevel-2 field simply by opening a board. The
	column is therefore selected only when `guests.may_see_blacklist()` says the
	caller is cleared for it, which is the one place that question is answered.

	For a caller who is not cleared the key is *absent*, never `False`: `False` is
	a claim about the guest that the caller is not entitled to and that may be
	untrue. `blacklist_reason` (permlevel 3) is never read here at all, by any
	caller - a reason has no business on an operational board.

	Still one query, whoever asks. Only the column list changes.
	"""
	guests = [g for g in set(guests or []) if g]
	if not guests:
		return {}

	fields = ["name", "vip_status", "guest_type"]

	if guest_identity_service.may_see_blacklist():
		fields.append("is_blacklisted")

	records = frappe.get_all(
		GUEST_DOCTYPE,
		filters={"name": ("in", guests)},
		fields=fields,
		limit_page_length=0,
	)

	return {row["name"]: row for row in records}


def _blacklist_flag(flags: dict) -> dict:
	"""The blacklist flag for a board row, as a fragment to splice in — or nothing.

	Spliced rather than assigned, so a row built for an uncleared caller carries
	no `is_blacklisted` key at all rather than a `False` one. Every board that
	shows the flag builds it this way, so the rule is applied identically on
	arrivals, departures and the in-house board (see `get_guest_flags`).

	The frontend already reads absence as "not disclosed" rather than as "no"
	(`resources/guests.js: hasField`), so an omitted key degrades to no badge
	instead of to a false clearance.
	"""
	if "is_blacklisted" not in flags:
		return {}

	return {"is_blacklisted": bool(flags["is_blacklisted"])}


def _board_disclosure() -> dict:
	"""What this caller may be told beyond the board's own DocType.

	A board is one row assembled from several DocTypes, and its endpoint gates on
	only one of them: the arrivals board on Reservation, the departures and
	in-house boards on Stay. Everything else on the row — the guest's standing,
	the folio's money — is read with `frappe.get_all`, which applies no permission
	at all, so the row would otherwise hand a caller data whose DocType they
	cannot open.

	That is exactly the defect 16.7.0's review found in `get_guest_flags` for
	`is_blacklisted`, and the fix for that one field left the same hole open for
	the rest. On this site ten roles hold Stay read and neither Guest nor Guest
	Folio read — Room Attendant, Housekeeping Manager and Supervisor, Maintenance
	Manager and Technician, Kitchen Manager and User, Food and Beverage Manager,
	Revenue Manager, Corporate Sales Manager — and the Command Center is their
	landing page, because the navigation entry for it carries no role filter.

	Asked once per board, not once per row: the answer cannot differ between rows
	of a single request.
	"""
	return {
		"guest": frappe.has_permission(guest_identity_service.GUEST_DOCTYPE, "read"),
		"folio": frappe.has_permission(folio_service.FOLIO_DOCTYPE, "read"),
	}


def _guest_standing(flags: dict, may_read_guest: bool) -> dict:
	"""The guest's standing on a board row — for a caller who may read Guest.

	`vip_status` and `guest_type` are permlevel 0, so any *Guest reader* may have
	them. They are still withheld from a caller who cannot read Guest at all:
	permlevel 0 means "not privileged among people entitled to the record", not
	"public". A room attendant does not need to know which guest is a VIP, and
	accumulated over a season "which guests are VIPs" is precisely the profile the
	permission was drawn around.
	"""
	if not may_read_guest:
		return {}

	return {
		"vip_status": flags.get("vip_status") or "",
		"guest_type": flags.get("guest_type") or "",
	}


def _folio_position(payload: dict, may_read_folio: bool) -> dict:
	"""A row's folio money — for a caller who may read Guest Folio.

	The balance, the folio's name and status, the split-folio figures and the
	checkout verdict all come from Guest Folio, which the board's own endpoint
	never checks. The blockers are the sharpest case: `get_departure_blockers`
	words them with the amounts inside the sentence ("The folio has an outstanding
	balance of 400.0"), so passing the strings through discloses the money even if
	the numeric fields were withheld.

	Withholding the whole group rather than blanking it keeps the frontend honest:
	`hasField` reads an absent key as "not disclosed to you", where a `0.00`
	balance would read as "settled" and a `can_check_out: true` would read as
	"this guest may leave" — both untrue, and the second dangerously so.
	"""
	if not may_read_folio:
		return {}

	return payload


def _alert_position(summary: dict, may_read_guest: bool) -> dict:
	"""How many active alerts a guest carries, and how bad the worst is.

	Both, or neither. The first draft of this gave the count to every board reader
	and gated only the grade, on the theory that "there is something to ask about"
	is not a disclosure. The security review took that apart, correctly: both
	numbers are read out of `Guest Alert`, which is a child table with no
	permissions of its own, so its reader set *is* Guest's — and the argument for
	the count named the front desk, which holds Guest read and was therefore never
	the audience in question. A room attendant learns that the guest in 412
	carries two alerts, acts on none of it, and over a season accumulates exactly
	the profile the permission was drawn around.

	A caller who may read Guest can already open that guest and read the alert
	bodies through the endpoint that authorises them, so neither number tells them
	anything new.

	Spliced rather than assigned, for the same reason as `_blacklist_flag`: an
	absent key is "not disclosed to you", where a `0` would read as "no alerts"
	and be untrue.
	"""
	if not may_read_guest:
		return {}

	return {
		"alert_count": cint((summary or {}).get("count")),
		"alert_severity": (summary or {}).get("severity") or "",
	}


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


def get_dashboard(property_name: str, on_date=None) -> dict:
	"""Everything the front office dashboard shows, in one response.

	Assembled server side because the alternative — a dozen requests from a
	screen that is open all day on every terminal — is the shape that does not
	survive a hundred concurrent users (Frontend Standards section 6).
	"""
	business_date = resolve_business_date(property_name, on_date)
	property_doc = get_property(property_name)

	room_states = get_room_states(property_name)
	rooms = list(room_states.values())

	in_house = stay_service.get_in_house(property_name)

	# The dashboard's money comes from Guest Folio, and this screen never asked
	# whether the caller may read it.
	#
	# `_board_disclosure` and `_folio_position` were written for exactly this and
	# then applied only to the three boards. `_board_disclosure`'s own docstring
	# names the Command Center as the landing page of the ten roles that hold Stay
	# read and not Guest Folio read - Room Attendant, the housekeeping and
	# maintenance lines, the kitchen roles, Revenue Manager, Corporate Sales
	# Manager - because the navigation entry for it carries no role filter. The
	# rule was correct; the screen the docstring cites was the one it was not
	# applied to.
	#
	# `_revenue_today` sums Folio Charge, Folio Payment and Guest Folio through
	# raw SQL, which applies no DocType permission, no permlevel filter and no
	# user permission. `outstanding_balance` is the sharpest of the three: a
	# property-wide sum over every unsettled folio, which is the hotel's open
	# receivables position. The departures and in-house panels on this same screen
	# already refuse to publish that figure in aggregate - `_departures_summary`
	# says in as many words that "totalling withheld figures would put the money
	# back on the screen with the rows' names stripped off" - while this published
	# a larger version of it above them.
	#
	# Spliced, so the whole `revenue` key is absent for an uncleared caller rather
	# than present and zeroed. A `0.00` room revenue reads as "a quiet day" and an
	# `0.00` outstanding balance reads as "everyone has paid"; both are claims the
	# caller is not entitled to and neither is true.
	#
	# Guarded before the call and not after it, so an uncleared caller does not
	# pay for three aggregate queries whose answer is then thrown away.
	may_read = _board_disclosure()

	return {
		"property": property_name,
		"property_name": property_doc.property_name,
		"business_date": str(business_date),
		"currency": property_doc.currency,
		"rooms": _room_counts(rooms),
		"front_office": _front_office_counts(property_name, business_date, in_house),
		**_folio_position(
			{"revenue": _revenue_today(property_name, business_date, property_doc.currency)}
			if may_read["folio"]
			else {},
			may_read["folio"],
		),
		# `performance` is deliberately **not** gated here, and the reason is worth
		# recording so it is not "tidied up" later.
		#
		# It looks like folio money and is not: `_last_closed_performance` reads
		# figures the Night Audit computed and stored on itself, so Night Audit is
		# the DocType that owns them and the disclosure boundary was drawn there on
		# purpose (HPMS-DEC-097). On this matrix Night Audit's reader set is
		# identical to Stay's, so every caller who got past this endpoint's
		# `Stay.read` gate already holds it, and a check here would be dead code
		# that reads as protection. Gating it on *Guest Folio* would be actively
		# wrong: it would blind the Revenue Manager, whose job is ADR and RevPAR,
		# on a boundary Night Audit's own permission does not draw.
		"performance": _last_closed_performance(property_name),
		"workload": _workload_counts(property_name, business_date),
	}


def _room_counts(rooms: list[dict]) -> dict:
	"""Room state counts across the four independent dimensions.

	Occupancy, housekeeping, maintenance and inventory are counted separately
	and never merged: a room can be vacant, dirty and out of service at once,
	and a single "status" number would hide two of those three facts
	(SAS section 3.2).
	"""
	counts = {
		"total": len(rooms),
		"active": 0,
		"occupied": 0,
		"vacant": 0,
		"vacant_clean": 0,
		"vacant_dirty": 0,
		"vacant_not_ready": 0,
		"ready": 0,
		"dirty": 0,
		"out_of_order": 0,
		"out_of_service": 0,
		"under_maintenance": 0,
		"blocked": 0,
		"assignable": 0,
	}

	for room in rooms:
		if room.get("is_active"):
			counts["active"] += 1

		occupancy = room.get("occupancy_status")
		housekeeping = room.get("housekeeping_status")
		maintenance = room.get("maintenance_status")

		if occupancy in room_service.OCCUPIED_STATES:
			counts["occupied"] += 1
		elif occupancy == "Vacant":
			counts["vacant"] += 1

			if housekeeping in room_service.READY_HOUSEKEEPING:
				counts["vacant_clean"] += 1
			else:
				# Every vacant room housekeeping has not released, not just the
				# ones marked Dirty: In Progress, Inspection Pending, DND and
				# Service Refused are all rooms the desk cannot give away yet.
				# `vacant_dirty` stays a strict count of Dirty because the rack
				# legend uses it; this is the one the desk's "not ready" counter
				# needs, and the room attention queue lists exactly these rooms,
				# so a tile reading lower than the list beneath it was the
				# alternative.
				counts["vacant_not_ready"] += 1

				if housekeeping == "Dirty":
					counts["vacant_dirty"] += 1

		if housekeeping in room_service.READY_HOUSEKEEPING:
			counts["ready"] += 1
		elif housekeeping == "Dirty":
			counts["dirty"] += 1

		if maintenance == "Out of Order":
			counts["out_of_order"] += 1
		elif maintenance == "Out of Service":
			counts["out_of_service"] += 1
		elif maintenance == "Under Maintenance":
			counts["under_maintenance"] += 1

		if room.get("inventory_status") in room_service.BLOCKING_INVENTORY:
			counts["blocked"] += 1

		if room.get("assignable"):
			counts["assignable"] += 1

	return counts


def _front_office_counts(property_name: str, business_date, in_house: list[dict]) -> dict:
	"""The day's arrival and departure position, counted in rooms.

	Rooms, not reservations, throughout: a three-room booking is three arrivals
	to the desk, and mixing the two units is how a dashboard ends up disagreeing
	with the board it links to. These are the same filters the arrivals and
	departures boards use, so the tile and the list always match.
	"""
	arrivals_expected = frappe.db.count(
		RESERVATION_ROOM_DOCTYPE,
		{
			"parenttype": reservation_service.RESERVATION_DOCTYPE,
			"property": property_name,
			"arrival_date": business_date,
			"reservation_status": ("in", ARRIVAL_STATES),
		},
	)

	# Rooms sold for today that still have nobody's room chosen. The desk's most
	# time-critical queue: an unassigned line cannot be made ready, cannot be
	# keyed and cannot be checked in. Counted on the same room lines and the same
	# states as `arrivals_expected`, so the two tiles cannot disagree.
	arrivals_unassigned = frappe.db.count(
		RESERVATION_ROOM_DOCTYPE,
		{
			"parenttype": reservation_service.RESERVATION_DOCTYPE,
			"property": property_name,
			"arrival_date": business_date,
			"reservation_status": ("in", ARRIVAL_STATES),
			"assigned_room": ("is", "not set"),
		},
	)

	arrivals_completed = frappe.db.count(
		stay_service.STAY_DOCTYPE,
		{
			"property": property_name,
			"arrival_date": business_date,
			"stay_status": ("!=", stay_service.EXPECTED),
		},
	)

	departures_completed = frappe.db.count(
		stay_service.STAY_DOCTYPE,
		{
			"property": property_name,
			"departure_date": business_date,
			"stay_status": stay_service.CHECKED_OUT,
		},
	)

	# Departures still to happen, plus those already gone, is the day's total.
	departures_pending = frappe.db.count(
		stay_service.STAY_DOCTYPE,
		{
			"property": property_name,
			"departure_date": business_date,
			"stay_status": ("in", (stay_service.IN_HOUSE, stay_service.DUE_OUT)),
		},
	)

	return {
		"arrivals_expected": arrivals_expected,
		"arrivals_pending": max(arrivals_expected - arrivals_completed, 0),
		"arrivals_completed": arrivals_completed,
		"arrivals_unassigned": arrivals_unassigned,
		"departures_expected": departures_pending + departures_completed,
		"departures_pending": departures_pending,
		"departures_completed": departures_completed,
		"in_house_rooms": len(in_house),
		"in_house_guests": sum(cint(s.get("adults")) + cint(s.get("children")) for s in in_house),
		"due_out": sum(1 for s in in_house if s["stay_status"] == stay_service.DUE_OUT),
	}


def _revenue_today(property_name: str, business_date, currency: str | None) -> dict:
	"""Money actually recorded against the business date so far.

	These are posted figures, not a forecast: room charges normally land when
	the night audit posts them, so this reads zero for most of the day and the
	screen says so. Inventing a projection here would put a number in front of
	the desk that no ledger would agree with.
	"""
	room_revenue = frappe.db.sql(
		"""
		select coalesce(sum(c.total_amount), 0)
		from `tabFolio Charge` c
		inner join `tabGuest Folio` f on f.name = c.parent
		where f.property = %(property)s
		  and c.business_date = %(date)s
		  and c.charge_type = 'Room Charge'
		  and c.is_reversed = 0
		""",
		{"property": property_name, "date": business_date},
	)[0][0]

	payments = frappe.db.sql(
		"""
		select coalesce(sum(p.amount), 0)
		from `tabFolio Payment` p
		inner join `tabGuest Folio` f on f.name = p.parent
		where f.property = %(property)s
		  and p.business_date = %(date)s
		  and p.is_reversed = 0
		""",
		{"property": property_name, "date": business_date},
	)[0][0]

	outstanding = frappe.db.sql(
		"""
		select coalesce(sum(balance), 0)
		from `tabGuest Folio`
		where property = %(property)s
		  and folio_status not in ('Settled', 'Closed')
		""",
		{"property": property_name},
	)[0][0]

	return {
		"currency": currency,
		"business_date": str(business_date),
		"room_revenue_posted": flt(room_revenue, 2),
		"payments_received": flt(payments, 2),
		"outstanding_balance": flt(outstanding, 2),
	}


def _last_closed_performance(property_name: str) -> dict:
	"""Occupancy, ADR and RevPAR from the last closed Night Audit.

	The audit is the only place these three are authoritative: it is what
	computed them, against a day whose charges are all posted. Today's figures
	do not exist yet and are not guessed here — the dashboard labels these with
	the business date they belong to (HPMS-DEC-030).
	"""
	# The three ratios and no absolute totals (16.7.5-R1B).
	#
	# `room_revenue`, `total_revenue` and `payments_received` were selected here
	# and published to every caller who got past this endpoint's `Stay.read` gate.
	# They are Guest Folio aggregates that the audit stores, so withholding
	# `revenue` above and then handing over last night's version of the same three
	# numbers closed nothing. No consumer wanted them: the Command Center renders
	# occupancy, ADR and RevPAR and nothing else from this block.
	#
	# The ratios stay ungated, and that is deliberate rather than an oversight.
	# Night Audit computed them and owns them (HPMS-DEC-097), and the Revenue
	# Manager - whose job is exactly these three - holds Night Audit read and no
	# Guest Folio read. Gating them would blind the one role they exist for.
	#
	# ADR times occupied rooms does approximate room revenue, and occupied rooms
	# is on the same response. That is an accepted consequence of the product's
	# decision to give the Revenue Manager ADR at all, not a hole this build
	# opened; it is recorded here so the next reader does not have to rediscover
	# the trade.
	records = frappe.get_all(
		NIGHT_AUDIT_DOCTYPE,
		filters={"property": property_name, "audit_status": "Closed"},
		fields=[
			"name",
			"business_date",
			"occupancy_percentage",
			"adr",
			"revpar",
			"currency",
		],
		order_by="business_date desc",
		limit_page_length=1,
	)

	if not records:
		return {"available": False}

	return {"available": True, **records[0], "business_date": str(records[0]["business_date"])}


#: "Still open" per department, taken from each service's own state names so a
#: renamed status cannot leave the dashboard silently counting zero.
OPEN_HOUSEKEEPING = (
	housekeeping_service.PENDING,
	housekeeping_service.ASSIGNED,
	housekeeping_service.IN_PROGRESS,
	housekeeping_service.INSPECTION_PENDING,
)
OPEN_MAINTENANCE = (
	maintenance_service.OPEN,
	maintenance_service.IN_PROGRESS,
	maintenance_service.VERIFICATION,
)
OPEN_GUEST_REQUESTS = (
	guest_service.OPEN,
	guest_service.ASSIGNED,
	guest_service.IN_PROGRESS,
	guest_service.ESCALATED,
	guest_service.REOPENED,
)


def _workload_counts(property_name: str, business_date) -> dict:
	"""Open work the front desk will be asked about."""
	return {
		"housekeeping_open": frappe.db.count(
			"Housekeeping Task",
			{
				"property": property_name,
				"scheduled_date": business_date,
				"task_status": ("in", OPEN_HOUSEKEEPING),
			},
		),
		"maintenance_open": frappe.db.count(
			"Maintenance Ticket",
			{"property": property_name, "ticket_status": ("in", OPEN_MAINTENANCE)},
		),
		"guest_requests_open": frappe.db.count(
			"Guest Request",
			{"property": property_name, "request_status": ("in", OPEN_GUEST_REQUESTS)},
		),
	}


# ---------------------------------------------------------------------------
# Arrivals
# ---------------------------------------------------------------------------


def get_arrivals_board(property_name: str, on_date=None) -> dict:
	"""One row per room to be checked in, for the business date.

	Row per room line rather than per reservation, because a room is what gets
	assigned, made ready and checked in. A three-room booking is three pieces
	of work at the desk and reads as three here.
	"""
	business_date = resolve_business_date(property_name, on_date)

	# Driven from the room lines, not the reservations: the line carries its own
	# arrival date and its own status copy, so "arriving today" means the same
	# thing here as it does in the dashboard counts and the availability engine.
	lines = frappe.get_all(
		RESERVATION_ROOM_DOCTYPE,
		filters={
			"parenttype": reservation_service.RESERVATION_DOCTYPE,
			"property": property_name,
			"arrival_date": business_date,
			"reservation_status": ("in", ARRIVAL_STATES),
		},
		fields=[
			"name",
			"parent",
			"room_type",
			"rooms",
			"assigned_room",
			"arrival_date",
			"departure_date",
			"nights",
			"adults",
			"children",
			"room_rate",
			"special_requests",
		],
		order_by="parent asc, idx asc",
		limit_page_length=0,
	)

	if not lines:
		return _empty_board(property_name, business_date, _arrivals_summary)

	reservations = frappe.get_all(
		reservation_service.RESERVATION_DOCTYPE,
		filters={"name": ("in", list({line["parent"] for line in lines}))},
		fields=[
			"name",
			"reservation_status",
			"reservation_type",
			"guest",
			"guest_name",
			"guest_mobile",
			"arrival_date",
			"departure_date",
			"arrival_time",
			"nights",
			"total_rooms",
			"total_amount",
			"currency",
			"booking_source",
			"guarantee_type",
			"deposit_required",
			"deposit_received",
			"special_requests",
		],
		order_by="guest_name asc",
		limit_page_length=0,
	)

	by_name = {row["name"]: row for row in reservations}
	lines = [line for line in lines if line["parent"] in by_name]
	lines.sort(key=lambda line: (by_name[line["parent"]]["guest_name"] or "", line["name"]))

	room_states = get_room_states(property_name, [l["assigned_room"] for l in lines if l["assigned_room"]])
	guest_flags = get_guest_flags([row["guest"] for row in reservations])
	may_read = _board_disclosure()
	room_type_names = _room_type_names(property_name)
	checked_in_lines = _checked_in_lines(property_name, list(by_name))

	rows = []

	for line in lines:
		reservation = by_name[line["parent"]]
		guest = guest_flags.get(reservation["guest"]) or {}
		room = room_states.get(line["assigned_room"]) if line["assigned_room"] else None
		stay = checked_in_lines.get((line["parent"], line["name"]))

		rows.append(
			{
				"key": line["name"],
				"reservation": reservation["name"],
				"room_line": line["name"],
				"reservation_status": reservation["reservation_status"],
				"reservation_type": reservation["reservation_type"],
				"booking_source": reservation["booking_source"],
				# This board is one row per *room line*, but cancelling and
				# marking a no-show act on the whole booking and stamp every
				# line. A screen offering either verb has to be able to say so,
				# so the room count travels with the row - it was already being
				# fetched and simply was not exposed.
				"total_rooms": cint(reservation["total_rooms"]),
				# The state machine's answer, not a copy of it. `TRANSITIONS` is
				# a pure status->set lookup, so this costs nothing per row and
				# keeps Vue from re-deriving which verbs are legal. It is what to
				# *offer*, never what will succeed: the board is fetched once and
				# never polled, and `_transition` re-reads the status under a lock,
				# so a stale offer fails cleanly instead of corrupting anything.
				# It also says nothing about roles or policy - those are separate
				# checks the caller still has to make.
				"allowed_transitions": sorted(
					reservation_service.TRANSITIONS.get(reservation["reservation_status"], set())
				),
				"guest": reservation["guest"],
				"guest_name": reservation["guest_name"],
				"guest_mobile": reservation["guest_mobile"],
				**_guest_standing(guest, may_read["guest"]),
				**_blacklist_flag(guest),
				"arrival_date": str(line["arrival_date"] or reservation["arrival_date"]),
				"departure_date": str(line["departure_date"] or reservation["departure_date"]),
				"arrival_time": str(reservation["arrival_time"] or ""),
				"nights": line["nights"] or reservation["nights"],
				"adults": line["adults"],
				"children": line["children"],
				"room_type": line["room_type"],
				"room_type_name": room_type_names.get(line["room_type"], line["room_type"]),
				"assigned_room": line["assigned_room"],
				"room_number": room["room_number"] if room else None,
				"room_ready": bool(room and room["ready"]),
				"room_assignable": bool(room and room["assignable"]),
				"occupancy_status": room["occupancy_status"] if room else None,
				"housekeeping_status": room["housekeeping_status"] if room else None,
				"maintenance_status": room["maintenance_status"] if room else None,
				"inventory_status": room["inventory_status"] if room else None,
				"guarantee_type": reservation["guarantee_type"],
				"deposit_required": flt(reservation["deposit_required"], 2),
				"deposit_received": flt(reservation["deposit_received"], 2),
				"deposit_outstanding": flt(
					flt(reservation["deposit_required"]) - flt(reservation["deposit_received"]), 2
				),
				"room_rate": flt(line["room_rate"], 2),
				"currency": reservation["currency"],
				"special_requests": line["special_requests"] or reservation["special_requests"] or "",
				"is_checked_in": bool(stay),
				"stay": stay,
			}
		)

	return {
		"property": property_name,
		"business_date": str(business_date),
		"currency": get_property(property_name).currency,
		"rows": rows,
		"summary": _arrivals_summary(rows),
	}


def _arrivals_summary(rows: list[dict]) -> dict:
	summary = {
		"total": len(rows),
		"pending": sum(1 for r in rows if not r["is_checked_in"]),
		"checked_in": sum(1 for r in rows if r["is_checked_in"]),
		"assigned": sum(1 for r in rows if r["assigned_room"]),
		"unassigned": sum(1 for r in rows if not r["assigned_room"]),
		"ready": sum(1 for r in rows if r["room_ready"]),
		"not_ready": sum(1 for r in rows if r["assigned_room"] and not r["room_ready"]),
		# Counted per booking, not per room line: a deposit is owed once on a
		# three-room reservation, and counting it three times would send the
		# desk chasing money that is not owed.
		"deposit_outstanding": len({r["reservation"] for r in rows if r["deposit_outstanding"] > 0.005}),
	}

	# Only for a caller who was shown the standing it counts (see
	# `_guest_standing`); otherwise the count restores in aggregate what the rows
	# withheld.
	if any("vip_status" in r for r in rows):
		summary["vip"] = sum(1 for r in rows if r.get("vip_status"))

	return summary


def _checked_in_lines(property_name: str, reservations: list[str]) -> dict[tuple, str]:
	"""Which reservation room lines already became a stay, keyed by (res, line)."""
	if not reservations:
		return {}

	records = frappe.get_all(
		stay_service.STAY_DOCTYPE,
		filters={
			"property": property_name,
			"reservation": ("in", reservations),
			"stay_status": ("!=", stay_service.EXPECTED),
		},
		fields=["name", "reservation", "reservation_room_line"],
		limit_page_length=0,
	)

	return {(row["reservation"], row["reservation_room_line"]): row["name"] for row in records}


def _room_type_names(property_name: str) -> dict[str, str]:
	records = frappe.get_all(
		ROOM_TYPE_DOCTYPE,
		filters={"property": property_name},
		fields=["name", "room_type_name"],
		limit_page_length=0,
	)

	return {row["name"]: row["room_type_name"] or row["name"] for row in records}


def _empty_board(property_name: str, business_date, summarise) -> dict:
	"""A board with no rows still carries its zeroed tiles, so a quiet day reads
	as zeros rather than as blanks the screen has to guess at."""
	return {
		"property": property_name,
		"business_date": str(business_date),
		"currency": get_property(property_name).currency,
		"rows": [],
		"summary": summarise([]),
	}


# ---------------------------------------------------------------------------
# Departures
# ---------------------------------------------------------------------------


def get_departures_board(property_name: str, on_date=None) -> dict:
	"""One row per stay leaving on the business date, with what blocks it.

	The blocker list is the checkout service's own, evaluated here against rows
	fetched in bulk. The board therefore cannot promise a checkout the checkout
	screen would refuse.
	"""
	business_date = resolve_business_date(property_name, on_date)

	stays = frappe.get_all(
		stay_service.STAY_DOCTYPE,
		filters={
			"property": property_name,
			"departure_date": business_date,
			"stay_status": ("in", DEPARTURE_STATES),
		},
		fields=[
			"name",
			"stay_status",
			"guest",
			"guest_name",
			"room",
			"room_type",
			"reservation",
			"arrival_date",
			"departure_date",
			"nights",
			"adults",
			"children",
			"room_rate",
			"currency",
			"folio",
			"checked_out_on",
		],
		order_by="room asc",
		limit_page_length=0,
	)

	if not stays:
		return _empty_board(property_name, business_date, _departures_summary)

	folios_by_stay = _folios_by_stay(property_name, [s["name"] for s in stays])
	room_states = get_room_states(property_name, [s["room"] for s in stays if s["room"]])
	guest_flags = get_guest_flags([s["guest"] for s in stays])
	may_read = _board_disclosure()
	room_type_names = _room_type_names(property_name)

	rows = []

	for stay in stays:
		folios = folios_by_stay.get(stay["name"], [])
		primary = next((f for f in folios if f["name"] == stay["folio"]), None) or (folios[0] if folios else None)
		related = [f for f in folios if not primary or f["name"] != primary["name"]]
		room = room_states.get(stay["room"]) if stay["room"] else None
		guest = guest_flags.get(stay["guest"]) or {}

		if primary:
			blockers = checkout_service.get_departure_blockers(stay["stay_status"], primary, related)
		else:
			# No folio at all is itself the blocker; checkout refuses the same way.
			blockers = [frappe._("Stay {0} has no folio.").format(stay["name"])]

		balance = flt(primary["balance"], 2) if primary else 0.0
		related_balance = sum(flt(f["balance"], 2) for f in related)

		rows.append(
			{
				"key": stay["name"],
				"stay": stay["name"],
				"stay_status": stay["stay_status"],
				"reservation": stay["reservation"],
				"guest": stay["guest"],
				"guest_name": stay["guest_name"],
				**_guest_standing(guest, may_read["guest"]),
				"room": stay["room"],
				"room_number": room["room_number"] if room else stay["room"],
				"room_type": stay["room_type"],
				"room_type_name": room_type_names.get(stay["room_type"], stay["room_type"]),
				"housekeeping_status": room["housekeeping_status"] if room else None,
				"arrival_date": str(stay["arrival_date"]),
				"departure_date": str(stay["departure_date"]),
				"nights": stay["nights"],
				"adults": stay["adults"],
				"children": stay["children"],
				"currency": (primary["currency"] if primary else None) or stay["currency"],
				"checked_out_on": str(stay["checked_out_on"] or ""),
				"is_checked_out": stay["stay_status"] == stay_service.CHECKED_OUT,
				**_folio_position(
					{
						"folio": primary["name"] if primary else None,
						"folio_status": primary["folio_status"] if primary else None,
						"balance": balance,
						"related_folios": len(related),
						"related_balance": flt(related_balance, 2),
						"blockers": blockers,
						"can_check_out": not blockers,
					},
					may_read["folio"],
				),
			}
		)

	return {
		"property": property_name,
		"business_date": str(business_date),
		"currency": get_property(property_name).currency,
		"rows": rows,
		"summary": _departures_summary(rows),
	}


def _departures_summary(rows: list[dict]) -> dict:
	"""Counts over the rows as they were disclosed, not as they were assembled.

	Reads through `_money(row)` so a caller who was not shown the folio position
	is not handed it back as a total. A summary is a lossy view of the same data,
	and totalling withheld figures would put the money back on the screen with the
	rows' names stripped off - which is not a protection, just a different report.
	"""
	outstanding = sum(_money(r, "balance") + _money(r, "related_balance") for r in rows)
	disclosed = any("balance" in r for r in rows)

	summary = {
		"total": len(rows),
		"due_out": sum(1 for r in rows if not r["is_checked_out"]),
		"checked_out": sum(1 for r in rows if r["is_checked_out"]),
		"ready": sum(1 for r in rows if r.get("can_check_out")),
		"blocked": sum(
			1 for r in rows if not r["is_checked_out"] and "can_check_out" in r and not r["can_check_out"]
		),
	}

	if not disclosed:
		return summary

	return {
		**summary,
		"balance_pending": sum(
			1
			for r in rows
			if not r["is_checked_out"]
			and abs(_money(r, "balance") + _money(r, "related_balance")) > 0.005
		),
		"outstanding_balance": flt(outstanding, 2),
	}


def _money(row: dict, field: str) -> float:
	"""A money field from a row that may not have been given one."""
	return flt(row.get(field) or 0)


def _folios_by_stay(property_name: str, stays: list[str]) -> dict[str, list[dict]]:
	"""Every folio attached to these stays, grouped, in one query."""
	if not stays:
		return {}

	records = frappe.get_all(
		folio_service.FOLIO_DOCTYPE,
		filters={"property": property_name, "stay": ("in", stays)},
		fields=["name", "stay", "folio_type", "folio_status", "balance", "currency"],
		limit_page_length=0,
	)

	grouped: dict[str, list[dict]] = {}
	for row in records:
		grouped.setdefault(row["stay"], []).append(row)

	return grouped


# ---------------------------------------------------------------------------
# In house
# ---------------------------------------------------------------------------


def get_in_house_board(property_name: str) -> dict:
	"""One row per guest in the house, with what they owe and what blocks the door.

	A sibling of `get_arrivals_board` and `get_departures_board`, built here and
	not in `stays` for two reasons. `stays.get_in_house` is read by
	`get_dashboard` and by the night audit, where a wider field list is dead
	weight and a changed one ripples; and every bulk helper this board needs -
	room states, folios by stay, guest flags, room type names - already lives
	here, next to the checkout service's own blocker rule. `services.stays`
	cannot reach any of it without importing `front_office`, which imports
	`stays`.

	The row set is the same one `stays.get_in_house` returns: the same property,
	the same two statuses (`IN_HOUSE_STATES`), the same `room` ordering. It is
	read here rather than borrowed because the board needs `reservation` and
	`currency`, which that reader does not select, and a second query over the
	same table to add two columns is waste, not safety.

	Readiness and blockers are the checkout service's answer, never re-derived:
	a board that told the desk a guest may leave while the checkout screen
	refused them would be worse than a board with no badge at all (SAD section 6).
	"""
	business_date = resolve_business_date(property_name)

	stays = frappe.get_all(
		stay_service.STAY_DOCTYPE,
		filters={"property": property_name, "stay_status": ("in", IN_HOUSE_STATES)},
		fields=[
			"name",
			"stay_status",
			"guest",
			"guest_name",
			"room",
			"room_type",
			"reservation",
			"arrival_date",
			"departure_date",
			"nights",
			"adults",
			"children",
			"room_rate",
			"currency",
			"folio",
			# Identity capture is a register/compliance obligation, and `check_in`
			# can be told to skip it, so the one screen that sees every in-house
			# guest is where an unverified stay has to be visible before the guest
			# leaves. Shown as an exception, never as a column of ticks.
			"id_verified",
		],
		order_by="room asc",
		limit_page_length=0,
	)

	if not stays:
		return _empty_board(property_name, business_date, _in_house_summary)

	guests = [s["guest"] for s in stays]

	folios_by_stay = _folios_by_stay(property_name, [s["name"] for s in stays])
	room_states = get_room_states(property_name, [s["room"] for s in stays if s["room"]])
	guest_flags = get_guest_flags(guests)
	room_type_names = _room_type_names(property_name)
	# A count and a grade, never a body. An alert body is free text about a guest
	# who may be standing at the counter reading the screen, so a board is told
	# how many there are and how bad the worst one is; the guest endpoints
	# authorise reading one. The grade is what stops the count fusing an allergy
	# with a room preference, which is how staff learn to ignore a number.
	#
	# The business date is passed in because it is already resolved above; the
	# helper would otherwise re-read the same column.
	alert_summary = guest_identity_service.get_active_alert_summary(
		guests, property_name, business_date=business_date
	)
	may_read = _board_disclosure()

	rows = []

	for stay in stays:
		folios = folios_by_stay.get(stay["name"], [])
		primary = next((f for f in folios if f["name"] == stay["folio"]), None) or (
			folios[0] if folios else None
		)
		related = [f for f in folios if not primary or f["name"] != primary["name"]]
		room = room_states.get(stay["room"]) if stay["room"] else None
		guest = guest_flags.get(stay["guest"]) or {}

		if primary:
			blockers = checkout_service.get_departure_blockers(stay["stay_status"], primary, related)
		else:
			# No folio at all is itself the blocker; checkout refuses the same way.
			blockers = [frappe._("Stay {0} has no folio.").format(stay["name"])]

		rows.append(
			{
				"key": stay["name"],
				# `name` as well as `stay`: this board is what `api.stays.in_house`
				# returns, and its rows have always been identified by `name`.
				"name": stay["name"],
				"stay": stay["name"],
				"stay_status": stay["stay_status"],
				"reservation": stay["reservation"],
				"property": property_name,
				"guest": stay["guest"],
				"guest_name": stay["guest_name"],
				**_guest_standing(guest, may_read["guest"]),
				**_blacklist_flag(guest),
				# The count travels with the grade: both are read out of Guest
				# Alert, whose reader set *is* Guest's, and a room attendant who
				# learns that the guest in 412 carries two alerts has been told
				# something about that person and nothing that helps them clean.
				**_alert_position(alert_summary.get(stay["guest"]), may_read["guest"]),
				"id_verified": bool(stay["id_verified"]),
				"room": stay["room"],
				"room_number": room["room_number"] if room else stay["room"],
				"room_type": stay["room_type"],
				"room_type_name": room_type_names.get(stay["room_type"], stay["room_type"]),
				"housekeeping_status": room["housekeeping_status"] if room else None,
				"arrival_date": str(stay["arrival_date"]),
				"departure_date": str(stay["departure_date"]),
				"nights": stay["nights"],
				"adults": stay["adults"],
				"children": stay["children"],
				"room_rate": flt(stay["room_rate"], 2),
				"currency": (primary["currency"] if primary else None) or stay["currency"],
				**_folio_position(
					{
						"folio": primary["name"] if primary else None,
						"folio_status": primary["folio_status"] if primary else None,
						# The balance the folio service maintains, not a sum of
						# charges recomputed here: one authoritative figure, and
						# the folio owns it.
						"balance": flt(primary["balance"], 2) if primary else 0.0,
						# Split folios stay counted, never folded into the balance
						# above. A company-pay split is a different payer's debt,
						# and adding it to the guest's would ask the wrong person
						# for the money.
						"related_folios": len(related),
						"related_balance": flt(sum(flt(f["balance"]) for f in related), 2),
						"blockers": blockers,
						"can_check_out": not blockers,
					},
					may_read["folio"],
				),
			}
		)

	return {
		"property": property_name,
		"business_date": str(business_date),
		"currency": get_property(property_name).currency,
		"rows": rows,
		"summary": _in_house_summary(rows),
	}


def _in_house_summary(rows: list[dict]) -> dict:
	"""The house at a glance.

	`in_house`, `due_out`, `adults` and `children` keep the names and the meaning
	they had when `api.stays.in_house` computed them itself; the screen and its
	tests are built on them.

	The guest and folio counts appear only for a caller who was shown the rows
	they are counted from — otherwise a summary would hand back, in aggregate,
	exactly what the rows withheld.
	"""
	summary = {
		"total": len(rows),
		"in_house": sum(1 for r in rows if r["stay_status"] == stay_service.IN_HOUSE),
		"due_out": sum(1 for r in rows if r["stay_status"] == stay_service.DUE_OUT),
		"adults": sum(cint(r["adults"]) for r in rows),
		"children": sum(cint(r["children"]) for r in rows),
	}

	if any("vip_status" in r for r in rows):
		summary["vip"] = sum(1 for r in rows if r.get("vip_status"))
		summary["with_alerts"] = sum(1 for r in rows if r.get("alert_count"))

	if any("balance" in r for r in rows):
		outstanding = sum(_money(r, "balance") + _money(r, "related_balance") for r in rows)

		summary["ready_to_check_out"] = sum(1 for r in rows if r.get("can_check_out"))
		summary["blocked"] = sum(1 for r in rows if not r.get("can_check_out"))
		summary["balance_pending"] = sum(
			1 for r in rows if abs(_money(r, "balance") + _money(r, "related_balance")) > 0.005
		)
		summary["outstanding_balance"] = flt(outstanding, 2)

	return summary


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------


def get_calendar(
	property_name: str,
	from_date=None,
	to_date=None,
	room_type: str | None = None,
	start: int = 0,
	limit: int = 25,
) -> dict:
	"""A room-by-date grid of what occupies each room.

	Bounded twice over — a capped date window and a page of rooms — because the
	honest shape of this screen at 500 rooms is a window onto the inventory, not
	the whole of it (SAD section 13).

	Bars are returned as date ranges rather than one entry per night: a fortnight
	view of 50 rooms is then a few hundred objects instead of several thousand.
	"""
	from_date = getdate(from_date) if from_date else resolve_business_date(property_name)
	to_date = getdate(to_date) if to_date else add_days(from_date, 13)

	if to_date < from_date:
		to_date = from_date

	if (to_date - from_date).days + 1 > MAX_CALENDAR_DAYS:
		to_date = add_days(from_date, MAX_CALENDAR_DAYS - 1)

	limit = max(1, min(cint(limit) or 25, MAX_CALENDAR_ROOMS))
	start = max(0, cint(start))

	room_filters = {"property": property_name, "is_active": 1}
	if room_type:
		room_filters["room_type"] = room_type

	total_rooms = frappe.db.count(ROOM_DOCTYPE, room_filters)

	rooms = frappe.get_all(
		ROOM_DOCTYPE,
		filters=room_filters,
		fields=list(ROOM_STATE_FIELDS),
		order_by="room_type asc, room_number asc",
		limit_start=start,
		limit_page_length=limit,
	)

	room_names = [row["name"] for row in rooms]
	room_type_names = _room_type_names(property_name)

	for row in rooms:
		row["room_type_name"] = room_type_names.get(row["room_type"], row["room_type"])

	bars = []
	bars.extend(_stay_bars(property_name, room_names, from_date, to_date))
	bars.extend(_reservation_bars(property_name, room_names, from_date, to_date))
	bars.extend(_block_bars(property_name, room_names, from_date, to_date))

	return {
		"property": property_name,
		"from_date": str(from_date),
		"to_date": str(to_date),
		"dates": _date_range(from_date, to_date),
		"rooms": rooms,
		"bars": bars,
		"unassigned": _unassigned_demand(property_name, from_date, to_date, room_type),
		"room_types": [
			{"name": name, "room_type_name": label} for name, label in sorted(room_type_names.items())
		],
		"total_rooms": total_rooms,
		"start": start,
		"limit": limit,
		"has_more": start + len(rooms) < total_rooms,
	}


def _date_range(from_date, to_date) -> list[str]:
	days = (to_date - from_date).days
	return [str(add_days(from_date, offset)) for offset in range(days + 1)]


def _stay_bars(property_name: str, rooms: list[str], from_date, to_date) -> list[dict]:
	"""Guests physically in a room over the window."""
	if not rooms:
		return []

	records = frappe.get_all(
		stay_service.STAY_DOCTYPE,
		filters={
			"property": property_name,
			"room": ("in", rooms),
			"arrival_date": ("<=", to_date),
			"departure_date": (">=", from_date),
			"stay_status": ("in", (stay_service.IN_HOUSE, stay_service.DUE_OUT, stay_service.CHECKED_OUT)),
		},
		fields=[
			"name",
			"room",
			"guest_name",
			"reservation",
			"arrival_date",
			"departure_date",
			"stay_status",
		],
		order_by="room asc, arrival_date asc",
		limit_page_length=0,
	)

	return [
		{
			"key": f"stay:{row['name']}",
			"kind": "stay",
			"room": row["room"],
			"label": row["guest_name"],
			"status": row["stay_status"],
			"from_date": str(row["arrival_date"]),
			"to_date": str(row["departure_date"]),
			"stay": row["name"],
			"reservation": row["reservation"],
		}
		for row in records
	]


def _reservation_bars(property_name: str, rooms: list[str], from_date, to_date) -> list[dict]:
	"""Bookings holding a specific room but not yet checked in.

	Only assigned lines can be drawn against a room; everything else is demand
	without a room and belongs in `unassigned`, not on a row it does not own.
	"""
	if not rooms:
		return []

	lines = frappe.get_all(
		RESERVATION_ROOM_DOCTYPE,
		filters={
			"parenttype": reservation_service.RESERVATION_DOCTYPE,
			"assigned_room": ("in", rooms),
			"arrival_date": ("<=", to_date),
			"departure_date": (">=", from_date),
			"reservation_status": ("in", CALENDAR_BAR_STATES),
		},
		fields=[
			"name",
			"parent",
			"assigned_room",
			"arrival_date",
			"departure_date",
			"reservation_status",
			"room_type",
		],
		order_by="assigned_room asc, arrival_date asc",
		limit_page_length=0,
	)

	if not lines:
		return []

	guest_names = dict(
		frappe.get_all(
			reservation_service.RESERVATION_DOCTYPE,
			filters={"name": ("in", list({l["parent"] for l in lines}))},
			fields=["name", "guest_name"],
			as_list=True,
			limit_page_length=0,
		)
	)

	return [
		{
			"key": f"res:{row['name']}",
			"kind": "reservation",
			"room": row["assigned_room"],
			"label": guest_names.get(row["parent"], row["parent"]),
			"status": row["reservation_status"],
			"from_date": str(row["arrival_date"]),
			"to_date": str(row["departure_date"]),
			"reservation": row["parent"],
			"room_line": row["name"],
		}
		for row in lines
	]


def _block_bars(property_name: str, rooms: list[str], from_date, to_date) -> list[dict]:
	"""Inventory held out of sale for a date range."""
	if not rooms:
		return []

	records = frappe.get_all(
		ROOM_BLOCK_DOCTYPE,
		filters={
			"property": property_name,
			"room": ("in", rooms),
			"status": "Active",
			"docstatus": 1,
			"from_date": ("<=", to_date),
			"to_date": (">=", from_date),
		},
		fields=["name", "room", "block_type", "from_date", "to_date", "reason"],
		order_by="room asc, from_date asc",
		limit_page_length=0,
	)

	return [
		{
			"key": f"block:{row['name']}",
			"kind": "block",
			"room": row["room"],
			"label": row["block_type"],
			"status": row["block_type"],
			"from_date": str(row["from_date"]),
			"to_date": str(row["to_date"]),
			"reason": row["reason"] or "",
		}
		for row in records
	]


def _unassigned_demand(property_name: str, from_date, to_date, room_type: str | None) -> list[dict]:
	"""Booked rooms in the window that have no room yet.

	Shown beside the grid because it is the work the calendar exists to
	surface: inventory sold but not placed.
	"""
	filters = {
		"parenttype": reservation_service.RESERVATION_DOCTYPE,
		"assigned_room": ("is", "not set"),
		"property": property_name,
		"arrival_date": ("<=", to_date),
		"departure_date": (">=", from_date),
		"reservation_status": ("in", CALENDAR_RESERVATION_STATES),
	}

	if room_type:
		filters["room_type"] = room_type

	lines = frappe.get_all(
		RESERVATION_ROOM_DOCTYPE,
		filters=filters,
		fields=[
			"name",
			"parent",
			"room_type",
			"rooms",
			"arrival_date",
			"departure_date",
			"reservation_status",
		],
		order_by="arrival_date asc",
		limit_page_length=200,
	)

	if not lines:
		return []

	guest_names = dict(
		frappe.get_all(
			reservation_service.RESERVATION_DOCTYPE,
			filters={"name": ("in", list({l["parent"] for l in lines}))},
			fields=["name", "guest_name"],
			as_list=True,
			limit_page_length=0,
		)
	)

	room_type_names = _room_type_names(property_name)

	return [
		{
			"key": f"unassigned:{row['name']}",
			"reservation": row["parent"],
			"room_line": row["name"],
			"label": guest_names.get(row["parent"], row["parent"]),
			"room_type": row["room_type"],
			"room_type_name": room_type_names.get(row["room_type"], row["room_type"]),
			"rooms": row["rooms"],
			"from_date": str(row["arrival_date"]),
			"to_date": str(row["departure_date"]),
			"status": row["reservation_status"],
		}
		for row in lines
	]
