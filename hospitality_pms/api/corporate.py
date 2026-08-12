"""Corporate account endpoints: negotiated rates, credit visibility, production.

`consume_credit()` and `release_credit()` in the service are deliberately not
exposed here. Both run inside the reservation confirm/cancel flow, under the
same `lock_document(ACCOUNT_DOCTYPE, ...)` that the booking itself takes, so
the credit movement and the inventory decision it belongs to happen as one
step. A standalone "consume credit" button would let credit move without a
booking behind it, which reopens exactly the race the lock exists to close,
and would let a user approve their own credit exception outside the escalation
path in `consume_credit()`. Those two calls stay internal to the booking
service; this module only reports the resulting position.
"""

import frappe

from hospitality_pms.services import corporate as service
from hospitality_pms.services.base import authorise_document, require_permission
from hospitality_pms.services.property import resolve_property

ACCOUNT_DOCTYPE = "Corporate Account"

ACCOUNT_FIELDS = (
	"name",
	"account_code",
	"account_name",
	"property",
	"is_active",
	"account_type",
	"customer",
	"tax_id",
	"registration_number",
	"industry",
	"address_line_1",
	"address_line_2",
	"city",
	"country",
	"phone",
	"email",
	"credit_limit",
	"credit_used",
	"credit_available",
	"payment_terms_days",
	"currency",
	"credit_status",
	"contract_start",
	"contract_end",
	"contract_reference",
	"purchase_order_reference",
	"billing_rule",
	"requires_purchase_order",
	"notes",
)

LIST_FIELDS = (
	"name",
	"account_code",
	"account_name",
	"account_type",
	"customer",
	"city",
	"country",
	"is_active",
	"credit_status",
	"credit_limit",
	"credit_used",
	"credit_available",
	"currency",
	"billing_rule",
)


@frappe.whitelist(methods=["GET"])
def list_accounts(
	property: str | None = None,
	credit_status: str | None = None,
	search: str | None = None,
	limit: int = 50,
	start: int = 0,
) -> dict:
	"""Filtered corporate account list for the corporate desk."""
	require_permission(ACCOUNT_DOCTYPE, "read")
	property_name = resolve_property(property)

	filters = {"property": property_name}
	if credit_status:
		filters["credit_status"] = credit_status

	or_filters = None
	if search:
		pattern = f"%{search.strip()}%"
		or_filters = {"account_name": ("like", pattern), "account_code": ("like", pattern)}

	limit = min(int(limit or 50), 200)

	records = frappe.get_list(
		ACCOUNT_DOCTYPE,
		filters=filters,
		or_filters=or_filters,
		fields=list(LIST_FIELDS),
		order_by="account_name asc",
		limit_page_length=limit,
		limit_start=int(start or 0),
	)

	return {
		"property": property_name,
		"accounts": records,
		"has_more": len(records) == limit,
	}


@frappe.whitelist(methods=["GET"])
def get_account(account: str) -> dict:
	"""One account with its negotiated rates and credit position."""
	doc = authorise_document(ACCOUNT_DOCTYPE, account, "read")

	return {
		"account": {field: doc.get(field) for field in ACCOUNT_FIELDS},
		"negotiated_rates": [
			{
				"name": row.name,
				"room_type": row.room_type,
				"rate_plan": row.rate_plan,
				"negotiated_rate": row.negotiated_rate,
				"valid_from": row.valid_from,
				"valid_upto": row.valid_upto,
				"is_active": row.is_active,
			}
			for row in doc.negotiated_rates
		],
		"credit_position": service.get_credit_position(account),
	}


@frappe.whitelist(methods=["GET"])
def get_credit_position(account: str) -> dict:
	"""Limit, used and available for one account."""
	authorise_document(ACCOUNT_DOCTYPE, account, "read")

	return service.get_credit_position(account)


@frappe.whitelist(methods=["GET"])
def check_credit(account: str, amount: float, reservation: str | None = None) -> dict:
	"""Whether an amount would fit the account's remaining credit.

	Read-only report, not a decision: it never changes `credit_used`.
	"""
	authorise_document(ACCOUNT_DOCTYPE, account, "read")

	return service.check_credit(account, float(amount), reservation=reservation)


@frappe.whitelist(methods=["POST"])
def set_credit_status(account: str, status: str, reason: str) -> dict:
	"""Suspend, restore or flag an account for exception approval."""
	authorise_document(ACCOUNT_DOCTYPE, account, "write")

	service.set_credit_status(account, status, reason)

	return get_account(account)


@frappe.whitelist(methods=["GET"])
def production_report(account: str, from_date: str, to_date: str) -> dict:
	"""Room nights and revenue produced by the account in a period."""
	authorise_document(ACCOUNT_DOCTYPE, account, "read")

	return service.get_production_report(account, from_date, to_date)
