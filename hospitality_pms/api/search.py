"""Global operational search endpoint for the Front Desk Command Center.

Thin by design: it normalises what an HTTP query string gives it and hands the
question to `services.search`, which is authoritative for what may be searched,
which properties are in scope and what a result is allowed to contain. There is
no permission decision, no filtering and no result shaping here - putting any of
it in the API layer would mean Desk and background callers got a different
answer from the Vue frontend (CLAUDE.md layering).
"""

import frappe

from hospitality_pms.services import search as search_service
from hospitality_pms.utils.params import clean_int, clean_str


@frappe.whitelist(methods=["GET"])
def operational_search(
	query: str | None = None,
	property: str | None = None,
	limit: int = search_service.DEFAULT_LIMIT,
) -> dict:
	"""Search guests, reservations, stays, rooms and folios for one fragment.

	GET, and it mutates nothing. Returns the frozen contract:

	    {
	      "query": str,            # the cleaned query, echoed back
	      "property": str | None,  # the property the search was scoped to
	      "min_length": int,       # so the client can explain a short query
	      "limit": int,            # the per-entity cap actually applied
	      "truncated": bool,       # True if any entity hit that cap
	      "counts": {<type>: int}, # one key per searchable type, always
	      "results": [
	        {
	          "type": str,              # one of the five DocType names
	          "id": str,                # the docname
	          "primary_label": str,
	          "secondary_label": str,   # safe context, may be ""
	          "property": str | None,   # None for Guest, which has no property
	          "status": str,            # stored status value, or ""
	          "safe_summary": str,      # short, non-sensitive, may be ""
	        }
	      ],
	    }

	Deliberately no `route_target`: Vue route names are the frontend's business
	and an API that named them would couple this layer to the SPA. The client
	maps `type` to a route.

	Deliberately no blanket `require_permission` either. Each entity is gated
	individually inside the service, because the five DocTypes have five
	different reader sets - a Night Auditor may read folios and a Room Attendant
	may not - and a single check here would refuse the whole search to a user who
	legitimately holds four of the five.

	`property` shadows the builtin. It is the contract the frontend is being
	built against, so it stays; the service takes it as `property_name`.
	"""
	return search_service.operational_search(
		query=clean_str(query),
		property_name=clean_str(property),
		limit=clean_int(limit, search_service.DEFAULT_LIMIT),
	)
