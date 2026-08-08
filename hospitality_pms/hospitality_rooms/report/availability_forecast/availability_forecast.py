"""Availability Forecast — sellable inventory per night, per room type, over a date range.

Answers the revenue/reservations question: "Over the next few weeks, which
room types are tightening up, and on which nights?" One row per night per room
type, breaking physical inventory down into sellable, blocked, sold and
available.

The arithmetic is never reimplemented here: every figure comes straight from
`hospitality_pms.services.availability.get_availability`, the same function
the booking screen and room-type confirmation path call. Duplicating that
arithmetic in a report would risk the report and the booking screen quietly
disagreeing about how many rooms are left.
"""

import frappe
from frappe import _
from frappe.utils import add_days, getdate, nowdate

from hospitality_pms.services.availability import get_availability


def execute(filters=None):
	filters = frappe._dict(filters or {})

	columns = get_columns()

	if not filters.get("property"):
		return columns, []

	data = get_data(filters)

	return columns, data


def get_columns():
	return [
		{"label": _("Date"), "fieldname": "date", "fieldtype": "Date", "width": 100},
		{
			"label": _("Room Type"),
			"fieldname": "room_type",
			"fieldtype": "Link",
			"options": "Room Type",
			"width": 120,
		},
		{"label": _("Physical"), "fieldname": "physical", "fieldtype": "Int", "width": 90},
		{"label": _("Sellable"), "fieldname": "sellable", "fieldtype": "Int", "width": 90},
		{"label": _("Blocked"), "fieldname": "blocked", "fieldtype": "Int", "width": 90},
		{"label": _("Sold"), "fieldname": "sold", "fieldtype": "Int", "width": 90},
		{"label": _("Available"), "fieldname": "available", "fieldtype": "Int", "width": 90},
	]


def get_data(filters):
	# `get_availability` applies its own read of Hotel Room / Room Type / block
	# / reservation data for this property only; the property filter below is
	# the scoping boundary the caller must always supply.
	from_date = getdate(filters.get("from_date") or nowdate())
	to_date = getdate(filters.get("to_date") or add_days(nowdate(), 30))

	if to_date <= from_date:
		frappe.throw(_("To Date must be after From Date."))

	# `get_availability`'s departure is exclusive of the last night, so the
	# range is queried one day past `to_date` to include `to_date` itself as a
	# forecast night.
	availability = get_availability(
		filters.property,
		from_date,
		add_days(to_date, 1),
		room_type=filters.get("room_type") or None,
	)

	data = []

	for room_type, bucket in availability["room_types"].items():
		for night in availability["nights"]:
			figures = bucket["by_night"][night]
			data.append(
				{
					"date": night,
					"room_type": room_type,
					"physical": bucket["physical"],
					"sellable": figures["sellable"],
					"blocked": figures["blocked"],
					"sold": figures["sold"],
					"available": figures["available"],
				}
			)

	data.sort(key=lambda row: (row["date"], row["room_type"]))

	return data
