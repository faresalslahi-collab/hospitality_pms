"""Desk boot additions.

The Desk needs one thing from this app before any screen renders: which property
the user is working in. Report filters are built synchronously when a report
opens, so a filter default cannot wait on a round trip - it has to already be in
`frappe.boot`.

Resolved per user through `services.property`, not read from a fixed setting, so
a user restricted to one property by a Property User Permission opens every
report on that property rather than on the site's default.
"""

import frappe


def boot_session(bootinfo):
	"""Attach the PMS context the Desk client needs at load.

	`business_date` travels with the property because a report's date filter
	should open on the day the hotel is operating, not the day the server
	thinks it is. A property that has not run its Night Audit is still working
	yesterday, and an arrivals list defaulted to the calendar date would show
	a day the desk has not reached.
	"""
	bootinfo.hospitality_pms = {"default_property": None, "business_date": None}

	if frappe.session.user == "Guest":
		return

	from hospitality_pms.services.property import get_business_date, get_default_property

	try:
		property_name = get_default_property()
		bootinfo.hospitality_pms["default_property"] = property_name

		if property_name:
			bootinfo.hospitality_pms["business_date"] = str(get_business_date(property_name))
	except Exception:
		# Boot must never fail. A user who cannot resolve a property - no
		# Property records yet on a fresh site, or no access to any - simply
		# gets no default and picks one in the filter, which is the same
		# behaviour as before this existed.
		bootinfo.hospitality_pms = {"default_property": None, "business_date": None}
