"""Failed Postings.

Financial question answered: which attempts to post a folio charge or payment
into ERPNext are currently stuck, and which of those deserve attention first?

Every row here is a `Hospitality Financial Posting Log` entry (HPMS-DEC-031).
A non-zero result is not itself a discrepancy in the accounts -- ERPNext was
never told about this money at all, so nothing is out of balance yet -- but it
is revenue or a receipt sitting outside the ledger until the posting is
retried successfully. The more attempts and the older the last attempt, the
more likely the underlying cause (a missing posting profile mapping, a closed
accounting period, a bad account on the folio's property) needs a person to
fix it rather than another automatic retry, which is why the sort surfaces the
worst offenders first.
"""

import frappe
from frappe import _

POSTING_LOG = "Hospitality Financial Posting Log"

DEFAULT_STATUS = "Failed"


def execute(filters=None):
	filters = frappe._dict(filters or {})

	if not filters.get("property"):
		frappe.throw(_("Property is mandatory."))

	columns = get_columns()
	data = get_data(filters)

	return columns, data


def get_data(filters):
	conditions = {
		"property": filters.property,
		"posting_status": filters.get("status") or DEFAULT_STATUS,
	}

	if filters.get("posting_type"):
		conditions["posting_type"] = filters.posting_type

	rows = frappe.get_all(
		POSTING_LOG,
		filters=conditions,
		fields=[
			"name as posting_log",
			"posting_type",
			"folio",
			"amount",
			"attempts",
			"last_attempt_on",
			"business_date",
			"error_message",
		],
		# Worst first: the most-retried postings, then the ones that have been
		# stuck longest.
		order_by="attempts desc, last_attempt_on asc",
	)

	return rows


def get_columns():
	return [
		{
			"fieldname": "posting_log",
			"label": _("Posting Log"),
			"fieldtype": "Link",
			"options": "Hospitality Financial Posting Log",
			"width": 150,
		},
		{
			"fieldname": "posting_type",
			"label": _("Posting Type"),
			"fieldtype": "Data",
			"width": 120,
		},
		{
			"fieldname": "folio",
			"label": _("Folio"),
			"fieldtype": "Link",
			"options": "Hospitality Guest Folio",
			"width": 140,
		},
		{
			"fieldname": "amount",
			"label": _("Amount"),
			"fieldtype": "Currency",
			"width": 110,
		},
		{
			"fieldname": "attempts",
			"label": _("Attempts"),
			"fieldtype": "Int",
			"width": 90,
		},
		{
			"fieldname": "last_attempt_on",
			"label": _("Last Attempt"),
			"fieldtype": "Datetime",
			"width": 160,
		},
		{
			"fieldname": "business_date",
			"label": _("Business Date"),
			"fieldtype": "Date",
			"width": 110,
		},
		{
			"fieldname": "error_message",
			"label": _("Error Message"),
			"fieldtype": "Data",
			"width": 320,
		},
	]
