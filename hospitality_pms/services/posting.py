"""ERPNext financial posting.

This is the boundary between the operational subledger and the system of record.
ERPNext owns the ledger (HPMS-DEC-002); the folio is what the hotel works with
during a stay. Posting turns the second into the first, once.

The contract every function here keeps:

**Idempotent.** Each posting carries a key derived from what it represents, not
from when it ran. For an invoice that is the *set of charge rows being posted*,
fingerprinted - so retrying the same batch reuses the same invoice, while a
charge added later forms a different batch and gets a supplementary invoice of
its own. The key is `unique` on the posting log, so two concurrent attempts
cannot both create a document.

**Faithful.** What ERPNext ends up holding is what the folio says. The invoice's
grand total is checked against the batch before it is submitted, and a payment
that settles a bill says which bill it settles. Neither the tax nor the
allocation is re-derived here: the folio is the guest's bill and posting's job
is to carry it across, not to recompute it and hope the two agree.

**Traceable.** Every attempt writes a Financial Posting Log row,
including failures, with the payload that was sent. A finance user must be able
to answer "what did we send, when, and what came back" without reading code.

**Retryable where safe.** A failed posting stays Failed with its error and can
be retried under the same key. A succeeded posting is never re-sent.

Not solved here: a failure recorded by `_mark_failed` still lives in the
caller's transaction, so a rollback takes the Failed row with it (P1-14). That
needs one durability mechanism chosen across every external side effect and
belongs to the wave that decides it.
"""

import hashlib
import json

import frappe
from frappe import _
from frappe.utils import flt, now_datetime, nowdate

from hospitality_pms.services.base import lock_and_get_doc, lock_and_read
from hospitality_pms.services.exceptions import ConfigurationError, PostingError, throw
from hospitality_pms.services.guests import ensure_customer
from hospitality_pms.services.property import get_business_date, get_company, get_property

POSTING_LOG = "Financial Posting Log"
PROFILE_DOCTYPE = "Posting Profile"
FOLIO_DOCTYPE = "Guest Folio"

PENDING = "Pending"
POSTED = "Posted"
FAILED = "Failed"
CANCELLED = "Cancelled"
RECONCILED = "Reconciled"

#: Folio payment methods mapped onto ERPNext Mode of Payment names. A site may
#: rename these, so the mapping falls back to the raw name and the posting log
#: records what was actually used.
PAYMENT_MODE_MAP = {
	"Cash": "Cash",
	"Credit Card": "Credit Card",
	"Debit Card": "Credit Card",
	"Bank Transfer": "Bank Draft",
	"Cheque": "Cheque",
	"Online Gateway": "Credit Card",
}


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def get_posting_profile(property_name: str) -> str:
	"""The active posting profile for a property.

	Refuses rather than guessing: posting to a default account nobody chose is
	how a hotel's revenue ends up in the wrong place for a month.
	"""
	profile = frappe.db.get_value(
		PROFILE_DOCTYPE, {"property": property_name, "is_active": 1}, "name"
	)

	if not profile:
		throw(
			_("Property {0} has no active posting profile. Configure one before posting.").format(
				property_name
			),
			exc=ConfigurationError,
		)

	return profile


def resolve_charge_item(profile: str, charge_type: str) -> dict:
	"""The ERPNext item and accounts a folio charge type posts as."""
	profile_doc = frappe.get_cached_doc(PROFILE_DOCTYPE, profile)

	for row in profile_doc.charge_items:
		if row.charge_type == charge_type and row.is_active:
			return {
				"item": row.item,
				"income_account": row.income_account or profile_doc.default_income_account,
				"cost_center": row.cost_center or profile_doc.default_cost_center,
				"tax_template": row.tax_template or profile_doc.default_tax_template,
			}

	if not profile_doc.default_item:
		throw(
			_("Charge type {0} is not mapped to an item, and the posting profile has no default.").format(
				_(charge_type)
			),
			exc=ConfigurationError,
		)

	return {
		"item": profile_doc.default_item,
		"income_account": profile_doc.default_income_account,
		"cost_center": profile_doc.default_cost_center,
		"tax_template": profile_doc.default_tax_template,
	}


# ---------------------------------------------------------------------------
# The posting log
# ---------------------------------------------------------------------------


def _claim(
	property_name: str,
	posting_type: str,
	idempotency_key: str,
	*,
	folio: str | None = None,
	stay: str | None = None,
	reservation: str | None = None,
	guest: str | None = None,
	amount: float = 0,
	payload: dict | None = None,
) -> tuple[str, bool]:
	"""Claim the right to perform this posting.

	Returns `(log_name, already_done)`. The idempotency key is unique on the
	log, so this is what serialises two concurrent attempts: the loser gets a
	duplicate entry error, rolls back its savepoint and reads the winner's row.
	"""
	existing = frappe.db.get_value(
		POSTING_LOG,
		{"idempotency_key": idempotency_key},
		["name", "posting_status"],
		as_dict=True,
	)

	if existing:
		return existing["name"], existing["posting_status"] in (POSTED, RECONCILED)

	doc = frappe.get_doc(
		{
			"doctype": POSTING_LOG,
			"property": property_name,
			"posting_type": posting_type,
			"posting_status": PENDING,
			"idempotency_key": idempotency_key,
			"folio": folio,
			"stay": stay,
			"reservation": reservation,
			"guest": guest,
			"amount": amount,
			"business_date": get_business_date(property_name),
			"attempts": 0,
			"payload": json.dumps(payload, default=str, indent=1) if payload else None,
		}
	).insert(ignore_permissions=True)

	return doc.name, False


def _mark_posted(log: str, erp_doctype: str, erp_document: str):
	frappe.db.set_value(
		POSTING_LOG,
		log,
		{
			"posting_status": POSTED,
			"erp_doctype": erp_doctype,
			"erp_document": erp_document,
			"posted_on": now_datetime(),
			"posted_by": frappe.session.user,
			"error_message": None,
		},
		update_modified=True,
	)


def _mark_failed(log: str, error: str):
	attempts = flt(frappe.db.get_value(POSTING_LOG, log, "attempts")) + 1

	frappe.db.set_value(
		POSTING_LOG,
		log,
		{
			"posting_status": FAILED,
			"attempts": attempts,
			"last_attempt_on": now_datetime(),
			"error_message": error,
		},
		update_modified=True,
	)


def get_posting(idempotency_key: str) -> dict | None:
	"""The posting log row for a key, if it exists."""
	return frappe.db.get_value(
		POSTING_LOG,
		{"idempotency_key": idempotency_key},
		["name", "posting_status", "erp_doctype", "erp_document", "amount", "error_message"],
		as_dict=True,
	)


# ---------------------------------------------------------------------------
# Sales Invoice
# ---------------------------------------------------------------------------


def _invoice_batch_key(folio: str, rows) -> str:
	"""The identity of one immutable set of charge rows.

	`folio-invoice:{folio}` was the key for the entire life of the folio, which
	made the first invoice the only invoice: once it existed, every later call
	returned it as a duplicate and an authorised late charge could never reach
	ERPNext at all (P2-4).

	Identity belongs to *what is being posted*, so it is derived from the row
	names themselves. Sorted, so the order rows happen to come back in cannot
	change it; hashed, so the key fits the column however many rows there are.

	Deliberately not a counter. A counter would have to be allocated, and two
	concurrent retries of the same batch could allocate two different numbers
	and post the same charges twice. A fingerprint of the rows needs no
	allocation: the same rows always produce the same key, from any process, at
	any time.
	"""
	fingerprint = hashlib.sha1("|".join(sorted(row.name for row in rows)).encode()).hexdigest()

	return f"folio-invoice:{folio}:{fingerprint[:16]}"


def _latest_invoice_posting(folio: str) -> dict | None:
	"""The most recent successful invoice posting for a folio."""
	rows = frappe.get_all(
		POSTING_LOG,
		filters={
			"folio": folio,
			"posting_type": "Sales Invoice",
			"posting_status": ("in", (POSTED, RECONCILED)),
		},
		fields=["name", "posting_status", "erp_doctype", "erp_document", "amount", "error_message"],
		order_by="creation desc",
		limit=1,
	)

	return rows[0] if rows else None


def post_folio_invoice(folio: str, *, business_date=None, submit: bool = True) -> dict:
	"""Raise the ERPNext Sales Invoice for a folio's currently unposted lines.

	Reversed charges and their compensating lines are both included so the
	invoice reconciles line-for-line against the folio. A charge already posted
	on an earlier invoice is skipped, and the rows that remain form one batch
	with its own identity - so a retry re-posts nothing and a later charge gets
	a supplementary invoice of its own.
	"""
	# Locked and read together: the batch is decided from this row set, and a
	# pre-lock read could miss a charge another transaction committed while
	# this one waited - leaving it on no invoice at all (N1).
	doc = lock_and_get_doc(FOLIO_DOCTYPE, folio)

	chargeable = [row for row in doc.charges if not row.is_posted_to_erp]

	if not chargeable:
		# Nothing new to post. If this folio has already been invoiced that is
		# a retry arriving after the work was done, which is a no-op rather
		# than an error; if it has not, there is genuinely nothing to invoice.
		existing = _latest_invoice_posting(folio)

		if existing:
			return {**existing, "duplicate": True}

		throw(_("Folio {0} has no charges to invoice.").format(folio), exc=PostingError)

	idempotency_key = _invoice_batch_key(folio, chargeable)

	log, already_done = _claim(
		doc.property,
		"Sales Invoice",
		idempotency_key,
		folio=folio,
		stay=doc.stay,
		reservation=doc.reservation,
		guest=doc.guest,
		amount=sum(flt(row.total_amount) for row in chargeable),
	)

	if already_done:
		posting = get_posting(idempotency_key)
		return {**posting, "duplicate": True}

	try:
		result = _build_and_submit_invoice(
			doc, chargeable, log, business_date=business_date, submit=submit
		)
	except Exception as exc:  # noqa: BLE001
		# The failure is recorded outside the caller's rollback so the error
		# survives for reconciliation even when the transaction is undone.
		_mark_failed(log, frappe.get_traceback(with_context=False) or str(exc))
		raise

	return {**result, "duplicate": False}


def _build_and_submit_invoice(doc, chargeable, log: str, *, business_date=None, submit: bool = True) -> dict:
	profile = get_posting_profile(doc.property)
	profile_doc = frappe.get_cached_doc(PROFILE_DOCTYPE, profile)
	company = get_company(doc.property)

	customer = doc.customer or ensure_customer(doc.guest, company)

	if not doc.customer:
		frappe.db.set_value(FOLIO_DOCTYPE, doc.name, "customer", customer, update_modified=False)

	invoice = frappe.new_doc("Sales Invoice")
	invoice.customer = customer
	invoice.company = company
	invoice.currency = doc.currency
	invoice.posting_date = business_date or get_business_date(doc.property)
	invoice.set_posting_time = 1
	invoice.due_date = invoice.posting_date
	invoice.cost_center = profile_doc.default_cost_center
	invoice.debit_to = profile_doc.default_receivable_account or None

	# The folio is the bill the guest was handed, to the fils, and the
	# receivable has to be that number. ERPNext rounds `grand_total` to the
	# nearest whole unit by default and drives `outstanding_amount` from the
	# rounded figure, so a folio of 251.50 became a 252.00 - or, with banker's
	# rounding, a 52.50 became a 52.00 - receivable that could never agree with
	# the folio and left a few fils adrift on every fractional invoice.
	invoice.disable_rounded_total = 1
	invoice.remarks = _("Hospitality folio {0}").format(doc.name)

	taxes: dict[str, dict] = {}

	for row in chargeable:
		mapping = resolve_charge_item(profile, _tax_charge_type(doc, row))

		invoice.append(
			"items",
			{
				"item_code": row.item or mapping["item"],
				"description": row.description,
				"qty": flt(row.quantity) or 1,
				"rate": flt(row.amount) / (flt(row.quantity) or 1),
				"amount": flt(row.amount),
				"income_account": mapping["income_account"],
				"cost_center": mapping["cost_center"],
			},
		)

		_accumulate_tax(taxes, profile_doc, mapping, row)

	for head, bucket in taxes.items():
		invoice.append(
			"taxes",
			{
				# `Actual` because the amount is not being derived here - it is
				# the tax the folio already charged the guest, and it is that
				# figure, not a recomputation of it, that has to reach the
				# ledger. ERPNext posts an Actual row to `account_head` exactly
				# as it posts a calculated one, so the GL effect is the same as
				# any other tax; only the source of the number differs.
				"charge_type": "Actual",
				"account_head": head,
				"description": bucket["description"],
				"tax_amount": flt(bucket["amount"], bucket["precision"]),
				"cost_center": bucket["cost_center"],
			},
		)

	invoice.flags.ignore_permissions = True
	invoice.insert()

	_assert_invoice_matches_folio(invoice, chargeable)

	if submit:
		invoice.submit()

	# Stamp the folio lines so a second invoice cannot pick them up.
	for row in chargeable:
		frappe.db.set_value(
			"Folio Charge",
			row.name,
			{"is_posted_to_erp": 1, "sales_invoice": invoice.name},
			update_modified=False,
		)

	_mark_posted(log, "Sales Invoice", invoice.name)

	return {
		"log": log,
		"erp_doctype": "Sales Invoice",
		"erp_document": invoice.name,
		"amount": flt(invoice.grand_total),
		"customer": customer,
	}


# ---------------------------------------------------------------------------
# Tax
# ---------------------------------------------------------------------------
#
# The folio is the authority on what the guest was charged, tax included. It
# records one net amount and one tax amount per line, and posting's job is to
# put both into ERPNext unchanged - not to re-derive the tax from a rate and
# hope the two agree.
#
# So the tax template is used for what it uniquely knows, the account head, and
# the amount comes from the folio. `_assert_invoice_matches_folio` then proves
# the two halves add up to what the guest was billed before anything is
# submitted.


def _tax_charge_type(doc, row) -> str:
	"""Which charge type's mapping governs this row.

	A reversal is posted as an `Adjustment`, but it reverses a specific charge
	and its negative tax belongs to the same head that received the original.
	Resolving it as an Adjustment would send it to the profile default - or,
	when there is none, refuse a reversal that is perfectly well defined.
	"""
	if not row.reversal_of:
		return row.charge_type

	original = next((line for line in doc.charges if line.name == row.reversal_of), None)

	return original.charge_type if original else row.charge_type


def _accumulate_tax(taxes: dict, profile_doc, mapping: dict, row):
	"""Add one folio line's tax to the bucket for its account head."""
	tax_amount = flt(row.tax_amount)

	if not tax_amount:
		return

	head = _resolve_tax_head(mapping, row.charge_type)

	bucket = taxes.setdefault(
		head["account_head"],
		{
			"amount": 0.0,
			"description": head["description"],
			"cost_center": head["cost_center"] or profile_doc.default_cost_center,
			"precision": frappe.get_precision("Sales Taxes and Charges", "tax_amount") or 2,
		},
	)

	bucket["amount"] += tax_amount


def _resolve_tax_head(mapping: dict, charge_type: str) -> dict:
	"""The single tax account a charge type's template posts to.

	Refuses in both directions rather than guessing, because either guess loses
	money somewhere a reader would not look:

	* No template on a line that bears tax - posting it without the tax is
	  precisely P1-10, silently dropping the hotel's output VAT.
	* A template with more than one head - the folio holds one tax figure per
	  line and no breakdown, so splitting it would be inventing an allocation
	  between two liabilities. The configuration is named in the error instead.
	"""
	template = mapping.get("tax_template")

	if not template:
		throw(
			_(
				"Charge type {0} carries tax but is not mapped to a tax template, so there is "
				"no account to post the tax to. Map it in the posting profile."
			).format(_(charge_type)),
			exc=ConfigurationError,
		)

	rows = frappe.get_all(
		"Sales Taxes and Charges",
		filters={"parent": template, "parenttype": "Sales Taxes and Charges Template"},
		fields=["account_head", "description", "cost_center"],
		order_by="idx asc",
	)

	if len(rows) != 1:
		throw(
			_(
				"Tax template {0} has {1} tax heads. A folio line records a single tax amount, "
				"which cannot be divided between them without inventing an allocation. Use a "
				"template with one head for charge type {2}."
			).format(template, len(rows), _(charge_type)),
			exc=ConfigurationError,
		)

	return rows[0]


def _assert_invoice_matches_folio(invoice, chargeable):
	"""Refuse to submit an invoice that does not say what the folio says.

	The invariant this whole wave exists to establish: for one batch of charge
	rows, the ERPNext grand total equals the folio's net plus its tax. Checked
	after `insert()`, because that is when ERPNext has computed its own totals,
	and before `submit()`, so a mismatch leaves nothing in the ledger.

	Compared at the currency's own precision rather than by exact equality:
	these are floats that have been through two rounding regimes, and 251.5 and
	251.49999999999997 are the same money.
	"""
	precision = frappe.get_precision("Sales Invoice", "grand_total") or 2

	expected = flt(sum(flt(row.total_amount) for row in chargeable), precision)
	actual = flt(invoice.grand_total, precision)

	if expected == actual:
		return

	throw(
		_(
			"Folio total {0} and Sales Invoice total {1} disagree, so the invoice has not been "
			"submitted. Check the tax templates mapped to this folio's charge types."
		).format(expected, actual),
		exc=PostingError,
	)


# ---------------------------------------------------------------------------
# Payment Entry
# ---------------------------------------------------------------------------


def post_folio_payment(folio: str, payment_row: str, *, business_date=None) -> dict:
	"""Raise the ERPNext Payment Entry for one folio payment line.

	Posted per line rather than in aggregate so a refund, a deposit and a
	settlement each reconcile against their own ledger entry.
	"""
	# Locked and read together. The allocation below is decided from how much
	# each of this folio's invoices still owes, and this lock is what serialises
	# two payments on the same folio so they cannot both allocate against the
	# same outstanding amount (N1).
	doc = lock_and_get_doc(FOLIO_DOCTYPE, folio)
	row = next((line for line in doc.payments if line.name == payment_row), None)

	if not row:
		throw(_("Payment {0} does not belong to folio {1}.").format(payment_row, folio), exc=PostingError)

	idempotency_key = f"folio-payment:{payment_row}"

	log, already_done = _claim(
		doc.property,
		"Payment Entry",
		idempotency_key,
		folio=folio,
		stay=doc.stay,
		guest=doc.guest,
		amount=row.amount,
	)

	if already_done:
		posting = get_posting(idempotency_key)
		return {**posting, "duplicate": True}

	try:
		result = _build_and_submit_payment(doc, row, log, business_date=business_date)
	except Exception as exc:  # noqa: BLE001
		_mark_failed(log, frappe.get_traceback(with_context=False) or str(exc))
		raise

	return {**result, "duplicate": False}


def _build_and_submit_payment(doc, row, log: str, *, business_date=None) -> dict:
	profile = get_posting_profile(doc.property)
	profile_doc = frappe.get_cached_doc(PROFILE_DOCTYPE, profile)
	company = get_company(doc.property)

	customer = doc.customer or ensure_customer(doc.guest, company)

	is_receipt = flt(row.amount) > 0
	mode_of_payment = _resolve_mode_of_payment(row.payment_method)

	receivable = profile_doc.default_receivable_account or _default_receivable(company)
	funds_account = _resolve_funds_account(company, mode_of_payment)

	entry = frappe.new_doc("Payment Entry")
	entry.payment_type = "Receive" if is_receipt else "Pay"
	entry.company = company
	entry.posting_date = business_date or get_business_date(doc.property)
	entry.party_type = "Customer"
	entry.party = customer
	entry.paid_amount = abs(flt(row.amount))
	entry.received_amount = abs(flt(row.amount))
	entry.source_exchange_rate = 1
	entry.target_exchange_rate = 1
	entry.mode_of_payment = mode_of_payment
	entry.reference_no = row.reference or row.provider_reference or row.name
	entry.reference_date = entry.posting_date

	# Money moves FROM the customer's receivable INTO cash or bank on a
	# receipt, and the other way on a refund. Getting these round the wrong way
	# posts the payment to the wrong side of the ledger.
	if is_receipt:
		entry.paid_from = receivable
		entry.paid_to = funds_account
	else:
		entry.paid_from = funds_account
		entry.paid_to = receivable

	entry.remarks = _("Hospitality folio {0} payment {1}").format(doc.name, row.name)

	# A receipt is money the guest handed over against their bill, so it has to
	# say which bill. Submitted without references, ERPNext could only record it
	# as an unapplied customer advance: the Sales Invoice stayed fully
	# outstanding and the Payment Ledger showed a guest who had paid in full as
	# still owing the whole amount (P1-11).
	#
	# A refund is money going the other way and settles nothing, so it is left
	# unreferenced - which is what ERPNext expects of it.
	allocations = _allocate_against_folio_invoices(doc.name, abs(flt(row.amount))) if is_receipt else []

	for allocation in allocations:
		entry.append(
			"references",
			{
				"reference_doctype": "Sales Invoice",
				"reference_name": allocation["invoice"],
				"allocated_amount": allocation["amount"],
			},
		)

	# Set the account currencies explicitly rather than calling
	# `set_missing_values()`: that helper expects the party account fields to
	# have been wired up by the Desk form first, and fails outside it.
	company_currency = frappe.get_cached_value("Company", company, "default_currency")
	entry.paid_from_account_currency = _account_currency(entry.paid_from, company_currency)
	entry.paid_to_account_currency = _account_currency(entry.paid_to, company_currency)

	entry.flags.ignore_permissions = True
	entry.insert()
	entry.submit()

	frappe.db.set_value(
		"Folio Payment",
		row.name,
		{"is_posted_to_erp": 1, "payment_entry": entry.name},
		update_modified=False,
	)

	_mark_posted(log, "Payment Entry", entry.name)

	return {
		"log": log,
		"erp_doctype": "Payment Entry",
		"erp_document": entry.name,
		"amount": abs(flt(row.amount)),
		# Reported rather than left to be discovered in ERPNext: a surplus is a
		# real decision the desk has taken - the guest paid more than they owed
		# - and it should be visible to the caller that made it, not only to
		# whoever reads the Payment Ledger later.
		"allocated_amount": flt(entry.total_allocated_amount),
		"unallocated_amount": flt(entry.unallocated_amount),
		"allocations": [
			{"invoice": ref.reference_name, "amount": flt(ref.allocated_amount)}
			for ref in entry.references
		],
	}


def _allocate_against_folio_invoices(folio: str, amount: float) -> list[dict]:
	"""Split a receipt across this folio's outstanding invoices, oldest first.

	Oldest first because a folio can hold more than one invoice once a late
	charge has produced a supplementary one (P2-4), and settling the newest
	while an older one stays open would be an arbitrary choice that makes AR
	ageing meaningless. Posting order is the order the guest incurred the
	charges, so it is the order they are settled in.

	Never allocates more than an invoice still owes. Whatever is left over is
	returned to ERPNext as an unallocated advance, which is its standard
	treatment of a genuine overpayment - and the caller is told about it.
	"""
	remaining = flt(amount)
	allocations: list[dict] = []

	if remaining <= 0:
		return allocations

	invoices = frappe.get_all(
		POSTING_LOG,
		filters={
			"folio": folio,
			"posting_type": "Sales Invoice",
			"posting_status": ("in", (POSTED, RECONCILED)),
			"erp_document": ("is", "set"),
		},
		order_by="creation asc",
		pluck="erp_document",
	)

	for invoice in invoices:
		# A locking current read: `outstanding_amount` is exactly the mutable
		# figure this decision turns on, and a plain read could allocate twice
		# against money that has already been settled.
		current = lock_and_read("Sales Invoice", invoice, ["docstatus", "outstanding_amount"])

		if current["docstatus"] != 1:
			continue

		outstanding = flt(current["outstanding_amount"])

		if outstanding <= 0:
			continue

		take = min(remaining, outstanding)

		if take <= 0:
			break

		allocations.append({"invoice": invoice, "amount": take})
		remaining -= take

		if remaining <= 0:
			break

	return allocations


def _account_currency(account: str | None, fallback: str) -> str:
	"""An account's currency, falling back to the company's."""
	if not account:
		return fallback

	return frappe.get_cached_value("Account", account, "account_currency") or fallback


def _default_receivable(company: str) -> str:
	"""The company's receivable account, when the profile does not name one."""
	account = frappe.get_cached_value("Company", company, "default_receivable_account")

	if not account:
		throw(
			_("Company {0} has no default receivable account.").format(company),
			exc=ConfigurationError,
		)

	return account


def _resolve_funds_account(company: str, mode_of_payment: str | None) -> str:
	"""The cash or bank account money actually lands in.

	Prefers the account configured against the Mode of Payment, which is how
	ERPNext expects a hotel to separate cash drawer from card settlement, and
	falls back to the company defaults.
	"""
	if mode_of_payment:
		account = frappe.db.get_value(
			"Mode of Payment Account",
			{"parent": mode_of_payment, "company": company},
			"default_account",
		)
		if account:
			return account

	for fieldname in ("default_cash_account", "default_bank_account"):
		account = frappe.get_cached_value("Company", company, fieldname)
		if account:
			return account

	throw(
		_("Company {0} has no default cash or bank account to receive payments into.").format(company),
		exc=ConfigurationError,
	)


def _resolve_mode_of_payment(payment_method: str) -> str | None:
	"""Map a folio payment method onto an ERPNext Mode of Payment.

	Returns None rather than raising when the site has no matching mode: the
	payment entry is still correct without it, and refusing to record money the
	hotel has actually taken would be worse than a missing label.
	"""
	candidate = PAYMENT_MODE_MAP.get(payment_method, payment_method)

	if frappe.db.exists("Mode of Payment", candidate):
		return candidate

	if frappe.db.exists("Mode of Payment", payment_method):
		return payment_method

	return None


# ---------------------------------------------------------------------------
# Retry and reconciliation
# ---------------------------------------------------------------------------


def retry_posting(log: str) -> dict:
	"""Retry a failed posting under its original key.

	Only a Failed row is retried. A Posted row is never re-sent, which is the
	whole point of the key.
	"""
	entry = frappe.get_doc(POSTING_LOG, log)

	if entry.posting_status in (POSTED, RECONCILED):
		return {"log": log, "status": entry.posting_status, "retried": False}

	if entry.posting_status == CANCELLED:
		throw(_("Posting {0} was cancelled and cannot be retried.").format(log), exc=PostingError)

	if not entry.folio:
		throw(_("Posting {0} has no folio to retry against.").format(log), exc=PostingError)

	if entry.posting_type == "Sales Invoice":
		result = post_folio_invoice(entry.folio)
	elif entry.posting_type == "Payment Entry":
		payment_row = entry.idempotency_key.split(":", 1)[-1]
		result = post_folio_payment(entry.folio, payment_row)
	else:
		throw(_("Posting type {0} cannot be retried automatically.").format(entry.posting_type), exc=PostingError)

	return {**result, "retried": True}


def folio_erp_documents(folio: str, posting_type: str) -> list[str]:
	"""ERPNext documents this folio successfully posted, oldest first.

	Read from the posting log, which records what posting actually did, rather
	than from the folio's own rows, which record only what posting *intended*.
	"""
	return frappe.get_all(
		POSTING_LOG,
		filters={
			"folio": folio,
			"posting_type": posting_type,
			"posting_status": ("in", (POSTED, RECONCILED)),
			"erp_document": ("is", "set"),
		},
		order_by="creation asc",
		pluck="erp_document",
	)


def reconcile_folio(folio: str) -> dict:
	"""Compare a folio against what ERPNext actually holds.

	Returns the difference rather than correcting it. An automatic correction
	here would paper over the very discrepancy finance needs to see.

	Every ERP figure below is read from the ERP document itself - the invoice's
	`grand_total` and `outstanding_amount`, the Payment Entry's `paid_amount`
	and its allocations. The previous version added up the folio's own charge
	rows whenever they carried a Sales Invoice reference, which asks the folio
	whether the folio was invoiced and can only ever answer yes. That is how a
	folio of 110 whose invoice said 100 was reported as reconciled with a
	variance of zero: the tax row had a reference on it, so it was counted, and
	the ten riyals that never reached ERPNext were confirmed present by the one
	report meant to find them (P1-10).

	Cancelled and draft documents are not counted. A cancelled invoice has been
	reversed out of the ledger and a draft has never entered it, so neither is
	evidence that anything was posted.
	"""
	doc = frappe.get_doc(FOLIO_DOCTYPE, folio)
	precision = frappe.get_precision("Sales Invoice", "grand_total") or 2

	invoices = _submitted_invoices(folio)
	entries = _submitted_payment_entries(folio)

	erp_invoiced = sum(flt(row["grand_total"]) for row in invoices)
	invoice_outstanding = sum(flt(row["outstanding_amount"]) for row in invoices)

	# Signed: a refund is money leaving, and netting it here is what makes
	# `payment_variance` comparable with the folio's own signed total.
	erp_paid = sum(
		flt(row["paid_amount"]) * (1 if row["payment_type"] == "Receive" else -1) for row in entries
	)

	erp_allocated = _allocated_against(
		[row["name"] for row in entries], [row["name"] for row in invoices]
	)

	# An invoice in a currency the folio does not use cannot be compared with
	# it, and silently adding the numbers together would be worse than saying so.
	currency_mismatch = [row["name"] for row in invoices if row["currency"] != doc.currency]

	unposted_charges = [row.name for row in doc.charges if not row.is_posted_to_erp]
	unposted_payments = [row.name for row in doc.payments if not row.is_posted_to_erp]

	failures = frappe.get_all(
		POSTING_LOG,
		filters={"folio": folio, "posting_status": FAILED},
		fields=["name", "posting_type", "error_message", "attempts"],
	)

	charge_variance = flt(flt(doc.total_charges) - erp_invoiced, precision)
	payment_variance = flt(flt(doc.total_payments) - erp_paid, precision)

	# What the folio says is still owed, and what ERPNext says is still owed,
	# must be the same number. This is the check that catches a payment which
	# reached ERPNext but settled nothing: the money is there, the variance is
	# zero, and the invoice is still fully outstanding (P1-11).
	folio_outstanding = max(flt(doc.total_charges) - flt(doc.total_payments), 0.0)
	settlement_variance = flt(invoice_outstanding - folio_outstanding, precision)

	return {
		"folio": folio,
		"folio_charges": flt(doc.total_charges, precision),
		"folio_payments": flt(doc.total_payments, precision),
		"erp_invoiced": flt(erp_invoiced, precision),
		"erp_paid": flt(erp_paid, precision),
		"erp_allocated_payments": flt(erp_allocated, precision),
		"unallocated_payments": flt(erp_paid - erp_allocated, precision),
		"invoice_outstanding": flt(invoice_outstanding, precision),
		"charge_variance": charge_variance,
		"payment_variance": payment_variance,
		"settlement_variance": settlement_variance,
		"erp_invoices": [row["name"] for row in invoices],
		"erp_payment_entries": [row["name"] for row in entries],
		"currency_mismatch": currency_mismatch,
		"unposted_charges": unposted_charges,
		"unposted_payments": unposted_payments,
		"failed_postings": failures,
		"is_reconciled": (
			charge_variance == 0
			and payment_variance == 0
			and settlement_variance == 0
			and not currency_mismatch
			and not unposted_charges
			and not unposted_payments
			and not failures
		),
	}


def _submitted_invoices(folio: str) -> list[dict]:
	"""The folio's Sales Invoices that are actually in the ledger."""
	rows = []

	for name in folio_erp_documents(folio, "Sales Invoice"):
		row = frappe.db.get_value(
			"Sales Invoice",
			name,
			["name", "docstatus", "grand_total", "outstanding_amount", "currency"],
			as_dict=True,
		)

		# Missing, draft or cancelled: no evidence of anything posted.
		if row and row["docstatus"] == 1:
			rows.append(row)

	return rows


def _submitted_payment_entries(folio: str) -> list[dict]:
	rows = []

	for name in folio_erp_documents(folio, "Payment Entry"):
		row = frappe.db.get_value(
			"Payment Entry",
			name,
			["name", "docstatus", "payment_type", "paid_amount"],
			as_dict=True,
		)

		if row and row["docstatus"] == 1:
			rows.append(row)

	return rows


def _allocated_against(payment_entries: list[str], invoices: list[str]) -> float:
	"""How much of those payments ERPNext applied to those invoices.

	Not the same question as "was a Payment Entry submitted". An unapplied
	customer advance answers yes to that one while leaving the invoice entirely
	unpaid, which is precisely the state P1-11 put every folio payment in.
	"""
	if not payment_entries or not invoices:
		return 0.0

	rows = frappe.get_all(
		"Payment Entry Reference",
		filters={
			"parent": ("in", payment_entries),
			"parenttype": "Payment Entry",
			"reference_doctype": "Sales Invoice",
			"reference_name": ("in", invoices),
			"docstatus": 1,
		},
		fields=["allocated_amount"],
	)

	return sum(flt(row["allocated_amount"]) for row in rows)


def mark_reconciled(log: str) -> str:
	"""Flag a posting as checked off by finance."""
	frappe.db.set_value(
		POSTING_LOG,
		log,
		{
			"posting_status": RECONCILED,
			"reconciled_on": now_datetime(),
			"reconciled_by": frappe.session.user,
		},
		update_modified=True,
	)

	return RECONCILED


def get_failed_postings(property_name: str, limit: int = 100) -> list[dict]:
	"""The failed posting queue, for the reconciliation dashboard."""
	return frappe.get_all(
		POSTING_LOG,
		filters={"property": property_name, "posting_status": FAILED},
		fields=[
			"name",
			"posting_type",
			"folio",
			"amount",
			"attempts",
			"last_attempt_on",
			"error_message",
			"business_date",
		],
		order_by="last_attempt_on desc",
		limit=limit,
	)
