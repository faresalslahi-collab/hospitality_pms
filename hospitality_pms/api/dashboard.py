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

	**Not a duplicate of `front_office.dashboard`, despite looking like one.**
	16.7's architecture inventory marked this endpoint for deprecation on the
	strength of the name; 16.7.1 checked, and it answers a different question for
	a different consumer, so it stays:

	- Consumer: the Desk **Number Card** (`fixtures/number_card.json`), which is
	  the only caller in the app. The Vue dashboard never calls it - its
	  "Arrivals today" tile comes from `front_office.dashboard`.
	- Unit: **reservations**, not rooms. `front_office._front_office_counts`
	  counts Reservation *Room lines*, because a three-room booking is three
	  pieces of work at a desk. A Desk card headed "Arrivals today" is read as a
	  count of bookings.
	- Scope: **every permitted property**, summed. The Vue aggregate is scoped to
	  the one property the user is working in.

	Delegating this to that aggregate would silently change the Desk card's
	number - the semantic drift the deprecation note was trying to avoid. It
	already delegates where it matters: the day comes from `get_business_date`
	and the rows from `reservation_service.get_arrivals`, so there is no second
	implementation of either rule. If this endpoint is ever retired, the Number
	Card fixture must be retired with it.
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
