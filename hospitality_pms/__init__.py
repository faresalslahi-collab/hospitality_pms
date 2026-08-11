__version__ = "16.6.3"


def check_app_permission() -> bool:
	"""Decide whether this user sees Hospitality PMS on the Desk apps screen.

	Frappe calls this from `add_to_apps_screen`. It governs visibility of the
	tile only -- every endpoint, DocType and service re-checks permissions
	server side regardless of what the apps screen chose to show.

	A hotel's Frappe site usually carries staff who have nothing to do with the
	property: accounts users on ERPNext alone, website users, integration
	accounts. Showing them a Hospitality PMS tile that opens onto a screen they
	cannot use is worse than not showing it at all, so the tile is offered only
	to users who actually hold a PMS role.
	"""
	import frappe

	if frappe.session.user == "Administrator":
		return True

	from frappe.utils.user import is_website_user

	if is_website_user():
		return False

	from hospitality_pms.setup.roles import ADMIN, PMS_ROLES

	# ADMIN carries "System Manager", which is not a PMS role but does
	# administer this app -- an administrator setting the property up needs the
	# tile before any hospitality role has been granted to anyone.
	permitted = set(PMS_ROLES) | set(ADMIN)

	return bool(permitted.intersection(frappe.get_roles()))
