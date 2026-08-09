"""Kitchen Consumption and Wastage — what left the kitchen as revenue, and what left it as a write-off.

Answers the kitchen manager's/F&B manager's cost conversation: "Over this
period, what did we waste and why, and how does that compare with what we
actually sold through room service and minibar?"

This report never recomputes the aggregation itself. Both sections are built
from `hospitality_pms.services.kitchen.get_consumption_report`, the same
function the operations API uses, so this report and that endpoint can never
disagree about the numbers:

* **Wastage by item** — `Wastage Entry` rows for the property,
  grouped by `item`, summed to quantity and estimated value, exactly as
  `get_consumption_report` aggregates them. This report adds one thing the
  service does not: a reason breakdown per item (how much of that item's
  wastage was Spoilage versus Expiry versus a Preparation Error, and so on),
  built from its own grouped query over the same rows.
* **Room service revenue by order type** — `Room Service Order`
  rows with `order_status = 'Delivered'`, grouped by `order_type`, exactly as
  `get_consumption_report` aggregates them.

The two sections share one flat table (a report with two independent
schemas cannot be one script report table otherwise): a `Section` column
marks each row "Wastage" or "Revenue", and the columns that do not apply to
a section are left blank on that row.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate

from hospitality_pms.services.kitchen import get_consumption_report


def execute(filters=None):
	filters = frappe._dict(filters or {})

	columns = get_columns()

	if not filters.get("property"):
		return columns, [], None, None

	data = get_data(filters)
	message = get_summary_message(data)

	return columns, data, message, None


def get_columns():
	return [
		{"label": _("Section"), "fieldname": "section", "fieldtype": "Data", "width": 90},
		{"label": _("Item"), "fieldname": "item", "fieldtype": "Link", "options": "Item", "width": 160},
		{"label": _("Quantity"), "fieldname": "quantity", "fieldtype": "Float", "precision": 2, "width": 90},
		{"label": _("Value"), "fieldname": "value", "fieldtype": "Currency", "width": 110},
		{"label": _("Reason Breakdown"), "fieldname": "reason_breakdown", "fieldtype": "Data", "width": 260},
		{"label": _("Order Type"), "fieldname": "order_type", "fieldtype": "Data", "width": 110},
		{"label": _("Orders"), "fieldname": "orders", "fieldtype": "Int", "width": 80},
		{"label": _("Revenue"), "fieldname": "revenue", "fieldtype": "Currency", "width": 110},
	]


def get_data(filters):
	from_date = getdate(filters.get("from_date") or getdate())
	to_date = getdate(filters.get("to_date") or getdate())

	# `get_consumption_report` already scopes both of its queries to
	# `property = %(property)s`; that is the same scoping boundary this
	# report's own reason-breakdown query below uses.
	report = get_consumption_report(filters.property, from_date, to_date)

	reason_breakdown = _get_reason_breakdown(filters.property, from_date, to_date)

	data = []

	for row in report["wastage"]:
		data.append(
			{
				"section": _("Wastage"),
				"item": row.get("item"),
				"quantity": flt(row.get("quantity"), 2),
				"value": flt(row.get("value"), 2),
				"reason_breakdown": reason_breakdown.get(row.get("item"), ""),
				"order_type": None,
				"orders": None,
				"revenue": None,
			}
		)

	for row in report["revenue"]:
		data.append(
			{
				"section": _("Revenue"),
				"item": None,
				"quantity": None,
				"value": None,
				"reason_breakdown": "",
				"order_type": row.get("order_type"),
				"orders": row.get("orders"),
				"revenue": flt(row.get("revenue"), 2),
			}
		)

	return data


def _get_reason_breakdown(property_name, from_date, to_date) -> dict:
	"""Build a "Spoilage: 3.0, Expiry: 1.0"-style summary per item, for the
	same rows `get_consumption_report` sums for its wastage-by-item section.

	The property filter is the scoping boundary for this raw SQL: every row
	is restricted to `property = %(property)s`.
	"""
	rows = frappe.db.sql(
		"""
		select item, reason, sum(quantity) as quantity
		from `tabWastage Entry`
		where property = %(property)s and wastage_date between %(from_date)s and %(to_date)s
		group by item, reason
		order by item asc, quantity desc
		""",
		{"property": property_name, "from_date": from_date, "to_date": to_date},
		as_dict=True,
	)

	breakdown = {}
	for row in rows:
		parts = breakdown.setdefault(row.item, [])
		parts.append(f"{_(row.reason)}: {flt(row.quantity, 2)}")

	return {item: ", ".join(parts) for item, parts in breakdown.items()}


def get_summary_message(data):
	"""Total wastage value versus total delivered revenue, for the period."""
	if not data:
		return None

	total_wastage_value = sum(flt(row["value"]) for row in data if row["value"] is not None)
	total_revenue = sum(flt(row["revenue"]) for row in data if row["revenue"] is not None)

	return (
		"<table class='table table-bordered' style='margin-bottom:0'>"
		f"<tbody><tr><th>{_('Total Wastage Value')}</th>"
		f"<td style='text-align:right'>{flt(total_wastage_value, 2)}</td>"
		f"<th>{_('Total Room Service / Minibar Revenue')}</th>"
		f"<td style='text-align:right'>{flt(total_revenue, 2)}</td></tr></tbody></table>"
	)
