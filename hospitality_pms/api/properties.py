"""Property context for the operational frontend.

The shell needs to know which property the user is operating in, what its
business date is, and how it formats money. Everything here is read only;
property configuration is maintained in Desk.
"""

import frappe

from hospitality_pms.services.base import require_permission
from hospitality_pms.services.property import (
	get_default_property,
	get_permitted_properties,
	require_property_access,
)

PROPERTY_DOCTYPE = "Property"

#: Fields the operational shell needs. Deliberately narrow: accounts, policies
#: and warehouse mappings are configuration and never reach the frontend.
CONTEXT_FIELDS = (
	"name",
	"property_code",
	"property_name",
	"property_type",
	"company",
	"currency",
	"country",
	"time_zone",
	"default_language",
	"business_date",
	"check_in_time",
	"check_out_time",
	"rounding_precision",
	"total_rooms",
)


@frappe.whitelist(methods=["GET"])
def get_property_context() -> dict:
	"""Properties this user may operate in, and which one to open by default."""
	require_permission(PROPERTY_DOCTYPE, "read")

	permitted = get_permitted_properties()

	if not permitted:
		return {"properties": [], "default_property": None}

	properties = frappe.get_all(
		PROPERTY_DOCTYPE,
		filters={"name": ("in", permitted)},
		fields=list(CONTEXT_FIELDS),
		order_by="property_name",
	)

	return {
		"properties": properties,
		"default_property": get_default_property(),
	}


@frappe.whitelist(methods=["GET"])
def get_property(property: str) -> dict:
	"""One property's operational context."""
	require_permission(PROPERTY_DOCTYPE, "read")
	require_property_access(property)

	return frappe.db.get_value(PROPERTY_DOCTYPE, property, list(CONTEXT_FIELDS), as_dict=True)
