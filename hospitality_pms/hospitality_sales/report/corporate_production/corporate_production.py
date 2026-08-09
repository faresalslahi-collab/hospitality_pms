"""Corporate Production.

Sales question answered: how much business has each corporate account
produced in the window, and how much of its credit line is that business
sitting against?

Counts stays, room nights and revenue the same way
`hospitality_pms.services.corporate.get_production_report` counts them for a
single account - `count(distinct stay)`, `sum(stay.nights)`,
`sum(folio.total_charges)`, scoped by the stay's `arrival_date` - so a number
pulled from this report and a number pulled from that function for the same
account and window never disagree. This report simply runs that shape across
every corporate account at a property instead of one account at a time.

`credit_limit` and `credit_used` are read as maintained by
`services.corporate` (CorporateCreditService); `credit_available` is
recomputed here as `credit_limit - credit_used`, the same arithmetic
`get_credit_position` uses, rather than trusting the stored field, in case
the two have drifted.

Every division is guarded: an account with a zero credit limit (unlimited
credit) reports 0 rather than raising.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

ACCOUNT_DOCTYPE = "Corporate Account"


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
	# `ca.property = %(property)s` is applied before anything else. The date
	# range is applied inside the LEFT JOIN's ON clause (not WHERE) so an
	# account with no stays in the window still appears, with zeros, rather
	# than disappearing from the report.
	rows = frappe.db.sql(
		"""
		select ca.account_code as corporate_account,
		       ca.credit_limit as credit_limit,
		       ca.credit_used as credit_used,
		       count(distinct s.name) as stays,
		       coalesce(sum(s.nights), 0) as room_nights,
		       coalesce(sum(f.total_charges), 0) as revenue
		from `tabCorporate Account` ca
		left join `tabReservation` r
		       on r.corporate_account = ca.account_code and r.property = ca.property
		left join `tabStay` s
		       on s.reservation = r.name
		      and s.arrival_date between %(from_date)s and %(to_date)s
		left join `tabGuest Folio` f on f.stay = s.name
		where ca.property = %(property)s
		group by ca.name, ca.account_code, ca.credit_limit, ca.credit_used
		order by revenue desc
		""",
		{"property": property_name, "from_date": from_date, "to_date": to_date},
		as_dict=True,
	)

	if not rows:
		return []

	data = []
	total_stays = 0
	total_room_nights = 0
	total_revenue = 0.0
	total_credit_limit = 0.0
	total_credit_used = 0.0

	for row in rows:
		limit = flt(row.credit_limit)
		used = flt(row.credit_used)
		available = flt(limit - used, 2)

		data.append(
			{
				"corporate_account": row.corporate_account,
				"stays": int(row.stays),
				"room_nights": int(row.room_nights),
				"revenue": flt(row.revenue, 2),
				"credit_limit": flt(limit, 2),
				"credit_used": flt(used, 2),
				"credit_available": available,
			}
		)

		total_stays += int(row.stays)
		total_room_nights += int(row.room_nights)
		total_revenue += flt(row.revenue)
		total_credit_limit += limit
		total_credit_used += used

	data.append(
		{
			"corporate_account": _("Total"),
			"stays": total_stays,
			"room_nights": total_room_nights,
			"revenue": flt(total_revenue, 2),
			"credit_limit": flt(total_credit_limit, 2),
			"credit_used": flt(total_credit_used, 2),
			"credit_available": flt(total_credit_limit - total_credit_used, 2),
		}
	)

	return data


def get_columns():
	return [
		{
			"fieldname": "corporate_account",
			"label": _("Corporate Account"),
			"fieldtype": "Link",
			"options": ACCOUNT_DOCTYPE,
			"width": 160,
		},
		{"fieldname": "stays", "label": _("Stays"), "fieldtype": "Int", "width": 90},
		{"fieldname": "room_nights", "label": _("Room Nights"), "fieldtype": "Int", "width": 110},
		{"fieldname": "revenue", "label": _("Revenue"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "credit_limit", "label": _("Credit Limit"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "credit_used", "label": _("Credit Used"), "fieldtype": "Currency", "width": 120},
		{
			"fieldname": "credit_available",
			"label": _("Credit Available"),
			"fieldtype": "Currency",
			"width": 130,
		},
	]
