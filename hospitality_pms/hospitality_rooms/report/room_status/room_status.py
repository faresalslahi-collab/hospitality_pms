"""Room Status — the four independent status dimensions of every room, at a glance.

Answers the operational question every shift asks: "Which rooms can we sell
right now, and for the ones we cannot, what exactly is stopping us —
maintenance, inventory block, an occupied guest, or housekeeping?" A room
carries occupancy, housekeeping, maintenance and inventory status
independently (see `hospitality_pms.services.rooms`), so a single "status"
column would hide real operational detail; this report keeps all four visible
and adds the one derived answer the desk actually needs: assignable or not,
and why not.

The blocking-reason precedence is not reinvented here: it is imported from
`hospitality_pms.api.rooms._blocking_reason`, the same function the room rack
API uses, so this report and the rack screen can never disagree about why a
room is blocked.
"""

import frappe
from frappe import _

from hospitality_pms.api.rooms import _blocking_reason


def execute(filters=None):
	filters = frappe._dict(filters or {})

	columns = get_columns()

	if not filters.get("property"):
		return columns, []

	data = get_data(filters)

	return columns, data


def get_columns():
	return [
		{"label": _("Room"), "fieldname": "name", "fieldtype": "Link", "options": "Hotel Room", "width": 100},
		{
			"label": _("Room Type"),
			"fieldname": "room_type",
			"fieldtype": "Link",
			"options": "Room Type",
			"width": 120,
		},
		{"label": _("Floor"), "fieldname": "floor", "fieldtype": "Link", "options": "Floor", "width": 100},
		{"label": _("Occupancy Status"), "fieldname": "occupancy_status", "fieldtype": "Data", "width": 110},
		{"label": _("Housekeeping Status"), "fieldname": "housekeeping_status", "fieldtype": "Data", "width": 130},
		{"label": _("Maintenance Status"), "fieldname": "maintenance_status", "fieldtype": "Data", "width": 130},
		{"label": _("Inventory Status"), "fieldname": "inventory_status", "fieldtype": "Data", "width": 110},
		{"label": _("Assignable"), "fieldname": "assignable", "fieldtype": "Data", "width": 90},
		{"label": _("Blocking Reason"), "fieldname": "blocking_reason", "fieldtype": "Data", "width": 140},
	]


def get_data(filters):
	# Permission scoping here comes from `frappe.get_all`, which applies the
	# Hotel Room DocType's own permission rules on top of the mandatory
	# `property` filter below.
	query_filters = {"property": filters.property}
	if filters.get("room_type"):
		query_filters["room_type"] = filters.room_type

	rooms = frappe.get_all(
		"Hotel Room",
		filters=query_filters,
		fields=[
			"name",
			"room_type",
			"floor",
			"is_active",
			"occupancy_status",
			"housekeeping_status",
			"maintenance_status",
			"inventory_status",
		],
		order_by="room_type asc, name asc",
		limit_page_length=0,
	)

	data = []

	for room in rooms:
		reason = _blocking_reason(room)
		data.append(
			{
				"name": room["name"],
				"room_type": room["room_type"],
				"floor": room["floor"],
				"occupancy_status": room["occupancy_status"],
				"housekeeping_status": room["housekeeping_status"],
				"maintenance_status": room["maintenance_status"],
				"inventory_status": room["inventory_status"],
				"assignable": _("No") if reason else _("Yes"),
				"blocking_reason": reason or "",
			}
		)

	return data
