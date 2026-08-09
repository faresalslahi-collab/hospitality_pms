"""Guest Request SLA — is guest services actually hitting its response promise.

Answers the guest relations / front office question: "Per request, did we
respond and finish inside the SLA we set when the guest asked, and where are
we missing it most?" One row per `Guest Request` raised in the
filter period (SAS 3.15 / Workflow Matrix section 9).

Notes on the columns:

* **Raised On** is the request's `creation` timestamp. The doctype has no
  separate "raised on" field: the SLA clock in `GuestService.create_request`
  starts from the moment the document is created, so `creation` *is* the
  raised time.
* **Breached** is Yes when `is_breached` was stamped true at completion
  (`GuestService.complete`), **or** when the request is still open past its
  `due_by` right now — a request does not have to be finished for a manager
  to already know it is late. This is a display-time computation only; it
  never writes back to `is_breached`, which stays the system's own record of
  what happened at completion.
* **SLA Minutes** is the target that was set on the request (`sla_minutes`),
  not a measured duration.

A breach rate by priority is appended above the table (via the report's
`message`), since a flat breach count says nothing about whether Urgent
requests specifically are the ones missing target.
"""

import frappe
from frappe import _
from frappe.utils import flt, get_datetime, now_datetime


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
			"label": _("Request"),
			"fieldname": "request",
			"fieldtype": "Link",
			"options": "Guest Request",
			"width": 130,
		},
		{"label": _("Subject"), "fieldname": "subject", "fieldtype": "Data", "width": 180},
		{"label": _("Category"), "fieldname": "category", "fieldtype": "Data", "width": 110},
		{"label": _("Priority"), "fieldname": "priority", "fieldtype": "Data", "width": 90},
		{"label": _("Raised On"), "fieldname": "raised_on", "fieldtype": "Datetime", "width": 150},
		{"label": _("Due By"), "fieldname": "due_by", "fieldtype": "Datetime", "width": 150},
		{"label": _("Responded On"), "fieldname": "responded_on", "fieldtype": "Datetime", "width": 150},
		{"label": _("Completed On"), "fieldname": "completed_on", "fieldtype": "Datetime", "width": 150},
		{"label": _("SLA Minutes"), "fieldname": "sla_minutes", "fieldtype": "Int", "width": 100},
		{"label": _("Breached"), "fieldname": "breached", "fieldtype": "Data", "width": 90},
		{"label": _("Escalation Level"), "fieldname": "escalation_level", "fieldtype": "Int", "width": 110},
		{"label": _("Reopened Count"), "fieldname": "reopened_count", "fieldtype": "Int", "width": 110},
	]


def get_data(filters):
	# The property filter is the scoping boundary: `frappe.get_all` applies
	# Guest Request's own permission rules on top of this
	# mandatory filter.
	conditions = {"property": filters.property}

	from_date = filters.get("from_date")
	to_date = filters.get("to_date")

	if from_date and to_date:
		conditions["creation"] = ["between", [from_date, to_date]]
	elif from_date:
		conditions["creation"] = [">=", from_date]
	elif to_date:
		conditions["creation"] = ["<=", to_date]

	if filters.get("category"):
		conditions["category"] = filters.category

	requests = frappe.get_all(
		"Guest Request",
		filters=conditions,
		fields=[
			"name",
			"subject",
			"category",
			"priority",
			"creation",
			"due_by",
			"responded_on",
			"completed_on",
			"sla_minutes",
			"is_breached",
			"escalation_level",
			"reopened_count",
		],
		order_by="creation asc",
		limit_page_length=0,
	)

	now = now_datetime()
	data = []

	for request in requests:
		still_overdue = (
			not request.completed_on and request.due_by and get_datetime(request.due_by) < now
		)
		breached = bool(request.is_breached) or bool(still_overdue)

		data.append(
			{
				"request": request.name,
				"subject": request.subject,
				"category": request.category,
				"priority": request.priority,
				"raised_on": request.creation,
				"due_by": request.due_by,
				"responded_on": request.responded_on,
				"completed_on": request.completed_on,
				"sla_minutes": request.sla_minutes,
				"breached": _("Yes") if breached else _("No"),
				"escalation_level": request.escalation_level or 0,
				"reopened_count": request.reopened_count or 0,
				"breached_raw": breached,
				"priority_raw": request.priority,
			}
		)

	return data


def get_summary_message(data):
	"""Breach rate by priority, shown above the report grid."""
	if not data:
		return None

	priority_order = ["Urgent", "High", "Normal", "Low"]
	buckets = {}

	for row in data:
		priority = row.get("priority_raw") or _("Not Set")
		bucket = buckets.setdefault(priority, {"total": 0, "breached": 0})
		bucket["total"] += 1
		if row["breached_raw"]:
			bucket["breached"] += 1

	ordered_priorities = [p for p in priority_order if p in buckets]
	ordered_priorities += [p for p in buckets if p not in priority_order]

	rows_html = ""
	for priority in ordered_priorities:
		bucket = buckets[priority]
		# Guard: a priority bucket always has at least one request (it is
		# only created from rows already in `data`), but the rate is still
		# computed defensively against a zero total.
		rate = flt(bucket["breached"] / bucket["total"] * 100, 1) if bucket["total"] else 0.0

		rows_html += (
			f"<tr><td>{frappe.utils.escape_html(_(priority))}</td>"
			f"<td style='text-align:right'>{bucket['total']}</td>"
			f"<td style='text-align:right'>{bucket['breached']}</td>"
			f"<td style='text-align:right'>{rate}%</td></tr>"
		)

	return (
		"<table class='table table-bordered' style='margin-bottom:0'>"
		f"<thead><tr><th>{_('Priority')}</th><th>{_('Requests')}</th>"
		f"<th>{_('Breached')}</th><th>{_('Breach Rate')}</th></tr></thead>"
		f"<tbody>{rows_html}</tbody></table>"
	)
