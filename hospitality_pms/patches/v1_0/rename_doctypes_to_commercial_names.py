"""Drop the redundant "Hospitality" prefix from PMS DocType names.

"Hospitality PMS" is the product. The entities inside it are Property, Guest,
Reservation, Stay, Guest Folio -- what the trade calls them and what the SAD
already specifies (see CLAUDE.md: "DocType names follow SAD section 7 verbatim,
no prefix"). The prefix survived on 76 DocTypes and made every list view,
link picker and workspace card read like a filing cabinet.

Runs in pre_model_sync so the tables, link values and dynamic links move before
`bench migrate` imports the renamed JSON definitions from disk. Doing it the
other way round would leave the old tables orphaned and create empty new ones.

`frappe.rename_doc` is the supported mechanism and does the parts that matter:
RENAME TABLE, Link/Table field options, parenttype on child rows, link *values*
across every referencing DocType, dynamic links, Custom DocPerm, attachments,
Version rows and saved user list settings. It skips the on-disk file moves
because `frappe.flags.in_patch` is set here -- correct, since the app source
already ships the renamed folders.

Idempotent: a name already renamed is skipped, so re-running migrate is safe,
and a fresh install (where no old DocType ever existed) is a no-op.
"""

import frappe

# The model-level helper, not the `frappe.rename_doc` shortcut: only this one
# takes `ignore_permissions`, and a patch has no interactive user to check.
from frappe.model.rename_doc import rename_doc

#: Old name -> new name. Five DocTypes keep their name and are not listed:
#: Hotel Room, Room Type, Reservation Room, Reservation Guest and
#: Reservation Rate Line.
#:
#: Six keep a qualifier on purpose:
#:   Property Department  -- ERPNext already ships "Department"
#:   Property Shift / Day -- Frappe HR ships the "Shift *" family
#:   PMS Settings         -- follows the "System Settings" convention
#:   PMS Integration Log / PMS Integration Failure Queue
#:                        -- Frappe ships "Integration Request"; bare names sit
#:                           one word away from it in every search box
RENAMES = {
	# Setup
	"Hospitality Property": "Property",
	"Hospitality Property Fee": "Property Fee",
	"Hospitality Property Language": "Property Language",
	"Hospitality Property Warehouse": "Property Warehouse",
	"Hospitality Building": "Building",
	"Hospitality Wing": "Wing",
	"Hospitality Floor": "Floor",
	"Hospitality Zone": "Zone",
	"Hospitality Department": "Property Department",
	"Hospitality Shift": "Property Shift",
	"Hospitality Shift Day": "Property Shift Day",
	"Hospitality Settings": "PMS Settings",
	# Rooms
	"Hospitality Room Block": "Room Block",
	"Hospitality Room Status Log": "Room Status Log",
	"Hospitality Room Feature": "Room Feature",
	"Hospitality Connecting Room": "Connecting Room",
	"Hospitality Room Type Amenity": "Room Type Amenity",
	# Guests
	"Hospitality Guest": "Guest",
	"Hospitality Guest Identification": "Guest Identification",
	"Hospitality Guest Preference": "Guest Preference",
	"Hospitality Guest Consent": "Guest Consent",
	"Hospitality Guest Alert": "Guest Alert",
	"Hospitality Guest Merge Log": "Guest Merge Log",
	# Rates
	"Hospitality Rate Plan": "Rate Plan",
	"Hospitality Rate Plan Room Type": "Rate Plan Room Type",
	"Hospitality Daily Rate": "Daily Rate",
	"Hospitality Rate Policy": "Rate Policy",
	"Hospitality Rate Restriction": "Rate Restriction",
	"Hospitality Room Inventory Restriction": "Room Inventory Restriction",
	# Reservations
	"Hotel Reservation": "Reservation",
	"Hospitality Reservation Log": "Reservation Log",
	# Front Office
	"Hospitality Stay": "Stay",
	"Hospitality Stay Companion": "Stay Companion",
	"Hospitality Stay Note": "Stay Note",
	"Hospitality Room Move": "Room Move",
	# Folio
	"Hospitality Guest Folio": "Guest Folio",
	"Hospitality Folio Charge": "Folio Charge",
	"Hospitality Folio Payment": "Folio Payment",
	"Hospitality Folio Log": "Folio Log",
	"Hospitality Posting Profile": "Posting Profile",
	"Hospitality Financial Posting Log": "Financial Posting Log",
	"Hospitality Charge Item Map": "Charge Item Map",
	# Night Audit
	"Hospitality Night Audit": "Night Audit",
	"Hospitality Night Audit Exception": "Night Audit Exception",
	# Housekeeping
	"Hospitality Housekeeping Task": "Housekeeping Task",
	"Hospitality Room Inspection": "Room Inspection",
	# Maintenance
	"Hospitality Maintenance Ticket": "Maintenance Ticket",
	"Hospitality Maintenance Work Log": "Maintenance Work Log",
	# Sales
	"Hospitality Corporate Account": "Corporate Account",
	"Hospitality Corporate Contact": "Corporate Contact",
	"Hospitality Corporate Rate": "Corporate Rate",
	"Hospitality Corporate Credit Log": "Corporate Credit Log",
	"Hospitality Group Reservation": "Group Reservation",
	"Hospitality Group Block Line": "Group Block Line",
	"Hospitality Rooming List Entry": "Rooming List Entry",
	# Services
	"Hospitality Guest Request": "Guest Request",
	"Hospitality Guest Request Log": "Guest Request Log",
	"Hospitality Room Service Order": "Room Service Order",
	"Hospitality Order Line": "Room Service Order Line",
	"Hospitality Menu Item": "Menu Item",
	"Hospitality Kitchen Requisition": "Kitchen Requisition",
	"Hospitality Requisition Line": "Kitchen Requisition Line",
	"Hospitality Wastage Entry": "Wastage Entry",
	# Integrations
	"Hospitality Channel": "Booking Channel",
	"Hospitality Channel Reservation": "Channel Reservation",
	"Hospitality Channel Room Mapping": "Channel Room Mapping",
	"Hospitality Channel Sync Log": "Channel Sync Log",
	"Hospitality Payment Provider": "Payment Provider",
	"Hospitality Payment Transaction": "Payment Transaction",
	"Hospitality Hardware Device": "Hardware Device",
	"Hospitality Key Card": "Key Card",
	"Hospitality Integration Request Log": "PMS Integration Log",
	"Hospitality Integration Failure Queue": "PMS Integration Failure Queue",
	"Hospitality Regulatory Export": "Regulatory Export",
	"Hospitality Regulatory Profile": "Regulatory Profile",
	"Hospitality Guest Registration": "Guest Registration",
}


def execute():
	renamed = 0

	for old, new in RENAMES.items():
		if not frappe.db.exists("DocType", old):
			# Already renamed, or a fresh install that never had the old name.
			continue

		if frappe.db.exists("DocType", new):
			frappe.log_error(
				title="PMS rename skipped",
				message=f"Both {old!r} and {new!r} exist; refusing to merge. Resolve by hand.",
			)
			continue

		rename_doc(
			doctype="DocType",
			old=old,
			new=new,
			force=True,
			ignore_permissions=True,
			show_alert=False,
			rebuild_search=False,
		)
		renamed += 1

	if renamed:
		rename_naming_series_property_setters()
		frappe.clear_cache()

	print(f"hospitality_pms: renamed {renamed} DocTypes to commercial names")


def rename_naming_series_property_setters():
	"""Re-key naming-series Property Setters onto the new DocType names.

	`rename_doc` updates `doc_type` because it is a Link field, but a Property
	Setter's *name* embeds the DocType -- "Hospitality Key Card-naming_series-
	options". Left stale, `make_property_setter` would not find the existing row
	and would insert a duplicate the next time anyone touches the naming series.
	"""
	for old, new in RENAMES.items():
		for ps in frappe.get_all(
			"Property Setter",
			filters={"doc_type": new, "name": ["like", f"{old}-%"]},
			pluck="name",
		):
			target = new + ps[len(old) :]
			if frappe.db.exists("Property Setter", target):
				frappe.delete_doc("Property Setter", ps, force=True, ignore_permissions=True)
			else:
				rename_doc(
					doctype="Property Setter",
					old=ps,
					new=target,
					force=True,
					ignore_permissions=True,
					show_alert=False,
					rebuild_search=False,
				)
