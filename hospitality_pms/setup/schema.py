"""Database constraints the DocType JSON cannot express.

Frappe's `unique` DocField flag makes a column unique across the whole table.
That is the wrong shape for a folio idempotency key, which must be unique
*within one folio*: two guests may each be charged under `minibar:water:1`
without either being a replay of the other.

A composite unique index is the only way to say that, so it is created here and
applied through every route a site can arrive by - fresh install, upgrade from
an earlier version, and repeated `bench migrate`.

Nothing in this module deletes or rewrites a financial row. If the data already
present would violate a constraint, it says so and stops.
"""

import frappe
from frappe import _

#: The financial child tables whose idempotency key must be unique per parent,
#: and the index name each one carries.
IDEMPOTENCY_CONSTRAINTS = {
	"Folio Charge": "unique_parent_idempotency_key",
	"Folio Payment": "unique_parent_idempotency_key",
}


def apply_all_constraints():
	"""Every database constraint this app adds. Idempotent."""
	apply_financial_idempotency_constraints()
	apply_night_audit_uniqueness()


def apply_night_audit_uniqueness():
	"""One Night Audit per property per business date, enforced by the database.

	A check-then-insert cannot promise this: two schedulers reading "no audit
	yet" at the same instant both create one, and a property with two audits for
	one date has two sets of figures, two exception lists and two ways to close
	(P2-1).

	Refuses rather than repairing if duplicates already exist. Which of two
	audits for one date is the real one - and what to do with the figures on the
	other - is a question for the hotel, not for a migration.
	"""
	table = "tabNight Audit"
	index = "unique_property_business_date"

	if not frappe.db.table_exists("Night Audit") or _index_exists(table, index):
		return

	duplicates = find_duplicate_audits()

	if duplicates:
		frappe.throw(
			_(
				"Night Audit cannot be made unique on (property, business date): {0} "
				"property/date combination(s) already have more than one audit. Nothing has been "
				"changed. Review them, close out the audits that should not exist, and run the "
				"migration again.\n\n{1}"
			).format(len(duplicates), _format_duplicate_audits(duplicates)),
			title=_("Duplicate Night Audits"),
		)

	frappe.db.sql_ddl(
		f"alter table `{table}` add unique index `{index}` (`property`, `business_date`)"
	)


def find_duplicate_audits() -> list[dict]:
	"""Property/date pairs holding more than one Night Audit, for reporting."""
	if not frappe.db.table_exists("Night Audit"):
		return []

	return frappe.db.sql(
		"""
		select property, business_date, count(*) as audits,
		       group_concat(concat(name, ' [', audit_status, ']') separator ', ') as which
		from `tabNight Audit`
		group by property, business_date
		having count(*) > 1
		order by audits desc
		""",
		as_dict=True,
	)


def _format_duplicate_audits(duplicates: list[dict], limit: int = 20) -> str:
	lines = [
		f"  {row['property']} {row['business_date']}: {row['which']}" for row in duplicates[:limit]
	]

	if len(duplicates) > limit:
		lines.append(f"  ... and {len(duplicates) - limit} more")

	return "\n".join(lines)


def apply_financial_idempotency_constraints():
	"""Create the per-folio unique idempotency index on the money tables.

	Idempotent: an index that already exists is left alone, so this is safe to
	call from `after_migrate` on every single migrate.
	"""
	for doctype, index_name in IDEMPOTENCY_CONSTRAINTS.items():
		_apply_unique_parent_key(doctype, index_name)


def _apply_unique_parent_key(doctype: str, index_name: str):
	table = f"tab{doctype}"

	if not frappe.db.table_exists(doctype):
		# The DocType has not been synced yet. `after_migrate` runs again after
		# it has been, so there is nothing to do and nothing to warn about.
		return

	if _index_exists(table, index_name):
		return

	duplicates = find_duplicate_keys(doctype)

	if duplicates:
		frappe.throw(
			_(
				"{0} cannot be made unique on (parent, idempotency_key): {1} key(s) are already "
				"duplicated on this site. No financial rows have been changed. Review and "
				"resolve them - by reversing the surplus posting through the folio service, "
				"which leaves an audit trail - and run the migration again.\n\n{2}"
			).format(doctype, len(duplicates), _format_duplicates(duplicates)),
			title=_("Duplicate financial idempotency keys"),
		)

	# NULL is not equal to NULL in a MariaDB unique index, so rows that never
	# carried a key - historical rows written before keys were mandatory - do
	# not collide with each other and do not need rewriting.
	frappe.db.sql_ddl(
		f"alter table `{table}` add unique index `{index_name}` (`parent`, `idempotency_key`)"
	)


def find_duplicate_keys(doctype: str) -> list[dict]:
	"""Rows that share a (parent, idempotency_key), for reporting only.

	An empty-string key is included deliberately: MariaDB treats `''` as a real
	value, so two such rows on one folio would collide. Only genuine NULLs are
	exempt.
	"""
	if not frappe.db.table_exists(doctype):
		return []

	return frappe.db.sql(
		f"""
		select parent, idempotency_key, count(*) as rows_affected
		from `tab{doctype}`
		where idempotency_key is not null
		group by parent, idempotency_key
		having count(*) > 1
		order by rows_affected desc, parent asc
		""",
		as_dict=True,
	)


def _format_duplicates(duplicates: list[dict], limit: int = 20) -> str:
	shown = duplicates[:limit]

	lines = [
		f"  {row['parent']}  key={row['idempotency_key']!r}  rows={row['rows_affected']}"
		for row in shown
	]

	if len(duplicates) > limit:
		lines.append(f"  ... and {len(duplicates) - limit} more")

	return "\n".join(lines)


def _index_exists(table: str, index_name: str) -> bool:
	return bool(
		frappe.db.sql(
			"""
			select 1 from information_schema.statistics
			where table_schema = database() and table_name = %s and index_name = %s
			limit 1
			""",
			(table, index_name),
		)
	)
