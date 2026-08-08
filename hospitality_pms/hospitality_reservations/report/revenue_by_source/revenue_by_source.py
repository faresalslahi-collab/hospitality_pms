"""Revenue by Source.

Sales question answered: which booking sources and channels bring the
reservations, the room nights, and the revenue - and what is each of those
bookings worth on average?

Scoped by arrival date, not booking date: this reports the business a source
delivered to the property during the window, the same way Occupancy and
Revenue and Revenue by Room Type report the window's operational activity
rather than when it was booked.

Only reservations that hold or held a firm commitment count towards revenue:
Confirmed, Guaranteed, Checked In, Checked Out and Closed. Draft, Waitlisted,
Cancelled and No Show reservations never produced revenue and are excluded,
the same distinction Cancellations and No Shows reports on separately.

Room nights are `rooms x nights` summed across a reservation's room lines
(`Reservation Room`), and revenue is the reservation's own `total_amount` -
the commercial value confirmed at booking time. Every division is guarded:
a source with no reservations in the window reports an average booking value
of 0 rather than raising.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

#: Reservation statuses that represent a firm, revenue-producing booking.
REVENUE_STATUSES = ("Confirmed", "Guaranteed", "Checked In", "Checked Out", "Closed")


def execute(filters=None):
	filters = frappe._dict(filters or {})

	if not filters.get("property"):
		frappe.throw(_("Property is mandatory."))

	from_date = getdate(filters.get("from_date") or nowdate())
	to_date = getdate(filters.get("to_date") or nowdate())

	if from_date > to_date:
		frappe.throw(_("From Date cannot be after To Date."))

	columns = get_columns()
	data = get_data(filters.property, from_date, to_date)

	return columns, data


def get_data(property_name: str, from_date, to_date) -> list[dict]:
	# Property is mandatory and is the scoping boundary for this query:
	# `r.property = %(property)s` is applied before anything else. The
	# reservation_status list is passed as a tuple parameter, never
	# string-formatted into the query.
	rows = frappe.db.sql(
		"""
		select booking_source,
		       channel,
		       count(*) as reservations,
		       coalesce(sum(room_nights), 0) as room_nights,
		       coalesce(sum(total_amount), 0) as revenue
		from (
			select r.name as name,
			       coalesce(nullif(r.booking_source, ''), %(unspecified)s) as booking_source,
			       coalesce(nullif(r.channel, ''), %(direct)s) as channel,
			       coalesce(
			           (select sum(rr.rooms * rr.nights)
			            from `tabReservation Room` rr
			            where rr.parent = r.name),
			           0
			       ) as room_nights,
			       coalesce(r.total_amount, 0) as total_amount
			from `tabHotel Reservation` r
			where r.property = %(property)s
			  and r.arrival_date between %(from_date)s and %(to_date)s
			  and r.reservation_status in %(statuses)s
		) booked
		group by booking_source, channel
		order by revenue desc
		""",
		{
			"property": property_name,
			"from_date": from_date,
			"to_date": to_date,
			"statuses": REVENUE_STATUSES,
			"unspecified": _("Unspecified"),
			"direct": _("Direct"),
		},
		as_dict=True,
	)

	if not rows:
		return []

	data = []
	total_reservations = 0
	total_room_nights = 0
	total_revenue = 0.0

	for row in rows:
		reservations = int(row.reservations)
		revenue = flt(row.revenue)

		data.append(
			{
				"booking_source": row.booking_source,
				"channel": row.channel,
				"reservations": reservations,
				"room_nights": int(row.room_nights),
				"revenue": flt(revenue, 2),
				"average_booking_value": _safe_div(revenue, reservations),
			}
		)

		total_reservations += reservations
		total_room_nights += int(row.room_nights)
		total_revenue += revenue

	data.append(
		{
			"booking_source": _("Total"),
			"channel": "",
			"reservations": total_reservations,
			"room_nights": total_room_nights,
			"revenue": flt(total_revenue, 2),
			"average_booking_value": _safe_div(total_revenue, total_reservations),
		}
	)

	return data


def _safe_div(numerator: float, denominator: float) -> float:
	"""Division guarded against a zero (or falsy) denominator. Never raises."""
	if not denominator:
		return 0.0
	return flt(numerator / denominator, 2)


def get_columns():
	return [
		{"fieldname": "booking_source", "label": _("Booking Source"), "fieldtype": "Data", "width": 150},
		{"fieldname": "channel", "label": _("Channel"), "fieldtype": "Data", "width": 130},
		{"fieldname": "reservations", "label": _("Reservations"), "fieldtype": "Int", "width": 110},
		{"fieldname": "room_nights", "label": _("Room Nights"), "fieldtype": "Int", "width": 110},
		{"fieldname": "revenue", "label": _("Revenue"), "fieldtype": "Currency", "width": 130},
		{
			"fieldname": "average_booking_value",
			"label": _("Average Booking Value"),
			"fieldtype": "Currency",
			"width": 160,
		},
	]
