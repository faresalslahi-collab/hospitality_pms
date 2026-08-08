"""Occupancy and Revenue.

Operational question answered: for each business date in the window, how full
were we and what did that fullness earn?

Uses the same definitions `hospitality_pms.services.night_audit._refresh_figures`
uses to close a business date, so this report and the Night Audit never
disagree about the same date:

    Occupancy % = occupied rooms / sellable rooms * 100
    ADR         = room revenue / occupied rooms
    RevPAR      = room revenue / sellable rooms

"Occupied rooms" and "room revenue" for a business date are counted from
posted Room Charge folio lines for that date (`charge_type = "Room Charge"`,
`is_reversed = 0`) rather than from stay date ranges. Night Audit's
`post_room_charges` posts exactly one such line per stay per business date
(idempotency key `room-charge:{stay}:{business_date}`), so counting those
lines *is* counting occupied rooms for that date, and summing their amount
*is* the room revenue Night Audit itself accumulates into `room_revenue`.

"Total revenue" additionally sums every other charge type posted on the same
business date (F&B, tax, service charge, adjustments, etc.) for a fuller
picture of the day; it is not used for ADR or RevPAR, which stay anchored to
room revenue only, exactly as Night Audit defines them.

Every division below is guarded: a day with no sellable rooms, or no occupied
rooms, reports 0 rather than raising.
"""

import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate, nowdate

FOLIO_DOCTYPE = "Hospitality Guest Folio"
CHARGE_DOCTYPE = "Hospitality Folio Charge"
ROOM_DOCTYPE = "Hotel Room"


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
	# Property is mandatory and is the scoping boundary for both raw SQL
	# queries below: every row is filtered to `f.property = %(property)s`
	# before anything else.
	sellable_rooms = frappe.db.count(ROOM_DOCTYPE, {"property": property_name, "is_active": 1})

	room_charge_by_date = _get_room_charge_figures(property_name, from_date, to_date)
	total_revenue_by_date = _get_total_revenue(property_name, from_date, to_date)

	data = []
	total_occupied = 0
	total_room_revenue = 0.0
	total_revenue_sum = 0.0
	num_days = 0

	current = from_date
	while current <= to_date:
		figures = room_charge_by_date.get(current)
		occupied_rooms = int(figures["occupied_rooms"]) if figures else 0
		room_revenue = flt(figures["room_revenue"]) if figures else 0.0
		total_revenue = total_revenue_by_date.get(current, 0.0)

		data.append(
			{
				# Deliberately a Data column, not Date: it lets the closing
				# "Total / Average" row carry a label instead of being run
				# through the Date formatter, which would blank out anything
				# that does not parse as a date.
				"business_date": str(current),
				"sellable_rooms": sellable_rooms,
				"occupied_rooms": occupied_rooms,
				"occupancy_percentage": _safe_pct(occupied_rooms, sellable_rooms),
				"room_revenue": flt(room_revenue, 2),
				"total_revenue": flt(total_revenue, 2),
				"adr": _safe_div(room_revenue, occupied_rooms),
				"revpar": _safe_div(room_revenue, sellable_rooms),
			}
		)

		total_occupied += occupied_rooms
		total_room_revenue += room_revenue
		total_revenue_sum += total_revenue
		num_days += 1
		current = add_days(current, 1)

	if data:
		room_nights_available = sellable_rooms * num_days
		data.append(
			{
				"business_date": _("Total / Average"),
				"sellable_rooms": sellable_rooms,
				"occupied_rooms": total_occupied,
				"occupancy_percentage": _safe_pct(total_occupied, room_nights_available),
				"room_revenue": flt(total_room_revenue, 2),
				"total_revenue": flt(total_revenue_sum, 2),
				"adr": _safe_div(total_room_revenue, total_occupied),
				"revpar": _safe_div(total_room_revenue, room_nights_available),
			}
		)

	return data


def _get_room_charge_figures(property_name: str, from_date, to_date) -> dict:
	"""Occupied rooms and room revenue per business date, from posted Room
	Charge folio lines only. `f.property = %(property)s` is the mandatory
	scoping boundary.
	"""
	rows = frappe.db.sql(
		"""
		select c.business_date as business_date,
		       count(*) as occupied_rooms,
		       coalesce(sum(c.total_amount), 0) as room_revenue
		from `tabHospitality Folio Charge` c
		inner join `tabHospitality Guest Folio` f on f.name = c.parent
		where f.property = %(property)s
		  and c.charge_type = 'Room Charge'
		  and c.is_reversed = 0
		  and c.business_date between %(from_date)s and %(to_date)s
		group by c.business_date
		""",
		{"property": property_name, "from_date": from_date, "to_date": to_date},
		as_dict=True,
	)

	return {row.business_date: row for row in rows}


def _get_total_revenue(property_name: str, from_date, to_date) -> dict:
	"""All posted, non-reversed charges per business date, any charge type.
	`f.property = %(property)s` is the mandatory scoping boundary.
	"""
	rows = frappe.db.sql(
		"""
		select c.business_date as business_date,
		       coalesce(sum(c.total_amount), 0) as total_revenue
		from `tabHospitality Folio Charge` c
		inner join `tabHospitality Guest Folio` f on f.name = c.parent
		where f.property = %(property)s
		  and c.is_reversed = 0
		  and c.business_date between %(from_date)s and %(to_date)s
		group by c.business_date
		""",
		{"property": property_name, "from_date": from_date, "to_date": to_date},
		as_dict=True,
	)

	return {row.business_date: flt(row.total_revenue) for row in rows}


def _safe_div(numerator: float, denominator: float) -> float:
	"""Division guarded against a zero (or falsy) denominator. Never raises."""
	if not denominator:
		return 0.0
	return flt(numerator / denominator, 2)


def _safe_pct(numerator: float, denominator: float) -> float:
	if not denominator:
		return 0.0
	return flt(numerator / denominator * 100, 2)


def get_columns():
	return [
		{"fieldname": "business_date", "label": _("Business Date"), "fieldtype": "Data", "width": 130},
		{"fieldname": "sellable_rooms", "label": _("Sellable Rooms"), "fieldtype": "Int", "width": 110},
		{"fieldname": "occupied_rooms", "label": _("Occupied Rooms"), "fieldtype": "Int", "width": 110},
		{
			"fieldname": "occupancy_percentage",
			"label": _("Occupancy %"),
			"fieldtype": "Percent",
			"width": 110,
		},
		{"fieldname": "room_revenue", "label": _("Room Revenue"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "total_revenue", "label": _("Total Revenue"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "adr", "label": _("ADR"), "fieldtype": "Currency", "width": 100},
		{"fieldname": "revpar", "label": _("RevPAR"), "fieldtype": "Currency", "width": 100},
	]
