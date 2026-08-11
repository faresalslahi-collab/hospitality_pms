"""Corporate accounts: negotiated rates, credit control and company-pay billing.

Credit is the part that matters. A corporate account with a credit limit is the
hotel lending money, so every booking that consumes credit checks it under a
lock, and exceeding the limit is an exception a human approves rather than
something the system quietly allows (Workflow Matrix section 8).
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate, now_datetime, nowdate

from hospitality_pms.services.base import lock_and_read, require_role
from hospitality_pms.services.exceptions import HospitalityPMSError, throw
from hospitality_pms.services.property import resolve_operational_date

ACCOUNT_DOCTYPE = "Corporate Account"
CREDIT_LOG_DOCTYPE = "Corporate Credit Log"

ACTIVE = "Active"
EXCEPTION_REQUIRED = "Exception Required"
SUSPENDED = "Suspended"

#: Approving credit beyond the limit is a finance decision; a general manager
#: is the escalation above it (Workflow Matrix section 8).
CREDIT_APPROVAL_ROLES = (
	"Finance Manager",
	"Hospitality Administrator",
	"System Manager",
)

CREDIT_ESCALATION_ROLES = ("General Manager", "Hospitality Administrator", "System Manager")

#: Which charges the company picks up, per billing rule.
COMPANY_PAID_CHARGES = {
	"Company Pays All": None,  # None means every charge type
	"Company Pays Room Only": {"Room Charge"},
	"Company Pays Room and Tax": {"Room Charge", "Tax", "Service Charge"},
	"Guest Pays All": set(),
}


# ---------------------------------------------------------------------------
# Rates
# ---------------------------------------------------------------------------


def get_negotiated_rate(account: str, room_type: str, on_date=None) -> dict | None:
	"""The contracted rate for a room type, if one is in force on a date.

	`on_date` is the date being priced - the night of the stay, not the day
	the booking is made. Pricing a stay in March asks what the contract says
	about March. Without one, the question is operational rather than
	forward-looking and the answer is the property's business date; the
	calendar date is never the right fallback for either.
	"""
	doc = frappe.get_cached_doc(ACCOUNT_DOCTYPE, account)
	on_date = _contract_date(doc, on_date)

	for row in doc.negotiated_rates:
		if row.room_type != room_type or not row.is_active:
			continue
		if row.valid_from and getdate(row.valid_from) > on_date:
			continue
		if row.valid_upto and getdate(row.valid_upto) < on_date:
			continue

		return {"rate": flt(row.negotiated_rate), "rate_plan": row.rate_plan}

	return None


def _contract_date(doc, on_date=None):
	"""Which date a contract question is being asked about.

	An explicit service date wins: a reservation for the 20th is checked
	against the 20th, whether or not the contract also covers today. Without
	one the question is about trading now, and "now" for a hotel is its
	business date - a property still working yesterday must not have its
	contracts expire a day early because the calendar has moved on.
	"""
	if on_date:
		return getdate(on_date)

	if doc.property:
		return resolve_operational_date(doc.property)

	return getdate(nowdate())


def assert_contract_valid(account: str, on_date=None):
	"""Refuse to trade on an expired contract, as at the relevant date."""
	doc = frappe.get_cached_doc(ACCOUNT_DOCTYPE, account)
	on_date = _contract_date(doc, on_date)

	if not doc.is_active:
		throw(_("Corporate account {0} is not active.").format(account), exc=HospitalityPMSError)

	if doc.contract_start and getdate(doc.contract_start) > on_date:
		throw(
			_("The contract for {0} starts on {1}.").format(account, doc.contract_start),
			exc=HospitalityPMSError,
		)

	if doc.contract_end and getdate(doc.contract_end) < on_date:
		throw(
			_("The contract for {0} ended on {1}.").format(account, doc.contract_end),
			exc=HospitalityPMSError,
		)


# ---------------------------------------------------------------------------
# Credit
# ---------------------------------------------------------------------------


def get_credit_position(account: str) -> dict:
	"""Limit, used and available, read straight off the account."""
	doc = frappe.get_cached_doc(ACCOUNT_DOCTYPE, account)

	limit = flt(doc.credit_limit)
	used = flt(doc.credit_used)

	return {
		"account": account,
		"credit_limit": limit,
		"credit_used": used,
		"credit_available": flt(limit - used, 2),
		"credit_status": doc.credit_status,
		"unlimited": limit <= 0,
	}


def check_credit(account: str, amount: float, *, reservation: str | None = None) -> dict:
	"""Whether an amount fits inside the account's remaining credit.

	Reports rather than decides: a booking that exceeds the limit is an
	exception the corporate desk escalates, not an outright refusal.
	"""
	position = get_credit_position(account)

	if position["credit_status"] == SUSPENDED:
		return {**position, "approved": False, "reason": _("The account is suspended.")}

	if position["unlimited"]:
		return {**position, "approved": True, "reason": None}

	fits = flt(amount) <= position["credit_available"] + 0.005

	return {
		**position,
		"approved": fits,
		"reason": None
		if fits
		else _("{0} exceeds the available credit of {1}.").format(
			flt(amount, 2), position["credit_available"]
		),
	}


def consume_credit(
	account: str, amount: float, *, reservation: str | None = None, folio: str | None = None, allow_exception: bool = False
) -> dict:
	"""Take an amount against the account's credit.

	Locked, because two bookings confirmed at the same instant must not both
	read the same remaining credit and both fit inside it.
	"""
	# The balance this decision is made from must be the committed balance at
	# the moment the lock was granted, not the one this transaction saw before
	# it started waiting. Locking and then reading separately is what let two
	# concurrent bookings both record `credit_before = 0` and both fit inside
	# the same remaining credit (P1-4, root cause N1).
	current = lock_and_read(
		ACCOUNT_DOCTYPE, account, ["credit_used", "credit_limit", "property"]
	)

	assert_contract_valid(account)

	before = flt(current["credit_used"])
	limit = flt(current["credit_limit"])
	property_name = current["property"]
	after = before + flt(amount)

	exceeded = limit > 0 and after > limit + 0.005

	if exceeded and not allow_exception:
		_log_credit(
			account,
			property_name,
			"Credit exceeded",
			amount=amount,
			before=before,
			after=after,
			reservation=reservation,
			folio=folio,
			reason=_("Requested amount exceeds the credit limit."),
		)

		frappe.db.set_value(ACCOUNT_DOCTYPE, account, "credit_status", EXCEPTION_REQUIRED)

		throw(
			_("This booking exceeds the credit limit for {0}. Finance approval is required.").format(
				account
			),
			exc=HospitalityPMSError,
		)

	if exceeded:
		# Approving past the limit is the finance decision itself.
		require_role(CREDIT_APPROVAL_ROLES)

	frappe.db.set_value(
		ACCOUNT_DOCTYPE,
		account,
		{"credit_used": after, "credit_available": flt(limit - after, 2)},
		update_modified=True,
	)

	_log_credit(
		account,
		property_name,
		"Credit consumed" + (" (exception approved)" if exceeded else ""),
		amount=amount,
		before=before,
		after=after,
		reservation=reservation,
		folio=folio,
		approved_by=frappe.session.user if exceeded else None,
	)

	return {"account": account, "credit_used": after, "exception_approved": exceeded}


def release_credit(account: str, amount: float, *, reason: str | None = None, folio: str | None = None) -> dict:
	"""Return credit when a booking is cancelled or an invoice is settled."""
	# Current under lock, for the same reason as consume_credit: releasing
	# against a stale balance loses whichever movement committed while this
	# transaction was waiting.
	current = lock_and_read(ACCOUNT_DOCTYPE, account, ["credit_used", "credit_limit", "property"])

	before = flt(current["credit_used"])
	after = max(before - flt(amount), 0.0)
	limit = flt(current["credit_limit"])

	frappe.db.set_value(
		ACCOUNT_DOCTYPE,
		account,
		{"credit_used": after, "credit_available": flt(limit - after, 2)},
		update_modified=True,
	)

	_log_credit(
		account, current["property"], "Credit released", amount=amount, before=before, after=after,
		folio=folio, reason=reason,
	)

	return {"account": account, "credit_used": after}


def set_credit_status(account: str, status: str, reason: str) -> str:
	"""Suspend, restore or flag an account for exception approval."""
	if status not in (ACTIVE, EXCEPTION_REQUIRED, SUSPENDED):
		throw(_("{0} is not a credit status.").format(status), exc=HospitalityPMSError)

	if not reason or not reason.strip():
		throw(_("A reason is required to change credit status."), exc=HospitalityPMSError)

	if status == ACTIVE:
		require_role(CREDIT_APPROVAL_ROLES + CREDIT_ESCALATION_ROLES)

	# `previous` goes into the audit trail, so it has to be the status this
	# change actually moved away from - not the one this transaction happened
	# to read before it acquired the lock.
	current = lock_and_read(ACCOUNT_DOCTYPE, account, ["credit_status", "property"])
	previous = current["credit_status"]

	frappe.db.set_value(ACCOUNT_DOCTYPE, account, "credit_status", status, update_modified=True)

	_log_credit(
		account, current["property"], "Credit status changed", from_status=previous, to_status=status,
		reason=reason.strip(), approved_by=frappe.session.user,
	)

	return status


def _log_credit(
	account: str,
	property_name: str,
	action: str,
	*,
	amount: float | None = None,
	before: float | None = None,
	after: float | None = None,
	from_status: str | None = None,
	to_status: str | None = None,
	reservation: str | None = None,
	folio: str | None = None,
	reason: str | None = None,
	approved_by: str | None = None,
):
	frappe.get_doc(
		{
			"doctype": CREDIT_LOG_DOCTYPE,
			"property": property_name,
			"corporate_account": account,
			"action": action,
			"amount": amount,
			"credit_before": before,
			"credit_after": after,
			"from_status": from_status,
			"to_status": to_status,
			"reservation": reservation,
			"folio": folio,
			"changed_by": frappe.session.user,
			"changed_at": now_datetime(),
			"reason": reason,
			"approved_by": approved_by,
		}
	).insert(ignore_permissions=True)


# ---------------------------------------------------------------------------
# Billing
# ---------------------------------------------------------------------------


def get_payer_for_charge(account: str, charge_type: str) -> str:
	"""Who pays a given charge type under the account's billing rule."""
	rule = frappe.get_cached_value(ACCOUNT_DOCTYPE, account, "billing_rule") or "Guest Pays All"
	covered = COMPANY_PAID_CHARGES.get(rule, set())

	if covered is None:
		return "Company"

	return "Company" if charge_type in covered else "Guest"


def split_folio_by_billing_rule(folio: str, account: str) -> dict:
	"""Move the company's share of a folio onto its own folio.

	Uses FolioService's split so the charges are moved once, both sides are
	logged, and the immutability rules still hold.
	"""
	from hospitality_pms.services import folio as folio_service

	doc = frappe.get_doc(folio_service.FOLIO_DOCTYPE, folio)

	company_rows = [
		row.name
		for row in doc.charges
		if not row.is_reversed and get_payer_for_charge(account, row.charge_type) == "Company"
	]

	if not company_rows:
		return {"folio": folio, "company_folio": None, "moved": 0}

	company_folio = folio_service.split_folio(folio, company_rows, folio_type="Company", payer="Company")

	frappe.db.set_value(
		folio_service.FOLIO_DOCTYPE,
		company_folio,
		"billing_instructions",
		_("Company account {0}").format(account),
		update_modified=False,
	)

	return {"folio": folio, "company_folio": company_folio, "moved": len(company_rows)}


def get_production_report(account: str, from_date, to_date) -> dict:
	"""Room nights and revenue produced by a corporate account in a period."""
	rows = frappe.db.sql(
		"""
		select count(distinct s.name) as stays,
		       coalesce(sum(s.nights), 0) as room_nights,
		       coalesce(sum(f.total_charges), 0) as revenue
		from `tabStay` s
		left join `tabGuest Folio` f on f.stay = s.name
		inner join `tabReservation` r on r.name = s.reservation
		where r.corporate_account = %(account)s
		  and s.arrival_date between %(from_date)s and %(to_date)s
		""",
		{"account": account, "from_date": getdate(from_date), "to_date": getdate(to_date)},
		as_dict=True,
	)

	result = rows[0] if rows else {"stays": 0, "room_nights": 0, "revenue": 0}

	return {
		"account": account,
		"from_date": str(getdate(from_date)),
		"to_date": str(getdate(to_date)),
		"stays": int(result["stays"] or 0),
		"room_nights": int(result["room_nights"] or 0),
		"revenue": flt(result["revenue"], 2),
		**get_credit_position(account),
	}
