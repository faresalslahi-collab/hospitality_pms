"""Cancellations and No Shows.

Operational question answered: of the arrivals expected in the window, which
never happened - because the guest cancelled, or because they simply did not
show - and what did that cost in cancellation charge and lost room nights?

Scoped by `arrival_date`, not by when the cancellation or no-show was
recorded: this reports lost demand for arrivals due in the window, matching
how Occupancy and Revenue and Revenue by Room Type report the window's
operational activity rather than when a record was last touched.

`hospitality_pms.services.reservations.cancel` and `.mark_no_show` write
different fields on the reservation: `cancel` sets `cancelled_on`,
`cancelled_by` and `cancellation_reason`; `mark_no_show` sets only
`no_show_on` and `cancellation_charge` - it does not record a "no-show by" or
a reason on the reservation itself (that detail lives in the append-only
`Reservation Log`, a separately access-controlled audit trail,
and is deliberately not joined into this report). "Cancelled On" therefore
falls back to `no_show_on` for a No Show row, and "Cancelled By" and "Reason"
are blank there - that gap in the data is real, not a bug in this report.

"Room Nights Lost" is `total_rooms x nights`: the full room-night value of
the reservation that never materialised.
"""

import frappe
from frappe import _
from frappe.utils import getdate, nowdate

#: Reservation statuses this report exists to explain.
LOST_STATUSES = ("Cancelled", "No Show")


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
	# status list is passed as a tuple parameter, never string-formatted
	# into the query.
	return frappe.db.sql(
		"""
		select r.name as reservation,
		       r.guest_name as guest,
		       r.arrival_date as arrival,
		       r.reservation_status as status,
		       coalesce(r.cancelled_on, r.no_show_on) as cancelled_on,
		       r.cancelled_by as cancelled_by,
		       r.cancellation_reason as reason,
		       coalesce(r.cancellation_charge, 0) as cancellation_charge,
		       coalesce(r.total_rooms, 1) * coalesce(r.nights, 0) as room_nights_lost
		from `tabReservation` r
		where r.property = %(property)s
		  and r.reservation_status in %(statuses)s
		  and r.arrival_date between %(from_date)s and %(to_date)s
		order by coalesce(r.cancelled_on, r.no_show_on) desc, r.arrival_date desc
		""",
		{
			"property": property_name,
			"from_date": from_date,
			"to_date": to_date,
			"statuses": LOST_STATUSES,
		},
		as_dict=True,
	)


def get_columns():
	return [
		{
			"fieldname": "reservation",
			"label": _("Reservation"),
			"fieldtype": "Link",
			"options": "Reservation",
			"width": 150,
		},
		{"fieldname": "guest", "label": _("Guest"), "fieldtype": "Data", "width": 150},
		{"fieldname": "arrival", "label": _("Arrival"), "fieldtype": "Date", "width": 100},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 100},
		{
			"fieldname": "cancelled_on",
			"label": _("Cancelled On"),
			"fieldtype": "Datetime",
			"width": 160,
		},
		{
			"fieldname": "cancelled_by",
			"label": _("Cancelled By"),
			"fieldtype": "Link",
			"options": "User",
			"width": 150,
		},
		{"fieldname": "reason", "label": _("Reason"), "fieldtype": "Data", "width": 200},
		{
			"fieldname": "cancellation_charge",
			"label": _("Cancellation Charge"),
			"fieldtype": "Currency",
			"width": 140,
		},
		{
			"fieldname": "room_nights_lost",
			"label": _("Room Nights Lost"),
			"fieldtype": "Int",
			"width": 130,
		},
	]
