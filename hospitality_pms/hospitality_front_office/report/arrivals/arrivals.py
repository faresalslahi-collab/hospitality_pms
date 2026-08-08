"""Arrivals — who is due to check in today (or on a chosen date), and are they ready to be checked in.

Answers the front desk's opening-shift question: "Which reservations are we
expecting to arrive, what room type and how many rooms do they hold, and is
the guarantee/deposit position clean enough that check-in will not stall?"

Source: `Hotel Reservation` joined to its `Reservation Room` lines, restricted
to reservations arriving on the filter date in a state that actually holds
inventory for that arrival (Confirmed or Guaranteed) — the same states the
availability engine treats as holding (see
`hospitality_pms.services.reservations.HOLDING_STATES`).
"""

import frappe
from frappe import _
from frappe.utils import getdate, nowdate


def execute(filters=None):
	filters = frappe._dict(filters or {})

	columns = get_columns()

	if not filters.get("property"):
		return columns, []

	data = get_data(filters)

	return columns, data


def get_columns():
	return [
		{
			"label": _("Reservation"),
			"fieldname": "reservation",
			"fieldtype": "Link",
			"options": "Hotel Reservation",
			"width": 150,
		},
		{"label": _("Guest"), "fieldname": "guest_name", "fieldtype": "Data", "width": 160},
		{
			"label": _("Room Type"),
			"fieldname": "room_type",
			"fieldtype": "Link",
			"options": "Room Type",
			"width": 120,
		},
		{"label": _("Rooms"), "fieldname": "rooms", "fieldtype": "Int", "width": 70},
		{"label": _("Nights"), "fieldname": "nights", "fieldtype": "Int", "width": 70},
		{"label": _("Status"), "fieldname": "reservation_status", "fieldtype": "Data", "width": 100},
		{"label": _("Guarantee"), "fieldname": "guarantee_type", "fieldtype": "Data", "width": 120},
		{
			"label": _("Deposit Required"),
			"fieldname": "deposit_required",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		},
		{
			"label": _("Deposit Received"),
			"fieldname": "deposit_received",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		},
		{
			"label": _("Total"),
			"fieldname": "total_amount",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		},
	]


def get_data(filters):
	# The property filter is the scoping boundary for this raw SQL: every row
	# returned is restricted to `r.property = %(property)s`, so a user who can
	# only see one property never receives rows from another through this
	# report even though the query bypasses `frappe.get_all` permission joins.
	return frappe.db.sql(
		"""
		select
			r.name as reservation,
			r.guest_name as guest_name,
			rr.room_type as room_type,
			rr.rooms as rooms,
			rr.nights as nights,
			r.reservation_status as reservation_status,
			r.guarantee_type as guarantee_type,
			r.deposit_required as deposit_required,
			r.deposit_received as deposit_received,
			r.total_amount as total_amount,
			r.currency as currency
		from `tabHotel Reservation` r
		inner join `tabReservation Room` rr on rr.parent = r.name
		where
			r.property = %(property)s
			and r.arrival_date = %(date)s
			and r.reservation_status in ('Confirmed', 'Guaranteed')
		order by r.guest_name asc, r.name asc
		""",
		{"property": filters.property, "date": getdate(filters.get("date") or nowdate())},
		as_dict=True,
	)
