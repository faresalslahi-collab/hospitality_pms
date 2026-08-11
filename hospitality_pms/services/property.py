"""Property context, configuration and business date.

Every operational service resolves its property through this module, so there is
one definition of "which property am I working in" and one definition of "what
is today" for the whole product.
"""

import frappe
from frappe import _
from frappe.utils import getdate

from hospitality_pms.services.exceptions import (
	ConfigurationError,
	HospitalityPMSError,
	PropertyAccessError,
	throw,
)

PROPERTY_DOCTYPE = "Property"

#: Set while the Night Audit service moves the business date forward. Nothing
#: else may change it, so a mis-click in Desk cannot re-open a closed day.
BUSINESS_DATE_FLAG = "hpms_business_date_transition"


def get_settings():
	"""System wide PMS Settings (cached single)."""
	return frappe.get_cached_doc("PMS Settings")


def get_property(name: str):
	"""Cached Property document."""
	if not name:
		throw(_("A property is required for this operation."), exc=ConfigurationError)

	return frappe.get_cached_doc(PROPERTY_DOCTYPE, name)


def get_active_properties() -> list[str]:
	"""Every active property, regardless of who is asking."""
	return frappe.get_all(PROPERTY_DOCTYPE, filters={"is_active": 1}, pluck="name", order_by="property_name")


# ---------------------------------------------------------------------------
# Property access
# ---------------------------------------------------------------------------


def get_permitted_properties(user: str | None = None) -> list[str]:
	"""Active properties the user may operate in.

	Access is expressed as Frappe User Permissions on Property, so
	Desk, the REST API and the Vue frontend all obey the same restriction
	without a parallel access model (HPMS-DEC-052).

	A user with no User Permission on Property is unrestricted,
	which is Frappe's own semantics and keeps single-property sites simple.
	"""
	user = user or frappe.session.user
	active = get_active_properties()

	restrictions = frappe.defaults.get_user_permissions(user).get(PROPERTY_DOCTYPE) or []
	if not restrictions:
		return active

	allowed = {row.get("doc") for row in restrictions if row.get("doc")}

	return [name for name in active if name in allowed]


def require_property_access(property_name: str, user: str | None = None) -> str:
	"""Raise unless the user may operate in this property."""
	if property_name in get_permitted_properties(user):
		return property_name

	throw(
		_("You do not have access to property {0}.").format(property_name),
		exc=PropertyAccessError,
	)


def get_default_property(user: str | None = None) -> str | None:
	"""The property to work in when the caller did not name one.

	Falls back through: the configured default (if the user may use it), the
	user's only permitted property, then nothing. Returning None is a valid
	answer; callers that need a property raise their own error.
	"""
	permitted = get_permitted_properties(user)

	if not permitted:
		return None

	configured = get_settings().default_property
	if configured and configured in permitted:
		return configured

	if len(permitted) == 1:
		return permitted[0]

	return None


def resolve_property(property_name: str | None = None, user: str | None = None) -> str:
	"""Resolve and authorise the property for an operation."""
	property_name = property_name or get_default_property(user)

	if not property_name:
		throw(_("No property is available for this user. Ask an administrator for access."), exc=PropertyAccessError)

	return require_property_access(property_name, user)


# ---------------------------------------------------------------------------
# Business date
# ---------------------------------------------------------------------------


def get_business_date(property_name: str):
	"""The property's current operating day.

	This is not `today()`. A property that has not yet run its Night Audit is
	still operating on yesterday's business date, and charges must post there.
	"""
	business_date = frappe.db.get_value(PROPERTY_DOCTYPE, property_name, "business_date")

	if not business_date:
		throw(
			_("Property {0} has no business date. Complete property setup before operating.").format(property_name),
			exc=ConfigurationError,
		)

	return getdate(business_date)


def is_business_date_closed(property_name: str, business_date) -> bool:
	"""Whether a Night Audit has already closed this property on this date.

	Queried directly rather than through the Night Audit service, which imports
	the folio service and would make the dependency circular. The status string
	is the contract between them.
	"""
	if not property_name or not business_date:
		return False

	return bool(
		frappe.db.exists(
			"Night Audit",
			{
				"property": property_name,
				"business_date": getdate(business_date),
				"audit_status": "Closed",
			},
		)
	)


def assert_posting_allowed(property_name: str, business_date, *, what: str, exc=HospitalityPMSError):
	"""Refuse ordinary money dated into a day the hotel has already closed.

	`PMS Settings.block_posting_after_close` existed and was read nowhere, so a
	charge could be back-dated into a business date whose Night Audit had
	closed and whose revenue had already been reported. The audit's figures
	then described a day that had since changed underneath them.

	Only the ordinary path is fenced. Corrections still have to be possible or
	a mistake in a closed day becomes permanent, so the callers exempt the
	privileged, reasoned workflows - an adjustment, a discount, a refund - each
	of which already demands an elevated role and a written reason. The
	difference being enforced is between *correcting* a closed day and quietly
	*back-dating into* one.

	`exc` lets the caller keep its own error contract - everything the folio
	service raises is a `FolioError`, and a caller catching that should not have
	to know this particular refusal came from a neighbouring module.
	"""
	if not get_settings().block_posting_after_close:
		return

	if not is_business_date_closed(property_name, business_date):
		return

	throw(
		_(
			"The business date {0} has been closed by the Night Audit, so {1} cannot be posted "
			"to it. Use an adjustment, or reopen the business date."
		).format(getdate(business_date), _(what)),
		exc=exc,
	)


def assert_business_date_change_allowed(doc):
	"""Guard the business date against edits outside the Night Audit.

	Called from the Property controller. The Night Audit service
	sets the flag around its own update; every other caller is refused.
	"""
	if not doc.has_value_changed("business_date"):
		return

	if doc.is_new() or frappe.flags.get(BUSINESS_DATE_FLAG):
		return

	throw(
		_("The business date is advanced by the Night Audit only. It cannot be edited directly."),
		exc=ConfigurationError,
	)


# ---------------------------------------------------------------------------
# Configuration lookups
# ---------------------------------------------------------------------------


def get_warehouse(property_name: str, purpose: str) -> str:
	"""Warehouse configured for a stock purpose, e.g. `Minibar`.

	Raises when unmapped rather than guessing: posting consumption to the wrong
	warehouse is not something to recover from silently.
	"""
	doc = get_property(property_name)

	rows = [row for row in doc.warehouses if row.purpose == purpose]
	if not rows:
		throw(
			_("Property {0} has no warehouse mapped for {1}.").format(property_name, _(purpose)),
			exc=ConfigurationError,
		)

	default = next((row for row in rows if row.is_default), rows[0])

	return default.warehouse


def get_active_fees(property_name: str, on_date=None) -> list:
	"""Property fees in force on a date.

	Fees are hospitality specific (service charge, tourism and municipality
	fees). Statutory VAT stays in the ERPNext tax template.
	"""
	doc = get_property(property_name)
	on_date = getdate(on_date or get_business_date(property_name))

	active = []

	for fee in doc.fees:
		if not fee.is_active:
			continue
		if fee.valid_from and getdate(fee.valid_from) > on_date:
			continue
		if fee.valid_upto and getdate(fee.valid_upto) < on_date:
			continue

		active.append(fee)

	return active


def get_company(property_name: str) -> str:
	"""The ERPNext Company that owns this property's financial records."""
	company = frappe.db.get_value(PROPERTY_DOCTYPE, property_name, "company")

	if not company:
		throw(_("Property {0} is not mapped to a company.").format(property_name), exc=ConfigurationError)

	return company
