"""Retry that actually retries.

What `retry_failed` used to do
------------------------------
It read the due rows, incremented `attempts`, set `queue_status = Retrying`,
pushed `next_attempt_on` out by a doubling backoff - and returned. It never
called anything. The rates that failed to reach a channel were never pushed
again; they were counted again. Two days of that left 3,169 rows describing 96
pieces of work, none of which had been reattempted once (N7, P1-13).

What it does now
----------------
Every operation type names a handler and a retry safety class. The scheduler
claims due operations from the durable ledger, looks the handler up, and runs
it. Success resolves the operation; failure schedules the next attempt or
abandons it; an unknown operation type is abandoned loudly rather than quietly
counted as retried.

Retry safety
------------
Not every operation may be re-run by a machine, and the difference is not a
detail:

* ``SAFE_RETRY`` - repeating it cannot do harm. A channel push sends the same
  numbers again; an ERP posting is guarded by its batch fingerprint.
* ``RECONCILE_FIRST`` - money moves. Safe to re-run only from ``Retrying``,
  which by construction means the provider explicitly refused and nothing
  happened at the far end. An operation whose outcome is *unknown* is never
  re-run: it is reconciled against the provider instead.
* ``MANUAL_ONLY`` - a person has to look. Importing a reservation creates
  guests, bookings and inventory holds part-way through, and no key makes a
  half-finished import safe to replay.
"""

from collections.abc import Callable
from dataclasses import dataclass

import frappe
from frappe import _
from frappe.utils import flt

from hospitality_pms.services import durability

#: Repeating this is harmless.
SAFE_RETRY = "Safe Retry"

#: Money moves; re-run only when the previous attempt provably did nothing.
RECONCILE_FIRST = "Reconcile First"

#: Never re-run automatically.
MANUAL_ONLY = "Manual Only"


@dataclass(frozen=True)
class OperationHandler:
	"""How one kind of operation is re-run, and whether it may be."""

	run: Callable[[dict, dict], object]
	safety: str
	max_attempts: int = durability.DEFAULT_MAX_ATTEMPTS


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _retry_initiate_payment(record: dict, payload: dict):
	from hospitality_pms.services.payments import initiate_payment

	return initiate_payment(
		payload["folio"],
		flt(payload.get("amount")),
		idempotency_key=record["operation_key"],
		provider=record.get("provider"),
	)


def _retry_refund_payment(record: dict, payload: dict):
	from hospitality_pms.services.payments import refund_payment

	return refund_payment(
		payload["transaction"],
		flt(payload.get("amount")),
		payload.get("reason") or _("Retried refund"),
		idempotency_key=record["operation_key"],
	)


def _retry_post_folio_invoice(record: dict, payload: dict):
	from hospitality_pms.services.posting import post_folio_invoice

	# The Wave-2 batch fingerprint is recomputed from the folio's still-unposted
	# rows, so a retry lands on the same logical batch and reuses its invoice
	# rather than raising a second one.
	return post_folio_invoice(payload["folio"])


def _retry_post_folio_payment(record: dict, payload: dict):
	from hospitality_pms.services.posting import post_folio_payment

	return post_folio_payment(payload["folio"], payload["payment_row"])


def _retry_push_availability(record: dict, payload: dict):
	from hospitality_pms.services.channel import push_availability

	# The same operation key, so the retry lands on the row it was claimed from
	# rather than opening a second one beside it.
	return push_availability(
		record["property"],
		payload["channel"],
		payload["from_date"],
		payload["to_date"],
		operation_key=record["operation_key"],
	)


def _retry_push_rates(record: dict, payload: dict):
	from hospitality_pms.services.channel import push_rates

	return push_rates(
		record["property"],
		payload["channel"],
		payload["from_date"],
		payload["to_date"],
		operation_key=record["operation_key"],
	)


#: Every operation the ledger can hold, and what to do with it.
#:
#: An operation absent from this table is not retried. That is deliberate: a
#: silent "retried" on work nobody knows how to perform is exactly the failure
#: mode this module was written to remove.
HANDLERS: dict[str, OperationHandler] = {
	"initiate_payment": OperationHandler(_retry_initiate_payment, RECONCILE_FIRST),
	"refund_payment": OperationHandler(_retry_refund_payment, RECONCILE_FIRST),
	"post_folio_invoice": OperationHandler(_retry_post_folio_invoice, SAFE_RETRY),
	"post_folio_payment": OperationHandler(_retry_post_folio_payment, SAFE_RETRY),
	"push_availability": OperationHandler(_retry_push_availability, SAFE_RETRY),
	"push_rates": OperationHandler(_retry_push_rates, SAFE_RETRY),
	# Importing a channel booking creates a guest, a reservation and an
	# inventory hold. A half-completed import cannot be replayed safely, so it
	# waits for someone who can see what already exists.
	"import_reservation": OperationHandler(None, MANUAL_ONLY),
	"unmatched_callback": OperationHandler(None, MANUAL_ONLY),
}


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def retry_due_operations(property_name: str, limit: int = 20) -> list[dict]:
	"""Claim the operations due for another attempt, and perform them."""
	results = []

	for record in durability.claim_due_operations(property_name, limit=limit):
		results.append(dispatch(record))

	return results


def dispatch(record: dict) -> dict:
	"""Re-run one claimed operation, or explain why it was not re-run.

	**This is a transaction boundary, and the only one in the service layer.**

	Each operation is one unit of work: it commits on success and rolls back on
	failure, so one broken folio in a sweep of twenty cannot undo the nineteen
	that worked, and cannot carry their half-finished state into the next
	attempt either. That is what makes the commit here legitimate where one
	inside an ordinary business service would not be - this function *is* the
	job, not a step in somebody else's.

	The durable ledger is unaffected by either outcome: it lives on its own
	connection and has already recorded what the provider said.
	"""
	operation = record["operation"]
	key = record["operation_key"]
	handler = HANDLERS.get(operation)

	if handler is None:
		# Not "retried" - stopped, and visibly. A row nobody can execute would
		# otherwise cycle through the queue for ever pretending to make progress.
		durability.abandon_operation(
			key,
			reason=_("No retry handler is registered for operation {0}.").format(operation),
		)

		return {"operation": key, "status": durability.ABANDONED, "reason": "unknown operation"}

	if handler.safety == MANUAL_ONLY:
		durability.flag_for_reconciliation(
			key, error=_("Operation {0} is not retried automatically.").format(operation)
		)

		return {
			"operation": key,
			"status": durability.NEEDS_RECONCILIATION,
			"reason": "manual only",
		}

	payload = durability.get_operation_payload(record)

	try:
		handler.run(record, payload)
	except Exception as exc:  # noqa: BLE001
		# The handler routes its own provider call through `run_durably`, which
		# has already recorded the right outcome - Retrying for a refusal,
		# Needs Reconciliation for silence. Reading the ledger back is how this
		# reports what happened without second-guessing that classification.
		frappe.db.rollback()

		current = durability.get_operation(key) or {}

		return {
			"operation": key,
			"status": current.get("queue_status", durability.RETRYING),
			"error": str(exc)[:500],
		}

	frappe.db.commit()

	return {"operation": key, "status": durability.RESOLVED}


def reconcile_due_operations(property_name: str, limit: int = 20) -> list[dict]:
	"""Try to establish the outcome of operations whose answer was lost.

	Only touches operations whose handler says money is involved and whose
	adapter can be asked; everything else stays put for a human.
	"""
	from hospitality_pms.services.payments import reconcile_operation

	results = []

	for record in durability.operations_needing_attention(property_name, limit=limit):
		if record["queue_status"] != durability.NEEDS_RECONCILIATION:
			continue

		handler = HANDLERS.get(record["operation"])

		if not handler or handler.safety != RECONCILE_FIRST:
			continue

		try:
			results.append(reconcile_operation(record["operation_key"]))
		except Exception as exc:  # noqa: BLE001
			frappe.db.rollback()
			results.append({"operation": record["operation_key"], "error": str(exc)[:500]})

	return results
