"""Payment Reconciliation.

Financial question answered: for every payment, deposit, refund or credit
recorded on a folio in a period, has it actually reached ERPNext as a
Payment Entry, and against which provider reference (if any) can it be traced
back to the gateway that took it?

Every row is a `Hospitality Folio Payment` line, exactly as
`services.posting.post_folio_payment` posts it -- per line, not in aggregate,
so a deposit, a settlement and a refund each reconcile against their own
ledger entry. A line with "Posted to ERP" = No is money the property has
already recorded as received (or refunded) that has not yet reached the
general ledger; it is not necessarily wrong, but it is not yet in the system
of record and should be posted or investigated before the books are closed
for the period.

Raw SQL is used here because the report joins the folio (for the mandatory
property scope) against its child payment table, which the report builder's
simple filter dict cannot express. The `property` filter is the scoping
boundary for the whole query: every other condition is optional, but the
property clause is always applied.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate


def execute(filters=None):
	filters = frappe._dict(filters or {})

	if not filters.get("property"):
		frappe.throw(_("Property is mandatory."))

	columns = get_columns()
	data = get_data(filters)

	return columns, data


def get_data(filters):
	params = {
		"property": filters.property,
		"from_date": getdate(filters.from_date) if filters.get("from_date") else None,
		"to_date": getdate(filters.to_date) if filters.get("to_date") else None,
	}

	# Parameterised SQL: every value is bound through `params`, never
	# string-formatted into the query. `f.property = %(property)s` is the
	# mandatory scoping boundary -- every folio payment returned belongs to a
	# folio at this property, nothing else narrows that.
	rows = frappe.db.sql(
		"""
		select
			f.name as folio,
			p.payment_date as payment_date,
			p.business_date as business_date,
			p.payment_type as payment_type,
			p.payment_method as payment_method,
			p.amount as amount,
			p.payer as payer,
			p.is_posted_to_erp as is_posted_to_erp,
			p.payment_entry as payment_entry,
			p.provider_reference as provider_reference
		from `tabHospitality Folio Payment` p
		inner join `tabHospitality Guest Folio` f on f.name = p.parent
		where f.property = %(property)s
		  and (%(from_date)s is null or p.payment_date >= %(from_date)s)
		  and (%(to_date)s is null or p.payment_date <= %(to_date)s)
		order by p.payment_date asc, f.name asc
		""",
		params,
		as_dict=True,
	)

	data = []
	for row in rows:
		data.append(
			{
				"folio": row.folio,
				"payment_date": row.payment_date,
				"business_date": row.business_date,
				"payment_type": row.payment_type,
				"payment_method": row.payment_method,
				"amount": flt(row.amount, 2),
				"payer": row.payer,
				"posted_to_erp": _("Yes") if row.is_posted_to_erp else _("No"),
				"payment_entry": row.payment_entry,
				"provider_reference": row.provider_reference,
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
			"fieldname": "payment_date",
			"label": _("Payment Date"),
			"fieldtype": "Date",
			"width": 110,
		},
		{
			"fieldname": "business_date",
			"label": _("Business Date"),
			"fieldtype": "Date",
			"width": 110,
		},
		{
			"fieldname": "payment_type",
			"label": _("Type"),
			"fieldtype": "Data",
			"width": 100,
		},
		{
			"fieldname": "payment_method",
			"label": _("Method"),
			"fieldtype": "Data",
			"width": 110,
		},
		{
			"fieldname": "amount",
			"label": _("Amount"),
			"fieldtype": "Currency",
			"width": 110,
		},
		{
			"fieldname": "payer",
			"label": _("Payer"),
			"fieldtype": "Data",
			"width": 100,
		},
		{
			"fieldname": "posted_to_erp",
			"label": _("Posted to ERP"),
			"fieldtype": "Data",
			"width": 100,
		},
		{
			"fieldname": "payment_entry",
			"label": _("Payment Entry"),
			"fieldtype": "Link",
			"options": "Payment Entry",
			"width": 140,
		},
		{
			"fieldname": "provider_reference",
			"label": _("Provider Reference"),
			"fieldtype": "Data",
			"width": 160,
		},
	]
