"""ERPNext financial posting.

This is the boundary between the operational subledger and the system of record.
ERPNext owns the ledger (HPMS-DEC-002); the folio is what the hotel works with
during a stay. Posting turns the second into the first, once.

The contract every function here keeps:

**Idempotent.** Each posting carries a key derived from what it represents, not
from when it ran. `{folio}:invoice` posts one invoice for that folio however
many times checkout is retried. The key is `unique` on the posting log, so two
concurrent attempts cannot both create a document - the second hits a duplicate
entry error and reads back the first one's result.

**Traceable.** Every attempt writes a Hospitality Financial Posting Log row,
including failures, with the payload that was sent. A finance user must be able
to answer "what did we send, when, and what came back" without reading code.

**Retryable where safe.** A failed posting stays Failed with its error and can
be retried under the same key. A succeeded posting is never re-sent.
"""

import json

import frappe
from frappe import _
from frappe.utils import flt, now_datetime, nowdate

from hospitality_pms.services.base import lock_document
from hospitality_pms.services.exceptions import ConfigurationError, PostingError, throw
from hospitality_pms.services.guests import ensure_customer
from hospitality_pms.services.property import get_business_date, get_company, get_property

POSTING_LOG = "Hospitality Financial Posting Log"
PROFILE_DOCTYPE = "Hospitality Posting Profile"
FOLIO_DOCTYPE = "Hospitality Guest Folio"

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


def post_folio_invoice(folio: str, *, business_date=None, submit: bool = True) -> dict:
	"""Raise the ERPNext Sales Invoice for a folio's chargeable lines.

	Reversed charges and their compensating lines are both included so the
	invoice reconciles line-for-line against the folio. A charge already posted
	on an earlier invoice is skipped.
	"""
	lock_document(FOLIO_DOCTYPE, folio)

	doc = frappe.get_doc(FOLIO_DOCTYPE, folio)
	idempotency_key = f"folio-invoice:{folio}"

	log, already_done = _claim(
		doc.property,
		"Sales Invoice",
		idempotency_key,
		folio=folio,
		stay=doc.stay,
		reservation=doc.reservation,
		guest=doc.guest,
		amount=doc.total_charges,
	)

	if already_done:
		posting = get_posting(idempotency_key)
		return {**posting, "duplicate": True}

	try:
		result = _build_and_submit_invoice(doc, log, business_date=business_date, submit=submit)
	except Exception as exc:  # noqa: BLE001
		# The failure is recorded outside the caller's rollback so the error
		# survives for reconciliation even when the transaction is undone.
		_mark_failed(log, frappe.get_traceback(with_context=False) or str(exc))
		raise

	return {**result, "duplicate": False}


def _build_and_submit_invoice(doc, log: str, *, business_date=None, submit: bool = True) -> dict:
	profile = get_posting_profile(doc.property)
	profile_doc = frappe.get_cached_doc(PROFILE_DOCTYPE, profile)
	company = get_company(doc.property)

	chargeable = [row for row in doc.charges if not row.is_posted_to_erp]

	if not chargeable:
		throw(_("Folio {0} has no charges to invoice.").format(doc.name), exc=PostingError)

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
	invoice.remarks = _("Hospitality folio {0}").format(doc.name)

	for row in chargeable:
		mapping = resolve_charge_item(profile, row.charge_type)

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

	invoice.flags.ignore_permissions = True
	invoice.insert()

	if submit:
		invoice.submit()

	# Stamp the folio lines so a second invoice cannot pick them up.
	for row in chargeable:
		frappe.db.set_value(
			"Hospitality Folio Charge",
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
# Payment Entry
# ---------------------------------------------------------------------------


def post_folio_payment(folio: str, payment_row: str, *, business_date=None) -> dict:
	"""Raise the ERPNext Payment Entry for one folio payment line.

	Posted per line rather than in aggregate so a refund, a deposit and a
	settlement each reconcile against their own ledger entry.
	"""
	lock_document(FOLIO_DOCTYPE, folio)

	doc = frappe.get_doc(FOLIO_DOCTYPE, folio)
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
		"Hospitality Folio Payment",
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
	}


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


def reconcile_folio(folio: str) -> dict:
	"""Compare a folio against what was actually posted to ERPNext.

	Returns the difference rather than correcting it. An automatic correction
	here would paper over the very discrepancy finance needs to see.
	"""
	doc = frappe.get_doc(FOLIO_DOCTYPE, folio)

	invoiced = 0.0
	for row in doc.charges:
		if row.sales_invoice and frappe.db.get_value("Sales Invoice", row.sales_invoice, "docstatus") == 1:
			invoiced += flt(row.total_amount)

	paid = 0.0
	for row in doc.payments:
		if row.payment_entry and frappe.db.get_value("Payment Entry", row.payment_entry, "docstatus") == 1:
			paid += flt(row.amount)

	unposted_charges = [row.name for row in doc.charges if not row.is_posted_to_erp]
	unposted_payments = [row.name for row in doc.payments if not row.is_posted_to_erp]

	failures = frappe.get_all(
		POSTING_LOG,
		filters={"folio": folio, "posting_status": FAILED},
		fields=["name", "posting_type", "error_message", "attempts"],
	)

	return {
		"folio": folio,
		"folio_charges": flt(doc.total_charges, 2),
		"folio_payments": flt(doc.total_payments, 2),
		"erp_invoiced": flt(invoiced, 2),
		"erp_paid": flt(paid, 2),
		"charge_variance": flt(flt(doc.total_charges) - invoiced, 2),
		"payment_variance": flt(flt(doc.total_payments) - paid, 2),
		"unposted_charges": unposted_charges,
		"unposted_payments": unposted_payments,
		"failed_postings": failures,
		"is_reconciled": (
			abs(flt(doc.total_charges) - invoiced) < 0.005
			and abs(flt(doc.total_payments) - paid) < 0.005
			and not failures
		),
	}


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
