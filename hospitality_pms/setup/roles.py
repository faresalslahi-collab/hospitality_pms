"""Create and maintain the Hospitality PMS Role records.

Source of truth: `docs/hospitality-pms/06_Hospitality_PMS_Roles_and_Permissions_
Matrix_v1.2_APPROVED.md`, section 1. `System Manager` is a Frappe built-in
role and is deliberately excluded from `PMS_ROLES` below -- this module must
never create, rename or modify it.

A note on `desk_access`: it only controls whether a user can open `/app`
(the Frappe Desk). It is a UX convenience, not a security boundary. Setting
it to 0 for operational roles hides the Desk from users who only ever work
in the `/pms` Vue frontend; it grants and revokes nothing on its own. The
real enforcement boundary is DocType permissions (Role Permission Manager /
`permissions.json` on each DocType) and the checks inside the whitelisted
API (see `services.base.require_permission()` / `require_role()`). A role
with `desk_access = 0` can still be as privileged, or as restricted, as its
DocType permissions say.
"""

import frappe

# Declarative role table: name -> {desk_access, description}.
#
# `description` documents the role for maintainers and is not written to the
# Role record: Frappe's Role DocType has no description field. It stays here so
# the intent of each role is readable next to its access decision.
#
# Frappe auto-creates a Role the first time a DocType JSON lists it in
# `permissions`, and an auto-created Role always gets `desk_access = 1`
# regardless of what this table says. That means, in practice, the main job
# of `create_roles()` is not "create" but "correct `desk_access` back to
# what the approved matrix requires" for the operational roles below.
PMS_ROLES = {
	"Hospitality Administrator": {
		"desk_access": 1,
		"description": "Configures property setup, integrations and app-wide policy; the top administrative role for the PMS app.",
	},
	"General Manager": {
		"desk_access": 1,
		"description": "Oversees the property; approves business policy, exceptions and major overrides across departments.",
	},
	"Hotel Manager": {
		"desk_access": 1,
		"description": "Runs day-to-day hotel operations; approves front office, housekeeping and maintenance exceptions.",
	},
	"Front Office Manager": {
		"desk_access": 1,
		"description": "Supervises front office; approves rate overrides, room changes and checkout exceptions.",
	},
	"Front Office Agent": {
		"desk_access": 0,
		"description": "Handles check-in, check-out, folio and guest-service tasks from the /pms frontend.",
	},
	"Reservation Manager": {
		"desk_access": 1,
		"description": "Oversees reservations and approves rate/policy exceptions for the reservations team.",
	},
	"Reservation Agent": {
		"desk_access": 0,
		"description": "Creates and manages bookings from the /pms frontend.",
	},
	"Revenue Manager": {
		"desk_access": 1,
		"description": "Owns rate plans, pricing strategy and rate-override policy.",
	},
	"Housekeeping Manager": {
		"desk_access": 1,
		"description": "Oversees housekeeping operations, inspections and room-status release.",
	},
	"Housekeeping Supervisor": {
		"desk_access": 1,
		"description": "Supervises room attendants; inspects and releases rooms after cleaning.",
	},
	"Room Attendant": {
		"desk_access": 0,
		"description": "Updates room cleaning status and task progress from the /pms frontend.",
	},
	"Maintenance Manager": {
		"desk_access": 1,
		"description": "Oversees maintenance operations and releases out-of-order/out-of-service rooms.",
	},
	"Maintenance Technician": {
		"desk_access": 0,
		"description": "Executes maintenance work orders from the /pms frontend.",
	},
	"Food and Beverage Manager": {
		"desk_access": 1,
		"description": "Oversees Food and Beverage operations, kitchen and outlet exceptions.",
	},
	"Kitchen Manager": {
		"desk_access": 1,
		"description": "Oversees kitchen operations and approves wastage/exception cases.",
	},
	"Kitchen User": {
		"desk_access": 0,
		"description": "Handles kitchen order and preparation tasks from the /pms frontend.",
	},
	"Corporate Sales Manager": {
		"desk_access": 1,
		"description": "Manages corporate accounts, contracted rates and corporate-credit exceptions.",
	},
	"Guest Relations Officer": {
		"desk_access": 0,
		"description": "Handles guest-relations tasks and requests from the /pms frontend.",
	},
	"Night Auditor": {
		"desk_access": 1,
		"description": "Performs the night-audit close and reconciliation; requests audit reopen.",
	},
	"Finance Manager": {
		"desk_access": 1,
		"description": "Approves financial posting, folio adjustments, reversals and audit exceptions.",
	},
	"Accounts User": {
		"desk_access": 1,
		"description": "Processes financial postings and routine accounting entries.",
	},
	"Read-Only Auditor": {
		"desk_access": 1,
		"description": "Reviews records and audit trails for compliance; holds no write access per the approved matrix.",
	},
}


def get_pms_roles() -> list[str]:
	"""Return the declared Hospitality PMS role names.

	Other modules should import this rather than re-listing role names, so
	the approved matrix stays the single source of truth.
	"""
	return list(PMS_ROLES.keys())


def get_operational_roles() -> list[str]:
	"""Return the declared roles with `desk_access = 0`.

	These are the roles whose users work only in the /pms Vue frontend.
	"""
	return [role for role, meta in PMS_ROLES.items() if meta["desk_access"] == 0]


def create_roles() -> None:
	"""Create/correct the declared Hospitality PMS roles. Idempotent.

	- Creates any Role from `PMS_ROLES` that does not yet exist.
	- For an existing Role, updates `desk_access` only when it differs from
	  the declared value, and saves only then -- running this on every
	  migrate must not create a document version when nothing changed.
	- Never touches `System Manager` or any role not declared above.
	- Never deletes a Role: an operator may already have users assigned to
	  it, and removing it would strand those assignments.

	Transaction control (commit) is left to the caller, matching the
	pattern in `install.py::sync_module_defs()`.
	"""
	created = []
	updated = []

	for role_name, meta in PMS_ROLES.items():
		if not frappe.db.exists("Role", role_name):
			doc = frappe.new_doc("Role")
			doc.role_name = role_name
			doc.desk_access = meta["desk_access"]
			doc.insert(ignore_permissions=True)
			created.append(role_name)
			continue

		doc = frappe.get_doc("Role", role_name)
		dirty = False

		# Frappe stores desk_access as 0/1; compare as int to avoid a
		# false "changed" on truthy-but-not-equal values (e.g. "1" vs 1).
		if int(doc.desk_access or 0) != int(meta["desk_access"]):
			doc.desk_access = meta["desk_access"]
			dirty = True

		if dirty:
			doc.save(ignore_permissions=True)
			updated.append(role_name)

	if created:
		print(f"Hospitality PMS roles created: {', '.join(sorted(created))}")
	if updated:
		print(f"Hospitality PMS roles updated: {', '.join(sorted(updated))}")
	if not created and not updated:
		print("Hospitality PMS roles: nothing to do, already in sync.")


# ---------------------------------------------------------------------------
# Role groups
# ---------------------------------------------------------------------------
# Named groups used by the permission matrix and by services that gate an
# action on a role family. Defined once here so a role never has to be spelled
# out in two places and drift.

ADMIN = ["Hospitality Administrator", "System Manager"]
MANAGEMENT = ["General Manager", "Hotel Manager"]
FRONT_OFFICE = ["Front Office Manager", "Front Office Agent"]
RESERVATIONS = ["Reservation Manager", "Reservation Agent"]
REVENUE = ["Revenue Manager"]
HOUSEKEEPING = ["Housekeeping Manager", "Housekeeping Supervisor", "Room Attendant"]
MAINTENANCE = ["Maintenance Manager", "Maintenance Technician"]
FNB = ["Food and Beverage Manager", "Kitchen Manager", "Kitchen User"]
SALES = ["Corporate Sales Manager"]
GUEST_RELATIONS = ["Guest Relations Officer"]
NIGHT_AUDIT = ["Night Auditor"]
FINANCE = ["Finance Manager", "Accounts User"]
AUDITOR = ["Read-Only Auditor"]

#: Every role that operates inside a property. Used for records that all
#: operational screens have to read, such as the property itself.
OPERATIONAL = (
	MANAGEMENT
	+ FRONT_OFFICE
	+ RESERVATIONS
	+ REVENUE
	+ HOUSEKEEPING
	+ MAINTENANCE
	+ FNB
	+ SALES
	+ GUEST_RELATIONS
	+ NIGHT_AUDIT
	+ FINANCE
)

#: Roles that may see records the Roles Matrix section 5 classes as technical
#: (status logs, posting logs, integration logs, failure queues).
TECHNICAL_READERS = ADMIN + MANAGEMENT + NIGHT_AUDIT + AUDITOR
