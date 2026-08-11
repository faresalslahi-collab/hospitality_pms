"""Bringing an existing failure queue under the durable operation model.

A site upgrading into Wave 3 arrives with whatever the old queue left behind.
The site this was written against had 3,169 rows describing 96 distinct pieces
of work: `_queue_failure` inserted a new row on every failed push, and
`retry_failed` never executed anything, so the queue grew all day and drained
never.

Those rows are integration evidence. They are **not** deleted here, and no
migration touches them automatically — which is why this is a command an
operator runs deliberately rather than a patch that runs itself:

    bench --site <site> execute hospitality_pms.setup.queue_maintenance.report
    bench --site <site> execute hospitality_pms.setup.queue_maintenance.adopt

`report` only reads. `adopt` writes a status and a note, and nothing else.

Why the legacy rows are retired rather than adopted
---------------------------------------------------
It is tempting to give each distinct legacy key an `operation_key` and let the
new dispatcher pick it up. That would be wrong. The old channel payload holds
only the rows that were being pushed - not the channel, not the date range - so
the retry handler has nothing to call the channel with. Adopting them would
produce work that fails for a new reason every half hour.

What actually replaces them is better: the scheduler's next pass opens one
standing operation per channel, with a live payload, and pushes the current
window. The legacy rows are marked as superseded by that, with a note saying
so, and kept.
"""

import frappe
from frappe.utils import now_datetime

from hospitality_pms.services import durability

LEDGER = "PMS Integration Failure Queue"

#: Channel pushes are replaced wholesale by the standing per-channel operation
#: the scheduler now maintains, so a backlog of them has no work left in it.
SUPERSEDED_BY_STANDING_OPERATION = ("push_availability", "push_rates")

#: These describe work that was never completed and that no machine may repeat.
NEEDS_A_PERSON = ("import_reservation", "unmatched_callback")


def _legacy_rows(limit: int | None = None) -> list[dict]:
	"""Rows written before this wave: no `operation_key`, and not yet closed."""
	return frappe.get_all(
		LEDGER,
		filters={
			"operation_key": ("is", "not set"),
			"queue_status": ("in", ("Pending", "Retrying")),
		},
		fields=["name", "property", "operation", "idempotency_key", "queue_status", "attempts"],
		order_by="creation asc",
		limit=limit,
	)


def report() -> dict:
	"""Classify what is in the queue. Reads only; changes nothing.

	Run this first. The counts say how much of the backlog is duplicated work
	that the new standing operations replace, and how much is something a
	person still has to deal with.
	"""
	rows = _legacy_rows()

	by_operation: dict[str, dict] = {}

	for row in rows:
		bucket = by_operation.setdefault(
			row["operation"], {"rows": 0, "distinct_keys": set(), "disposition": _disposition(row)}
		)
		bucket["rows"] += 1
		bucket["distinct_keys"].add(row["idempotency_key"])

	summary = {
		operation: {
			"rows": bucket["rows"],
			"distinct_operations": len(bucket["distinct_keys"]),
			"duplicate_rows": bucket["rows"] - len(bucket["distinct_keys"]),
			"disposition": bucket["disposition"],
		}
		for operation, bucket in by_operation.items()
	}

	total = sum(bucket["rows"] for bucket in summary.values())

	print(f"\nLegacy queue rows still open: {total}")

	for operation, bucket in sorted(summary.items()):
		print(
			f"  {operation:<24} rows={bucket['rows']:<6} distinct={bucket['distinct_operations']:<5} "
			f"duplicates={bucket['duplicate_rows']:<6} -> {bucket['disposition']}"
		)

	print("\nNothing has been changed. Run `adopt` to apply these dispositions.\n")

	return {"total": total, "by_operation": summary}


def _disposition(row: dict) -> str:
	if row["operation"] in SUPERSEDED_BY_STANDING_OPERATION:
		return "supersede"

	if row["operation"] in NEEDS_A_PERSON:
		return "manual review"

	return "leave alone"


def adopt(dry_run: int = 1, limit: int | None = None) -> dict:
	"""Close out the legacy backlog, without destroying any of it.

	Defaults to a dry run, because the honest default for a command that
	rewrites three thousand integration records is to do nothing and say what
	it would have done:

        bench ... execute hospitality_pms.setup.queue_maintenance.adopt
        bench ... execute hospitality_pms.setup.queue_maintenance.adopt --kwargs '{"dry_run": 0}'

	Channel pushes are marked Abandoned and annotated as superseded by the
	standing per-channel operation. Imports and unmatched callbacks are moved
	to Needs Reconciliation, which is where the new model puts work a person
	has to look at. Anything else is left exactly as it is and reported.

	No row is deleted, and no `idempotency_key`, payload or error is rewritten.
	"""
	dry_run = bool(int(dry_run))
	rows = _legacy_rows(limit=limit)

	counts = {"superseded": 0, "manual review": 0, "left alone": 0}

	for row in rows:
		disposition = _disposition(row)

		if disposition == "supersede":
			counts["superseded"] += 1
			if not dry_run:
				_close(
					row,
					durability.ABANDONED,
					"Superseded by the standing durable operation for this channel "
					"(Wave 3). Retained as integration history; no work is lost.",
				)
		elif disposition == "manual review":
			counts["manual review"] += 1
			if not dry_run:
				_close(
					row,
					durability.NEEDS_RECONCILIATION,
					"Carried over from the legacy failure queue. This operation was never "
					"completed and cannot be replayed automatically; review it by hand.",
				)
		else:
			counts["left alone"] += 1

	if not dry_run:
		frappe.db.commit()

	print(f"\n{'Would close' if dry_run else 'Closed'}: {counts}")

	if dry_run:
		print("Dry run - nothing was written. Pass --kwargs '{\"dry_run\": 0}' to apply.\n")

	return {"dry_run": dry_run, "counts": counts, "rows_considered": len(rows)}


def _close(row: dict, status: str, note: str):
	frappe.db.set_value(
		LEDGER,
		row["name"],
		{
			"queue_status": status,
			"next_attempt_on": None,
			"resolved_on": now_datetime(),
			"resolved_by": frappe.session.user,
			"notes": note,
		},
		update_modified=True,
	)
