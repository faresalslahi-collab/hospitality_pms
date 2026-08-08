"""Regulatory Submissions — every generated compliance export, and where it stands with the authority.

Answers the compliance question a night auditor or finance manager checks
routinely: "What have we generated for the regulator this period, has it
actually been submitted, and did anything fail?" One row per
`Hospitality Regulatory Export` whose reporting period overlaps the filter
range (SAS section 5 / `services/regulatory.py`).

A report_summary card above the table counts `Hospitality Guest Registration`
rows still in `Pending` status for the property, regardless of the date
filter: that count is the number a compliance officer actually has to chase
today, not a historical figure scoped to whatever period this report happens
to be showing.
"""

import frappe
from frappe import _


def execute(filters=None):
	filters = frappe._dict(filters or {})

	columns = get_columns()

	if not filters.get("property"):
		return columns, [], None, None, []

	data = get_data(filters)
	report_summary = get_report_summary(filters)

	return columns, data, None, None, report_summary


def get_columns():
	return [
		{
			"label": _("Export"),
			"fieldname": "export",
			"fieldtype": "Link",
			"options": "Hospitality Regulatory Export",
			"width": 140,
		},
		{"label": _("Type"), "fieldname": "export_type", "fieldtype": "Data", "width": 130},
		{"label": _("Status"), "fieldname": "export_status", "fieldtype": "Data", "width": 100},
		{"label": _("Period From"), "fieldname": "from_date", "fieldtype": "Date", "width": 100},
		{"label": _("Period To"), "fieldname": "to_date", "fieldtype": "Date", "width": 100},
		{"label": _("Record Count"), "fieldname": "record_count", "fieldtype": "Int", "width": 100},
		{"label": _("Generated On"), "fieldname": "generated_on", "fieldtype": "Datetime", "width": 150},
		{"label": _("Submitted On"), "fieldname": "submitted_on", "fieldtype": "Datetime", "width": 150},
		{
			"label": _("Acknowledgement Reference"),
			"fieldname": "acknowledgement_reference",
			"fieldtype": "Data",
			"width": 170,
		},
		{"label": _("Error"), "fieldname": "error", "fieldtype": "Data", "width": 200},
	]


def get_data(filters):
	# The property filter is the scoping boundary for this raw SQL: every
	# export returned is restricted to `property = %(property)s`.
	params = {"property": filters.property}

	period_clause = ""
	from_date = filters.get("from_date")
	to_date = filters.get("to_date")

	if from_date and to_date:
		# Overlap test: the export's own reporting period touches the
		# filter's period at all, rather than requiring it to sit fully inside.
		period_clause = " and e.from_date <= %(to_date)s and e.to_date >= %(from_date)s"
		params["from_date"] = from_date
		params["to_date"] = to_date
	elif from_date:
		period_clause = " and e.to_date >= %(from_date)s"
		params["from_date"] = from_date
	elif to_date:
		period_clause = " and e.from_date <= %(to_date)s"
		params["to_date"] = to_date

	export_type_clause = ""
	if filters.get("export_type"):
		export_type_clause = " and e.export_type = %(export_type)s"
		params["export_type"] = filters.export_type

	return frappe.db.sql(
		f"""
		select
			e.name as export,
			e.export_type as export_type,
			e.export_status as export_status,
			e.from_date as from_date,
			e.to_date as to_date,
			e.record_count as record_count,
			e.generated_on as generated_on,
			e.submitted_on as submitted_on,
			e.acknowledgement_reference as acknowledgement_reference,
			e.error_message as error
		from `tabHospitality Regulatory Export` e
		where e.property = %(property)s
			{period_clause}
			{export_type_clause}
		order by e.from_date desc, e.name asc
		""",
		params,
		as_dict=True,
	)


def get_report_summary(filters):
	pending_count = frappe.db.count(
		"Hospitality Guest Registration",
		filters={"property": filters.property, "registration_status": "Pending"},
	)

	return [
		{
			"value": pending_count,
			"indicator": "Red" if pending_count else "Green",
			"label": _("Guest Registrations Still Pending"),
			"datatype": "Int",
		}
	]
