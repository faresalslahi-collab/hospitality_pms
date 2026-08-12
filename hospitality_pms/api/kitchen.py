"""Kitchen, room service and minibar endpoints.

Lines for a requisition or an order arrive as a JSON string over HTTP; parse
with `frappe.parse_json` when that is what shows up, same as `api/folio.py`
`split_folio` does for `charge_rows`.
"""

import frappe
from frappe import _

from hospitality_pms.services import kitchen as service
from hospitality_pms.services.base import authorise_document, require_permission
from hospitality_pms.services.property import resolve_property

REQUISITION_DOCTYPE = "Kitchen Requisition"
ORDER_DOCTYPE = "Room Service Order"
WASTAGE_DOCTYPE = "Wastage Entry"
MENU_DOCTYPE = "Menu Item"

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
	authorise_document(REQUISITION_DOCTYPE, requisition, "write")

	service.issue_requisition(requisition)

	return get_requisition(requisition)


@frappe.whitelist(methods=["GET"])
def get_requisition(requisition: str) -> dict:
	"""One requisition with its lines."""
	# `authorise_document` rather than `check_permission` alone (16.7.5). A User
	# Permission created without `apply_to_all_doctypes` restricts only the
	# DocTypes it names, so step 2 can legitimately pass for a record in a
	# property the caller may not operate in - and every one of these DocTypes
	# carries a required `property`, so the third check always fires.
	doc = authorise_document(REQUISITION_DOCTYPE, requisition, "read")

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


#: Order fields that belong to a DocType other than the order itself.
#:
#: Each is dropped unless the caller may read the source. A kitchen fulfils an
#: order from the room, the lines and the notes; the guest's identity and the
#: folio are a different question with a different answer.
_ORDER_FIELD_SOURCE = {
	"guest": "Guest",
	"stay": "Stay",
	"folio": "Guest Folio",
	"folio_charge_row": "Guest Folio",
}


def _order_disclosure() -> set[str]:
	"""The order fields this caller is entitled to, asked once per request."""
	allowed = {field for field in ORDER_FIELDS if field not in _ORDER_FIELD_SOURCE}

	for field, doctype in _ORDER_FIELD_SOURCE.items():
		if frappe.has_permission(doctype, "read"):
			allowed.add(field)

	return allowed


# ---------------------------------------------------------------------------
# Room service and minibar orders
# ---------------------------------------------------------------------------


@frappe.whitelist(methods=["GET"])
def board(property: str | None = None, include_closed: int = 0) -> dict:
	"""The room service board: what the kitchen still has to cook.

	Read-only. Placing, advancing and delivering an order all go through their
	own endpoints below, which is where the pricing and the folio charge are
	decided.
	"""
	require_permission(ORDER_DOCTYPE, "read")
	property_name = resolve_property(property)

	return service.get_order_board(property_name, include_closed=bool(int(include_closed or 0)))



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
	"""One order with its priced lines.

	The guest and folio identifiers are dropped for a caller who may not read
	those DocTypes - the same rule the order board applies. `Room Service Order`
	read is held by every kitchen role and by none of them does it imply Guest or
	Guest Folio read, so gating only the order would publish the guest's identity
	and the folio their money sits on through a second door.
	"""
	# `authorise_document` rather than `check_permission` alone (16.7.5). A User
	# Permission created without `apply_to_all_doctypes` restricts only the
	# DocTypes it names, so step 2 can legitimately pass for a record in a
	# property the caller may not operate in - and every one of these DocTypes
	# carries a required `property`, so the third check always fires.
	doc = authorise_document(ORDER_DOCTYPE, order, "read")

	fields = [field for field in ORDER_FIELDS if field in _order_disclosure()]

	return {
		"order": {field: doc.get(field) for field in fields},
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
	authorise_document(ORDER_DOCTYPE, order, "write")

	service.set_order_status(order, status)

	return get_order(order)


@frappe.whitelist(methods=["POST"])
def deliver_order(order: str) -> dict:
	"""Deliver the order and charge it to the folio, exactly once."""
	authorise_document(ORDER_DOCTYPE, order, "write")

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
