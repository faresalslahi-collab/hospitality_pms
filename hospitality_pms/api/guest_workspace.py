"""Read models for the Guest 360 workspace.

Four endpoints, all read-only: the workspace payload the screen opens on, and
three paginated histories. Every mutation the workspace performs goes through the
hardened guest services in `api.guests`; nothing here writes.

**Why this module exists separately from `api/guests.py`.** That module is the
guest *lifecycle* surface - search, create, update, match, merge. These four are a
screen's read model: one aggregate assembled for one page, and the histories it
pages through. Keeping them apart means the lifecycle API is not gradually
reshaped by what a particular screen wanted to display, which is the same
separation `api/reservation_workspace.py` draws against `api/reservations.py`.

**The disclosure rule.** A guest workspace is the widest aggregate in the product,
and an aggregate is where permission boundaries quietly dissolve. 16.7.1 shipped a
board that gated on `Stay.read` and then handed out Guest Folio balances, because
each field was read with a permission-free query and only the endpoint's own
DocType was ever checked. So every field group below is gated on the DocType the
value actually came from, and a caller who is not cleared gets **no key** rather
than a blanked one - absence reads as "not disclosed to you", where a `0.00` reads
as "nothing owed" and would be a lie.

`Guest.read` is emphatically not the authority for anything but the guest record.
Ten roles hold `Guest.read` without `Stay.read`; ten hold `Reservation.read` and
`Stay.read` without `Guest Folio.read`. Concretely, per group:

- profile, preferences, alerts, dietary/allergy/accessibility - **Guest**.
- identifications - **Guest permlevel 1**. Reservation Agent holds `Guest.read`
  and has no permlevel-1 row.
- `is_blacklisted` - **Guest permlevel 2**; `blacklist_reason` - **permlevel 3**,
  which no front-office role holds. Both answered by the two helpers in
  `services.guests` that own the question.
- reservation history - **Reservation**.
- stay history, the current stay, and the stay statistics - **Stay**.
- folio history and any balance - **Guest Folio**.
- merge - the **role** gate in `services.guests.MERGE_ROLES`, not a DocType.

**Property scoping.** A Guest carries no `property` and none is invented for it: a
guest is a person, not a property's record, and the same person checks into Doha
this year and Dubai next. So the guest root is estate-wide, and every *owned*
history below is scoped independently to the caller's permitted properties. A
guest is visible; another property's bookings for them are not.

**Stay statistics are derived, not read.** `Guest.total_stays`, `total_nights`,
`last_stay_on` and `lifetime_value` are read-only columns that nothing in the app
writes - they are permanently zero, and the guest profile rendered that zero as
though it were a fact. They are computed here from `Stay`, under `Stay.read`,
scoped to permitted properties. Which is also why they cannot come back from
`api.guests.search_guests`: that endpoint answers to `Guest.read` alone.
"""

import frappe
from frappe.query_builder.functions import Count, Max, Sum

from hospitality_pms.services import guests as guest_service
from hospitality_pms.services.base import authorise_document, require_permission
from hospitality_pms.services.property import get_permitted_properties
from hospitality_pms.utils.params import clean_int

GUEST_DOCTYPE = "Guest"
RESERVATION_DOCTYPE = "Reservation"
RESERVATION_GUEST_DOCTYPE = "Reservation Guest"
STAY_DOCTYPE = "Stay"
FOLIO_DOCTYPE = "Guest Folio"
ROOM_DOCTYPE = "Hotel Room"
ROOM_TYPE_DOCTYPE = "Room Type"

#: Statuses in which a guest is physically in the house.
#:
#: Both, never `In House` alone: a guest who is due out this morning is still in
#: the room, and a workspace that says otherwise sends the desk to the wrong door.
IN_HOUSE_STATES = ("In House", "Due Out")

#: Stay statuses that count towards the derived statistics.
#:
#: `Expected` is excluded: a booking that has not arrived is not a stay the guest
#: has had, and counting it would make the figure disagree with the history table
#: printed underneath it.
STAYED_STATES = ("In House", "Due Out", "Checked Out", "Closed")

#: The guest's own columns the workspace renders. An allow list, so a field added
#: to the Guest DocType in a later build is not published to the front desk just
#: because nobody remembered to exclude it.
#:
#: Deliberately absent: `total_stays`, `total_nights`, `last_stay_on` and
#: `lifetime_value`, which are derived under `Stay.read` instead of read from
#: columns nothing maintains; `is_blacklisted` and its companions, which are
#: permlevel-gated below; `customer`, which is an ERPNext link the desk has no
#: use for; `notes`, which is free text that has never been permission-reviewed.
PROFILE_FIELDS = (
	"name",
	"guest_name",
	"salutation",
	"first_name",
	"middle_name",
	"last_name",
	"gender",
	"date_of_birth",
	"nationality",
	"preferred_language",
	"mobile_no",
	"phone",
	"email_id",
	"address_line_1",
	"address_line_2",
	"city",
	"state",
	"country",
	"pincode",
	"guest_type",
	"vip_status",
	"market_segment",
	"source",
	"originating_property",
)

#: Preference rows. `Guest Preference` is a child table with no permissions of its
#: own, so this list is the boundary.
PREFERENCE_FIELDS = ("name", "preference_category", "preference", "notes")

#: Identification rows, published only at permlevel 1.
#:
#: `id_image` is **not** here. It is a raw file URL, and Frappe authorises a file
#: download against the *attached-to* document at permlevel 0 - so the URL is a
#: wider grant than the permlevel-1 row that carries it. Recorded in 16.7.3 as
#: DEFERRED - DOCUMENT SECURITY DESIGN; do not add it back without the Guest
#: Document modelling that makes it enforceable.
IDENTIFICATION_FIELDS = (
	"name",
	"id_type",
	"id_number",
	"issuing_country",
	"issue_date",
	"expiry_date",
	"is_primary",
	"verified",
)

#: Alert rows. `alert_type` spans Medical, Behaviour and Security, so this is
#: sensitive text sitting at permlevel 0 - it is gated on `Guest.read` by the
#: endpoint and goes no wider.
ALERT_FIELDS = ("name", "alert_type", "severity", "alert", "is_active", "valid_upto")

#: Reservation history columns.
RESERVATION_FIELDS = (
	"name",
	"property",
	"reservation_status",
	"reservation_type",
	"arrival_date",
	"departure_date",
	"nights",
	"total_rooms",
	"booking_source",
	"booked_on",
)

#: Stay history columns.
#:
#: `room` and `room_type` are Link *columns on Stay*, so reading them is a Stay
#: read; anything about the room's own state would be a `Hotel Room` read and is
#: not published here. Same rule `_room_lines` follows in the reservation
#: workspace.
STAY_FIELDS = (
	"name",
	"property",
	"stay_status",
	"room",
	"room_type",
	"arrival_date",
	"departure_date",
	"nights",
	"checked_in_on",
	"checked_out_on",
	"reservation",
)

#: Folio history columns. Money only, and no posting or reconciliation state:
#: `Financial Posting Log` has its own, narrower reader set, and 16.7.5 owns the
#: financial actions this tab deliberately does not offer.
FOLIO_FIELDS = (
	"name",
	"property",
	"folio_status",
	"folio_type",
	"stay",
	"currency",
	"total_charges",
	"total_taxes",
	"total_payments",
	"total_adjustments",
	"balance",
	"opened_on",
	"closed_on",
)

#: Default and ceiling for one page of history.
PAGE_LENGTH = 20
MAX_PAGE_LENGTH = 100


def _disclosure() -> dict:
	"""Which sources this caller may read.

	Asked once per request: the answer cannot differ between fields of one
	response, and asking per field would be a permission check per history row.

	This map describes the **caller's** capability and never the record's
	content. `blacklist: True` says "your roles are cleared for the flag", not
	"this guest has one" - a workspace needs the first to tell "no company on
	this booking" apart from "you may not see the company", and must never
	publish the second to someone uncleared for it.
	"""
	return {
		"guest": frappe.has_permission(GUEST_DOCTYPE, "read"),
		"reservation": frappe.has_permission(RESERVATION_DOCTYPE, "read"),
		"stay": frappe.has_permission(STAY_DOCTYPE, "read"),
		"folio": frappe.has_permission(FOLIO_DOCTYPE, "read"),
		"identity": 1 in frappe.get_meta(GUEST_DOCTYPE).get_permlevel_access("read"),
		"blacklist": guest_service.may_see_blacklist(),
		"blacklist_reason": guest_service.may_see_blacklist_reason(),
		"merge": bool(set(frappe.get_roles()) & set(guest_service.MERGE_ROLES)),
	}


def _bounds(limit, start) -> tuple[int, int]:
	"""One page of history, bounded server-side.

	A guest's lifetime history is unbounded in principle and the screen shows a
	page of it, so the ceiling is the server's to set. Matches the `limit`/`start`
	contract every list endpoint in the app already uses - not `page`/`offset`.

	Both ends are clamped, and the floor is not decoration: a negative `limit`
	survives `min(-1, 100)` and reaches `limit_page_length`, which Frappe renders
	as `LIMIT -1` - a MariaDB syntax error, so a client-supplied `-1` answers a
	read-only endpoint with a 500 rather than a refusal. No row is disclosed by
	it, but a parameter the caller controls should not be able to fault the
	server at all.
	"""
	return (
		max(min(clean_int(limit, PAGE_LENGTH) or PAGE_LENGTH, MAX_PAGE_LENGTH), 1),
		max(clean_int(start, 0) or 0, 0),
	)


def _identity(doc, may_read: dict) -> dict:
	"""Identification documents, at permlevel 1.

	Absent rather than empty for an uncleared caller: `[]` reads as "this guest
	has no papers on file", which is a claim about the guest, and for a guest
	whose passport was scanned at check-in it is a false one.
	"""
	if not may_read["identity"]:
		return {}

	return {
		"identifications": [
			{field: row.get(field) for field in IDENTIFICATION_FIELDS}
			for row in doc.identifications
		]
	}


def _standing(doc, may_read: dict) -> dict:
	"""VIP standing, and the blacklist only for callers cleared for it.

	The flag and its reason are two questions with two different answers: eleven
	roles may know a guest is blacklisted, six may know why, and no front-office
	role is among the six. `False` is withheld from the uncleared as firmly as
	`True` - it is a claim about the guest either way.
	"""
	standing = {
		"vip_status": doc.vip_status or "",
		"guest_type": doc.guest_type or "",
	}

	if may_read["blacklist"]:
		standing["is_blacklisted"] = bool(doc.is_blacklisted)

	if may_read["blacklist_reason"]:
		standing["blacklist_reason"] = doc.blacklist_reason or ""

	return {"standing": standing}


def _stay_statistics(guest: str, may_read: dict, properties: list[str]) -> dict:
	"""How often this guest has stayed, derived from Stay.

	Not read from `Guest.total_stays`. That column and its three companions are
	read-only and nothing in the app writes them, so they are permanently zero -
	and `GuestProfile.vue` rendered `total_stays ?? 0`, publishing a fabricated
	fact to every reader. Derived here instead, which also puts the figure behind
	`Stay.read` where a statement about a guest's stays belongs.

	Scoped to the caller's permitted properties, so the number agrees with the
	history table underneath it rather than counting stays the caller may not
	list.
	"""
	if not may_read["stay"] or not properties:
		return {}

	# One aggregate query rather than paging a lifetime of stays into Python to
	# count them. Through the query builder because Frappe v16 refuses SQL
	# function strings in `get_all` field lists, and `property` is reached with
	# `stay["property"]` because attribute access collides with a pypika
	# pseudo-column of the same name.
	stay = frappe.qb.DocType(STAY_DOCTYPE)

	totals = (
		frappe.qb.from_(stay)
		.select(
			Count(stay.name).as_("stays"),
			Sum(stay.nights).as_("nights"),
			Max(stay.arrival_date).as_("last_arrival"),
		)
		.where(stay.guest == guest)
		.where(stay["property"].isin(properties))
		.where(stay.stay_status.isin(STAYED_STATES))
	).run(as_dict=True)

	row = totals[0] if totals else {}

	return {
		"stay_statistics": {
			"total_stays": int(row.get("stays") or 0),
			"total_nights": int(row.get("nights") or 0),
			"last_stay_on": row.get("last_arrival"),
		}
	}


def _current_stay(guest: str, may_read: dict, properties: list[str]) -> dict:
	"""The stay the guest is in right now, if the caller may read Stay.

	`Stay.room` is the room the guest is actually in, which since 16.7.3 is also
	the room the inventory row names - `change_room` moves the type with it. The
	booked room is a different concept and belongs to the reservation history,
	where it is labelled as such.
	"""
	if not may_read["stay"] or not properties:
		return {}

	rows = frappe.get_list(
		STAY_DOCTYPE,
		filters={
			"guest": guest,
			"property": ("in", properties),
			"stay_status": ("in", IN_HOUSE_STATES),
		},
		fields=list(STAY_FIELDS),
		order_by="arrival_date desc",
		limit_page_length=1,
	)

	if not rows:
		return {"current_stay": None}

	stay = dict(rows[0])

	# The folio *link* is a Guest Folio identifier, so it travels only with Guest
	# Folio read. Its balance never travels here at all - that is the Folios tab,
	# which is gated as a whole.
	if may_read["folio"]:
		stay["folio"] = frappe.db.get_value(STAY_DOCTYPE, stay["name"], "folio")

	return {"current_stay": stay}


@frappe.whitelist(methods=["GET"])
def get_workspace(guest: str) -> dict:
	"""The Guest 360 payload: everything the workspace opens on, once.

	One aggregate rather than a call per tab, so the tabs cannot show six
	different moments of the same guest. The three histories are separate because
	a lifetime of bookings is not needed to paint the page, and each pages
	independently.

	Every block is spliced in by a helper that returns `{}` when the caller is
	not cleared for its source, so an absent key means "not disclosed to you".
	The `disclosure` map is published alongside so the screen can say the honest
	thing - "you may not see this" reads differently from "there is none".
	"""
	doc = authorise_document(GUEST_DOCTYPE, guest, "read")

	may_read = _disclosure()
	properties = get_permitted_properties()

	payload = {
		"guest": {field: doc.get(field) for field in PROFILE_FIELDS},
		"preferences": [
			{field: row.get(field) for field in PREFERENCE_FIELDS} for row in doc.preferences
		],
		"alerts": [
			{field: row.get(field) for field in ALERT_FIELDS}
			for row in doc.alerts
			if row.is_active
		],
		"care": {
			"dietary_requirements": doc.dietary_requirements or "",
			"allergies": doc.allergies or "",
			"accessibility_requirements": doc.accessibility_requirements or "",
		},
		"disclosure": dict(may_read),
	}

	payload.update(_identity(doc, may_read))
	payload.update(_standing(doc, may_read))
	payload.update(_stay_statistics(guest, may_read, properties))
	payload.update(_current_stay(guest, may_read, properties))

	return payload


def _reservation_names(guest: str, properties: list[str]) -> list[str]:
	"""Every reservation this guest is on, as themselves or as a companion.

	Two sources, because a guest reaches a booking two ways: `Reservation.guest`
	names the person the booking is for, and `Reservation Guest` carries the
	others on it. A history built from the header link alone silently loses every
	booking the guest travelled on, which reads as "no history" rather than as
	"a partial one".

	Returns names only. The row read that follows is a `get_list`, so Frappe's own
	permission conditions apply to what is actually published; this step decides
	*which* rows to ask about, under an explicit property filter.
	"""
	names = set(
		frappe.get_all(
			RESERVATION_DOCTYPE,
			filters={"guest": guest, "property": ("in", properties)},
			pluck="name",
		)
	)

	companions = frappe.get_all(
		RESERVATION_GUEST_DOCTYPE,
		filters={"guest": guest, "parenttype": RESERVATION_DOCTYPE},
		pluck="parent",
	)

	names.update(companions)

	return sorted(names)


@frappe.whitelist(methods=["GET"])
def get_reservations(guest: str, limit: int = PAGE_LENGTH, start: int = 0) -> dict:
	"""This guest's booking history, one page at a time.

	Two gates, because the payload spans two DocTypes with different reader sets:
	the guest must be readable, and so must Reservation. Neither implies the
	other, and `Guest.read` in particular is not authority for a booking.
	"""
	require_permission(RESERVATION_DOCTYPE, "read")
	authorise_document(GUEST_DOCTYPE, guest, "read")

	limit, start = _bounds(limit, start)
	properties = get_permitted_properties()

	if not properties:
		return {"guest": guest, "reservations": [], "has_more": False}

	names = _reservation_names(guest, properties)

	if not names:
		return {"guest": guest, "reservations": [], "has_more": False}

	rows = frappe.get_list(
		RESERVATION_DOCTYPE,
		filters={"name": ("in", names), "property": ("in", properties)},
		fields=list(RESERVATION_FIELDS),
		order_by="arrival_date desc, creation desc",
		limit_page_length=limit,
		limit_start=start,
	)

	return {
		"guest": guest,
		"reservations": rows,
		"has_more": len(rows) == limit,
	}


@frappe.whitelist(methods=["GET"])
def get_stays(guest: str, limit: int = PAGE_LENGTH, start: int = 0) -> dict:
	"""This guest's stay history, one page at a time."""
	require_permission(STAY_DOCTYPE, "read")
	authorise_document(GUEST_DOCTYPE, guest, "read")

	limit, start = _bounds(limit, start)
	properties = get_permitted_properties()

	if not properties:
		return {"guest": guest, "stays": [], "has_more": False}

	rows = frappe.get_list(
		STAY_DOCTYPE,
		filters={"guest": guest, "property": ("in", properties)},
		fields=list(STAY_FIELDS),
		order_by="arrival_date desc, creation desc",
		limit_page_length=limit,
		limit_start=start,
	)

	return {
		"guest": guest,
		"stays": rows,
		"has_more": len(rows) == limit,
	}


@frappe.whitelist(methods=["GET"])
def get_folios(guest: str, limit: int = PAGE_LENGTH, start: int = 0) -> dict:
	"""This guest's folio history, one page at a time.

	The tab this feeds is the reason the whole module is careful. Ten roles hold
	`Reservation.read` and `Stay.read` without `Guest Folio.read` - Revenue
	Manager, the housekeeping and maintenance roles, the kitchen roles and
	Corporate Sales Manager among them - and 16.7.1 handed every one of them a
	balance. Read-only operational context: no refund, no posting, no
	reconciliation, no settlement. 16.7.5 owns those.
	"""
	require_permission(FOLIO_DOCTYPE, "read")
	authorise_document(GUEST_DOCTYPE, guest, "read")

	limit, start = _bounds(limit, start)
	properties = get_permitted_properties()

	if not properties:
		return {"guest": guest, "folios": [], "has_more": False}

	rows = frappe.get_list(
		FOLIO_DOCTYPE,
		filters={"guest": guest, "property": ("in", properties)},
		fields=list(FOLIO_FIELDS),
		order_by="opened_on desc, creation desc",
		limit_page_length=limit,
		limit_start=start,
	)

	return {
		"guest": guest,
		"folios": rows,
		"has_more": len(rows) == limit,
	}
