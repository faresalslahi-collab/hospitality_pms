"""Revenue by Room Type.

Revenue question answered: which room types produce the room-night volume,
and which produce the money?

Reads the same posted Room Charge folio lines Night Audit posts
(`hospitality_pms.services.night_audit.post_room_charges`), so the building
blocks match the operational record exactly: one Room Charge line per stay
per business date, joined back to its room type through the stay.

    ADR = room revenue / room nights

Room nights here plays the part Night Audit's "occupied rooms" plays for a
single business date: one Room Charge line is one room, one night. Summed
across the window and grouped by room type, that count is the room type's
room nights.

"Share of Revenue %" is each room type's room revenue as a percentage of the
window's total room revenue across all room types.

Every division below is guarded: a room type with no room nights in the
window reports an ADR of 0 rather than raising.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate


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
	# `f.property = %(property)s` is applied before anything else.
	rows = frappe.db.sql(
		"""
		select coalesce(s.room_type, '') as room_type,
		       count(*) as room_nights,
		       coalesce(sum(c.total_amount), 0) as room_revenue
		from `tabFolio Charge` c
		inner join `tabGuest Folio` f on f.name = c.parent
		left join `tabStay` s on s.name = f.stay
		where f.property = %(property)s
		  and c.charge_type = 'Room Charge'
		  and c.is_reversed = 0
		  and c.business_date between %(from_date)s and %(to_date)s
		group by s.room_type
		order by room_revenue desc
		""",
		{"property": property_name, "from_date": from_date, "to_date": to_date},
		as_dict=True,
	)

	if not rows:
		return []

	total_room_revenue = sum(flt(row.room_revenue) for row in rows)
	total_room_nights = sum(int(row.room_nights) for row in rows)

	data = []
	for row in rows:
		room_nights = int(row.room_nights)
		room_revenue = flt(row.room_revenue)

		data.append(
			{
				"room_type": row.room_type or _("Unspecified"),
				"room_nights": room_nights,
				"room_revenue": flt(room_revenue, 2),
				"adr": _safe_div(room_revenue, room_nights),
				"revenue_share": _safe_pct(room_revenue, total_room_revenue),
			}
		)

	data.append(
		{
			"room_type": _("Total"),
			"room_nights": total_room_nights,
			"room_revenue": flt(total_room_revenue, 2),
			"adr": _safe_div(total_room_revenue, total_room_nights),
			"revenue_share": _safe_pct(total_room_revenue, total_room_revenue),
		}
	)

	return data


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
		{
			"fieldname": "room_type",
			"label": _("Room Type"),
			"fieldtype": "Data",
			"width": 160,
		},
		{"fieldname": "room_nights", "label": _("Room Nights"), "fieldtype": "Int", "width": 110},
		{"fieldname": "room_revenue", "label": _("Room Revenue"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "adr", "label": _("ADR"), "fieldtype": "Currency", "width": 100},
		{
			"fieldname": "revenue_share",
			"label": _("Share of Revenue %"),
			"fieldtype": "Percent",
			"width": 140,
		},
	]
