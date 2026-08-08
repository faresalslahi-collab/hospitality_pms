"""Housekeeping Productivity — who is cleaning, how much, how fast, and how well.

Answers the housekeeping manager's staffing question: "Per attendant, over this
period, how many rooms did they actually finish, how long did it take, and did
supervisors pass their work the first time round?"

Source: `Hospitality Housekeeping Task` (SAS 3.11), scoped to tasks scheduled
in the filter period and grouped by `assigned_to`. `Hospitality Room
Inspection` rows are joined in through their `housekeeping_task` link to
attribute a supervisor's pass/fail back to the attendant who did the clean,
not to the inspector.

How the derived figures are calculated:

* **Rooms cleaned** — the count of *distinct* rooms with at least one
  Completed task assigned to the attendant in the period (an attendant who
  redoes the same room twice in one day is not double-counted here; that is
  what "tasks completed" is for).
* **Average minutes per room** — total actual minutes logged on Completed
  tasks divided by rooms cleaned. Guarded: an attendant with zero rooms
  cleaned shows 0, never a division error.
* **First-time pass rate %** — of the housekeeping tasks in the period that
  received at least one inspection, the share whose *earliest* recorded
  inspection (by `inspected_on`) was a Pass. A task inspected twice (failed,
  re-cleaned, then passed) counts as a first-time *fail*, because the room
  was not right the first time a supervisor looked at it. Guarded against a
  zero denominator (no inspected tasks in period) by returning 0.
"""

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
	filters = frappe._dict(filters or {})

	columns = get_columns()

	if not filters.get("property"):
		return columns, []

	data = get_data(filters)

	return columns, data


def get_columns():
	return [
		{"label": _("Attendant"), "fieldname": "attendant", "fieldtype": "Link", "options": "User", "width": 160},
		{"label": _("Tasks Completed"), "fieldname": "tasks_completed", "fieldtype": "Int", "width": 110},
		{"label": _("Rooms Cleaned"), "fieldname": "rooms_cleaned", "fieldtype": "Int", "width": 110},
		{"label": _("Total Minutes"), "fieldname": "total_minutes", "fieldtype": "Int", "width": 110},
		{
			"label": _("Avg Minutes / Room"),
			"fieldname": "avg_minutes_per_room",
			"fieldtype": "Float",
			"precision": 1,
			"width": 130,
		},
		{
			"label": _("Housekeeping Credits"),
			"fieldname": "housekeeping_credits",
			"fieldtype": "Int",
			"width": 130,
		},
		{"label": _("Inspections Passed"), "fieldname": "inspections_passed", "fieldtype": "Int", "width": 120},
		{"label": _("Inspections Failed"), "fieldname": "inspections_failed", "fieldtype": "Int", "width": 120},
		{
			"label": _("First-Time Pass Rate"),
			"fieldname": "first_time_pass_rate",
			"fieldtype": "Percent",
			"width": 130,
		},
	]


def get_data(filters):
	# The property filter is the scoping boundary for every query below: each
	# one is restricted to `property = %(property)s`, so a user who can only
	# see one property never receives another property's attendants or tasks
	# through this raw SQL.
	params = {
		"property": filters.property,
		"from_date": filters.get("from_date") or "1900-01-01",
		"to_date": filters.get("to_date") or "2999-12-31",
	}

	attendant_clause = ""
	if filters.get("attendant"):
		attendant_clause = " and t.assigned_to = %(attendant)s"
		params["attendant"] = filters.attendant

	task_rows = frappe.db.sql(
		f"""
		select
			t.assigned_to as attendant,
			sum(case when t.task_status = 'Completed' then 1 else 0 end) as tasks_completed,
			count(distinct case when t.task_status = 'Completed' then t.room end) as rooms_cleaned,
			sum(case when t.task_status = 'Completed' then t.actual_minutes else 0 end) as total_minutes,
			sum(case when t.task_status = 'Completed' then t.housekeeping_credits else 0 end)
				as housekeeping_credits
		from `tabHospitality Housekeeping Task` t
		where t.property = %(property)s
			and t.scheduled_date between %(from_date)s and %(to_date)s
			and t.assigned_to is not null and t.assigned_to != ''
			{attendant_clause}
		group by t.assigned_to
		""",
		params,
		as_dict=True,
	)

	inspection_rows = frappe.db.sql(
		f"""
		select
			t.assigned_to as attendant,
			sum(case when i.result = 'Passed' then 1 else 0 end) as inspections_passed,
			sum(case when i.result = 'Failed' then 1 else 0 end) as inspections_failed
		from `tabHospitality Room Inspection` i
		inner join `tabHospitality Housekeeping Task` t on t.name = i.housekeeping_task
		where t.property = %(property)s
			and t.scheduled_date between %(from_date)s and %(to_date)s
			and t.assigned_to is not null and t.assigned_to != ''
			{attendant_clause}
		group by t.assigned_to
		""",
		params,
		as_dict=True,
	)

	# First-time result per task: the earliest inspection recorded for each
	# housekeeping task, ranked by `inspected_on`, then rolled up per attendant.
	first_time_rows = frappe.db.sql(
		f"""
		select
			ranked.attendant as attendant,
			sum(case when ranked.result = 'Passed' then 1 else 0 end) as first_time_passed,
			count(*) as first_time_total
		from (
			select
				t.assigned_to as attendant,
				i.result as result,
				row_number() over (
					partition by i.housekeeping_task
					order by i.inspected_on asc
				) as rn
			from `tabHospitality Room Inspection` i
			inner join `tabHospitality Housekeeping Task` t on t.name = i.housekeeping_task
			where t.property = %(property)s
				and t.scheduled_date between %(from_date)s and %(to_date)s
				and t.assigned_to is not null and t.assigned_to != ''
				{attendant_clause}
		) ranked
		where ranked.rn = 1
		group by ranked.attendant
		""",
		params,
		as_dict=True,
	)

	by_attendant = {}

	for row in task_rows:
		by_attendant.setdefault(row.attendant, {}).update(
			{
				"tasks_completed": row.tasks_completed or 0,
				"rooms_cleaned": row.rooms_cleaned or 0,
				"total_minutes": row.total_minutes or 0,
				"housekeeping_credits": row.housekeeping_credits or 0,
			}
		)

	for row in inspection_rows:
		by_attendant.setdefault(row.attendant, {})
		by_attendant[row.attendant]["inspections_passed"] = row.inspections_passed or 0
		by_attendant[row.attendant]["inspections_failed"] = row.inspections_failed or 0

	first_time = {row.attendant: row for row in first_time_rows}

	data = []

	for attendant, figures in by_attendant.items():
		rooms_cleaned = figures.get("rooms_cleaned", 0)
		total_minutes = figures.get("total_minutes", 0)

		# Guard: an attendant with no completed rooms yet must not divide by zero.
		avg_minutes_per_room = flt(total_minutes) / rooms_cleaned if rooms_cleaned else 0.0

		ft_row = first_time.get(attendant)
		ft_total = ft_row.first_time_total if ft_row else 0
		ft_passed = ft_row.first_time_passed if ft_row else 0

		# Guard: no inspected tasks in the period means no rate to report, not
		# a division error.
		first_time_pass_rate = (flt(ft_passed) / ft_total * 100) if ft_total else 0.0

		data.append(
			{
				"attendant": attendant,
				"tasks_completed": figures.get("tasks_completed", 0),
				"rooms_cleaned": rooms_cleaned,
				"total_minutes": total_minutes,
				"avg_minutes_per_room": flt(avg_minutes_per_room, 1),
				"housekeeping_credits": figures.get("housekeeping_credits", 0),
				"inspections_passed": figures.get("inspections_passed", 0),
				"inspections_failed": figures.get("inspections_failed", 0),
				"first_time_pass_rate": flt(first_time_pass_rate, 1),
			}
		)

	data.sort(key=lambda row: row["attendant"] or "")

	return data
