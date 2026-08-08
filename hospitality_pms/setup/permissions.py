"""The approved role permission matrix, expressed once, in the repository.

Permissions are stored in each DocType's JSON, which is the upgrade-safe place
for them: Custom DocPerm records are discarded by `bench migrate`.

`apply_permissions()` writes this matrix into those JSON files. It is a
development-time maintenance command, not a runtime hook - the JSON it produces
is the artifact that ships:

    bench --site <site> execute hospitality_pms.setup.permissions.apply_permissions

Run it whenever the matrix below changes, then commit the resulting JSON.
"""

import frappe

from hospitality_pms.setup.roles import (
	ADMIN,
	AUDITOR,
	FINANCE,
	FRONT_OFFICE,
	GUEST_RELATIONS,
	MANAGEMENT,
	NIGHT_AUDIT,
	OPERATIONAL,
	RESERVATIONS,
	REVENUE,
	SALES,
	TECHNICAL_READERS,
)
from hospitality_pms.setup.roles import FNB
from hospitality_pms.setup.roles import HOUSEKEEPING as HK
from hospitality_pms.setup.roles import MAINTENANCE as MTN

# ---------------------------------------------------------------------------
# Permission row builders
# ---------------------------------------------------------------------------


def read_only(role: str, permlevel: int = 0) -> dict:
	return {
		"role": role,
		"permlevel": permlevel,
		"read": 1,
		"write": 0,
		"create": 0,
		"delete": 0,
		"submit": 0,
		"cancel": 0,
		"amend": 0,
		"report": 1,
		"export": 0,
		"share": 0,
		"print": 1,
		"email": 0,
	}


def writer(role: str, permlevel: int = 0, delete: int = 0, submit: int = 0) -> dict:
	row = read_only(role, permlevel)
	row.update(
		{
			"write": 1,
			"create": 1,
			"delete": delete,
			"submit": submit,
			"cancel": submit,
			"amend": submit,
			"export": 1,
			"share": 1,
			"email": 1,
		}
	)
	return row


def auditor_row(role: str = "Read-Only Auditor") -> dict:
	"""The auditor reads and extracts, and can never change anything."""
	row = read_only(role)
	row["export"] = 1
	return row


def build(
	readers=(),
	writers=(),
	submitters=(),
	deleters=(),
	level_one_readers=(),
	level_one_writers=(),
	level_two_readers=(),
	level_two_writers=(),
	level_three_readers=(),
	level_three_writers=(),
) -> list[dict]:
	"""Compose a permission list. The strongest grant for a role wins."""
	rows: dict[tuple[str, int], dict] = {}

	for role in readers:
		rows[(role, 0)] = read_only(role)
	for role in writers:
		rows[(role, 0)] = writer(role)
	for role in submitters:
		rows[(role, 0)] = writer(role, submit=1)
	for role in deleters:
		rows[(role, 0)] = writer(role, delete=1, submit=1 if role in submitters else 0)

	for role in level_one_readers:
		rows[(role, 1)] = read_only(role, permlevel=1)
	for role in level_one_writers:
		rows[(role, 1)] = writer(role, permlevel=1)
	for role in level_two_readers:
		rows[(role, 2)] = read_only(role, permlevel=2)
	for role in level_two_writers:
		rows[(role, 2)] = writer(role, permlevel=2)
	for role in level_three_readers:
		rows[(role, 3)] = read_only(role, permlevel=3)
	for role in level_three_writers:
		rows[(role, 3)] = writer(role, permlevel=3)

	rows[("Read-Only Auditor", 0)] = auditor_row()

	return list(rows.values())


# ---------------------------------------------------------------------------
# Matrix
# ---------------------------------------------------------------------------

GUEST_HANDLERS = FRONT_OFFICE + RESERVATIONS + GUEST_RELATIONS
GUEST_READERS = GUEST_HANDLERS + MANAGEMENT + NIGHT_AUDIT + FINANCE + AUDITOR

#: Roles that may see and record guest identification documents. Deliberately
#: narrow: housekeeping, maintenance and kitchen never need passport data.
ID_WRITERS = FRONT_OFFICE + ["Reservation Manager"] + GUEST_RELATIONS + MANAGEMENT + ADMIN
ID_READERS = ID_WRITERS + NIGHT_AUDIT + FINANCE + AUDITOR

#: Blacklisting requires elevated approval (Roles Matrix section 4), but the
#: front desk has to see the flag or it cannot refuse a check-in. So the flag
#: and the reason sit at different levels: everyone serving guests sees THAT a
#: guest is blacklisted; only the roles that set it see WHY, because the reason
#: can carry incident detail that has no business on a front desk screen.
BLACKLIST_WRITERS = ["Hotel Manager", "General Manager", "Guest Relations Officer", *ADMIN]
BLACKLIST_READERS = BLACKLIST_WRITERS + FRONT_OFFICE + RESERVATIONS + NIGHT_AUDIT + AUDITOR
BLACKLIST_REASON_READERS = BLACKLIST_WRITERS + AUDITOR

MATRIX = {
	# --- Setup ------------------------------------------------------------
	"Hospitality Property": build(
		readers=OPERATIONAL + AUDITOR,
		writers=["Hospitality Administrator"],
		deleters=["System Manager"],
		# Permlevel 1 guards the accounting mapping: a wrong account here
		# misdirects every future posting.
		level_one_readers=["Accounts User", "Read-Only Auditor", *MANAGEMENT],
		level_one_writers=["Finance Manager", *ADMIN],
	),
	"Hospitality Settings": build(readers=MANAGEMENT + AUDITOR, writers=ADMIN),
	"Hospitality Building": build(readers=OPERATIONAL + AUDITOR, deleters=ADMIN),
	"Hospitality Wing": build(readers=OPERATIONAL + AUDITOR, deleters=ADMIN),
	"Hospitality Floor": build(readers=OPERATIONAL + AUDITOR, deleters=ADMIN),
	"Hospitality Zone": build(readers=OPERATIONAL + AUDITOR, deleters=ADMIN),
	"Hospitality Department": build(readers=OPERATIONAL + AUDITOR, writers=MANAGEMENT, deleters=ADMIN),
	"Hospitality Shift": build(readers=OPERATIONAL + AUDITOR, writers=MANAGEMENT, deleters=ADMIN),
	# --- Rooms ------------------------------------------------------------
	# Room configuration is commercial: revenue and management own it.
	"Room Type": build(
		readers=OPERATIONAL + AUDITOR,
		writers=REVENUE + MANAGEMENT,
		deleters=ADMIN,
	),
	# Front office, housekeeping and maintenance managers maintain rooms.
	# Status changes do not need write here: the API gates each dimension on
	# its own role family and the service writes the field directly.
	"Hotel Room": build(
		readers=OPERATIONAL + AUDITOR,
		writers=["Front Office Manager", "Housekeeping Manager", "Maintenance Manager", *MANAGEMENT],
		deleters=ADMIN,
	),
	"Hospitality Room Block": build(
		readers=OPERATIONAL + AUDITOR,
		submitters=[
			"Front Office Manager",
			"Housekeeping Manager",
			"Maintenance Manager",
			"Revenue Manager",
			"Reservation Manager",
			*MANAGEMENT,
		],
		deleters=ADMIN,
	),
	# Technical record (Roles Matrix section 5): hidden from ordinary
	# operational users and never written through the UI.
	"Hospitality Room Status Log": build(readers=TECHNICAL_READERS + HK[:2] + MTN[:1]),
	# --- Guests -----------------------------------------------------------
	"Hospitality Guest": build(
		readers=GUEST_READERS,
		writers=GUEST_HANDLERS + MANAGEMENT,
		deleters=ADMIN,
		level_one_readers=ID_READERS,
		level_one_writers=ID_WRITERS,
		level_two_readers=BLACKLIST_READERS,
		level_two_writers=BLACKLIST_WRITERS,
		level_three_readers=BLACKLIST_REASON_READERS,
		level_three_writers=BLACKLIST_WRITERS,
	),
	"Hospitality Guest Merge Log": build(readers=TECHNICAL_READERS + ["Guest Relations Officer"]),
	# --- Rates ------------------------------------------------------------
	# Revenue owns pricing; everyone who quotes a guest has to read it.
	"Hospitality Rate Plan": build(
		readers=OPERATIONAL + AUDITOR,
		writers=REVENUE + MANAGEMENT,
		deleters=ADMIN,
	),
	"Hospitality Rate Policy": build(
		readers=OPERATIONAL + AUDITOR,
		writers=REVENUE + MANAGEMENT + ["Finance Manager"],
		deleters=ADMIN,
	),
	"Hospitality Daily Rate": build(
		readers=OPERATIONAL + AUDITOR,
		writers=REVENUE + ["Reservation Manager", *MANAGEMENT],
		deleters=ADMIN,
	),
	"Hospitality Room Inventory Restriction": build(
		readers=OPERATIONAL + AUDITOR,
		writers=REVENUE + ["Reservation Manager", "Front Office Manager", *MANAGEMENT],
		deleters=ADMIN,
	),
	# --- Reservations -----------------------------------------------------
	# Reservations and front office create and work bookings. Housekeeping and
	# maintenance read them, because arrivals drive cleaning priority.
	"Hotel Reservation": build(
		readers=OPERATIONAL + AUDITOR,
		writers=RESERVATIONS + FRONT_OFFICE + GUEST_RELATIONS + MANAGEMENT,
		deleters=ADMIN,
	),
	"Hospitality Reservation Log": build(
		readers=TECHNICAL_READERS + RESERVATIONS + ["Front Office Manager"]
	),
	# --- Front office and folio ------------------------------------------
	"Hospitality Stay": build(
		readers=OPERATIONAL + AUDITOR,
		writers=FRONT_OFFICE + GUEST_RELATIONS + MANAGEMENT,
		deleters=ADMIN,
	),
	# The folio is the operational subledger. Front office works it; finance
	# corrects it. Nobody deletes from it - corrections are reversals.
	"Hospitality Guest Folio": build(
		readers=FRONT_OFFICE + RESERVATIONS + GUEST_RELATIONS + MANAGEMENT + FINANCE + NIGHT_AUDIT + AUDITOR,
		writers=FRONT_OFFICE + FINANCE + MANAGEMENT + NIGHT_AUDIT,
		deleters=ADMIN,
	),
	"Hospitality Folio Log": build(readers=TECHNICAL_READERS + FINANCE + ["Front Office Manager"]),
	# --- Posting and integrations -----------------------------------------
	# Posting configuration decides where every riyal lands, so it is finance
	# and administration only.
	"Hospitality Posting Profile": build(
		readers=MANAGEMENT + FINANCE + AUDITOR,
		writers=["Finance Manager", *ADMIN],
		deleters=ADMIN,
	),
	# Technical records (Roles Matrix section 5). Finance reads them to
	# reconcile; nobody edits them through the UI.
	"Hospitality Financial Posting Log": build(readers=TECHNICAL_READERS + FINANCE),
	"Hospitality Payment Provider": build(
		readers=["Finance Manager", *MANAGEMENT, *ADMIN, *AUDITOR],
		writers=ADMIN,
		deleters=ADMIN,
	),
	"Hospitality Payment Transaction": build(
		readers=FRONT_OFFICE + FINANCE + MANAGEMENT + NIGHT_AUDIT + AUDITOR,
		writers=["Front Office Manager", *FINANCE, *ADMIN],
	),
	"Hospitality Integration Request Log": build(readers=TECHNICAL_READERS),
	"Hospitality Integration Failure Queue": build(
		readers=TECHNICAL_READERS + FINANCE,
		writers=ADMIN,
	),
	# --- Night audit ------------------------------------------------------
	# The auditor runs it; finance and management review it; nobody else edits
	# a closed business date.
	"Hospitality Night Audit": build(
		readers=OPERATIONAL + AUDITOR,
		writers=NIGHT_AUDIT + ["Finance Manager", *MANAGEMENT],
		deleters=ADMIN,
	),
	# --- Housekeeping -----------------------------------------------------
	# Attendants work their own tasks, so they need write; the service still
	# gates inspection sign-off on a supervisor role.
	"Hospitality Housekeeping Task": build(
		readers=OPERATIONAL + AUDITOR,
		writers=HK + ["Front Office Manager", *MANAGEMENT],
		deleters=ADMIN,
	),
	"Hospitality Room Inspection": build(
		readers=OPERATIONAL + AUDITOR,
		writers=["Housekeeping Supervisor", "Housekeeping Manager", *MANAGEMENT],
		deleters=ADMIN,
	),
	# --- Maintenance ------------------------------------------------------
	# Anyone operational can raise a ticket - housekeeping finds most faults -
	# but taking a room out of service is gated on a manager in the service.
	"Hospitality Maintenance Ticket": build(
		readers=OPERATIONAL + AUDITOR,
		writers=MTN + HK + ["Front Office Manager", *MANAGEMENT],
		deleters=ADMIN,
	),
	# --- Corporate and groups ---------------------------------------------
	# Sales owns the account; finance owns the credit decision, which is why
	# credit status changes are gated in the service rather than by write.
	"Hospitality Corporate Account": build(
		readers=OPERATIONAL + AUDITOR,
		writers=SALES + ["Reservation Manager", *FINANCE, *MANAGEMENT],
		deleters=ADMIN,
	),
	"Hospitality Corporate Credit Log": build(readers=TECHNICAL_READERS + FINANCE + SALES),
	"Hospitality Group Reservation": build(
		readers=OPERATIONAL + AUDITOR,
		writers=SALES + RESERVATIONS + ["Front Office Manager", *MANAGEMENT],
		deleters=ADMIN,
	),
	# --- Guest services ---------------------------------------------------
	# Anyone serving a guest can raise and work a request; compensation is
	# gated on a role inside the service.
	"Hospitality Guest Request": build(
		readers=OPERATIONAL + AUDITOR,
		writers=FRONT_OFFICE + GUEST_RELATIONS + HK + MTN + FNB + MANAGEMENT,
		deleters=ADMIN,
	),
	"Hospitality Guest Request Log": build(
		readers=TECHNICAL_READERS + GUEST_RELATIONS + ["Front Office Manager"]
	),
	# --- Kitchen, room service, minibar -----------------------------------
	"Hospitality Menu Item": build(
		readers=OPERATIONAL + AUDITOR,
		writers=FNB + MANAGEMENT,
		deleters=ADMIN,
	),
	"Hospitality Kitchen Requisition": build(
		readers=FNB + MANAGEMENT + FINANCE + AUDITOR,
		writers=FNB + MANAGEMENT,
		deleters=ADMIN,
	),
	"Hospitality Room Service Order": build(
		readers=OPERATIONAL + AUDITOR,
		writers=FNB + FRONT_OFFICE + MANAGEMENT,
		deleters=ADMIN,
	),
	"Hospitality Wastage Entry": build(
		readers=FNB + MANAGEMENT + FINANCE + AUDITOR,
		writers=["Kitchen Manager", "Food and Beverage Manager", *MANAGEMENT],
		deleters=ADMIN,
	),
	# --- Channel, hardware, regulatory ------------------------------------
	# Channel and device credentials are administrative; their logs are
	# technical records (Roles Matrix section 5).
	"Hospitality Channel": build(
		readers=["Revenue Manager", "Reservation Manager", *MANAGEMENT, *ADMIN, *AUDITOR],
		writers=ADMIN,
		deleters=ADMIN,
	),
	"Hospitality Channel Reservation": build(
		readers=TECHNICAL_READERS + RESERVATIONS + ["Revenue Manager"],
		writers=ADMIN,
	),
	"Hospitality Channel Sync Log": build(readers=TECHNICAL_READERS + ["Revenue Manager"]),
	"Hospitality Hardware Device": build(
		readers=["Front Office Manager", *MANAGEMENT, *ADMIN, *AUDITOR],
		writers=ADMIN,
		deleters=ADMIN,
	),
	"Hospitality Key Card": build(
		readers=FRONT_OFFICE + MANAGEMENT + AUDITOR + ADMIN,
		writers=FRONT_OFFICE + MANAGEMENT,
	),
	# Regulatory data is statutory and privacy sensitive: management, finance,
	# the night auditor and the auditor only.
	"Hospitality Regulatory Profile": build(
		readers=MANAGEMENT + FINANCE + AUDITOR + ADMIN,
		writers=ADMIN,
		deleters=ADMIN,
	),
	"Hospitality Regulatory Export": build(
		readers=MANAGEMENT + FINANCE + NIGHT_AUDIT + AUDITOR + ADMIN,
		writers=["Finance Manager", *NIGHT_AUDIT, *ADMIN],
	),
	"Hospitality Guest Registration": build(
		readers=FRONT_OFFICE + MANAGEMENT + NIGHT_AUDIT + AUDITOR + ADMIN,
		writers=FRONT_OFFICE + NIGHT_AUDIT + MANAGEMENT,
	),
}

#: Fields moved above permlevel 0. Everything that decides where money lands,
#: plus guest identification and blacklisting.
RESTRICTED_FIELDS = {
	"Hospitality Property": {
		1: (
			"receivable_account",
			"room_revenue_account",
			"deposit_liability_account",
			"default_tax_template",
		),
	},
	"Hospitality Guest": {
		1: ("identifications",),
		2: ("is_blacklisted", "blacklisted_by", "blacklisted_on"),
		3: ("blacklist_reason",),
	},
}


def apply_permissions():
	"""Write the matrix into the DocType JSON files."""
	for doctype, permissions in MATRIX.items():
		if not frappe.db.exists("DocType", doctype):
			print(f"skipped  {doctype} (not installed)")
			continue

		doc = frappe.get_doc("DocType", doctype)

		levels = RESTRICTED_FIELDS.get(doctype, {})
		by_field = {field: level for level, fields in levels.items() for field in fields}

		for field in doc.fields:
			target = by_field.get(field.fieldname, 0)
			if field.permlevel != target:
				field.permlevel = target

		doc.permissions = []
		for row in permissions:
			doc.append("permissions", row)

		doc.save()
		print(f"applied  {doctype}  ({len(permissions)} rows)")

	frappe.db.commit()
	print("permission matrix applied")
