"""Rooms Out of Service — the revenue-loss list: every room not sellable right now, and for how long.

Answers the question a duty manager or revenue manager asks every morning:
"Which rooms can we not sell today because of maintenance, since when, and
who do I chase to get them back?"

Source: `Hotel Room` filtered to the maintenance dimension's blocking states
(`Under Maintenance`, `Out of Service`, `Out of Order` — the same set
`hospitality_pms.services.rooms.BLOCKING_MAINTENANCE` uses to decide a room is
not assignable), left-joined to the room's open maintenance ticket and to any
active `Hospitality Room Block` holding it out of inventory.

**How "Days Out of Service" is calculated** — a room is pulled from sale by a
submitted, Active `Hospitality Room Block` (`MaintenanceService.
take_out_of_service` always raises one; see `services/maintenance.py`), so
that block's `from_date` is the authoritative start of the outage wherever an
active block exists for the room. Only when no active block is found (for
example, a maintenance status set directly rather than through a ticket's
out-of-service flow) does this report fall back to the open ticket's
`reported_on` date as the best available start date. Days out of service is
then `as_of_date - start_date`, floored at 0.
"""

import frappe
from frappe import _
from frappe.utils import getdate, nowdate

BLOCKING_MAINTENANCE = ("Under Maintenance", "Out of Service", "Out of Order")
OPEN_TICKET_STATUSES = ("Open", "In Progress", "Verification")


def execute(filters=None):
	filters = frappe._dict(filters or {})

	columns = get_columns()

	if not filters.get("property"):
		return columns, []

	data = get_data(filters)

	return columns, data


def get_columns():
	return [
		{"label": _("Room"), "fieldname": "room", "fieldtype": "Link", "options": "Hotel Room", "width": 100},
		{
			"label": _("Room Type"),
			"fieldname": "room_type",
			"fieldtype": "Link",
			"options": "Room Type",
			"width": 120,
		},
		{"label": _("Maintenance Status"), "fieldname": "maintenance_status", "fieldtype": "Data", "width": 130},
		{
			"label": _("Ticket"),
			"fieldname": "ticket",
			"fieldtype": "Link",
			"options": "Hospitality Maintenance Ticket",
			"width": 130,
		},
		{"label": _("Ticket Status"), "fieldname": "ticket_status", "fieldtype": "Data", "width": 100},
		{"label": _("Category"), "fieldname": "category", "fieldtype": "Data", "width": 100},
		{"label": _("Priority"), "fieldname": "priority", "fieldtype": "Data", "width": 90},
		{"label": _("Reported On"), "fieldname": "reported_on", "fieldtype": "Datetime", "width": 150},
		{
			"label": _("Days Out of Service"),
			"fieldname": "days_out_of_service",
			"fieldtype": "Int",
			"width": 130,
		},
		{
			"label": _("Room Block"),
			"fieldname": "room_block",
			"fieldtype": "Link",
			"options": "Hospitality Room Block",
			"width": 130,
		},
		{"label": _("Block To Date"), "fieldname": "block_to_date", "fieldtype": "Date", "width": 110},
		{
			"label": _("Verified By"),
			"fieldname": "verified_by",
			"fieldtype": "Link",
			"options": "User",
			"width": 140,
		},
	]


def get_data(filters):
	as_of_date = getdate(filters.get("as_of_date") or nowdate())

	# The property filter is the scoping boundary for this raw SQL: every
	# room, ticket and block joined below is restricted to
	# `property = %(property)s`.
	rooms = frappe.db.sql(
		"""
		select
			r.name as room,
			r.room_type as room_type,
			r.maintenance_status as maintenance_status
		from `tabHotel Room` r
		where r.property = %(property)s
			and r.maintenance_status in %(blocking)s
		order by r.name asc
		""",
		{"property": filters.property, "blocking": BLOCKING_MAINTENANCE},
		as_dict=True,
	)

	if not rooms:
		return []

	room_names = [row.room for row in rooms]

	# The single most recent still-open ticket per room, so a room does not
	# appear twice when more than one open ticket exists against it.
	tickets = frappe.db.sql(
		"""
		select
			t1.room as room,
			t1.name as ticket,
			t1.ticket_status as ticket_status,
			t1.category as category,
			t1.priority as priority,
			t1.reported_on as reported_on,
			t1.verified_by as verified_by
		from `tabHospitality Maintenance Ticket` t1
		inner join (
			select room, max(reported_on) as latest_reported_on
			from `tabHospitality Maintenance Ticket`
			where property = %(property)s
				and room in %(rooms)s
				and ticket_status in %(open_statuses)s
			group by room
		) t2 on t2.room = t1.room and t2.latest_reported_on = t1.reported_on
		where t1.property = %(property)s
		""",
		{"property": filters.property, "rooms": room_names, "open_statuses": OPEN_TICKET_STATUSES},
		as_dict=True,
	)
	ticket_by_room = {row.room: row for row in tickets}

	# The active block currently holding each room out of inventory, if any.
	blocks = frappe.db.sql(
		"""
		select room, name as room_block, from_date, to_date
		from `tabHospitality Room Block`
		where property = %(property)s
			and room in %(rooms)s
			and docstatus = 1
			and status = 'Active'
			and from_date <= %(as_of_date)s
		order by from_date desc
		""",
		{"property": filters.property, "rooms": room_names, "as_of_date": as_of_date},
		as_dict=True,
	)
	# Keep the earliest-starting active block per room: if a room somehow
	# carries more than one active block, the outage began at the earlier one.
	block_by_room = {}
	for row in blocks:
		existing = block_by_room.get(row.room)
		if not existing or getdate(row.from_date) < getdate(existing.from_date):
			block_by_room[row.room] = row

	data = []

	for room in rooms:
		ticket = ticket_by_room.get(room.room)
		block = block_by_room.get(room.room)

		if block:
			start_date = getdate(block.from_date)
		elif ticket and ticket.reported_on:
			start_date = getdate(ticket.reported_on)
		else:
			start_date = None

		days_out_of_service = max((as_of_date - start_date).days, 0) if start_date else 0

		data.append(
			{
				"room": room.room,
				"room_type": room.room_type,
				"maintenance_status": room.maintenance_status,
				"ticket": ticket.ticket if ticket else None,
				"ticket_status": ticket.ticket_status if ticket else None,
				"category": ticket.category if ticket else None,
				"priority": ticket.priority if ticket else None,
				"reported_on": ticket.reported_on if ticket else None,
				"days_out_of_service": days_out_of_service,
				"room_block": block.room_block if block else None,
				"block_to_date": block.to_date if block else None,
				"verified_by": ticket.verified_by if ticket else None,
			}
		)

	data.sort(key=lambda row: row["days_out_of_service"], reverse=True)

	return data
