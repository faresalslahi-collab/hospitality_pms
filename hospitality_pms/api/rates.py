"""Rate plan lookups for the operational frontend.

Read-only. Pricing itself is never done here and never in the client: an amount
comes from `services.rates.get_rate_breakdown` through `api.reservations.quote`,
which is the one authority on what a night costs.

This module exists because 16.7.2 needed a rate-plan *picker* and there was no
honest way to build one. `services.rates.get_applicable_rate_plans` already
answers the exact question — which plans will price this room type on this night —
and is what `reservations.change_line_room_type` consults before it keeps or drops
a line's plan, but it was not whitelisted, so no screen could ask it.

What the two screens that already offer a picker do instead is worth recording,
because it is the thing this endpoint replaces: `ReservationNew.vue` and
`WalkIn.vue` build their lists from a generic `listResource('Rate Plan')` filtered
only on property and `is_active`. That offers plans which do not cover the chosen
room type and plans whose validity has expired, and the refusal then arrives from
the server after the agent has chosen. Asking the service is both narrower and
correct, and it keeps the date rule in one place — the fallback is the property's
operating day, not the calendar's, so a plan does not expire a day early on a
hotel that has not yet run its night audit.
"""

import frappe

from hospitality_pms.services import rates as service
from hospitality_pms.services.base import require_permission
from hospitality_pms.services.property import resolve_property
from hospitality_pms.utils.params import clean_str

RATE_PLAN_DOCTYPE = "Rate Plan"


@frappe.whitelist(methods=["GET"])
def applicable_rate_plans(
	property: str | None = None, room_type: str | None = None, on_date: str | None = None
) -> list[dict]:
	"""Rate plans that will price this room type on this night.

	Authorised twice over, because a rate plan is commercial configuration: the
	caller must be able to read Rate Plan at all, and `resolve_property` re-checks
	that they hold the property — so a picker cannot be used to enumerate another
	property's commercial setup.

	`on_date` is the night being priced, which for a future booking is neither
	today nor the business date. It is passed through untouched; the service
	falls back to the property's operating day when it is absent.
	"""
	require_permission(RATE_PLAN_DOCTYPE, "read")

	property_name = resolve_property(property)
	room_type = clean_str(room_type)

	if not room_type:
		# No room type, no question to answer. An empty list rather than every
		# plan in the property: a picker with nothing selected must not quietly
		# offer plans that may not cover whatever is chosen next.
		return []

	return service.get_applicable_rate_plans(property_name, room_type, clean_str(on_date))
