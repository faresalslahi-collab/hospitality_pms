"""Maintenance Response Times — how long a ticket sits before it is assigned, and before it is fixed.

Answers the maintenance manager's question: "Are we assigning and closing
tickets inside a reasonable time, and is that time getting worse for any one
priority?" One row per ticket reported in the filter period, from
`Hospitality Maintenance Ticket` (SAS 3.12).

How the derived figures are calculated:

* **Hours to assign** = `assigned_on - reported_on`, in hours. Blank when the
  ticket has not been assigned yet, never a negative or fabricated number.
* **Hours to complete** = `completed_on - reported_on`, in hours (the
  technician's "work done" milestone, not the later verification/release
  step — see `MaintenanceService.complete_work`). Blank until the ticket
  reaches that point.
* **Repeat defect** mirrors `is_repeat_defect`, which `MaintenanceService.
  create_ticket` sets when the same room had a Completed ticket in the same
  category within the previous 30 days.

A summary of the average hours to assign and to complete, broken down by
priority, is appended above the table (via the report's `message`) so a
manager can see at a glance whether Urgent tickets really are handled faster
than Low ones.
"""

import frappe
from frappe import _
from frappe.utils import flt, get_datetime


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
		{
			"label": _("Ticket"),
			"fieldname": "ticket",
			"fieldtype": "Link",
			"options": "Hospitality Maintenance Ticket",
			"width": 130,
		},
		# Data, not Link: this may hold either a room code or a free-text area
		# (lobby, plant room), and a Link column would try to resolve the
		# latter as a broken Hotel Room link.
		{"label": _("Room / Area"), "fieldname": "room_or_area", "fieldtype": "Data", "width": 120},
		{"label": _("Category"), "fieldname": "category", "fieldtype": "Data", "width": 110},
		{"label": _("Priority"), "fieldname": "priority", "fieldtype": "Data", "width": 90},
		{"label": _("Reported On"), "fieldname": "reported_on", "fieldtype": "Datetime", "width": 150},
		{"label": _("Assigned On"), "fieldname": "assigned_on", "fieldtype": "Datetime", "width": 150},
		{"label": _("Started On"), "fieldname": "started_on", "fieldtype": "Datetime", "width": 150},
		{"label": _("Completed On"), "fieldname": "completed_on", "fieldtype": "Datetime", "width": 150},
		{
			"label": _("Hours to Assign"),
			"fieldname": "hours_to_assign",
			"fieldtype": "Float",
			"precision": 1,
			"width": 110,
		},
		{
			"label": _("Hours to Complete"),
			"fieldname": "hours_to_complete",
			"fieldtype": "Float",
			"precision": 1,
			"width": 120,
		},
		{"label": _("Repeat Defect"), "fieldname": "repeat_defect", "fieldtype": "Data", "width": 100},
	]


def get_data(filters):
	# The property filter is the scoping boundary here: `frappe.get_all`
	# applies Hospitality Maintenance Ticket's own permission rules on top of
	# this mandatory filter.
	conditions = {"property": filters.property}

	from_date = filters.get("from_date")
	to_date = filters.get("to_date")

	if from_date and to_date:
		conditions["reported_on"] = ["between", [from_date, to_date]]
	elif from_date:
		conditions["reported_on"] = [">=", from_date]
	elif to_date:
		conditions["reported_on"] = ["<=", to_date]

	tickets = frappe.get_all(
		"Hospitality Maintenance Ticket",
		filters=conditions,
		fields=[
			"name",
			"room",
			"area",
			"category",
			"priority",
			"reported_on",
			"assigned_on",
			"started_on",
			"completed_on",
			"is_repeat_defect",
		],
		order_by="reported_on asc",
		limit_page_length=0,
	)

	data = []

	for ticket in tickets:
		hours_to_assign = _hours_between(ticket.reported_on, ticket.assigned_on)
		hours_to_complete = _hours_between(ticket.reported_on, ticket.completed_on)

		data.append(
			{
				"ticket": ticket.name,
				"room_or_area": ticket.room or ticket.area,
				"category": ticket.category,
				"priority": ticket.priority,
				"reported_on": ticket.reported_on,
				"assigned_on": ticket.assigned_on,
				"started_on": ticket.started_on,
				"completed_on": ticket.completed_on,
				"hours_to_assign": hours_to_assign,
				"hours_to_complete": hours_to_complete,
				"repeat_defect": _("Yes") if ticket.is_repeat_defect else _("No"),
				"priority_raw": ticket.priority,
			}
		)

	return data


def _hours_between(start, end):
	"""Hours from `start` to `end`, or None when either end is not yet set.

	None (not 0) is returned when the milestone has not happened yet, so it
	renders blank rather than a misleading zero.
	"""
	if not start or not end:
		return None

	seconds = (get_datetime(end) - get_datetime(start)).total_seconds()

	return flt(seconds / 3600, 1)


def get_summary_message(data):
	"""A compact by-priority average, shown above the report grid."""
	if not data:
		return None

	priority_order = ["Urgent", "High", "Normal", "Low"]
	buckets = {}

	for row in data:
		priority = row.get("priority_raw") or _("Not Set")
		bucket = buckets.setdefault(priority, {"assign": [], "complete": []})

		if row["hours_to_assign"] is not None:
			bucket["assign"].append(row["hours_to_assign"])
		if row["hours_to_complete"] is not None:
			bucket["complete"].append(row["hours_to_complete"])

	ordered_priorities = [p for p in priority_order if p in buckets]
	ordered_priorities += [p for p in buckets if p not in priority_order]

	rows_html = ""
	for priority in ordered_priorities:
		bucket = buckets[priority]
		avg_assign = flt(sum(bucket["assign"]) / len(bucket["assign"]), 1) if bucket["assign"] else 0
		avg_complete = flt(sum(bucket["complete"]) / len(bucket["complete"]), 1) if bucket["complete"] else 0

		rows_html += (
			f"<tr><td>{frappe.utils.escape_html(_(priority))}</td>"
			f"<td style='text-align:right'>{avg_assign}</td>"
			f"<td style='text-align:right'>{avg_complete}</td></tr>"
		)

	return (
		"<table class='table table-bordered' style='margin-bottom:0'>"
		f"<thead><tr><th>{_('Priority')}</th><th>{_('Avg Hours to Assign')}</th>"
		f"<th>{_('Avg Hours to Complete')}</th></tr></thead>"
		f"<tbody>{rows_html}</tbody></table>"
	)
