"""Guest Folio: the operational hospitality subledger.

The folio is **not** the general ledger (HPMS-DEC-003). ERPNext remains the
system of record; the folio is what the front desk works with during a stay and
what checkout reconciles against the invoice it raises.

Two properties are non-negotiable here:

**Idempotency.** Every charge and payment carries an idempotency key. A retried
night audit, a replayed gateway callback or a double-clicked button must post
once. `post_charge` and `post_payment` return the existing line unchanged when
the key has been seen (HPMS-DEC-031).

**No silent edits.** A posted charge is never modified or deleted. Corrections
are reversals: a new, negative line that references the original, with a reason
and an actor. That is what makes the folio reconcilable.
"""

import frappe
from frappe import _
from frappe.utils import flt, now_datetime, nowdate

from hospitality_pms.services.base import assert_transition, lock_document, require_role
from hospitality_pms.services.exceptions import FolioError, throw
from hospitality_pms.services.property import get_business_date

FOLIO_DOCTYPE = "Hospitality Guest Folio"
FOLIO_LOG_DOCTYPE = "Hospitality Folio Log"

OPEN = "Open"
UNDER_REVIEW = "Under Review"
DISPUTED = "Disputed"
READY = "Ready for Settlement"
PARTIALLY_SETTLED = "Partially Settled"
SETTLED = "Settled"
CLOSED = "Closed"

#: Folio state machine, from Workflow Matrix section 4.
TRANSITIONS = {
	OPEN: {UNDER_REVIEW, DISPUTED, READY, CLOSED},
	UNDER_REVIEW: {DISPUTED, READY, OPEN},
	DISPUTED: {UNDER_REVIEW, READY},
	READY: {PARTIALLY_SETTLED, SETTLED, DISPUTED, UNDER_REVIEW},
	PARTIALLY_SETTLED: {SETTLED, DISPUTED, READY},
	SETTLED: {CLOSED, UNDER_REVIEW},
	CLOSED: {UNDER_REVIEW},
}

#: States in which new charges may still be posted. A settled or closed folio
#: is refused, which is what stops a late minibar charge landing after the
#: guest has paid and gone.
POSTABLE_STATES = (OPEN, UNDER_REVIEW, DISPUTED, READY, PARTIALLY_SETTLED)

#: Reversals, adjustments and reopening are finance decisions
#: (Roles Matrix section 4).
FINANCE_ROLES = (
	"Finance Manager",
	"Accounts User",
	"Hospitality Administrator",
	"System Manager",
)

ADJUSTMENT_ROLES = (
	"Finance Manager",
	"Front Office Manager",
	"Hotel Manager",
	"General Manager",
	"Hospitality Administrator",
	"System Manager",
)

REOPEN_ROLES = (
	"Finance Manager",
	"Hotel Manager",
	"General Manager",
	"Hospitality Administrator",
	"System Manager",
)

#: Charge types that reduce the balance rather than increase it.
CREDIT_CHARGE_TYPES = ("Discount",)


# ---------------------------------------------------------------------------
# Opening
# ---------------------------------------------------------------------------


def open_folio(
	property_name: str,
	guest: str,
	*,
	stay: str | None = None,
	reservation: str | None = None,
	room: str | None = None,
	folio_type: str = "Master",
	parent_folio: str | None = None,
	billing_instructions: str | None = None,
) -> str:
	"""Open a folio. One master folio per stay.

	Returns the existing master folio if the stay already has one, so a
	repeated check-in attempt cannot leave a guest with two folios.
	"""
	if stay and folio_type == "Master":
		existing = frappe.db.get_value(
			FOLIO_DOCTYPE, {"stay": stay, "folio_type": "Master"}, "name"
		)
		if existing:
			return existing

	doc = frappe.get_doc(
		{
			"doctype": FOLIO_DOCTYPE,
			"property": property_name,
			"guest": guest,
			"stay": stay,
			"reservation": reservation,
			"room": room,
			"folio_type": folio_type,
			"parent_folio": parent_folio,
			"folio_status": OPEN,
			"opened_on": now_datetime(),
			"billing_instructions": billing_instructions,
		}
	).insert(ignore_permissions=True)

	_log(doc.name, property_name, "Folio opened", to_status=OPEN)

	return doc.name


# ---------------------------------------------------------------------------
# Posting
# ---------------------------------------------------------------------------


def post_charge(
	folio: str,
	charge_type: str,
	description: str,
	amount: float,
	*,
	idempotency_key: str,
	quantity: float = 1,
	unit_price: float | None = None,
	tax_amount: float = 0,
	item: str | None = None,
	payer: str = "Guest",
	charge_date=None,
	business_date=None,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
) -> dict:
	"""Post a charge to a folio, exactly once per idempotency key.

	The key is the caller's promise about identity: the night audit uses
	`{stay}:room-charge:{business_date}`, so re-running the audit for a date
	that already posted returns the original line instead of charging twice.
	"""
	if not idempotency_key:
		throw(_("An idempotency key is required to post a charge."), exc=FolioError)

	lock_document(FOLIO_DOCTYPE, folio)

	existing = _find_by_key("Hospitality Folio Charge", folio, idempotency_key)
	if existing:
		return {**existing, "duplicate": True}

	doc = frappe.get_doc(FOLIO_DOCTYPE, folio)

	if doc.folio_status not in POSTABLE_STATES:
		throw(
			_("Folio {0} is {1} and cannot take new charges.").format(folio, _(doc.folio_status)),
			exc=FolioError,
		)

	amount = flt(amount)
	tax_amount = flt(tax_amount)

	# Discounts are entered as positive numbers by operators and stored
	# negative, so the balance arithmetic is a plain sum everywhere else.
	if charge_type in CREDIT_CHARGE_TYPES and amount > 0:
		amount = -amount

	row = doc.append(
		"charges",
		{
			"charge_date": charge_date or nowdate(),
			"business_date": business_date or get_business_date(doc.property),
			"charge_type": charge_type,
			"description": description,
			"item": item,
			"quantity": quantity,
			"unit_price": unit_price if unit_price is not None else amount,
			"amount": amount,
			"tax_amount": tax_amount,
			"total_amount": amount + tax_amount,
			"payer": payer,
			"posted_by": frappe.session.user,
			"posted_on": now_datetime(),
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"idempotency_key": idempotency_key,
		},
	)

	_recalculate(doc)
	doc.save(ignore_permissions=True)

	_log(
		folio,
		doc.property,
		f"Charge posted: {charge_type}",
		amount=row.total_amount,
		details={"description": description, "idempotency_key": idempotency_key},
	)

	return {"row": row.name, "amount": row.amount, "total_amount": row.total_amount, "duplicate": False}


def post_payment(
	folio: str,
	amount: float,
	payment_method: str,
	*,
	idempotency_key: str,
	payment_type: str = "Payment",
	reference: str | None = None,
	provider_reference: str | None = None,
	payer: str = "Guest",
	payment_date=None,
	business_date=None,
) -> dict:
	"""Record a payment or deposit against a folio, exactly once per key.

	Gateway callbacks are replayed routinely, so this is the guard that stops a
	guest being credited twice for one card capture.
	"""
	if not idempotency_key:
		throw(_("An idempotency key is required to post a payment."), exc=FolioError)

	lock_document(FOLIO_DOCTYPE, folio)

	existing = _find_by_key("Hospitality Folio Payment", folio, idempotency_key)
	if existing:
		return {**existing, "duplicate": True}

	doc = frappe.get_doc(FOLIO_DOCTYPE, folio)

	if doc.folio_status == CLOSED:
		throw(_("Folio {0} is closed and cannot take payments.").format(folio), exc=FolioError)

	amount = flt(amount)

	if amount <= 0:
		throw(_("A payment amount must be greater than zero."), exc=FolioError)

	# A refund reduces what has been received.
	if payment_type == "Refund":
		amount = -amount

	row = doc.append(
		"payments",
		{
			"payment_date": payment_date or nowdate(),
			"business_date": business_date or get_business_date(doc.property),
			"payment_type": payment_type,
			"payment_method": payment_method,
			"amount": amount,
			"reference": reference,
			"provider_reference": provider_reference,
			"payer": payer,
			"received_by": frappe.session.user,
			"received_on": now_datetime(),
			"idempotency_key": idempotency_key,
		},
	)

	_recalculate(doc)
	doc.save(ignore_permissions=True)

	_log(
		folio,
		doc.property,
		f"Payment recorded: {payment_type}",
		amount=amount,
		details={"method": payment_method, "idempotency_key": idempotency_key},
	)

	return {"row": row.name, "amount": amount, "balance": doc.balance, "duplicate": False}


def _find_by_key(child_doctype: str, folio: str, idempotency_key: str) -> dict | None:
	"""The row already posted under this key, if any."""
	row = frappe.db.get_value(
		child_doctype,
		{"parent": folio, "idempotency_key": idempotency_key},
		["name", "amount"],
		as_dict=True,
	)

	return {"row": row["name"], "amount": row["amount"]} if row else None


# ---------------------------------------------------------------------------
# Reversal and adjustment
# ---------------------------------------------------------------------------


def reverse_charge(folio: str, charge_row: str, reason: str) -> dict:
	"""Reverse a posted charge with a compensating line.

	The original is never edited or deleted: an auditor must be able to see
	what was charged, that it was reversed, by whom and why (SAS section 7).
	"""
	require_role(FINANCE_ROLES)

	if not reason or not reason.strip():
		throw(_("A reason is required to reverse a charge."), exc=FolioError)

	lock_document(FOLIO_DOCTYPE, folio)

	doc = frappe.get_doc(FOLIO_DOCTYPE, folio)
	original = next((row for row in doc.charges if row.name == charge_row), None)

	if not original:
		throw(_("Charge {0} does not belong to folio {1}.").format(charge_row, folio), exc=FolioError)

	if original.is_reversed:
		throw(_("Charge {0} has already been reversed.").format(charge_row), exc=FolioError)

	original.is_reversed = 1
	original.reversed_by = frappe.session.user
	original.reversed_on = now_datetime()
	original.reversal_reason = reason.strip()

	doc.append(
		"charges",
		{
			"charge_date": nowdate(),
			"business_date": get_business_date(doc.property),
			"charge_type": "Adjustment",
			"description": _("Reversal of {0}").format(original.description),
			"quantity": 1,
			"unit_price": -flt(original.amount),
			"amount": -flt(original.amount),
			"tax_amount": -flt(original.tax_amount),
			"total_amount": -flt(original.total_amount),
			"payer": original.payer,
			"posted_by": frappe.session.user,
			"posted_on": now_datetime(),
			"reversal_of": charge_row,
			"reversal_reason": reason.strip(),
			"idempotency_key": f"reversal:{charge_row}",
		},
	)

	_recalculate(doc)
	doc.save(ignore_permissions=True)

	_log(
		folio,
		doc.property,
		"Charge reversed",
		amount=-flt(original.total_amount),
		reason=reason.strip(),
		details={"charge_row": charge_row},
	)

	return {"reversed": charge_row, "balance": doc.balance}


def post_adjustment(folio: str, amount: float, description: str, reason: str, *, payer: str = "Guest") -> dict:
	"""Post a manual adjustment. Always audited, always reasoned."""
	require_role(ADJUSTMENT_ROLES)

	if not reason or not reason.strip():
		throw(_("A reason is required to adjust a folio."), exc=FolioError)

	return post_charge(
		folio,
		"Adjustment",
		description,
		amount,
		payer=payer,
		idempotency_key=f"adjustment:{folio}:{frappe.generate_hash(length=12)}",
	)


# ---------------------------------------------------------------------------
# Totals
# ---------------------------------------------------------------------------


def _recalculate(doc):
	"""Recompute the folio totals from its lines.

	Totals are derived, never entered. Reversed originals stay in the list and
	their compensating lines cancel them out, so the sum is correct without
	special-casing.
	"""
	charges = sum(flt(row.total_amount) for row in doc.charges)
	taxes = sum(flt(row.tax_amount) for row in doc.charges)
	adjustments = sum(flt(row.total_amount) for row in doc.charges if row.charge_type == "Adjustment")
	payments = sum(flt(row.amount) for row in doc.payments if not row.is_reversed)

	doc.total_charges = flt(charges, 2)
	doc.total_taxes = flt(taxes, 2)
	doc.total_adjustments = flt(adjustments, 2)
	doc.total_payments = flt(payments, 2)
	doc.balance = flt(charges - payments, 2)


def recalculate(folio: str) -> float:
	"""Public recompute, for repair and reconciliation paths."""
	doc = frappe.get_doc(FOLIO_DOCTYPE, folio)
	_recalculate(doc)
	doc.save(ignore_permissions=True)

	return doc.balance


def get_balance(folio: str) -> float:
	return flt(frappe.db.get_value(FOLIO_DOCTYPE, folio, "balance"))


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


def transition(folio: str, target: str, *, reason: str | None = None) -> str:
	"""Move the folio state, validating against the approved machine."""
	lock_document(FOLIO_DOCTYPE, folio)

	doc = frappe.get_doc(FOLIO_DOCTYPE, folio)
	previous = doc.folio_status

	assert_transition(previous, target, TRANSITIONS, _("Folio"))

	if previous == CLOSED and target == UNDER_REVIEW:
		# Reopening a closed folio is a controlled exception, because it
		# reopens something ERPNext has already been told about.
		require_role(REOPEN_ROLES)

		if not reason or not reason.strip():
			throw(_("A reason is required to reopen a closed folio."), exc=FolioError)

	if target in (SETTLED, CLOSED) and abs(flt(doc.balance)) > 0.005:
		throw(
			_("Folio {0} has an outstanding balance of {1} and cannot be {2}.").format(
				folio, flt(doc.balance, 2), _(target)
			),
			exc=FolioError,
		)

	frappe.db.set_value(FOLIO_DOCTYPE, folio, "folio_status", target, update_modified=True)

	if target == CLOSED:
		frappe.db.set_value(FOLIO_DOCTYPE, folio, "closed_on", now_datetime(), update_modified=False)

	_log(folio, doc.property, "Status changed", from_status=previous, to_status=target, reason=reason)

	return target


# ---------------------------------------------------------------------------
# Split and merge
# ---------------------------------------------------------------------------


def split_folio(folio: str, charge_rows: list[str], *, folio_type: str = "Split", payer: str = "Company") -> str:
	"""Move selected charges onto a new folio.

	Used for company-pay / guest-pay separation. The charges are moved, not
	copied: a charge exists on exactly one folio, or the two folios would sum
	to more than the guest owes.
	"""
	require_role(ADJUSTMENT_ROLES)

	lock_document(FOLIO_DOCTYPE, folio)

	source = frappe.get_doc(FOLIO_DOCTYPE, folio)

	if source.folio_status in (SETTLED, CLOSED):
		throw(_("A {0} folio cannot be split.").format(_(source.folio_status)), exc=FolioError)

	moving = [row for row in source.charges if row.name in set(charge_rows)]

	if not moving:
		throw(_("Select at least one charge to move."), exc=FolioError)

	target = open_folio(
		source.property,
		source.guest,
		stay=source.stay,
		reservation=source.reservation,
		room=source.room,
		folio_type=folio_type,
		parent_folio=folio,
	)

	target_doc = frappe.get_doc(FOLIO_DOCTYPE, target)

	for row in moving:
		values = row.as_dict()
		for field in ("name", "parent", "parentfield", "parenttype", "idx", "creation", "modified", "owner", "modified_by"):
			values.pop(field, None)

		values["payer"] = payer
		values["idempotency_key"] = f"split:{row.name}"
		target_doc.append("charges", values)

	source.charges = [row for row in source.charges if row.name not in set(charge_rows)]

	_recalculate(source)
	_recalculate(target_doc)

	# The rows are moving to another folio, not being destroyed, so the folio's
	# "corrections are reversals" guard is told this is a move.
	source.flags.hpms_moving_rows = True
	source.save(ignore_permissions=True)
	target_doc.save(ignore_permissions=True)

	_log(folio, source.property, "Charges split out", details={"to_folio": target, "rows": charge_rows})
	_log(target, source.property, "Charges split in", details={"from_folio": folio, "rows": charge_rows})

	return target


def merge_folio(source_folio: str, target_folio: str) -> str:
	"""Move every charge and payment from one folio into another."""
	require_role(ADJUSTMENT_ROLES)

	if source_folio == target_folio:
		throw(_("A folio cannot be merged into itself."), exc=FolioError)

	for name in sorted([source_folio, target_folio]):
		lock_document(FOLIO_DOCTYPE, name)

	source = frappe.get_doc(FOLIO_DOCTYPE, source_folio)
	target = frappe.get_doc(FOLIO_DOCTYPE, target_folio)

	for state_holder in (source, target):
		if state_holder.folio_status in (SETTLED, CLOSED):
			throw(
				_("Folio {0} is {1} and cannot be merged.").format(
					state_holder.name, _(state_holder.folio_status)
				),
				exc=FolioError,
			)

	for table in ("charges", "payments"):
		for row in source.get(table):
			values = row.as_dict()
			for field in ("name", "parent", "parentfield", "parenttype", "idx", "creation", "modified", "owner", "modified_by"):
				values.pop(field, None)
			values["idempotency_key"] = f"merge:{row.name}"
			target.append(table, values)

		source.set(table, [])

	_recalculate(source)
	_recalculate(target)

	source.flags.hpms_moving_rows = True
	source.save(ignore_permissions=True)
	target.save(ignore_permissions=True)

	transition(source_folio, CLOSED, reason=_("Merged into {0}").format(target_folio))

	_log(target_folio, target.property, "Folio merged in", details={"from_folio": source_folio})

	return target_folio


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


def _log(
	folio: str,
	property_name: str,
	action: str,
	*,
	from_status: str | None = None,
	to_status: str | None = None,
	amount: float | None = None,
	reason: str | None = None,
	details: dict | None = None,
):
	import json

	frappe.get_doc(
		{
			"doctype": FOLIO_LOG_DOCTYPE,
			"property": property_name,
			"folio": folio,
			"action": action,
			"from_status": from_status,
			"to_status": to_status,
			"amount": amount,
			"changed_by": frappe.session.user,
			"changed_at": now_datetime(),
			"reason": reason,
			"details": json.dumps(details, default=str) if details else None,
		}
	).insert(ignore_permissions=True)


def get_folio_for_stay(stay: str) -> str | None:
	return frappe.db.get_value(FOLIO_DOCTYPE, {"stay": stay, "folio_type": "Master"}, "name")
