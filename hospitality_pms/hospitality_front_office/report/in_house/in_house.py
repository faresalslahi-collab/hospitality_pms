"""In House — who is physically in the hotel as of a given date, and what do they owe.

Answers the standing front-office question: "Who is currently resident, in
which room, on what rate, and what is on their folio right now?" Also used to
reconstruct the in-house position for a date other than today (e.g. checking
who was in house as of last night for a hand-over).

Source: `Hospitality Stay` records in `In House` or `Due Out`, restricted to
stays whose night span covers the as-of date. The span test mirrors the
availability engine's night arithmetic — arrival inclusive, departure
exclusive (`arrival_date <= as_of < departure_date`) — so a guest departing on
the as-of date still shows here (they are in house until they leave) while a
guest arriving on the as-of date but not yet checked in does not (their stay
does not exist until check-in creates it).
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
		{"label": _("Room"), "fieldname": "room", "fieldtype": "Link", "options": "Hotel Room", "width": 100},
		{"label": _("Guest"), "fieldname": "guest_name", "fieldtype": "Data", "width": 160},
		{"label": _("Arrival"), "fieldname": "arrival_date", "fieldtype": "Date", "width": 100},
		{"label": _("Departure"), "fieldname": "departure_date", "fieldtype": "Date", "width": 100},
		{"label": _("Nights"), "fieldname": "nights", "fieldtype": "Int", "width": 70},
		{"label": _("Adults"), "fieldname": "adults", "fieldtype": "Int", "width": 70},
		{"label": _("Children"), "fieldname": "children", "fieldtype": "Int", "width": 70},
		{
			"label": _("Rate"),
			"fieldname": "room_rate",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 100,
		},
		{
			"label": _("Folio"),
			"fieldname": "folio",
			"fieldtype": "Link",
			"options": "Hospitality Guest Folio",
			"width": 150,
		},
		{
			"label": _("Balance"),
			"fieldname": "balance",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		},
	]


def get_data(filters):
	# The property filter is the scoping boundary for this raw SQL: every row
	# is restricted to `s.property = %(property)s`.
	return frappe.db.sql(
		"""
		select
			s.room as room,
			s.guest_name as guest_name,
			s.arrival_date as arrival_date,
			s.departure_date as departure_date,
			s.nights as nights,
			s.adults as adults,
			s.children as children,
			s.room_rate as room_rate,
			s.folio as folio,
			f.balance as balance,
			s.currency as currency
		from `tabHospitality Stay` s
		left join `tabHospitality Guest Folio` f on f.name = s.folio
		where
			s.property = %(property)s
			and s.stay_status in ('In House', 'Due Out')
			and s.arrival_date <= %(as_of)s
			and s.departure_date > %(as_of)s
		order by s.room asc
		""",
		{"property": filters.property, "as_of": getdate(filters.get("date") or nowdate())},
		as_dict=True,
	)
