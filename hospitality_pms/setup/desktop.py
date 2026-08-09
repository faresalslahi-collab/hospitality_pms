"""Keep the Hospitality PMS tile visible on the Desk apps screen.

Creating the `Desktop Icon` is not enough on a site that has been used before.
Frappe v16's apps screen (`frappe/desk/page/desktop/desktop.js`) prefers a
saved `Desktop Layout` over `boot.desktop_icons` *wholesale*: once a user has
arranged their screen, the stored snapshot becomes the entire icon list and no
later icon -- ours or anyone's -- can reach that user. An operator who set up
their Desk before this app was installed would therefore never see the tile,
however correct the icon record is.

This reconciles the two: every stored layout that has never heard of the tile
gets it appended. A layout that already lists it is left exactly as it is,
hidden or not, because at that point the arrangement is the user's decision.
"""

import json

import frappe

ICON_LABEL = "Hospitality PMS"

# The shape `desktop.js` expects of an entry in a saved layout: the Desktop Icon
# fields that `get_desktop_icons()` puts into boot, plus `child_icons`.
ICON_FIELDS = (
	"name",
	"label",
	"bg_color",
	"link",
	"link_type",
	"app",
	"icon_type",
	"parent_icon",
	"icon",
	"link_to",
	"idx",
	"standard",
	"logo_url",
	"hidden",
	"restrict_removal",
	"icon_image",
)


def sync_desktop_presence():
	"""Repair every saved Desk layout that predates the Hospitality PMS tile."""
	icon = frappe.db.get_value("Desktop Icon", ICON_LABEL, ICON_FIELDS, as_dict=True)

	if not icon:
		# `bench migrate` imports desktop_icon/hospitality_pms.json before app
		# hooks run. No icon here means that sync did not happen, and inventing
		# one from this side would only mask the real failure.
		return

	users = frappe.get_all("Desktop Layout", pluck="name")
	repaired = [user for user in users if add_icon_to_layout(user, icon)]

	if repaired:
		frappe.db.commit()

	# Both the per-user icon list and the bootinfo that carries it are cached.
	frappe.cache.delete_key("desktop_icons")
	frappe.cache.delete_key("bootinfo")

	return repaired


def add_icon_to_layout(user, icon):
	"""Append `icon` to one user's stored layout. Return True if it changed."""
	layout = frappe.db.get_value("Desktop Layout", user, "layout")

	if not layout:
		return False

	try:
		icons = json.loads(layout)
	except ValueError:
		# A layout we cannot read is a layout we must not rewrite.
		return False

	if not isinstance(icons, list) or layout_contains(icons, ICON_LABEL):
		return False

	entry = dict(icon)
	entry["child_icons"] = []
	# Last on the screen: an app added after the fact does not get to push
	# aside the arrangement the user already has.
	entry["idx"] = max((i.get("idx") or 0 for i in icons), default=0) + 1

	icons.append(entry)
	frappe.db.set_value("Desktop Layout", user, "layout", json.dumps(icons), update_modified=False)

	return True


def layout_contains(icons, label):
	"""Whether `label` appears anywhere in a layout, including inside folders."""
	for icon in icons:
		if icon.get("label") == label:
			return True

		if layout_contains(icon.get("child_icons") or [], label):
			return True

	return False
