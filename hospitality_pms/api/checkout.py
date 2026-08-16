"""Checkout, ERP posting and reconciliation endpoints."""

import frappe
from frappe import _

from hospitality_pms.services import checkout as service
from hospitality_pms.services import finance_messages
from hospitality_pms.services import posting as posting_service
from hospitality_pms.services.base import authorise_document, may_read_doctype, require_role
from hospitality_pms.services.property import resolve_property

STAY_DOCTYPE = "Stay"
FOLIO_DOCTYPE = "Guest Folio"

RECONCILIATION_ROLES = (
	"Finance Manager",
	"Accounts User",
	"Night Auditor",
	"Hotel Manager",
	"General Manager",
	"Hospitality Administrator",
	"System Manager",
)


#: The checkout summary's folio group: every field of it that belongs to Guest
#: Folio rather than to the Stay this endpoint authorises.
#:
#: `related_folios` carries other folios' names *and their balances*, so it is
#: money twice over. `can_check_out` is here because it is a verdict computed
#: from folio state, and a `true` would read as "this guest may leave".
FOLIO_FIELDS = (
	"folio",
	"currency",
	"total_charges",
	"total_payments",
	"balance",
	"related_folios",
	"can_check_out",
)


def _disclose_checkout(summary: dict, *, may_read_folio: bool) -> dict:
	"""The checkout summary as this caller is entitled to see it.

	`authorise_document(Stay, ...)` authorises the Stay, and the Stay only. The
	rest of this payload is Guest Folio's - the folio's name, its currency, its
	charge and payment totals, its balance, the split folios' names and balances,
	and the departure verdict computed from all of it - and no Guest Folio check
	stood in front of any of it. Ten roles hold Stay read without Guest Folio
	read, so a Room Attendant could pass any stay id in their own property and be
	told what that guest owes.

	The departures and in-house boards already refuse exactly this, through
	`front_office._folio_position`, whose docstring names the blocker sentences as
	the sharpest case. The board fix simply did not follow the rule into the
	single-stay reader, which then carried *more* than the board did:
	`total_charges` and `total_payments` are not on the board at all.

	Applied here at the controller boundary rather than inside
	`checkout.get_checkout_summary`, deliberately. `checkout.check_out` calls that
	service for itself and decides the city-ledger case on the blocker text
	(`all(_("balance") in blocker ...)`), so a service that redacted according to
	the session's permissions would change a credit decision into a function of
	who happened to be looking. The service stays honest; the endpoint discloses.

	Blockers are abstracted rather than dropped, which is the one place this
	departs from `_folio_position`'s all-or-nothing splice. An operational caller
	still has to be able to see that a departure is blocked, or the screen offers
	a checkout that will be refused with no reason given. So:

	* blockers that carry no money - "The stay is Checked Out", the disputed-folio
	  sentence - pass through unchanged;
	* every amount-bearing blocker collapses into one fixed sentence that names no
	  figure, no folio and no count.

	That does disclose the *existence* of an unsettled balance, which the boards
	do not, and it is a deliberate trade the brief asks for: the workflow fact
	("a cashier must act") is operational, the amount is financial. It discloses
	strictly less than a count would - one blocker or five reads identically -
	and nothing about how much or to which folio.
	"""
	if may_read_folio:
		return summary

	disclosed = {field: value for field, value in summary.items() if field not in FOLIO_FIELDS}
	disclosed["blockers"] = _abstract_blockers(
		summary.get("blockers") or [], summary.get("blocker_kinds") or []
	)
	# The kinds name the categories rather than the amounts, so they disclose no
	# more than the abstracted sentences above - but they are the *unabstracted*
	# list, and shipping them alongside a redacted one would let a client
	# reconstruct which sentence was removed and how many there were.
	disclosed.pop("blocker_kinds", None)

	return disclosed


def _abstract_blockers(blockers: list[str], kinds: list[str]) -> list[str]:
	"""Folio blockers reduced to the operational fact, stay blockers left alone.

	Classified by `kind`, not by reading the sentence. The messages are
	translated and two of them interpolate an amount, so matching on the word
	"balance" would silently stop redacting on an Arabic session - and Arabic is
	a first-release requirement.

	In the normal path the generic line is *added*, so a stay-status blocker keeps
	its own sentence and only the money ones collapse.

	If the two lists ever disagree in length the pairing cannot be trusted, and
	then the whole list **is** replaced by the generic line. That is a deliberate
	choice between two bad outcomes and not an oversight: without kinds there is no
	way to tell which sentence carries an amount, and passing an unclassifiable
	sentence through on the chance that it is only a stay status would disclose the
	figure whenever the guess is wrong. Losing the specific reason costs the
	operator a trip to the cashier; guessing wrong costs the guest their privacy.
	The branch is unreachable from `get_checkout_summary`, which always returns
	both lists together, and exists for a hand-built or future caller.

	The generic sentence names no amount, no folio and no count: one folio blocker
	or five read identically.
	"""
	generic = _("Checkout requires cashier action before this stay can depart.")

	if len(kinds) != len(blockers):
		return [generic] if blockers else []

	safe = [
		message
		for message, kind in zip(blockers, kinds, strict=True)
		if kind not in service.FOLIO_BLOCKER_KINDS
	]

	if len(safe) != len(blockers):
		safe.append(generic)

	return safe


#: The ERP documents a posting result names, and the DocType each belongs to.
#:
#: `log` is a `Financial Posting Log`, `erp_document` is whatever `erp_doctype`
#: says it is - a Sales Invoice or a Payment Entry - and `customer` is an ERPNext
#: Customer. Front Office holds read on none of the three.
_POSTING_LOG_DOCTYPE = "Financial Posting Log"
_CUSTOMER_DOCTYPE = "Customer"

#: The keys of a posting result that name an ERP document or an ERP party, or
#: carry raw failure text. Any caller rebuilding a projected result must drop
#: these before merging the projection back in, or the merge silently restores
#: what it claims to withhold.
#:
#: `name` is here because it is the same thing as `log` under another key. The
#: idempotent-replay path does not go through `post_folio_invoice`'s success
#: return at all - it hands back `get_posting`'s row, whose primary key *is* the
#: `Financial Posting Log`. A whitelist naming only `log` therefore leaked the
#: posting-log name on exactly the path a retry is most likely to take.
#:
#: `error_message` is a truncated `str(exc)`. `services/finance_messages.py`
#: exists because that text is not for operators - it carries connection strings,
#: table names and idempotency keys - and the `reconciliation` endpoint routes it
#: through `safe_failed_postings` for that reason. It is never re-disclosed here,
#: not even to a posting-log reader: the sanitised category is what that audience
#: is given, through the endpoint built for it.
_POSTING_IDENTIFIER_FIELDS = (
	"log",
	"name",
	"erp_document",
	"customer",
	"allocations",
	"error_message",
)


def _disclose_posting(posting: dict | None) -> dict | None:
	"""A posting result as this caller is entitled to see it.

	Not one of the Codex findings, and the sharpest of the ones found while
	fixing them. `check_out` is authorised on **Stay write**, whose role set
	includes Front Office Agent, and it returned `posting` verbatim from
	`posting.post_folio_invoice`: the `Financial Posting Log` name, the
	`Sales Invoice` name and the ERPNext `Customer`. Front Office holds no
	permlevel-0 read on any of them - `Sales Invoice`'s `All` row sits at
	permlevel 1, which `frappe.has_permission(..., "read")` does not consult.

	So the gate `api/folio.py` already applies was defeated by a different
	endpoint: an agent refused `sales_invoice` on `get_folio` received the same
	invoice name from `check_out`, plus two identifiers `get_folio` never offers.
	`services/posting.py` is explicit that its elevated posting identity buys
	execution and not disclosure - "outside this block the agent still cannot
	read one Sales Invoice" - and this was the boundary that borrowed it.

	Shaped exactly like `api/folio.py`'s `_posting_disclosure`: the operational
	fact unconditionally, the identifiers only to a caller who may read them, and
	a `disclosure` map so a client can tell "not posted" from "not your business".
	The service return is untouched; the Night Audit and `retry_posting` consume
	it internally and must keep the identifiers.
	"""
	if posting is None:
		return None

	erp_doctype = posting.get("erp_doctype")

	disclosed = {
		# Everything the posting reported that is *not* an ERP identifier.
		#
		# Carried rather than re-listed, because the service reports facts the
		# caller that triggered the posting is entitled to and a whitelist written
		# by hand silently swallowed three of them: `duplicate`, which is the
		# idempotent-replay signal, and `allocated_amount`/`unallocated_amount`,
		# where `posting.py` says in as many words that "a surplus is a real
		# decision the desk has taken - the guest paid more than they owed - and it
		# should be visible to the caller that made it". `allocations` is excluded
		# by `_POSTING_IDENTIFIER_FIELDS` because its rows name Sales Invoices.
		**{
			field: value
			for field, value in posting.items()
			if field not in _POSTING_IDENTIFIER_FIELDS
		},
		# What the desk actually needs to know: did it post, and for how much.
		# The amount is the folio's own money, which a Stay writer may see - every
		# role holding Stay write also holds Guest Folio read.
		"posted": bool(posting.get("erp_document")),
		"erp_doctype": erp_doctype,
		"disclosure": {
			# Capability only, never record content. `False` means "you may not be
			# told this document's name" and never "nothing was posted"; whether
			# anything posted is `posted` above, which every caller gets.
			"log": frappe.has_permission(_POSTING_LOG_DOCTYPE, "read"),
			# Fails **closed** on a doctype this bench does not have. An earlier
			# draft answered `True` when the name was unknown, on the reasoning that
			# there was nothing to be entitled to - but the flag is then used to
			# decide disclosure, so an unrecognised name became an unconditional
			# reveal. `_exception_reference` in `api/night_audit.py` treats the same
			# input as a refusal and cites the rename patch; the two must agree.
			"erp_document": may_read_doctype(erp_doctype),
			"customer": frappe.has_permission(_CUSTOMER_DOCTYPE, "read"),
		},
	}

	if disclosed["disclosure"]["log"]:
		# `name` is the posting log's own key on the replay path, where `log` is
		# absent; both spellings are the same disclosure.
		for field in ("log", "name"):
			if posting.get(field):
				disclosed[field] = posting[field]

	if disclosed["disclosure"]["erp_document"] and posting.get("erp_document"):
		disclosed["erp_document"] = posting["erp_document"]

	if disclosed["disclosure"]["customer"] and posting.get("customer"):
		disclosed["customer"] = posting["customer"]

	return disclosed


def _disclose_posting_result(result: dict | None) -> dict | None:
	"""`checkout._post_to_erp`'s envelope, projected posting by posting.

	The service returns `{"invoice": <posting or None>, "payments": [<posting>, ...]}`
	- one ERP document for the charges and one per unposted payment - and each of
	those carries its own identifiers. The envelope's own shape is preserved
	exactly, because `check_out`'s response and this endpoint's are read by the
	checkout screen and by the Night Audit's catch-up path.
	"""
	if result is None:
		return None

	return {
		**result,
		"invoice": _disclose_posting(result.get("invoice")),
		"payments": [_disclose_posting(row) for row in result.get("payments") or []],
	}


@frappe.whitelist(methods=["GET"])
def summary(stay: str) -> dict:
	"""What the guest owes and anything blocking departure.

	`authorise_document` authorises the Stay; `_disclose_checkout` decides how
	much of the folio attached to it this caller may be told (16.7.5-R1B).
	"""
	authorise_document(STAY_DOCTYPE, stay, "read")

	return _disclose_checkout(
		service.get_checkout_summary(stay),
		may_read_folio=frappe.has_permission(FOLIO_DOCTYPE, "read"),
	)


@frappe.whitelist(methods=["POST"])
def check_out(
	stay: str,
	post_to_erp: int = 1,
	allow_open_balance: int = 0,
	reason: str | None = None,
) -> dict:
	"""Settle, post and release the room."""
	authorise_document(STAY_DOCTYPE, stay, "write")

	result = service.check_out(
		stay,
		post_to_erp=bool(int(post_to_erp or 0)),
		allow_open_balance=bool(int(allow_open_balance or 0)),
		reason=reason,
	)

	# The ERP identifiers in `posting` are not this endpoint's to disclose; see
	# `_disclose_posting`. Every role holding Stay write also holds Guest Folio
	# read, so the folio figures beside it need no gate here - which is why only
	# the posting block is projected.
	if "posting" in result:
		result = {**result, "posting": _disclose_posting_result(result["posting"])}

	return result


@frappe.whitelist(methods=["POST"])
def reverse_checkout(stay: str, reason: str) -> dict:
	"""Undo a checkout. Requires front office and finance authority."""
	authorise_document(STAY_DOCTYPE, stay, "write")

	result = service.reverse_checkout(stay, reason)

	# `standing_invoices` is a list of `Sales Invoice` names, and no hospitality
	# role holds read on that DocType - the only grant in the app is to the posting
	# service user. `CHECKOUT_REVERSAL_ROLES` is narrow but includes Front Office
	# Manager, who `api/folio.py` already refuses the same invoice name to.
	#
	# Reported rather than fixed in the first R1B pass, on the grounds that the
	# note beside it is genuinely operational - finance must know a standing
	# invoice is outstanding. That reasoning survives; publishing the *names* to do
	# it does not, once `check_out`, `post_folio` and `retry_posting` have all been
	# projected for exactly this audience. Fixing three of four endpoints that
	# return the same kind of payload fixes none of them.
	#
	# The operational fact is kept unconditionally and made explicit as a count, so
	# the screen can still say "two invoices need finance's attention" without
	# naming them. `Checkout.vue` renders the note either way.
	# `cancelled_invoices` is the same disclosure - `Sales Invoice` names - under a
	# name that describes the problem instead of the payload, so it is gated by the
	# same permission and counted the same way. `needs_erp_reconciliation` is a
	# boolean about this folio's own consistency and is kept unconditionally: it is
	# what tells the caller to stop, and a screen that could not see it would go on
	# treating the reversal as complete.
	invoices = result.get("standing_invoices") or []
	cancelled = result.get("cancelled_invoices") or []
	may_read_invoices = may_read_doctype("Sales Invoice")

	withheld = ("standing_invoices", "cancelled_invoices")

	disclosed = {
		**{field: value for field, value in result.items() if field not in withheld},
		"standing_invoice_count": len(invoices),
		"cancelled_invoice_count": len(cancelled),
		"disclosure": {field: may_read_invoices for field in withheld},
	}

	if may_read_invoices:
		if invoices:
			disclosed["standing_invoices"] = invoices

		if cancelled:
			disclosed["cancelled_invoices"] = cancelled

	return disclosed


@frappe.whitelist(methods=["GET"])
def reconciliation(property: str | None = None) -> dict:
	"""Failed postings and folios that do not agree with ERPNext."""
	require_role(RECONCILIATION_ROLES)
	property_name = resolve_property(property)

	# Projected, never published raw. `get_failed_postings` returns the
	# `Financial Posting Log`'s `error_message` and the durable ledger's
	# `last_error` - both truncated `str(exc)` - and this endpoint used to hand
	# them to a browser. Its own shape is fixed by its test and by what Night
	# Audit reads, so it is projected here rather than narrowed there.
	failed = finance_messages.safe_failed_postings(
		posting_service.get_failed_postings(property_name)
	)

	unposted = posting_service.closed_folios_with_unposted_charges(property_name)

	return {
		"property": property_name,
		"failed_postings": failed,
		"closed_folios_with_unposted_charges": unposted,
	}


@frappe.whitelist(methods=["GET"])
def reconcile_folio(folio: str) -> dict:
	"""Compare one folio against what actually reached ERPNext."""
	require_role(RECONCILIATION_ROLES)
	authorise_document(FOLIO_DOCTYPE, folio, "read")

	# `erp_invoices` and `erp_payment_entries` are lists of Sales Invoice and
	# Payment Entry names. `RECONCILIATION_ROLES` is narrow, but Night Auditor,
	# Hotel Manager and General Manager are all in it and none of them holds read
	# on either DocType - the same audience `post_folio` and `retry_posting` are
	# projected for.
	#
	# The variance figures themselves stay: this endpoint is `Guest Folio`
	# -authorised, so its money is the caller's to see, and the counts are what
	# finance works the reconciliation from.
	result = posting_service.reconcile_folio(folio)

	# `currency_mismatch` is here because it is also a list of Sales Invoice
	# names - it was missed on the first pass, which gated the two keys whose
	# names said "erp" and left the third, which is the same disclosure under a
	# name that describes the problem rather than the payload.
	gated = {
		"erp_invoices": "Sales Invoice",
		"erp_payment_entries": "Payment Entry",
		"currency_mismatch": "Sales Invoice",
		# Credit notes are Sales Invoices, raised in ERPNext by finance, and the
		# list names them. `erp_returned` is a figure rather than an identifier
		# and stays unconditionally, for the reason the variance figures do: this
		# endpoint is folio-authorised, so its money is the caller's to see.
		"erp_credit_notes": "Sales Invoice",
	}

	disclosure = {
		field: frappe.has_permission(doctype, "read") for field, doctype in gated.items()
	}

	# `stale_postings` is excluded from the spread as well as gated below. It is not
	# in `gated` because its rows are projected field by field rather than passed or
	# withheld whole, but leaving it out of the exclusion would splice the raw rows -
	# ERP document names included - into the response and rely on the projection
	# further down overwriting them. That happens to hold today and is one edited
	# condition away from not holding.
	withheld = set(gated) | {"stale_postings"}

	disclosed = {
		**{field: value for field, value in result.items() if field not in withheld},
		**{field: result[field] for field in gated if disclosure[field] and field in result},
		"disclosure": disclosure,
	}

	# `failed_postings` carries the raw `error_message`, which is what
	# `finance_messages` exists to keep out of a browser.
	#
	# Projected here rather than routed through `finance_messages.safe_failed_postings`,
	# deliberately. That function was written for `get_failed_postings`' row shape,
	# which joins the durable ledger; `reconcile_folio` produces only
	# `name`/`posting_type`/`error_message`/`attempts`. Borrowing it does not crash -
	# every access is `row.get` - but it reads a `operation_status` that is not there,
	# so `_NO_RETRY` can never fire and every row would be asserted retryable with
	# "This posting did not reach the accounting system and can be retried." For a
	# posting whose durable outcome is `Needs Reconciliation` that is exactly the
	# false claim `finance_messages` exists to prevent, and offering a Retry button
	# on it would throw rather than act.
	#
	# So the raw text is dropped and nothing is asserted in its place. The row keeps
	# its posting-log name, which every `RECONCILIATION_ROLES` holder may read, and
	# the `reconciliation` endpoint remains the place that classifies a failure.
	if result.get("failed_postings"):
		disclosed["failed_postings"] = [
			{field: value for field, value in row.items() if field != "error_message"}
			for row in result["failed_postings"]
		]

	# `stale_postings` rows name an ERP document, which is the same disclosure the
	# three keys above are gated on - so the name is dropped unless the caller may
	# read it. What is left is the posting-log name, the type, the status and the
	# amount: enough for finance to open the log row and work it, and for the screen
	# to say *why* the folio does not reconcile, which is the whole point of the key.
	# `needs_erp_reconciliation` is a boolean and stays unconditionally.
	#
	# Rebuilt field by field rather than by popping two keys, so a field added to
	# the service's row shape later has to be considered here before it is published.
	#
	# `may_read_doctype` rather than `frappe.has_permission`, matching
	# `_disclose_posting` above: the doctype comes off the row, so it is the
	# polymorphic case that helper exists for, and it fails closed on a name that is
	# not a DocType at all.
	#
	# Outside the `if`, unconditionally: `disclosure` is a claim about what this
	# response withheld, and a key that appears only when there is something to
	# withhold lets a client tell the two cases apart by its absence - the exact
	# leak-by-omission this module refuses at `standing_invoices`. Keyed
	# `stale_postings`, matching the payload field, so a client reading
	# `disclosure[field]` gets an answer rather than `undefined`.
	stale = result.get("stale_postings") or []
	may_name = {row["erp_doctype"]: may_read_doctype(row["erp_doctype"]) for row in stale}

	# True when nothing was withheld - which is honest for an empty list, and for a
	# mixed-doctype list is False as soon as *any* row's document was dropped. It
	# cannot claim disclosure that did not happen, and it cannot silently pass a
	# partially-redacted list off as complete.
	disclosed["disclosure"]["stale_postings"] = all(may_name.get(row["erp_doctype"]) for row in stale)

	if stale:
		disclosed["stale_postings"] = [
			{
				"log": row["log"],
				"posting_type": row["posting_type"],
				"posting_status": row["posting_status"],
				"amount": row["amount"],
				# `erp_doctype` is emitted unconditionally, matching `_disclose_posting`
				# above. Withholding it while publishing `posting_type`, which carries the
				# same value on every row `_mark_posted` has written, would be a gate that
				# reads as protection and provides none. The document's *name* is the
				# disclosure, and that is what is gated.
				"erp_doctype": row["erp_doctype"],
				**({"erp_document": row["erp_document"]} if may_name.get(row["erp_doctype"]) else {}),
			}
			for row in stale
		]

	return disclosed


@frappe.whitelist(methods=["POST"])
def withdraw_posting(log: str, reason: str) -> dict:
	"""Withdraw the PMS's claim on a posting the ledger no longer supports.

	The finance end of the recovery path. `retry_posting` beside it refuses a
	Posted row whose document has left the ledger, and it is right to: the
	folio's charge rows are still stamped and re-sending under the same key would
	either double-post or post a batch that no longer matches the stamps. This is
	the other answer - record that the claim is empty, and let finance settle the
	folio from there.

	Deliberately *not* on `RECONCILIATION_ROLES`. That set exists so a Night
	Auditor can see the reconciliation queue; writing off a claim on the ledger is
	a decision for the roles in `WITHDRAWAL_ROLES`, and the service re-checks it.
	The property is re-checked there too, against the posting's own record rather
	than anything sent here.

	The response names nothing the caller may not read: `log` is their own
	argument, already authorised above, and no accounting document appears in it.
	"""
	require_role(posting_service.WITHDRAWAL_ROLES)
	authorise_document(posting_service.POSTING_LOG, log, "read")

	return posting_service.withdraw_stale_posting(log, reason)


@frappe.whitelist(methods=["POST"])
def rearm_posting_operation(operation_key: str, reason: str) -> dict:
	"""Re-arm an Abandoned folio-posting operation once its cause is fixed.

	The operator exit from a Night Audit stranded by an abandoned posting (F-NA1):
	after correcting the configuration that made the posting fail (e.g. mapping the
	missing tax template), finance re-arms the operation and it posts. The service
	re-checks the role (`WITHDRAWAL_ROLES`) and the property from the operation's
	own record, refuses anything that is not a safe-retry folio posting, and refuses
	if the operation names an ERP document that is still live - so this can never
	post a second invoice for one that already exists. It is not the deferred
	Finance Recovery: it only re-attempts work whose side effect is proven absent.
	"""
	require_role(posting_service.WITHDRAWAL_ROLES)

	return posting_service.rearm_abandoned_posting(operation_key, reason)


@frappe.whitelist(methods=["POST"])
def retry_posting(log: str) -> dict:
	"""Retry a failed posting under its original idempotency key."""
	require_role(RECONCILIATION_ROLES)
	authorise_document(posting_service.POSTING_LOG, log, "read")

	# Projected exactly as `post_folio` is, and for the identical reason: a
	# successful retry returns `post_folio_invoice`'s own shape, so this endpoint
	# handed out the `Sales Invoice` name and the ERPNext `Customer` that
	# `post_folio` beside it was just changed to withhold, to the same role set.
	# Fixing one of two endpoints that return the same payload fixes neither.
	#
	# The `retried` and `status` keys are the operational answer and are kept.
	# Rebuilt from the disclosed projection *outwards*, never by spreading the raw
	# result first: `_disclose_posting` omits the identifiers rather than nulling
	# them, so a `{**result, **disclosed}` merge would leave every one of them in
	# place and read as if it had redacted something.
	result = posting_service.retry_posting(log)

	# No ERP document named means nothing to project *about*, but the result can
	# still carry `name` and `error_message` - so it is stripped rather than
	# returned whole. Every disclosure boundary in this module fails closed; this
	# one used to be the exception.
	#
	# `log` is added back unconditionally, and that is not a gap: `log` is the
	# caller's own argument, and `authorise_document` above has already proved they
	# may read that record. Asking `may_read_doctype` again here would be a check
	# whose answer is necessarily yes, which reads as protection and is not.
	if not result.get("erp_doctype"):
		return {
			**{
				field: value
				for field, value in result.items()
				if field not in _POSTING_IDENTIFIER_FIELDS
			},
			"log": log,
			# Emitted on both paths, so a client cannot tell them apart by the
			# absence of the map itself.
			"disclosure": {
				"log": True,
				"erp_document": False,
				"customer": may_read_doctype(_CUSTOMER_DOCTYPE),
			},
		}

	# `_disclose_posting` already carries every non-identifier field through, so
	# this merge only re-adds the keys `retry_posting` itself wraps the posting in -
	# `retried` and `status`.
	carried = {
		field: value
		for field, value in result.items()
		if field not in _POSTING_IDENTIFIER_FIELDS
	}

	return {**carried, **(_disclose_posting(result) or {})}


@frappe.whitelist(methods=["POST"])
def post_folio(folio: str) -> dict:
	"""Post a folio's invoice and payments without checking the guest out.

	Used by the Night Audit and by finance catching up a folio that failed to
	post at checkout.
	"""
	require_role(RECONCILIATION_ROLES)
	authorise_document(FOLIO_DOCTYPE, folio, "write")

	# Projected for the same reason as `check_out`, and it is not redundant here
	# even though `RECONCILIATION_ROLES` is narrow: Night Auditor, Hotel Manager
	# and General Manager are all in it and none of them holds `Sales Invoice` or
	# `Payment Entry` read. They keep the posting-log name, which they may read.
	return _disclose_posting_result(service._post_to_erp(folio))
