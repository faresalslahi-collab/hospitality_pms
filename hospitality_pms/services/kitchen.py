"""Kitchen, room service and minibar.

Two integrations meet here, and both must stay honest:

* **Stock.** A requisition and a wastage entry move real inventory, so they
  create ERPNext Stock Entries. ERPNext owns the stock ledger (HPMS-DEC-002);
  this app records why the movement happened, not what the balance now is.
* **Revenue.** A room service or minibar order charges the guest, so it posts
  to the folio through FolioService under a key derived from the order. An
  order delivered twice by a retried request charges once.

Full Restaurant POS is deferred (HPMS-DEC-015); this is the MVP the approved
scope calls for.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate, now_datetime, nowdate

from hospitality_pms.services.base import lock_document, require_role
from hospitality_pms.services.exceptions import ConfigurationError, HospitalityPMSError, throw
from hospitality_pms.services.property import get_business_date, get_company, get_warehouse

REQUISITION_DOCTYPE = "Hospitality Kitchen Requisition"
ORDER_DOCTYPE = "Hospitality Room Service Order"
WASTAGE_DOCTYPE = "Hospitality Wastage Entry"
MENU_DOCTYPE = "Hospitality Menu Item"

#: Writing off stock is a management decision, not a line cook's
#: (Roles Matrix section 3).
WASTAGE_APPROVAL_ROLES = (
	"Kitchen Manager",
	"Food and Beverage Manager",
	"Hotel Manager",
	"General Manager",
	"Hospitality Administrator",
	"System Manager",
)


# ---------------------------------------------------------------------------
# Requisitions
# ---------------------------------------------------------------------------


def create_requisition(
	property_name: str,
	lines: list[dict],
	*,
	from_warehouse: str | None = None,
	to_warehouse: str | None = None,
	department: str | None = None,
	requisition_date=None,
	notes: str | None = None,
) -> str:
	"""Raise a store-to-kitchen requisition."""
	if not lines:
		throw(_("A requisition needs at least one line."), exc=HospitalityPMSError)

	from_warehouse = from_warehouse or get_warehouse(property_name, "General Store")
	to_warehouse = to_warehouse or get_warehouse(property_name, "Kitchen Store")

	if from_warehouse == to_warehouse:
		throw(_("The source and destination warehouses must differ."), exc=ConfigurationError)

	doc = frappe.get_doc(
		{
			"doctype": REQUISITION_DOCTYPE,
			"property": property_name,
			"requisition_status": "Draft",
			"requisition_date": getdate(requisition_date or get_business_date(property_name)),
			"department": department,
			"from_warehouse": from_warehouse,
			"to_warehouse": to_warehouse,
			"requested_by": frappe.session.user,
			"notes": notes,
			"lines": lines,
		}
	).insert(ignore_permissions=True)

	frappe.db.set_value(REQUISITION_DOCTYPE, doc.name, "requisition_status", "Submitted", update_modified=False)

	return doc.name


def issue_requisition(requisition: str) -> dict:
	"""Move the stock, by creating and submitting an ERPNext Stock Entry.

	Idempotent: a requisition that already carries a submitted stock entry
	returns it rather than moving the stock a second time.
	"""
	lock_document(REQUISITION_DOCTYPE, requisition)

	doc = frappe.get_doc(REQUISITION_DOCTYPE, requisition)

	if doc.stock_entry and frappe.db.exists("Stock Entry", doc.stock_entry):
		return {"requisition": requisition, "stock_entry": doc.stock_entry, "duplicate": True}

	if doc.requisition_status == "Cancelled":
		throw(_("Requisition {0} is cancelled.").format(requisition), exc=HospitalityPMSError)

	entry = frappe.new_doc("Stock Entry")
	entry.stock_entry_type = "Material Transfer"
	entry.company = get_company(doc.property)
	entry.posting_date = doc.requisition_date
	entry.set_posting_time = 1
	entry.remarks = _("Hospitality kitchen requisition {0}").format(requisition)

	for row in doc.lines:
		entry.append(
			"items",
			{
				"item_code": row.item,
				"qty": flt(row.quantity),
				"uom": row.uom or frappe.db.get_value("Item", row.item, "stock_uom"),
				"s_warehouse": doc.from_warehouse,
				"t_warehouse": doc.to_warehouse,
			},
		)

	entry.flags.ignore_permissions = True
	entry.insert()
	entry.submit()

	for row in doc.lines:
		frappe.db.set_value(
			"Hospitality Requisition Line", row.name, "issued_quantity", flt(row.quantity), update_modified=False
		)

	frappe.db.set_value(
		REQUISITION_DOCTYPE,
		requisition,
		{
			"requisition_status": "Issued",
			"stock_entry": entry.name,
			"issued_by": frappe.session.user,
			"issued_on": now_datetime(),
		},
		update_modified=True,
	)

	return {"requisition": requisition, "stock_entry": entry.name, "duplicate": False}


# ---------------------------------------------------------------------------
# Room service and minibar
# ---------------------------------------------------------------------------


def create_order(
	property_name: str,
	lines: list[dict],
	*,
	stay: str | None = None,
	room: str | None = None,
	order_type: str = "Room Service",
	special_instructions: str | None = None,
) -> str:
	"""Place a room service or minibar order against a stay."""
	if not lines:
		throw(_("An order needs at least one line."), exc=HospitalityPMSError)

	from hospitality_pms.services import folio as folio_service

	folio = folio_service.get_folio_for_stay(stay) if stay else None

	if not folio:
		throw(
			_("This order has no open folio to charge. The guest must be in house."),
			exc=HospitalityPMSError,
		)

	stay_doc = frappe.db.get_value(
		"Hospitality Stay", stay, ["room", "guest", "property"], as_dict=True
	)

	priced = []
	subtotal = 0.0

	for line in lines:
		menu_item = line.get("menu_item")
		item = frappe.db.get_value(
			MENU_DOCTYPE, menu_item, ["menu_item_name", "selling_rate", "is_active"], as_dict=True
		)

		if not item or not item["is_active"]:
			throw(_("Menu item {0} is not available.").format(menu_item), exc=HospitalityPMSError)

		quantity = flt(line.get("quantity") or 1)
		# The rate comes from the menu, not the caller: a client that could set
		# its own price could give the guest anything away.
		rate = flt(item["selling_rate"])
		amount = quantity * rate
		subtotal += amount

		priced.append(
			{
				"menu_item": menu_item,
				"item_name": item["menu_item_name"],
				"quantity": quantity,
				"rate": rate,
				"amount": amount,
				"notes": line.get("notes"),
			}
		)

	doc = frappe.get_doc(
		{
			"doctype": ORDER_DOCTYPE,
			"property": property_name,
			"order_status": "Placed",
			"order_type": order_type,
			"room": room or stay_doc.get("room"),
			"stay": stay,
			"guest": stay_doc.get("guest"),
			"folio": folio,
			"ordered_on": now_datetime(),
			"lines": priced,
			"subtotal": flt(subtotal, 2),
			"total_amount": flt(subtotal, 2),
			"special_instructions": special_instructions,
		}
	).insert(ignore_permissions=True)

	return doc.name


def set_order_status(order: str, status: str) -> str:
	"""Move an order through preparation."""
	if status not in ("Placed", "Preparing", "Ready", "Delivered", "Cancelled"):
		throw(_("{0} is not an order status.").format(status), exc=HospitalityPMSError)

	lock_document(ORDER_DOCTYPE, order)

	if status == "Delivered":
		return deliver_order(order)["order"]

	frappe.db.set_value(ORDER_DOCTYPE, order, "order_status", status, update_modified=True)

	return order


def deliver_order(order: str) -> dict:
	"""Deliver the order and charge it to the folio, exactly once."""
	from hospitality_pms.services import folio as folio_service

	lock_document(ORDER_DOCTYPE, order)
	doc = frappe.get_doc(ORDER_DOCTYPE, order)

	if doc.order_status == "Cancelled":
		throw(_("Order {0} is cancelled.").format(order), exc=HospitalityPMSError)

	if doc.folio_charge_row:
		return {"order": order, "folio_charge": doc.folio_charge_row, "duplicate": True}

	if not doc.folio:
		throw(_("Order {0} has no folio to charge.").format(order), exc=HospitalityPMSError)

	charge_type = "Minibar" if doc.order_type == "Minibar" else "Room Service"

	result = folio_service.post_charge(
		doc.folio,
		charge_type,
		_("{0} order {1}").format(charge_type, order),
		flt(doc.total_amount),
		idempotency_key=f"order:{order}",
		reference_doctype=ORDER_DOCTYPE,
		reference_name=order,
	)

	frappe.db.set_value(
		ORDER_DOCTYPE,
		order,
		{
			"order_status": "Delivered",
			"delivered_on": now_datetime(),
			"delivered_by": frappe.session.user,
			"folio_charge_row": result["row"],
		},
		update_modified=True,
	)

	consumption = _consume_order_stock(doc)

	return {
		"order": order,
		"folio_charge": result["row"],
		"stock_entry": consumption,
		"duplicate": False,
	}


def _consume_order_stock(doc) -> str | None:
	"""Issue the stock an order actually consumed.

	Only menu items mapped to a stock item move stock; a service-only item
	(a corkage fee, say) has nothing to issue. Returns None when there is
	nothing to move, rather than creating an empty stock entry.
	"""
	items = []

	for row in doc.lines:
		item = frappe.db.get_value(MENU_DOCTYPE, row.menu_item, "item")

		if not item or not frappe.db.get_value("Item", item, "is_stock_item"):
			continue

		items.append({"item_code": item, "qty": flt(row.quantity)})

	if not items:
		return None

	try:
		warehouse = get_warehouse(doc.property, "Minibar" if doc.order_type == "Minibar" else "Kitchen Store")
	except Exception:  # noqa: BLE001
		# A property that has not mapped the warehouse yet still gets the
		# revenue; the consumption is simply not recorded, and the missing
		# mapping surfaces as a configuration error elsewhere.
		return None

	entry = frappe.new_doc("Stock Entry")
	entry.stock_entry_type = "Material Issue"
	entry.company = get_company(doc.property)
	entry.posting_date = get_business_date(doc.property)
	entry.set_posting_time = 1
	entry.remarks = _("Consumption for order {0}").format(doc.name)

	for line in items:
		entry.append("items", {**line, "s_warehouse": warehouse})

	entry.flags.ignore_permissions = True
	entry.insert()
	entry.submit()

	return entry.name


# ---------------------------------------------------------------------------
# Wastage
# ---------------------------------------------------------------------------


def record_wastage(
	property_name: str,
	item: str,
	quantity: float,
	reason: str,
	notes: str,
	*,
	warehouse: str | None = None,
	department: str | None = None,
	uom: str | None = None,
) -> dict:
	"""Write off stock, with an ERPNext Stock Entry behind it.

	Requires a manager: wastage is where food cost quietly disappears, so it
	is approved rather than self-served.
	"""
	require_role(WASTAGE_APPROVAL_ROLES)

	if not notes or not notes.strip():
		throw(_("Wastage must be explained."), exc=HospitalityPMSError)

	if flt(quantity) <= 0:
		throw(_("Wastage quantity must be greater than zero."), exc=HospitalityPMSError)

	warehouse = warehouse or get_warehouse(property_name, "Kitchen Store")

	doc = frappe.get_doc(
		{
			"doctype": WASTAGE_DOCTYPE,
			"property": property_name,
			"wastage_date": get_business_date(property_name),
			"department": department,
			"warehouse": warehouse,
			"item": item,
			"quantity": flt(quantity),
			"uom": uom or frappe.db.get_value("Item", item, "stock_uom"),
			"reason": reason,
			"notes": notes.strip(),
			"recorded_by": frappe.session.user,
			"approved_by": frappe.session.user,
		}
	).insert(ignore_permissions=True)

	entry = frappe.new_doc("Stock Entry")
	entry.stock_entry_type = "Material Issue"
	entry.company = get_company(property_name)
	entry.posting_date = doc.wastage_date
	entry.set_posting_time = 1
	entry.remarks = _("Wastage {0}: {1}").format(doc.name, reason)
	entry.append("items", {"item_code": item, "qty": flt(quantity), "s_warehouse": warehouse})

	entry.flags.ignore_permissions = True
	entry.insert()
	entry.submit()

	value = flt(entry.total_outgoing_value or 0, 2)

	frappe.db.set_value(
		WASTAGE_DOCTYPE,
		doc.name,
		{"stock_entry": entry.name, "estimated_value": value},
		update_modified=False,
	)

	return {"wastage": doc.name, "stock_entry": entry.name, "value": value}


def get_consumption_report(property_name: str, from_date, to_date) -> dict:
	"""Requisitioned versus wasted, for the kitchen cost conversation."""
	wastage = frappe.db.sql(
		"""
		select item, sum(quantity) as quantity, sum(estimated_value) as value
		from `tabHospitality Wastage Entry`
		where property = %(property)s and wastage_date between %(from_date)s and %(to_date)s
		group by item
		order by value desc
		""",
		{"property": property_name, "from_date": getdate(from_date), "to_date": getdate(to_date)},
		as_dict=True,
	)

	revenue = frappe.db.sql(
		"""
		select order_type, count(*) as orders, sum(total_amount) as revenue
		from `tabHospitality Room Service Order`
		where property = %(property)s
		  and order_status = 'Delivered'
		  and date(ordered_on) between %(from_date)s and %(to_date)s
		group by order_type
		""",
		{"property": property_name, "from_date": getdate(from_date), "to_date": getdate(to_date)},
		as_dict=True,
	)

	return {
		"property": property_name,
		"from_date": str(getdate(from_date)),
		"to_date": str(getdate(to_date)),
		"wastage": wastage,
		"revenue": revenue,
		"total_wastage_value": flt(sum(flt(row["value"]) for row in wastage), 2),
		"total_revenue": flt(sum(flt(row["revenue"]) for row in revenue), 2),
	}


# ---------------------------------------------------------------------------
# Boards
# ---------------------------------------------------------------------------

#: Orders still being worked. Delivered and Cancelled are finished, and a board
#: that kept showing them would bury the ones that still need cooking.
OPEN_ORDER_STATES = ("Placed", "Preparing", "Ready")


def get_order_board(property_name: str, *, include_closed: bool = False) -> dict:
	"""Room service orders for a property, oldest first.

	Oldest first on purpose: a room service board is a queue, and the order
	that has been waiting longest is the one the kitchen should be cooking.

	Line counts come from one grouped query rather than one per order, so a
	busy evening costs the same two queries as a quiet one.
	"""
	states = ("Placed", "Preparing", "Ready", "Delivered", "Cancelled") if include_closed else OPEN_ORDER_STATES

	orders = frappe.get_all(
		ORDER_DOCTYPE,
		filters={"property": property_name, "order_status": ("in", states)},
		fields=[
			"name",
			"order_status",
			"order_type",
			"room",
			"stay",
			"guest",
			"folio",
			"ordered_on",
			"delivered_on",
			"total_amount",
			"currency",
			"special_instructions",
			"folio_charge_row",
		],
		order_by="ordered_on asc",
		limit_page_length=0,
	)

	if orders:
		lines = frappe.get_all(
			"Hospitality Order Line",
			filters={"parenttype": ORDER_DOCTYPE, "parent": ("in", [o["name"] for o in orders])},
			fields=["parent", "quantity"],
			limit_page_length=0,
		)

		by_order: dict[str, dict] = {}
		for row in lines:
			bucket = by_order.setdefault(row["parent"], {"lines": 0, "items": 0.0})
			bucket["lines"] += 1
			bucket["items"] += flt(row["quantity"])

		# The order carries the guest link but not their name; one lookup for
		# the whole board rather than one per row.
		guests = {g for g in (o["guest"] for o in orders) if g}
		names = (
			dict(
				frappe.get_all(
					"Hospitality Guest",
					filters={"name": ("in", list(guests))},
					fields=["name", "guest_name"],
					as_list=True,
					limit_page_length=0,
				)
			)
			if guests
			else {}
		)

		for order in orders:
			row = by_order.get(order["name"]) or {}
			order["line_count"] = int(row.get("lines") or 0)
			order["item_count"] = flt(row.get("items") or 0)
			order["guest_name"] = names.get(order["guest"], "")

	return {
		"property": property_name,
		"orders": orders,
		"summary": {
			"open": sum(1 for o in orders if o["order_status"] in OPEN_ORDER_STATES),
			"placed": sum(1 for o in orders if o["order_status"] == "Placed"),
			"preparing": sum(1 for o in orders if o["order_status"] == "Preparing"),
			"ready": sum(1 for o in orders if o["order_status"] == "Ready"),
			"delivered": sum(1 for o in orders if o["order_status"] == "Delivered"),
			"open_value": flt(
				sum(flt(o["total_amount"]) for o in orders if o["order_status"] in OPEN_ORDER_STATES), 2
			),
		},
	}
