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
from hospitality_pms.services import housekeeping as housekeeping_service
from hospitality_pms.services import maintenance as maintenance_service
from hospitality_pms.services import reservations as reservation_service
from hospitality_pms.services import rooms as room_service
from hospitality_pms.services import stays as stay_service
from hospitality_pms.services.property import get_business_date, get_property

ROOM_DOCTYPE = "Hotel Room"
ROOM_TYPE_DOCTYPE = "Room Type"
RESERVATION_ROOM_DOCTYPE = "Reservation Room"
ROOM_BLOCK_DOCTYPE = "Hospitality Room Block"
GUEST_DOCTYPE = "Hospitality Guest"
NIGHT_AUDIT_DOCTYPE = "Hospitality Night Audit"

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

	Defaults to the property's business date rather than today: a property that
	has not run its night audit is still working yesterday, and its arrivals
	board must agree with its audit (SAS section 6).
	"""
	return getdate(on_date) if on_date else getdate(get_business_date(property_name))


def get_room_states(property_name: str, rooms: list[str] | None = None) -> dict[str, dict]:
	"""Every room's four dimensions, keyed by room name, in one query."""
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

	for row in records:
		row["assignable"] = room_service.is_assignable(row["name"], state=row)
		row["ready"] = bool(row.get("housekeeping_status") in room_service.READY_HOUSEKEEPING)

	return {row["name"]: row for row in records}


def get_guest_flags(guests: list[str]) -> dict[str, dict]:
	"""VIP standing and blacklist state for a set of guests, in one query.

	The desk needs to know before the guest reaches the counter, and it is the
	same two fields on every board.
	"""
	guests = [g for g in set(guests or []) if g]
	if not guests:
		return {}

	records = frappe.get_all(
		GUEST_DOCTYPE,
		filters={"name": ("in", guests)},
		fields=["name", "vip_status", "is_blacklisted", "guest_type"],
		limit_page_length=0,
	)

	return {row["name"]: row for row in records}


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

	return {
		"property": property_name,
		"property_name": property_doc.property_name,
		"business_date": str(business_date),
		"currency": property_doc.currency,
		"rooms": _room_counts(rooms),
		"front_office": _front_office_counts(property_name, business_date, in_house),
		"revenue": _revenue_today(property_name, business_date, property_doc.currency),
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
			elif housekeeping == "Dirty":
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
		from `tabHospitality Folio Charge` c
		inner join `tabHospitality Guest Folio` f on f.name = c.parent
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
		from `tabHospitality Folio Payment` p
		inner join `tabHospitality Guest Folio` f on f.name = p.parent
		where f.property = %(property)s
		  and p.business_date = %(date)s
		  and p.is_reversed = 0
		""",
		{"property": property_name, "date": business_date},
	)[0][0]

	outstanding = frappe.db.sql(
		"""
		select coalesce(sum(balance), 0)
		from `tabHospitality Guest Folio`
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
	records = frappe.get_all(
		NIGHT_AUDIT_DOCTYPE,
		filters={"property": property_name, "audit_status": "Closed"},
		fields=[
			"name",
			"business_date",
			"occupancy_percentage",
			"adr",
			"revpar",
			"room_revenue",
			"total_revenue",
			"payments_received",
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
			"Hospitality Housekeeping Task",
			{
				"property": property_name,
				"scheduled_date": business_date,
				"task_status": ("in", OPEN_HOUSEKEEPING),
			},
		),
		"maintenance_open": frappe.db.count(
			"Hospitality Maintenance Ticket",
			{"property": property_name, "ticket_status": ("in", OPEN_MAINTENANCE)},
		),
		"guest_requests_open": frappe.db.count(
			"Hospitality Guest Request",
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
				"guest": reservation["guest"],
				"guest_name": reservation["guest_name"],
				"guest_mobile": reservation["guest_mobile"],
				"vip_status": guest.get("vip_status") or "",
				"is_blacklisted": bool(guest.get("is_blacklisted")),
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
	return {
		"total": len(rows),
		"pending": sum(1 for r in rows if not r["is_checked_in"]),
		"checked_in": sum(1 for r in rows if r["is_checked_in"]),
		"assigned": sum(1 for r in rows if r["assigned_room"]),
		"unassigned": sum(1 for r in rows if not r["assigned_room"]),
		"ready": sum(1 for r in rows if r["room_ready"]),
		"not_ready": sum(1 for r in rows if r["assigned_room"] and not r["room_ready"]),
		"vip": sum(1 for r in rows if r["vip_status"]),
		# Counted per booking, not per room line: a deposit is owed once on a
		# three-room reservation, and counting it three times would send the
		# desk chasing money that is not owed.
		"deposit_outstanding": len({r["reservation"] for r in rows if r["deposit_outstanding"] > 0.005}),
	}


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
				"vip_status": guest.get("vip_status") or "",
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
				"folio": primary["name"] if primary else None,
				"folio_status": primary["folio_status"] if primary else None,
				"balance": balance,
				"related_folios": len(related),
				"related_balance": flt(related_balance, 2),
				"currency": (primary["currency"] if primary else None) or stay["currency"],
				"checked_out_on": str(stay["checked_out_on"] or ""),
				"is_checked_out": stay["stay_status"] == stay_service.CHECKED_OUT,
				"blockers": blockers,
				"can_check_out": not blockers,
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
	outstanding = sum(r["balance"] + r["related_balance"] for r in rows if not r["is_checked_out"])

	return {
		"total": len(rows),
		"due_out": sum(1 for r in rows if not r["is_checked_out"]),
		"checked_out": sum(1 for r in rows if r["is_checked_out"]),
		"ready": sum(1 for r in rows if r["can_check_out"]),
		"blocked": sum(1 for r in rows if not r["is_checked_out"] and not r["can_check_out"]),
		"balance_pending": sum(
			1 for r in rows if not r["is_checked_out"] and abs(r["balance"] + r["related_balance"]) > 0.005
		),
		"outstanding_balance": flt(outstanding, 2),
	}


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
