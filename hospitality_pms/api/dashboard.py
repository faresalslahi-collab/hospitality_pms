"""Desk dashboard endpoints.

Number Cards of type "Document Type" are a filter over one DocType, evaluated by
Frappe. That is enough for a card whose question is "how many rows are in this
state", which is most of them. It is not enough for a card whose question
involves the property's **business date**.

A hotel's operating day is not the server's calendar day: a property that has
not run its Night Audit is still working yesterday, and every arrival, departure
and room charge is dated against that business date rather than `nowdate()`. A
static filter cannot express it, and a dynamic filter cannot either - those are
evaluated in the browser, where the business date is unknown and a workstation
clock is not an acceptable source for it.

So the cards that are business-date sensitive are Custom cards backed by the
methods here, which read the date from the property exactly as the rest of the
system does.
"""

import frappe

from hospitality_pms.services import reservations as reservation_service
from hospitality_pms.services.base import require_permission
from hospitality_pms.services.property import get_business_date, get_permitted_properties


# POST is allowed here even though this only reads. The Desk Number Card widget
# fetches a Custom card with `frappe.xcall`, which posts by default, so a
# GET-only method answers the dashboard with "Not permitted" and the card hangs
# on "Loading...". The house rule that mutating endpoints are POST-only is not
# weakened by a method that changes nothing.
@frappe.whitelist(methods=["GET", "POST"])
def arrivals_today() -> dict:
	"""Reservations due to arrive on each permitted property's business date.

	Summed across the properties this user may see, which for a user with no
	Property User Permission is every active property - Frappe's own semantics,
	and the same rule `services.property` applies everywhere else (HPMS-DEC-052).
	A single-property site therefore gets the answer it expects without any
	configuration.
	"""
	require_permission(reservation_service.RESERVATION_DOCTYPE, "read")

	total = 0

	for property_name in get_permitted_properties():
		# Each property closes its own day, so they can legitimately sit on
		# different business dates; the date is read per property rather than
		# once for the whole site.
		total += len(
			reservation_service.get_arrivals(property_name, get_business_date(property_name))
		)

	return {"value": total, "fieldtype": "Int"}
