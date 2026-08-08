"""Whitelisted API surface for the Vue operational frontend.

Conventions for every module in this package:

* One module per operational domain (`reservations.py`, `rooms.py`, ...).
* Endpoints are thin. They validate input, call a service in
  `hospitality_pms.services`, and shape the response. No business rules here.
* Every endpoint enforces permissions server side, including endpoints that use
  raw queries or aggregates (Frontend Standards section 4: route guards are not
  a security boundary).
* Return only the fields the screen needs, and paginate anything unbounded
  (SAD section 13).
* Read endpoints use `allow_guest=False` (the default) and are marked
  `methods=["GET"]`; anything that mutates state is `methods=["POST"]` so it is
  CSRF protected.
"""

import frappe


@frappe.whitelist(methods=["GET"])
def ping() -> dict:
	"""Baseline connectivity/version probe used by the frontend shell."""
	from hospitality_pms import __version__

	return {
		"app": "hospitality_pms",
		"version": __version__,
		"user": frappe.session.user,
	}
