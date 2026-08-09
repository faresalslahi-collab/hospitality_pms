"""Corporate Credit Exposure.

Financial question answered: how much of each corporate, travel-agent,
government or airline account's negotiated credit is currently in use, and
how much unbilled folio balance sits behind that number today?

`credit_limit`, `credit_used` and `credit_available` are read as maintained by
`services.corporate` (CorporateCreditService) -- this report never recomputes
them, only presents them. "Outstanding folio balance" is a separate figure:
the sum of `balance` on every open folio whose reservation carries this
account as `corporate_account` (per `services.corporate.get_production_report`,
which links folios to an account the same way). It can run ahead of
`credit_used` when a stay has charged more than the credit ledger has
recorded, or behind it when charges have been settled but credit has not yet
been released -- either gap is worth a finance follow-up, not just the
utilisation percentage on its own.

What a non-zero exposure means: utilisation over 100% is an account already
over its limit (an exception the credit service would have required approval
for); utilisation over 90% is flagged here as a plain-language warning because
the next booking may tip it over. A contract past its end date being used at
all is a policy question, not a maths one, so it is flagged in words rather
than colour -- this report is read as a printed exposure list, and a printed
page has no colour.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

ACCOUNT_DOCTYPE = "Corporate Account"

#: Utilisation at or above this is flagged for attention before an account is
#: over its limit outright.
UTILISATION_WARNING_PCT = 90.0


def execute(filters=None):
	filters = frappe._dict(filters or {})

	if not filters.get("property"):
		frappe.throw(_("Property is mandatory."))

	columns = get_columns()
	accounts = get_accounts(filters)

	if not accounts:
		return columns, []

	outstanding_by_account = get_outstanding_balances(filters.property)
	today = getdate(nowdate())

	data = []
	for account in accounts:
		limit = flt(account.credit_limit)
		used = flt(account.credit_used)
		available = flt(account.credit_available)

		utilisation_pct = flt((used / limit) * 100, 2) if limit > 0 else 0.0
		contract_expired = bool(account.contract_end) and getdate(account.contract_end) < today

		flags = []
		if limit > 0 and utilisation_pct >= UTILISATION_WARNING_PCT:
			flags.append(_("Over {0}% utilisation").format(int(UTILISATION_WARNING_PCT)))
		if contract_expired:
			flags.append(_("Contract expired"))

		data.append(
			{
				"account_code": account.account_code,
				"account_name": account.account_name,
				"account_type": account.account_type,
				"credit_status": account.credit_status,
				"credit_limit": flt(limit, 2),
				"credit_used": flt(used, 2),
				"credit_available": flt(available, 2),
				"utilisation_pct": utilisation_pct,
				"outstanding_folio_balance": flt(outstanding_by_account.get(account.account_code, 0.0), 2),
				"contract_end": account.contract_end,
				"attention": "; ".join(flags) if flags else _("OK"),
			}
		)

	return columns, data


def get_accounts(filters):
	conditions = {"property": filters.property}

	if filters.get("credit_status"):
		conditions["credit_status"] = filters.credit_status

	return frappe.get_all(
		ACCOUNT_DOCTYPE,
		filters=conditions,
		fields=[
			"account_code",
			"account_name",
			"account_type",
			"credit_status",
			"credit_limit",
			"credit_used",
			"credit_available",
			"contract_end",
		],
		order_by="account_name asc",
	)


def get_outstanding_balances(property_name: str) -> dict:
	"""Outstanding folio balance per corporate account, at this property.

	Raw SQL because the balance lives on the folio while the account link
	lives on the reservation, which the ORM's simple filter dict cannot join.
	`f.property = %(property)s` is the mandatory scoping boundary applied
	before anything else in this query.
	"""
	rows = frappe.db.sql(
		"""
		select r.corporate_account as account_code, sum(f.balance) as outstanding
		from `tabGuest Folio` f
		inner join `tabReservation` r on r.name = f.reservation
		where f.property = %(property)s
		  and r.corporate_account is not null
		  and r.corporate_account != ''
		group by r.corporate_account
		""",
		{"property": property_name},
		as_dict=True,
	)

	return {row.account_code: flt(row.outstanding) for row in rows}


def get_columns():
	return [
		{
			"fieldname": "account_code",
			"label": _("Corporate Account"),
			"fieldtype": "Link",
			"options": "Corporate Account",
			"width": 150,
		},
		{
			"fieldname": "account_type",
			"label": _("Type"),
			"fieldtype": "Data",
			"width": 100,
		},
		{
			"fieldname": "credit_status",
			"label": _("Credit Status"),
			"fieldtype": "Data",
			"width": 130,
		},
		{
			"fieldname": "credit_limit",
			"label": _("Credit Limit"),
			"fieldtype": "Currency",
			"width": 120,
		},
		{
			"fieldname": "credit_used",
			"label": _("Credit Used"),
			"fieldtype": "Currency",
			"width": 120,
		},
		{
			"fieldname": "credit_available",
			"label": _("Credit Available"),
			"fieldtype": "Currency",
			"width": 130,
		},
		{
			"fieldname": "utilisation_pct",
			"label": _("Utilisation %"),
			"fieldtype": "Percent",
			"width": 110,
		},
		{
			"fieldname": "outstanding_folio_balance",
			"label": _("Outstanding Folio Balance"),
			"fieldtype": "Currency",
			"width": 160,
		},
		{
			"fieldname": "contract_end",
			"label": _("Contract End"),
			"fieldtype": "Date",
			"width": 110,
		},
		{
			"fieldname": "attention",
			"label": _("Attention"),
			"fieldtype": "Data",
			"width": 220,
		},
	]
