"""Guest endpoints for the operational frontend.

Guest identification and blacklist data sit above permlevel 0, so these
endpoints return only what the calling user is allowed to see.
"""

import frappe
from frappe import _

from hospitality_pms.services.base import require_permission
from hospitality_pms.services.guests import (
	find_duplicates,
	get_active_alerts,
	merge_guests,
)

GUEST_DOCTYPE = "Hospitality Guest"

#: Fields safe for a guest search result. No identification, no blacklist.
SEARCH_FIELDS = (
	"name",
	"guest_name",
	"email_id",
	"mobile_no",
	"nationality",
	"vip_status",
	"guest_type",
	"total_stays",
	"last_stay_on",
)


@frappe.whitelist(methods=["GET"])
def search_guests(query: str | None = None, limit: int = 20) -> list[dict]:
	"""Type-ahead guest search for the front desk.

	Searches name, email and mobile. Identification numbers are deliberately
	not searchable here; looking a guest up by passport number goes through
	`find_matches`, which is gated on the identification permission level.
	"""
	require_permission(GUEST_DOCTYPE, "read")

	limit = min(int(limit or 20), 50)
	query = (query or "").strip()

	if not query:
		return frappe.get_list(
			GUEST_DOCTYPE,
			fields=list(SEARCH_FIELDS),
			order_by="modified desc",
			limit_page_length=limit,
		)

	pattern = f"%{query}%"

	return frappe.get_list(
		GUEST_DOCTYPE,
		filters={"is_blacklisted": ("!=", 1)} if not _may_see_blacklist() else None,
		or_filters={
			"guest_name": ("like", pattern),
			"email_id": ("like", pattern),
			"mobile_no": ("like", pattern),
		},
		fields=list(SEARCH_FIELDS),
		order_by="guest_name asc",
		limit_page_length=limit,
	)


def _may_see_blacklist() -> bool:
	"""Whether this user may see that a guest is blacklisted."""
	return 2 in frappe.get_meta(GUEST_DOCTYPE).get_permlevel_access("read")


@frappe.whitelist(methods=["GET"])
def get_guest(guest: str) -> dict:
	"""One guest, with the operational context the front desk needs."""
	require_permission(GUEST_DOCTYPE, "read")

	doc = frappe.get_doc(GUEST_DOCTYPE, guest)
	doc.check_permission("read")

	readable = frappe.get_meta(GUEST_DOCTYPE).get_permlevel_access("read")

	payload = {
		"name": doc.name,
		"guest_name": doc.guest_name,
		"first_name": doc.first_name,
		"last_name": doc.last_name,
		"email_id": doc.email_id,
		"mobile_no": doc.mobile_no,
		"nationality": doc.nationality,
		"preferred_language": doc.preferred_language,
		"guest_type": doc.guest_type,
		"vip_status": doc.vip_status,
		"date_of_birth": doc.date_of_birth,
		"customer": doc.customer,
		"total_stays": doc.total_stays,
		"total_nights": doc.total_nights,
		"last_stay_on": doc.last_stay_on,
		"preferences": [
			{"category": row.preference_category, "preference": row.preference, "notes": row.notes}
			for row in doc.preferences
		],
		"dietary_requirements": doc.dietary_requirements,
		"allergies": doc.allergies,
		"accessibility_requirements": doc.accessibility_requirements,
		"alerts": get_active_alerts(guest),
	}

	# Identification is permlevel 1; blacklist status is permlevel 2. Each is
	# added only when this user is cleared for that level.
	if 1 in readable:
		payload["identifications"] = [
			{
				"id_type": row.id_type,
				"id_number": row.id_number,
				"issuing_country": row.issuing_country,
				"expiry_date": row.expiry_date,
				"is_primary": row.is_primary,
				"verified": row.verified,
			}
			for row in doc.identifications
		]

	# The flag is level 2 so the desk can refuse a check-in; the reason is
	# level 3 because it can carry incident detail the desk does not need.
	if 2 in readable:
		payload["is_blacklisted"] = doc.is_blacklisted

	if 3 in readable:
		payload["blacklist_reason"] = doc.blacklist_reason

	return payload


@frappe.whitelist(methods=["POST"])
def find_matches(
	first_name: str | None = None,
	last_name: str | None = None,
	email_id: str | None = None,
	mobile_no: str | None = None,
	id_number: str | None = None,
	date_of_birth: str | None = None,
	exclude: str | None = None,
) -> list[dict]:
	"""Existing guests that may be the same person.

	POST because the payload carries identification data that should not end
	up in a URL, a proxy log or the browser history.
	"""
	require_permission(GUEST_DOCTYPE, "read")

	if id_number and 1 not in frappe.get_meta(GUEST_DOCTYPE).get_permlevel_access("read"):
		frappe.throw(
			_("You are not permitted to search by identification number."),
			frappe.PermissionError,
		)

	return find_duplicates(
		first_name=first_name,
		last_name=last_name,
		email_id=email_id,
		mobile_no=mobile_no,
		id_number=id_number,
		date_of_birth=date_of_birth,
		exclude=exclude,
	)


@frappe.whitelist(methods=["POST"])
def merge(source: str, target: str, reason: str) -> dict:
	"""Merge a duplicate guest into the record that is being kept.

	The service enforces the role requirement and writes the merge log.
	"""
	require_permission(GUEST_DOCTYPE, "write")

	return merge_guests(source, target, reason)
