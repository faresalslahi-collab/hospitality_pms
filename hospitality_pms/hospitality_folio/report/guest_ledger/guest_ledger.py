"""Guest Ledger.

Financial question answered: for each folio, in date order, what was charged
and what was collected, and what did the guest owe after each line -- the
auditor's reconstruction of a stay from its individual postings rather than
from the folio's rolled-up totals.

The running balance is rebuilt line by line the same way
`services.folio._recalculate` rebuilds the folio's own totals: every charge
line counts in full, including a reversed original, because its compensating
negative "Reversal of ..." line is also a row in this report and the two net
to zero together (HPMS-DEC per `folio.py`, "corrections are reversals"). A
reversed original charge with no compensating line visible in the selected
date range is exactly the kind of gap this report exists to surface. Payment
lines follow the same rule the folio total uses: a payment flagged reversed is
left out of the running balance, though the row itself is still listed so the
audit trail is not silently dropped. A non-zero balance on the last row for a
folio should match that folio's own `balance` field for the same cut-off date;
if it does not, the folio's stored totals and its own line items have drifted
apart and `hospitality_pms.services.folio.recalculate` is the repair path, not
this report.

Raw SQL joins the charge and payment child tables against the parent folio
purely to read rows; `f.property = %(property)s` is the mandatory scoping
boundary applied in both queries before any other condition.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate

FOLIO_DOCTYPE = "Hospitality Guest Folio"


def execute(filters=None):
	filters = frappe._dict(filters or {})

	if not filters.get("property"):
		frappe.throw(_("Property is mandatory."))

	columns = get_columns()
	folios = get_folios(filters)

	if not folios:
		return columns, []

	folio_names = [f.name for f in folios]
	folio_meta = {f.name: f for f in folios}

	entries = get_entries(filters, folio_names)

	data = build_ledger(folios, folio_meta, entries)

	return columns, data


def get_folios(filters):
	conditions = {"property": filters.property}

	if filters.get("folio_status"):
		conditions["folio_status"] = filters.folio_status

	return frappe.get_all(
		FOLIO_DOCTYPE,
		filters=conditions,
		fields=["name", "guest", "guest_name"],
		order_by="opened_on asc",
	)


def get_entries(filters, folio_names):
	"""Every charge and payment line for the folios in scope, tagged by kind.

	Two parameterised queries rather than a UNION with mismatched column
	types, combined in Python once both are back. `f.property = %(property)s`
	is the scoping boundary in each; the date range and folio list only
	narrow further.
	"""
	params = {
		"property": filters.property,
		"from_date": getdate(filters.from_date) if filters.get("from_date") else None,
		"to_date": getdate(filters.to_date) if filters.get("to_date") else None,
	}

	if not folio_names:
		return []

	charge_rows = frappe.db.sql(
		"""
		select
			f.name as folio,
			c.charge_date as entry_date,
			c.business_date as business_date,
			c.charge_type as entry_type,
			c.description as description,
			c.total_amount as charge_amount,
			0 as payment_amount,
			c.is_reversed as is_reversed,
			c.idx as idx
		from `tabHospitality Folio Charge` c
		inner join `tabHospitality Guest Folio` f on f.name = c.parent
		where f.property = %(property)s
		  and f.name in %(folios)s
		  and (%(from_date)s is null or c.charge_date >= %(from_date)s)
		  and (%(to_date)s is null or c.charge_date <= %(to_date)s)
		""",
		{**params, "folios": tuple(folio_names)},
		as_dict=True,
	)

	payment_rows = frappe.db.sql(
		"""
		select
			f.name as folio,
			p.payment_date as entry_date,
			p.business_date as business_date,
			p.payment_type as entry_type,
			concat(p.payment_type, ' - ', p.payment_method) as description,
			0 as charge_amount,
			p.amount as payment_amount,
			p.is_reversed as is_reversed,
			p.idx as idx
		from `tabHospitality Folio Payment` p
		inner join `tabHospitality Guest Folio` f on f.name = p.parent
		where f.property = %(property)s
		  and f.name in %(folios)s
		  and (%(from_date)s is null or p.payment_date >= %(from_date)s)
		  and (%(to_date)s is null or p.payment_date <= %(to_date)s)
		""",
		{**params, "folios": tuple(folio_names)},
		as_dict=True,
	)

	for row in charge_rows:
		row["kind_order"] = 0
	for row in payment_rows:
		row["kind_order"] = 1

	return list(charge_rows) + list(payment_rows)


def build_ledger(folios, folio_meta, entries):
	by_folio = {}
	for row in entries:
		by_folio.setdefault(row.folio, []).append(row)

	data = []
	for folio in folios:
		rows = by_folio.get(folio.name, [])
		rows.sort(key=lambda r: (r.entry_date, r.kind_order, r.idx))

		running_balance = 0.0
		for row in rows:
			charge_amount = flt(row.charge_amount)
			raw_payment_amount = flt(row.payment_amount)

			# A reversed payment is excluded from the running balance, the same
			# way services.folio._recalculate excludes it from total_payments.
			# A reversed charge is never excluded: its compensating negative
			# line is a separate row here and the two net to zero together.
			payment_amount = 0.0 if row.is_reversed else raw_payment_amount

			running_balance = flt(running_balance + charge_amount - payment_amount, 2)

			data.append(
				{
					"folio": folio.name,
					"guest": folio.guest,
					"guest_name": folio.guest_name,
					"date": row.entry_date,
					"business_date": row.business_date,
					"entry_type": row.entry_type,
					"description": row.description,
					"charge": flt(charge_amount, 2) or None,
					"payment": flt(raw_payment_amount, 2) or None,
					"running_balance": running_balance,
					"reversed": _("Yes") if row.is_reversed else _("No"),
				}
			)

	return data


def get_columns():
	return [
		{
			"fieldname": "folio",
			"label": _("Folio"),
			"fieldtype": "Link",
			"options": "Hospitality Guest Folio",
			"width": 140,
		},
		{
			"fieldname": "guest",
			"label": _("Guest"),
			"fieldtype": "Link",
			"options": "Hospitality Guest",
			"width": 140,
		},
		{
			"fieldname": "date",
			"label": _("Date"),
			"fieldtype": "Date",
			"width": 100,
		},
		{
			"fieldname": "business_date",
			"label": _("Business Date"),
			"fieldtype": "Date",
			"width": 110,
		},
		{
			"fieldname": "entry_type",
			"label": _("Type"),
			"fieldtype": "Data",
			"width": 120,
		},
		{
			"fieldname": "description",
			"label": _("Description"),
			"fieldtype": "Data",
			"width": 220,
		},
		{
			"fieldname": "charge",
			"label": _("Charge"),
			"fieldtype": "Currency",
			"width": 110,
		},
		{
			"fieldname": "payment",
			"label": _("Payment"),
			"fieldtype": "Currency",
			"width": 110,
		},
		{
			"fieldname": "running_balance",
			"label": _("Running Balance"),
			"fieldtype": "Currency",
			"width": 130,
		},
		{
			"fieldname": "reversed",
			"label": _("Reversed"),
			"fieldtype": "Data",
			"width": 90,
		},
	]
