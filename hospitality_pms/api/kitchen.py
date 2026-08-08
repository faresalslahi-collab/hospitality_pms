"""Kitchen, room service and minibar endpoints.

Lines for a requisition or an order arrive as a JSON string over HTTP; parse
with `frappe.parse_json` when that is what shows up, same as `api/folio.py`
`split_folio` does for `charge_rows`.
"""

import frappe
from frappe import _

from hospitality_pms.services import kitchen as service
from hospitality_pms.services.base import require_permission
from hospitality_pms.services.property import resolve_property

REQUISITION_DOCTYPE = "Hospitality Kitchen Requisition"
ORDER_DOCTYPE = "Hospitality Room Service Order"
WASTAGE_DOCTYPE = "Hospitality Wastage Entry"
MENU_DOCTYPE = "Hospitality Menu Item"

MENU_ITEM_FIELDS = (
	"name",
	"menu_item_code",
	"menu_item_name",
	"property",
	"is_active",
	"category",
	"item",
	"selling_rate",
	"currency",
	"preparation_minutes",
	"is_available_for_room_service",
	"is_minibar_item",
	"description",
)

REQUISITION_FIELDS = (
	"name",
	"property",
	"requisition_status",
	"requisition_date",
	"department",
	"from_warehouse",
	"to_warehouse",
	"requested_by",
	"issued_by",
	"issued_on",
	"stock_entry",
	"notes",
)

ORDER_FIELDS = (
	"name",
	"property",
	"order_status",
	"order_type",
	"room",
	"stay",
	"guest",
	"folio",
	"ordered_on",
	"delivered_on",
	"delivered_by",
	"subtotal",
	"service_charge",
	"tax_amount",
	"total_amount",
	"currency",
	"folio_charge_row",
	"special_instructions",
)


# ---------------------------------------------------------------------------
# Menu
# ---------------------------------------------------------------------------


@frappe.whitelist(methods=["GET"])
def list_menu_items(
	property: str | None = None,
	category: str | None = None,
	order_type: str | None = None,
	search: str | None = None,
) -> dict:
	"""Active menu items available for ordering."""
	require_permission(MENU_DOCTYPE, "read")
	property_name = resolve_property(property)

	filters = {"property": property_name, "is_active": 1}
	if category:
		filters["category"] = category
	if order_type == "Minibar":
		filters["is_minibar_item"] = 1
	elif order_type == "Room Service":
		filters["is_available_for_room_service"] = 1

	or_filters = None
	if search:
		pattern = f"%{search.strip()}%"
		or_filters = {"menu_item_name": ("like", pattern), "menu_item_code": ("like", pattern)}

	records = frappe.get_list(
		MENU_DOCTYPE,
		filters=filters,
		or_filters=or_filters,
		fields=list(MENU_ITEM_FIELDS),
		order_by="category asc, menu_item_name asc",
		limit_page_length=0,
	)

	return {"property": property_name, "menu_items": records}


# ---------------------------------------------------------------------------
# Requisitions
# ---------------------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
def create_requisition(
	property: str | None = None,
	lines: list | str = None,
	from_warehouse: str | None = None,
	to_warehouse: str | None = None,
	department: str | None = None,
	requisition_date: str | None = None,
	notes: str | None = None,
) -> dict:
	"""Raise a store-to-kitchen requisition."""
	require_permission(REQUISITION_DOCTYPE, "create")
	property_name = resolve_property(property)

	rows = frappe.parse_json(lines) if isinstance(lines, str) else list(lines or [])
	if not rows:
		frappe.throw(_("A requisition needs at least one line."))

	requisition = service.create_requisition(
		property_name,
		rows,
		from_warehouse=from_warehouse,
		to_warehouse=to_warehouse,
		department=department,
		requisition_date=requisition_date,
		notes=notes,
	)

	return get_requisition(requisition)


@frappe.whitelist(methods=["POST"])
def issue_requisition(requisition: str) -> dict:
	"""Move the stock: create and submit the requisition's Stock Entry."""
	require_permission(REQUISITION_DOCTYPE, "write")

	service.issue_requisition(requisition)

	return get_requisition(requisition)


@frappe.whitelist(methods=["GET"])
def get_requisition(requisition: str) -> dict:
	"""One requisition with its lines."""
	require_permission(REQUISITION_DOCTYPE, "read")

	doc = frappe.get_doc(REQUISITION_DOCTYPE, requisition)
	doc.check_permission("read")

	return {
		"requisition": {field: doc.get(field) for field in REQUISITION_FIELDS},
		"lines": [
			{
				"name": row.name,
				"item": row.item,
				"item_name": row.item_name,
				"quantity": row.quantity,
				"uom": row.uom,
				"issued_quantity": row.issued_quantity,
				"notes": row.notes,
			}
			for row in doc.lines
		],
	}


# ---------------------------------------------------------------------------
# Room service and minibar orders
# ---------------------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
def create_order(
	property: str | None = None,
	lines: list | str = None,
	stay: str | None = None,
	room: str | None = None,
	order_type: str = "Room Service",
	special_instructions: str | None = None,
) -> dict:
	"""Place a room service or minibar order against a stay."""
	require_permission(ORDER_DOCTYPE, "create")
	property_name = resolve_property(property)

	rows = frappe.parse_json(lines) if isinstance(lines, str) else list(lines or [])
	if not rows:
		frappe.throw(_("An order needs at least one line."))

	order = service.create_order(
		property_name,
		rows,
		stay=stay,
		room=room,
		order_type=order_type,
		special_instructions=special_instructions,
	)

	return get_order(order)


@frappe.whitelist(methods=["GET"])
def get_order(order: str) -> dict:
	"""One order with its priced lines."""
	require_permission(ORDER_DOCTYPE, "read")

	doc = frappe.get_doc(ORDER_DOCTYPE, order)
	doc.check_permission("read")

	return {
		"order": {field: doc.get(field) for field in ORDER_FIELDS},
		"lines": [
			{
				"name": row.name,
				"menu_item": row.menu_item,
				"item_name": row.item_name,
				"quantity": row.quantity,
				"rate": row.rate,
				"amount": row.amount,
				"is_prepared": bool(row.is_prepared),
				"notes": row.notes,
			}
			for row in doc.lines
		],
	}


@frappe.whitelist(methods=["POST"])
def set_order_status(order: str, status: str) -> dict:
	"""Move an order through preparation.

	A status of "Delivered" is handled by the service as a delegation to
	`deliver_order`, so it charges the folio the same way this endpoint's own
	`deliver_order` does - once, under one idempotency key.
	"""
	require_permission(ORDER_DOCTYPE, "write")

	service.set_order_status(order, status)

	return get_order(order)


@frappe.whitelist(methods=["POST"])
def deliver_order(order: str) -> dict:
	"""Deliver the order and charge it to the folio, exactly once."""
	require_permission(ORDER_DOCTYPE, "write")

	service.deliver_order(order)

	return get_order(order)


# ---------------------------------------------------------------------------
# Wastage
# ---------------------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
def record_wastage(
	property: str | None = None,
	item: str = None,
	quantity: float = None,
	reason: str = None,
	notes: str = None,
	warehouse: str | None = None,
	department: str | None = None,
	uom: str | None = None,
) -> dict:
	"""Write off stock. The service requires a manager role and a note."""
	require_permission(WASTAGE_DOCTYPE, "create")
	property_name = resolve_property(property)

	result = service.record_wastage(
		property_name,
		item,
		float(quantity or 0),
		reason,
		notes,
		warehouse=warehouse,
		department=department,
		uom=uom,
	)

	doc = frappe.get_doc(WASTAGE_DOCTYPE, result["wastage"])
	doc.check_permission("read")

	return {
		"wastage": {
			"name": doc.name,
			"property": doc.property,
			"wastage_date": doc.wastage_date,
			"department": doc.department,
			"warehouse": doc.warehouse,
			"item": doc.item,
			"quantity": doc.quantity,
			"uom": doc.uom,
			"reason": doc.reason,
			"notes": doc.notes,
			"estimated_value": doc.estimated_value,
			"stock_entry": doc.stock_entry,
			"recorded_by": doc.recorded_by,
			"approved_by": doc.approved_by,
		}
	}


@frappe.whitelist(methods=["GET"])
def consumption_report(property: str | None = None, from_date: str = None, to_date: str = None) -> dict:
	"""Requisitioned versus wasted stock, and the revenue it produced."""
	require_permission(WASTAGE_DOCTYPE, "read")
	property_name = resolve_property(property)

	return service.get_consumption_report(property_name, from_date, to_date)
