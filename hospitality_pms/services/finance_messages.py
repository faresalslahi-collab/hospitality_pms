"""Turn a financial failure into something an operator can act on.

Until 16.7.5 a failed posting reached the reconciliation screen as
`str(exc)[:2000]` - a raw Python exception, truncated. `get_failed_postings`
returns `error_message` straight off `Financial Posting Log` and `last_error`
straight off the durable ledger, and `api.checkout.reconciliation` published
both verbatim. A Finance Manager looking at why last night's revenue did not
reach ERPNext was shown a traceback fragment, an endpoint URL or a MariaDB
error string, none of which tells them what to do next.

This module answers three questions the raw text does not:

* **What kind of problem is it** - a category an operator recognises, not an
  exception class.
* **What happens if I press the button** - `can_retry`, derived from *both* the
  posting status and the durable ledger's `queue_status`, because they disagree
  in exactly the case that matters. An explicit refusal from ERPNext is
  retryable: nothing happened, so repeating it is safe. Silence is not: the
  operation may have landed, and `run_durably` refuses to repeat it until a
  human establishes what actually happened. A Retry button offered on that row
  throws rather than acts.
* **What do I quote to support** - a diagnostic identifier. The raw text is
  withheld; the identifier that lets someone with log access find it is not.
  Hiding the identifier too would just move the operator's problem.

What deliberately does not appear here: the exception text, the payload, the
operation key, the connection strategy, scheduler internals (`claimed_on`,
`next_attempt_on`, `max_attempts`), ERP account names, and `docstatus`. The
identifier is a document name the caller already holds permission to see.
"""

from frappe import _

from hospitality_pms.services import durability

#: Operator-facing categories. Deliberately a small, closed set: an operator
#: acts differently on each, and a category nobody acts on differently is a
#: category that should not exist.
POSTING_FAILED = "Posting Failed"
RETRY_AVAILABLE = "Retry Available"
NEEDS_FINANCE_REVIEW = "Needs Finance Review"
RECONCILIATION_REQUIRED = "Reconciliation Required"
CONFIGURATION = "Accounting Configuration"

#: Ledger states that must never offer a retry, and why each one refuses.
#:
#: `run_durably` raises on both, so a button here would surface an
#: `IntegrationError` to the operator instead of doing anything.
#: The message is a callable, not a string. `_()` at module scope resolves once
#: at import and freezes the translation into whichever language happened to
#: load the module first - which on an Arabic-first site is the wrong one.
_NO_RETRY = {
	durability.NEEDS_RECONCILIATION: (
		RECONCILIATION_REQUIRED,
		# The outcome is unknown, not failed. Repeating it could double-post.
		lambda: _("The outcome of this operation is unknown and must be confirmed before it is repeated."),
	),
	durability.ABANDONED: (
		NEEDS_FINANCE_REVIEW,
		lambda: _("This operation was abandoned after repeated failures and needs manual review."),
	),
}

#: Substrings that identify a configuration problem rather than a transient
#: one. Matched against the raw text *here*, so the raw text itself never
#: leaves this module.
#:
#: Deliberately conservative: an unrecognised failure is reported as a plain
#: posting failure, which is honest, rather than being guessed into a category
#: that would send finance to the wrong screen.
_CONFIGURATION_MARKERS = (
	"posting profile",
	"tax account",
	"tax template",
	"charge item",
	"cost center",
	"company",
	"warehouse",
	"currency",
)


def _is_configuration(raw: str | None) -> bool:
	if not raw:
		return False

	lowered = raw.lower()

	return any(marker in lowered for marker in _CONFIGURATION_MARKERS)


def describe_failure(row: dict) -> dict:
	"""One failed posting, as an operator should read it.

	`row` is a `get_failed_postings` entry. That function's shape is fixed by
	its own test and by what Night Audit reads, so it is projected here rather
	than changed there.
	"""
	queue_status = row.get("operation_status")
	raw = row.get("error_message")

	blocked = _NO_RETRY.get(queue_status)

	if blocked:
		category, message_for = blocked
		message = message_for()
		can_retry = False
	elif _is_configuration(raw):
		category = CONFIGURATION
		message = _(
			"Accounting configuration is incomplete for this posting. "
			"Check the property's posting profile before retrying."
		)
		# Retrying an unconfigured posting fails the same way every time, so the
		# button is offered but the message says what to fix first.
		can_retry = True
	else:
		category = RETRY_AVAILABLE
		message = _("This posting did not reach the accounting system and can be retried.")
		can_retry = True

	attempts = int(row.get("attempts") or 0)

	if can_retry and attempts >= durability.DEFAULT_MAX_ATTEMPTS:
		category = NEEDS_FINANCE_REVIEW
		message = _("This posting has failed repeatedly and needs finance review before another attempt.")
		can_retry = False

	return {
		"category": category,
		"message": message,
		"can_retry": can_retry,
		# The identifier, never the text. Support can find the exception with
		# this; the operator cannot be shown a traceback by it.
		"reference": row.get("name"),
		"attempts": attempts,
	}


def safe_failed_postings(rows: list[dict]) -> list[dict]:
	"""`get_failed_postings`, with the raw text replaced by an operator message.

	Every key that carried internals is dropped rather than blanked:
	`error_message` (raw exception), `durable_operation` (the operation key,
	which is internal identity and in some paths encodes amounts) and
	`operation_status` (a ledger state whose meaning is already carried by
	`category` and `can_retry`).
	"""
	safe = []

	for row in rows:
		described = describe_failure(row)

		safe.append(
			{
				"name": row.get("name"),
				"posting_type": row.get("posting_type"),
				"folio": row.get("folio"),
				"amount": row.get("amount"),
				"business_date": row.get("business_date"),
				"last_attempt_on": row.get("last_attempt_on"),
				**described,
			}
		)

	return safe
