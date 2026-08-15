"""Durable identity for operations with an external side effect.

The problem
-----------
When Hospitality PMS asks a payment provider, a channel or ERPNext to do
something, three things can happen: it works, it fails, or the answer is lost.
The third is the dangerous one, and the system had no way to record any of them
reliably, because every record was written inside the transaction that the
failure was about to roll back. The provider was called, the failure row was
written, the exception propagated, and the rollback erased the only evidence
that anyone had been contacted (P1-13, P1-14).

The rule this module exists to enforce
--------------------------------------
**No external side effect without a durable identity first.** Before a provider
is called there is a committed row saying what is about to be attempted, under
what key, for which property. Whatever happens next - success, failure, silence,
a crashed worker - that row is still there afterwards.

How durability is achieved
--------------------------
Through a second database connection. It has its own transaction, so a rollback
on the caller's connection cannot reach it.

The two obvious alternatives were rejected:

* `frappe.db.commit()` in the service. Forbidden by the build rules, and wrong
  regardless: it would commit the caller's half-finished business work along
  with the evidence, so a failed check-in would leave a real Stay behind.
* `frappe.db.after_rollback`. Fires at the right moment on the right
  connection, but whatever it writes is itself uncommitted, and in a request
  that is ending nothing ever commits it.

The cost is one short connection per state change on an operation that is
already making a network call, which is not a cost worth optimising.

The division of labour
----------------------
This ledger is **not** the business record. A Payment Transaction and a
Financial Posting Log still record what the hotel's books say, and they stay in
the caller's transaction on purpose: if the invoice rolls back, the log row
saying it was posted must roll back with it, or the log would lie.

This ledger records something different - *what we asked an external system to
do, and what came back*. That has to survive precisely when the business
transaction does not.
"""

import json
from contextlib import contextmanager
from dataclasses import dataclass

import frappe
from frappe import _
from frappe.utils import add_to_date, get_datetime, now_datetime

from hospitality_pms.services.exceptions import (
	IntegrationAmbiguousError,
	IntegrationError,
	throw,
)

OPERATION_LEDGER = "PMS Integration Failure Queue"

# -- states -----------------------------------------------------------------
#
#     Pending ──► Executing ──► Resolved
#                     │
#                     ├──► Retrying ──► Executing ...
#                     │        └──► Abandoned        (attempts exhausted)
#                     │
#                     └──► Needs Reconciliation      (outcome unknown)
#                              └──► Resolved / Abandoned, once established
#
# Resolved and Abandoned are terminal: nothing reopens them, because doing so
# is how a settled operation gets performed a second time.

PENDING = "Pending"
EXECUTING = "Executing"
RETRYING = "Retrying"
NEEDS_RECONCILIATION = "Needs Reconciliation"
RESOLVED = "Resolved"
ABANDONED = "Abandoned"

TERMINAL_STATES = (RESOLVED, ABANDONED)

#: States a scheduler may pick up and run.
CLAIMABLE_STATES = (PENDING, RETRYING)

#: Attempts before an operation stops retrying and waits for a human. Bounded
#: so a permanently broken integration reaches a terminal state instead of
#: retrying for ever.
DEFAULT_MAX_ATTEMPTS = 5

#: First backoff step, doubled per attempt.
BASE_BACKOFF_MINUTES = 5

#: How long a claim is honoured before the worker holding it is presumed dead.
#: Long enough for a slow provider call, short enough that a crashed worker does
#: not strand the operation until someone notices.
CLAIM_LEASE_MINUTES = 30


# ---------------------------------------------------------------------------
# The independent connection
# ---------------------------------------------------------------------------


@contextmanager
def _durable_db():
	"""Run a block against a connection of its own, committed on the way out.

	`frappe.local.db` is swapped for the duration so ordinary ORM calls inside
	the block go to the second connection - naming, validation and all - and
	then swapped back. The block is deliberately tiny: it writes one ledger row
	and nothing else, so nothing unrelated can be caught by the commit.

	Everything that touches the ledger goes through here, including reads.
	Split between two connections it would deadlock: the caller's transaction
	would hold a lock the durable write then waited on for ever.
	"""
	from frappe.database import get_db

	conf = frappe.local.conf

	connection = get_db(
		socket=conf.db_socket,
		host=conf.db_host,
		port=conf.db_port,
		user=conf.db_user or conf.db_name,
		password=conf.db_password,
		cur_db_name=conf.db_name,
	)
	connection.connect()

	previous = frappe.local.db
	frappe.local.db = connection

	try:
		yield connection
		connection.commit()
	except Exception:
		connection.rollback()
		raise
	finally:
		frappe.local.db = previous
		connection.close()


# ---------------------------------------------------------------------------
# Recording an operation
# ---------------------------------------------------------------------------


def begin_operation(
	*,
	property_name: str,
	integration_type: str,
	operation: str,
	operation_key: str,
	payload: dict | None = None,
	provider: str | None = None,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
	max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> dict:
	"""Durably record that this operation is about to be attempted.

	Called *before* the external side effect, every time - the first attempt and
	every retry. Returns the ledger row as it now stands.

	The row is keyed on `operation_key`, which is unique, so one logical
	operation is one row however many times it is attempted. That is what stops
	the channel queue growing a fresh row per scheduler pass (N7).

	A terminal operation is left exactly as it is. Reopening a Resolved
	operation would be a licence to perform it twice, and reopening an Abandoned
	one would undo a human's decision to stop.

	Identity is fixed at creation. `property`, `operation`, `provider` and the
	reference are written once and never updated, so a replayed payload cannot
	point a retry at another property's money (Part 12).
	"""
	with _durable_db():
		existing = frappe.db.get_value(
			OPERATION_LEDGER,
			{"operation_key": operation_key},
			["name", "queue_status", "attempts", "max_attempts"],
			as_dict=True,
		)

		if existing:
			# Terminal, or of unknown outcome: left exactly as it is, and the
			# caller is told so. Moving a Needs Reconciliation row back to
			# Executing would quietly grant permission to call the provider
			# again - for an operation that may already have moved the money.
			if existing["queue_status"] in TERMINAL_STATES + (NEEDS_RECONCILIATION,):
				return _read(operation_key)

			frappe.db.set_value(
				OPERATION_LEDGER,
				existing["name"],
				{
					"queue_status": EXECUTING,
					"attempts": int(existing["attempts"] or 0) + 1,
					"claimed_on": now_datetime(),
					# Refreshed because it is genuinely new information about
					# this attempt; identity fields above are not.
					"payload": _dump(payload),
				},
				update_modified=True,
			)

			return _read(operation_key)

		frappe.get_doc(
			{
				"doctype": OPERATION_LEDGER,
				"property": property_name,
				"integration_type": integration_type,
				"provider": provider,
				"operation": operation,
				"operation_key": operation_key,
				# The legacy column is kept in step so existing reports and the
				# rows already on site stay readable side by side.
				"idempotency_key": operation_key,
				"payload": _dump(payload),
				"reference_doctype": reference_doctype,
				"reference_name": reference_name,
				"queue_status": EXECUTING,
				"attempts": 1,
				"max_attempts": max_attempts,
				"claimed_on": now_datetime(),
			}
		).insert(ignore_permissions=True)

		return _read(operation_key)


def complete_operation(operation_key: str, *, external_reference: str | None = None, note: str | None = None):
	"""The external system did what was asked. Terminal."""
	_update(
		operation_key,
		{
			"queue_status": RESOLVED,
			"external_reference": external_reference,
			"resolved_on": now_datetime(),
			"resolved_by": frappe.session.user,
			"next_attempt_on": None,
			"claimed_on": None,
			"last_error": None,
			"notes": note,
		},
	)


def reopen_absent_operation(operation_key: str, *, reason: str) -> bool:
	"""Reopen a Resolved operation whose external artifact is proven not to exist.

	Resolved is normally terminal, because reopening an operation with a real
	external side effect is a licence to perform it twice. This is the single,
	deliberately narrow exception, and the safety rests entirely on the caller.

	It exists for a same-database ERP posting (Sales Invoice / Payment Entry)
	whose recording transaction rolled back *after* `run_durably` committed the
	ledger row on its own connection. ERPNext shares the caller's database, so
	when the caller asks `_erp_document_is_live(external_reference)` and gets
	False, that is authoritative proof the document does not exist and the work
	genuinely did not happen - re-running cannot double-post because there is
	nothing to double. NEVER call this for a payment gateway or any operation
	whose outcome cannot be verified from our own database; for those, an unknown
	outcome is `flag_for_reconciliation`, not a reopen.

	Returns True if a Resolved row was reopened. A row that is not Resolved is
	left untouched (another worker may already have re-posted it).
	"""
	with _durable_db():
		existing = frappe.db.get_value(
			OPERATION_LEDGER,
			{"operation_key": operation_key},
			["name", "queue_status"],
			as_dict=True,
		)

		if not existing or existing["queue_status"] != RESOLVED:
			return False

		frappe.db.set_value(
			OPERATION_LEDGER,
			existing["name"],
			{
				"queue_status": PENDING,
				"external_reference": None,
				"resolved_on": None,
				"resolved_by": None,
				"next_attempt_on": None,
				"claimed_on": None,
				"last_error": (reason or "")[:2000],
			},
			update_modified=True,
		)

	return True


def rearm_operation(operation_key: str, *, reason: str) -> bool:
	"""Re-arm an Abandoned operation so it may be attempted again.

	Abandoned is terminal - a human decided the operation had failed enough times
	to stop. Reviving one is therefore a deliberate, audited act, and like
	`reopen_absent_operation` the safety rests on the caller: this must only be
	called for a *safe-retry* operation (one whose failure mode is an explicit
	refusal, so nothing happened at the far end - `post_folio_invoice` /
	`post_folio_payment`, never a RECONCILE_FIRST money op) and only after the
	caller has proven no external side effect exists (`external_reference` empty or
	not live). The attempt counter is reset so the corrected operation gets a fresh
	budget, and the reason is recorded for the audit trail.

	Returns True if an Abandoned row was re-armed; a row in any other state is left
	untouched.
	"""
	with _durable_db():
		existing = frappe.db.get_value(
			OPERATION_LEDGER,
			{"operation_key": operation_key},
			["name", "queue_status"],
			as_dict=True,
		)

		if not existing or existing["queue_status"] != ABANDONED:
			return False

		frappe.db.set_value(
			OPERATION_LEDGER,
			existing["name"],
			{
				"queue_status": PENDING,
				"attempts": 0,
				"resolved_on": None,
				"resolved_by": None,
				"next_attempt_on": None,
				"claimed_on": None,
				"last_error": (reason or "")[:2000],
			},
			update_modified=True,
		)

	return True


def fail_operation(
	operation_key: str, *, error: str, retryable: bool = True, retry_in_minutes: int | None = None
) -> str:
	"""The external system explicitly refused. Schedule a retry, or give up.

	An explicit refusal is the safe kind of failure: nothing happened at the far
	end, so trying again cannot duplicate anything. Contrast
	`flag_for_reconciliation`, which is for the case where it might have.
	"""
	with _durable_db():
		record = frappe.db.get_value(
			OPERATION_LEDGER,
			{"operation_key": operation_key},
			["name", "attempts", "max_attempts", "queue_status"],
			as_dict=True,
		)

		if not record or record["queue_status"] in TERMINAL_STATES:
			return record["queue_status"] if record else ABANDONED

		attempts = int(record["attempts"] or 0)
		limit = int(record["max_attempts"] or DEFAULT_MAX_ATTEMPTS)

		exhausted = not retryable or attempts >= limit
		status = ABANDONED if exhausted else RETRYING

		if retry_in_minutes is None:
			retry_in_minutes = BASE_BACKOFF_MINUTES * (2 ** max(attempts - 1, 0))

		frappe.db.set_value(
			OPERATION_LEDGER,
			record["name"],
			{
				"queue_status": status,
				"last_error": (error or "")[:2000],
				"claimed_on": None,
				"next_attempt_on": None
				if exhausted
				else add_to_date(now_datetime(), minutes=retry_in_minutes),
				"resolved_on": now_datetime() if exhausted else None,
			},
			update_modified=True,
		)

		return status


def flag_for_reconciliation(operation_key: str, *, error: str, external_reference: str | None = None):
	"""The outcome is unknown - a timeout, a dropped connection, a lost reply.

	Deliberately not a failure. The provider may have applied the refund and
	only the answer went missing, so retrying blindly is how a guest gets
	refunded twice. The operation stops here until something establishes what
	actually happened: a status lookup where the adapter supports one, a human
	where it does not.
	"""
	_update(
		operation_key,
		{
			"queue_status": NEEDS_RECONCILIATION,
			"last_error": (error or "")[:2000],
			"external_reference": external_reference,
			"claimed_on": None,
			"next_attempt_on": None,
		},
	)


def abandon_operation(operation_key: str, *, reason: str):
	"""Stop trying. Terminal, and waiting for a human."""
	_update(
		operation_key,
		{
			"queue_status": ABANDONED,
			"last_error": (reason or "")[:2000],
			"claimed_on": None,
			"next_attempt_on": None,
			"resolved_on": now_datetime(),
		},
	)


# ---------------------------------------------------------------------------
# Running an operation
# ---------------------------------------------------------------------------


@dataclass
class DurableResult:
	"""What happened when an operation was run through the ledger."""

	#: False when the provider was not called because the ledger already says
	#: this operation reached it. The caller reconciles its own state instead.
	performed: bool
	result: object
	record: dict

	@property
	def external_reference(self) -> str | None:
		return (self.record or {}).get("external_reference")


def run_durably(
	*,
	property_name: str,
	integration_type: str,
	operation: str,
	operation_key: str,
	call,
	payload: dict | None = None,
	provider: str | None = None,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
	max_attempts: int = DEFAULT_MAX_ATTEMPTS,
	reference_of=None,
) -> DurableResult:
	"""Perform an external side effect with a durable record either side of it.

	The whole of Wave 3 in one function:

	1. commit a record of the intent, before anything leaves the building;
	2. make the call;
	3. commit what came back.

	Steps 1 and 3 are on a connection of their own, so step 3 survives the
	caller's transaction failing after step 2 succeeded - which is the exact
	shape of the residual P1-12 risk.

	Three outcomes, three different answers:

	* **Success** - Resolved, with the provider's reference if it gave one.
	* **Refusal** (`IntegrationError` and friends) - Retrying with backoff, or
	  Abandoned once attempts run out. Safe, because nothing happened remotely.
	* **Silence** (`IntegrationAmbiguousError`) - Needs Reconciliation, and no
	  automatic retry. The provider may have acted, and a second attempt could
	  move the money twice.

	And if the ledger already says Resolved, the call is not made at all:
	`performed` comes back False with the original reference attached. That is
	what stops a retry re-refunding a guest whose first refund succeeded and
	whose database transaction then died.

	`reference_of` extracts the provider's reference from the result, when
	there is one to extract.
	"""
	record = begin_operation(
		property_name=property_name,
		integration_type=integration_type,
		operation=operation,
		operation_key=operation_key,
		payload=payload,
		provider=provider,
		reference_doctype=reference_doctype,
		reference_name=reference_name,
		max_attempts=max_attempts,
	)

	status = record["queue_status"]

	if status == RESOLVED:
		# Already done at the far end. Saying so is the point: the caller can
		# bring its own state into line without asking the provider again.
		return DurableResult(performed=False, result=None, record=record)

	if status == NEEDS_RECONCILIATION:
		throw(
			_(
				"Operation {0} has an unresolved outcome from a previous attempt and will not be "
				"repeated until it is reconciled."
			).format(operation_key),
			exc=IntegrationError,
		)

	if status == ABANDONED:
		throw(
			_("Operation {0} was abandoned after repeated failures and needs manual review.").format(
				operation_key
			),
			exc=IntegrationError,
		)

	try:
		result = call()
	except IntegrationAmbiguousError as exc:
		flag_for_reconciliation(operation_key, error=str(exc))
		raise
	except Exception as exc:  # noqa: BLE001
		fail_operation(operation_key, error=str(exc))
		raise

	complete_operation(
		operation_key, external_reference=reference_of(result) if reference_of else None
	)

	return DurableResult(performed=True, result=result, record=get_operation(operation_key))


# ---------------------------------------------------------------------------
# Claiming
# ---------------------------------------------------------------------------


def claim_due_operations(property_name: str, limit: int = 20) -> list[dict]:
	"""Take ownership of the operations due for another attempt.

	The claim is the point at which two schedulers stop being a problem. Rows
	are locked with `SELECT ... FOR UPDATE` and moved to Executing inside one
	transaction on the durable connection, so a second worker arriving mid-claim
	waits, and then sees them already Executing rather than Pending.

	A row Executing for longer than the lease is taken back: its worker is
	presumed dead, and leaving it claimed for ever would strand the operation.
	"""
	now = now_datetime()
	stale_before = add_to_date(now, minutes=-CLAIM_LEASE_MINUTES)

	with _durable_db():
		rows = frappe.db.sql(
			f"""
			select name, operation_key
			from `tab{OPERATION_LEDGER}`
			where property = %(property)s
			  and (
			        (queue_status in %(claimable)s and ifnull(next_attempt_on, %(now)s) <= %(now)s)
			     or (queue_status = %(executing)s and claimed_on is not null and claimed_on < %(stale)s)
			  )
			order by ifnull(next_attempt_on, creation) asc
			limit %(limit)s
			for update
			""",
			{
				"property": property_name,
				"claimable": CLAIMABLE_STATES,
				"executing": EXECUTING,
				"now": now,
				"stale": stale_before,
				"limit": int(limit),
			},
			as_dict=True,
		)

		for row in rows:
			frappe.db.set_value(
				OPERATION_LEDGER,
				row["name"],
				{"queue_status": EXECUTING, "claimed_on": now},
				update_modified=True,
			)

		claimed = [_read_within(row["operation_key"]) for row in rows]

	return [row for row in claimed if row]


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

#: The fields callers and tests read back. Named explicitly so a schema change
#: that drops one is a loud failure rather than a silently missing key.
LEDGER_FIELDS = (
	"name",
	"property",
	"integration_type",
	"provider",
	"operation",
	"operation_key",
	"external_reference",
	"payload",
	"reference_doctype",
	"reference_name",
	"queue_status",
	"attempts",
	"max_attempts",
	"next_attempt_on",
	"claimed_on",
	"last_error",
	"resolved_on",
	"notes",
)


def get_operation(operation_key: str) -> dict | None:
	"""The durable record for a logical operation, if there is one."""
	with _durable_db():
		return _read_within(operation_key)


def get_operation_payload(record: dict) -> dict:
	"""The stored parameters of an operation, as a dict."""
	if not record or not record.get("payload"):
		return {}

	try:
		return json.loads(record["payload"]) or {}
	except (TypeError, ValueError):
		return {}


def operations_needing_attention(property_name: str, limit: int = 100) -> list[dict]:
	"""Everything a human has to look at: abandoned, or of unknown outcome."""
	with _durable_db():
		return frappe.get_all(
			OPERATION_LEDGER,
			filters={
				"property": property_name,
				"queue_status": ("in", (ABANDONED, NEEDS_RECONCILIATION)),
			},
			fields=list(LEDGER_FIELDS),
			order_by="modified desc",
			limit=limit,
		)


def find_operations(*, property_name: str, operation: str | None = None, limit: int = 100) -> list[dict]:
	"""Ledger rows for a property, newest first.

	Read through the durable connection like everything else here. A caller
	reading the ledger with `frappe.db` would be answered from its own
	transaction's snapshot, which was very likely opened before the durable
	write it is looking for - the same stale-read trap Wave 1 closed elsewhere.
	"""
	filters = {"property": property_name, "operation_key": ("is", "set")}

	if operation:
		filters["operation"] = operation

	with _durable_db():
		return frappe.get_all(
			OPERATION_LEDGER, filters=filters, fields=list(LEDGER_FIELDS), order_by="modified desc", limit=limit
		)


def is_due(operation_key: str) -> bool:
	"""Whether this operation may be attempted now.

	A fresh operation is due; one waiting out its backoff is not; a terminal or
	unreconciled one never is. The scheduler consults this before pushing again
	so that a channel which is down does not burn its whole attempt budget in
	an afternoon, and so an abandoned operation is not quietly restarted on the
	next pass.
	"""
	record = get_operation(operation_key)

	if not record:
		return True

	if record["queue_status"] in TERMINAL_STATES + (NEEDS_RECONCILIATION,):
		return False

	if not record["next_attempt_on"]:
		return True

	return get_datetime(record["next_attempt_on"]) <= now_datetime()


def reschedule_now(operation_key: str) -> str:
	"""Make a waiting operation due immediately - the "retry now" action.

	Only moves a retryable operation forward in time. It cannot revive a
	terminal one, and it cannot bypass reconciliation for an operation whose
	outcome is unknown; both of those would be a way to perform something
	twice.
	"""
	record = get_operation(operation_key)

	if not record or record["queue_status"] not in CLAIMABLE_STATES:
		return record["queue_status"] if record else ABANDONED

	_update(operation_key, {"next_attempt_on": now_datetime()})

	return record["queue_status"]


def failed_posting_operations(property_name: str, limit: int = 100) -> list[dict]:
	"""Posting operations that did not succeed, from the durable ledger.

	Everything except Resolved: a posting still Retrying has not reached
	ERPNext, and one Abandoned or awaiting reconciliation certainly has not.
	Reporting only the Abandoned ones would hide a folio that is quietly
	failing every half hour.
	"""
	with _durable_db():
		return frappe.get_all(
			OPERATION_LEDGER,
			filters={
				"property": property_name,
				"operation": ("in", ("post_folio_invoice", "post_folio_payment")),
				"queue_status": ("!=", RESOLVED),
			},
			fields=[
				"name",
				"operation",
				"operation_key",
				"reference_name",
				"queue_status",
				"attempts",
				"last_error",
				"modified",
			],
			order_by="modified desc",
			limit=limit,
		)


def purge_operations(*, property_name: str):
	"""Remove a property's ledger rows. For tests, which commit theirs."""
	with _durable_db():
		frappe.db.delete(OPERATION_LEDGER, {"property": property_name})


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _update(operation_key: str, values: dict):
	with _durable_db():
		name = frappe.db.get_value(OPERATION_LEDGER, {"operation_key": operation_key}, "name")

		if not name:
			return

		frappe.db.set_value(OPERATION_LEDGER, name, values, update_modified=True)


def _read(operation_key: str) -> dict | None:
	"""Read inside an already-open durable block."""
	return _read_within(operation_key)


def _read_within(operation_key: str) -> dict | None:
	# Guarded, because `{"operation_key": None}` is a filter that matches every
	# legacy row whose key was never set - so a missing key would silently
	# return somebody else's operation rather than nothing.
	if not operation_key:
		return None

	return frappe.db.get_value(
		OPERATION_LEDGER, {"operation_key": operation_key}, list(LEDGER_FIELDS), as_dict=True
	)


def _dump(payload) -> str | None:
	return json.dumps(payload, default=str) if payload else None
