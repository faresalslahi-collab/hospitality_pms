"""Finding the bookings that predate one-room-per-row.

Wave 5 makes confirmation normalise a booked quantity into one `Reservation
Room` row per physical room (P1-6). Bookings confirmed before that arrived with
`rooms = 3` on a single row, and those rows are still there.

Nothing here rewrites them, and no patch does it on migrate. A historical row
saying three rooms is genuinely ambiguous: three rooms were sold and inventory
counted them, but only one was ever assignable, one Stay exists at most, and one
folio took the whole deposit. Splitting it now would invent two rooms that never
had a guest, two folios that were never opened, and - if the booking is already
checked in - two arrivals that never happened. The reverse is worse: collapsing
it to one room would silently release inventory the hotel sold.

So this reports, and a human decides:

    bench --site <site> execute hospitality_pms.setup.inventory_audit.report

Rows on **Draft** reservations need nothing at all - they normalise the moment
they are confirmed. Rows on cancelled or no-show bookings hold no inventory and
need nothing either. What matters is the holding states, and within those, the
ones a guest has already arrived on.
"""

import frappe

from hospitality_pms.services.availability import HOLDING_RESERVATION_STATES

CHECKED_IN = "Checked In"


def find_multi_room_lines() -> list[dict]:
	"""Every room line still carrying a quantity while it holds inventory."""
	return frappe.db.sql(
		"""
		select
			line.name as room_line,
			line.parent as reservation,
			line.property,
			line.room_type,
			line.rooms,
			line.arrival_date,
			line.departure_date,
			line.assigned_room,
			line.reservation_status,
			(select count(*) from `tabStay` stay where stay.reservation = line.parent) as stays,
			(select count(*) from `tabGuest Folio` folio where folio.reservation = line.parent) as folios
		from `tabReservation Room` line
		where line.rooms > 1
		  and line.reservation_status in %(holding)s
		order by line.reservation_status, line.arrival_date, line.parent
		""",
		{"holding": HOLDING_RESERVATION_STATES},
		as_dict=True,
	)


def report() -> dict:
	"""Read-only. Says what is there and what each case would need."""
	rows = find_multi_room_lines()

	summary = {
		"lines": len(rows),
		"reservations": len({row["reservation"] for row in rows}),
		"rooms_held": sum(int(row["rooms"] or 1) for row in rows),
		"checked_in": sum(1 for row in rows if row["reservation_status"] == CHECKED_IN),
		"assigned": sum(1 for row in rows if row["assigned_room"]),
		"by_status": {},
	}

	for row in rows:
		summary["by_status"].setdefault(row["reservation_status"], 0)
		summary["by_status"][row["reservation_status"]] += 1

	print(f"Reservation Room rows holding a quantity > 1: {summary['lines']}")
	print(f"  across reservations:        {summary['reservations']}")
	print(f"  rooms held by those rows:   {summary['rooms_held']}")
	print(f"  by reservation status:      {summary['by_status'] or '-'}")
	print(f"  already assigned a room:    {summary['assigned']}")
	print(f"  already checked in:         {summary['checked_in']}")

	if not rows:
		print("\nNothing to do: every holding room line is already one room per row.")
		return {"summary": summary, "lines": rows}

	print(
		"\nNot normalised automatically. Confirmed-but-not-arrived bookings can be"
		"\nre-confirmed through the service to split them safely; anything already"
		"\nchecked in has a Stay and a folio behind one of the rooms and needs a"
		"\nfront-office decision, not a migration."
	)

	for row in rows:
		print(
			f"  {row['reservation']:24} {row['reservation_status']:12} "
			f"{row['room_type']:18} rooms={row['rooms']} "
			f"{row['arrival_date']}..{row['departure_date']} "
			f"stays={row['stays']} folios={row['folios']}"
		)

	return {"summary": summary, "lines": rows}
