"""Undo the ERPNext permissions the posting-service setup used to revoke.

Until 16.7.5-R1C, `setup/posting_service.py` granted the posting identity read on
`Sales Invoice`, `Account`, `Item` and `Customer` by inserting a bare
`Custom DocPerm` row for each. Frappe replaces a DocType's **entire** permission
list once any Custom DocPerm exists for it, so each of those four inserts did not
add a grant - it became the whole grant set, and every standard ERPNext
permission on that DocType stopped applying to every role.

Measured on the bench this patch was written for: **122** individual
`(role, permlevel, ptype)` grants gone. Accounts Manager and Accounts User lost
`Sales Invoice` and `Account` outright; `Item Manager`, `Stock Manager`,
`Stock User`, `Sales User`, `Purchase User`, `Maintenance User` and
`Manufacturing User` lost `Item`; `Sales Master Manager`, `Sales Manager`,
`Sales User` and the stock roles lost `Customer`. Even `All`'s permlevel-1 read on
`Sales Invoice` went. Any site that also runs ERPNext accounting or stock was
therefore quietly broken by installing this app.

The setup code no longer causes this - it goes through
`frappe.permissions.add_permission`, which copies the standard rows into
Custom DocPerm before adding its own. But a site that has already migrated lost
those rows before the fix existed, so stopping the damage is not the same as
undoing it. This patch undoes it, **once**.

Once, and deliberately not from `after_migrate`. The repair identifies our own
damage by its fingerprint: every Custom DocPerm on the parent belongs to the
posting service role. An operator who narrows one of these DocTypes down to
*only* the posting service - a locked-down finance site revoking Accounts User
from `Sales Invoice`, say - produces that same fingerprint, and a repair on every
migrate would re-grant the permissions they had just removed, for ever, with no
way to opt out. As a patch it runs before anyone has had the chance to express
such an intention, and never again afterwards.

Idempotent by the patch log, and idempotent in itself: re-running it after a
successful run finds many roles on each parent and declines.
"""

import frappe

from hospitality_pms.setup.posting_service import (
	POSTING_SERVICE_ROLE,
	SERVICE_PERMISSIONS,
	ensure_posting_service,
)


def execute():
	affected = [declared["doctype"] for declared in SERVICE_PERMISSIONS]

	before = {doctype: _missing_standard_grants(doctype) for doctype in affected}
	skipped = []

	for doctype in affected:
		roles = set(frappe.get_all("Custom DocPerm", filters={"parent": doctype}, pluck="role"))

		if roles - {POSTING_SERVICE_ROLE}:
			# Somebody's configuration, not our accident. Reported, never rewritten.
			skipped.append((doctype, sorted(roles - {POSTING_SERVICE_ROLE})))

	ensure_posting_service(repair=True)

	for doctype in affected:
		missing_before = before[doctype]
		missing_after = _missing_standard_grants(doctype)
		restored = len(missing_before) - len(missing_after)

		if restored:
			print(
				f"  Hospitality PMS: restored {restored} standard ERPNext permission "
				f"grant(s) on {doctype}"
			)

		if missing_after:
			print(
				f"  Hospitality PMS: {len(missing_after)} standard grant(s) on {doctype} "
				f"are still not in effect - review Custom DocPerm for this DocType"
			)

	for doctype, roles in skipped:
		print(
			f"  Hospitality PMS: left {doctype} permissions alone - custom rows exist "
			f"for {roles}, so this DocType is configured rather than damaged"
		)


def _missing_standard_grants(doctype: str) -> set:
	"""Standard grants that the effective permission set does not currently carry."""
	ptypes = [
		field.fieldname
		for field in frappe.get_meta("Custom DocPerm").fields
		if field.fieldtype == "Check" and field.fieldname != "if_owner"
	]

	def granted(table: str) -> set:
		rows = frappe.get_all(
			table,
			filters={"parent": doctype},
			fields=["role", "permlevel", "if_owner", *ptypes],
		)

		return {
			(row["role"], row["permlevel"], int(row.get("if_owner") or 0), ptype)
			for row in rows
			for ptype in ptypes
			if row.get(ptype)
		}

	standard = granted("DocPerm")

	# The same rule `Meta.set_custom_permissions` applies: custom rows replace the
	# standard set entirely when any exist.
	effective = (
		granted("Custom DocPerm")
		if frappe.db.exists("Custom DocPerm", {"parent": doctype})
		else standard
	)

	return standard - effective
