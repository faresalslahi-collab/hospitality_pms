"""Install and migrate hooks for Hospitality PMS.

Everything performed here must be idempotent: `install-app`, `migrate` and
re-installation on an existing site must all converge to the same state.
"""

import frappe


def after_install():
	"""Run once when the app is installed on a site."""
	sync_module_defs()
	sync_roles()


def after_migrate():
	"""Run after every `bench migrate`.

	Module Defs are only created by the framework at install time, so a module
	added to `modules.txt` in a later build would never appear on a site that is
	upgraded rather than freshly installed. Syncing here keeps every bench
	reproducible from the repository alone.
	"""
	sync_module_defs()
	sync_roles()


def sync_roles():
	"""Create the approved PMS roles and correct their desk access.

	Frappe auto-creates any role a DocType JSON references, always with desk
	access enabled, so this has to run after the DocType sync to put the
	operational roles back to frontend-only.
	"""
	from hospitality_pms.setup.roles import create_roles

	create_roles()
	frappe.db.commit()


def before_uninstall():
	"""Run before the app is removed from a site.

	Operational and financial records are retained per the approved data
	retention policy (SAS section 8); nothing is destroyed here.
	"""
	pass


def sync_module_defs():
	"""Create Module Def records for every module declared in `modules.txt`.

	Modules that the app no longer declares are removed only when nothing
	references them, so a stale Module Def can never take DocTypes with it.
	"""
	declared = set(frappe.get_module_list("hospitality_pms"))

	existing = set(
		frappe.get_all(
			"Module Def",
			filters={"app_name": "hospitality_pms"},
			pluck="name",
		)
	)

	for module in sorted(declared - existing):
		doc = frappe.new_doc("Module Def")
		doc.app_name = "hospitality_pms"
		doc.module_name = module
		doc.insert(ignore_permissions=True, ignore_if_duplicate=True)

	for module in sorted(existing - declared):
		if frappe.db.exists("DocType", {"module": module}):
			continue

		frappe.delete_doc("Module Def", module, ignore_permissions=True, force=True)

	frappe.db.commit()
