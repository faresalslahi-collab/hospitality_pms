"""Departures — who is due to check out today (or on a chosen date), and what do they still owe.

Answers the front desk's question for the departure shift: "Which stays leave
today, which room are they in, and is their folio settled or does it still
carry a balance that needs collecting before they walk out?"

Source: `Hospitality Stay`, not the reservation — a stay is the physical
occupancy record, and its `folio` link carries the balance that actually
matters at checkout. Closed stays (already audited and archived) are excluded;
everything still open on the departure date is shown, including a stay that
has already been checked out today, so front desk can see who left without
paying a balance.
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
			"label": _("Stay"),
			"fieldname": "stay",
			"fieldtype": "Link",
			"options": "Hospitality Stay",
			"width": 150,
		},
		{"label": _("Guest"), "fieldname": "guest_name", "fieldtype": "Data", "width": 160},
		{"label": _("Room"), "fieldname": "room", "fieldtype": "Link", "options": "Hotel Room", "width": 100},
		{"label": _("Arrival"), "fieldname": "arrival_date", "fieldtype": "Date", "width": 100},
		{"label": _("Departure"), "fieldname": "departure_date", "fieldtype": "Date", "width": 100},
		{"label": _("Nights"), "fieldname": "nights", "fieldtype": "Int", "width": 70},
		{
			"label": _("Folio"),
			"fieldname": "folio",
			"fieldtype": "Link",
			"options": "Hospitality Guest Folio",
			"width": 150,
		},
		{
			"label": _("Folio Balance"),
			"fieldname": "balance",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		},
		{"label": _("Stay Status"), "fieldname": "stay_status", "fieldtype": "Data", "width": 100},
	]


def get_data(filters):
	# The property filter is the scoping boundary for this raw SQL: every row
	# is restricted to `s.property = %(property)s`.
	return frappe.db.sql(
		"""
		select
			s.name as stay,
			s.guest_name as guest_name,
			s.room as room,
			s.arrival_date as arrival_date,
			s.departure_date as departure_date,
			s.nights as nights,
			s.folio as folio,
			f.balance as balance,
			f.currency as currency,
			s.stay_status as stay_status
		from `tabHospitality Stay` s
		left join `tabHospitality Guest Folio` f on f.name = s.folio
		where
			s.property = %(property)s
			and s.departure_date = %(date)s
			and s.stay_status != 'Closed'
		order by s.room asc
		""",
		{"property": filters.property, "date": getdate(filters.get("date") or nowdate())},
		as_dict=True,
	)
