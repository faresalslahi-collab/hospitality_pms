"""Global operational search for the front desk.

One question, asked across the five records a front desk agent actually has in
front of them: *the guest at the counter, their booking, their stay, their room,
their bill.* Nothing else is searchable here. A generic "search any DocType"
endpoint is how an operational search becomes a data export, so the entity list
is a closed constant rather than a caller-supplied argument.

Three properties hold this together, and each one is load-bearing:

**Every search read goes through `frappe.get_list`.** `get_list` applies DocType
permissions *and* User Permissions, which is the mechanism the product's
property scoping is built on (HPMS-DEC-052); `get_all` applies neither, and a
search that used it would answer questions about every property in the estate.
16.7.0's review found exactly that defect elsewhere in this app. There is no
`get_all` in this module at all.

**The property filter is explicit as well.** `resolve_property` authorises the
property the caller named, and the four property-bearing entities are then
filtered on it by hand. That is deliberate belt-and-braces: the permission-aware
read is the guarantee, and the explicit filter is what still holds if a User
Permission row is ever loosened by mistake.

**Only reviewed columns are ever selected.** Each searcher names its own field
list and composes its labels from it. There is no path here that returns a
document as JSON, so a field added to one of these DocTypes in a later build
does not silently become visible to the front desk - and identification,
blacklist, alert bodies and folio money can never be reached at all, because
nothing selects them.

A typeahead, not a report: two characters minimum, five results per entity, one
query per entity and five queries in total, the same for every caller. No
hydration pass, no second lookup per row, no per-caller extra step.
"""

from typing import NamedTuple

import frappe
from frappe import _
from frappe.utils import formatdate

from hospitality_pms.services.property import get_permitted_properties, resolve_property
from hospitality_pms.utils.params import clean_int, clean_str

GUEST = "Guest"
RESERVATION = "Reservation"
STAY = "Stay"
HOTEL_ROOM = "Hotel Room"
GUEST_FOLIO = "Guest Folio"

#: The only records this endpoint will ever look at, in the order they are
#: returned. Front desk order: who, what they booked, what they are living in,
#: which room, what they owe.
SEARCHABLE_TYPES = (GUEST, RESERVATION, STAY, HOTEL_ROOM, GUEST_FOLIO)

#: A single character matches most of the estate, so the query is refused before
#: any database work happens rather than being run and truncated.
MIN_QUERY_LENGTH = 2

DEFAULT_LIMIT = 5
MAX_LIMIT = 10

#: The response contract, frozen: every result dict has exactly these keys, for
#: every entity. Published so the tests can assert the shape rather than
#: restating it.
RESULT_KEYS = (
	"type",
	"id",
	"primary_label",
	"secondary_label",
	"property",
	"status",
	"safe_summary",
)


class PropertyScope(NamedTuple):
	"""Which properties this search may look at, and what to tell the client.

	`name` is the single property the search was scoped to, or None when the
	caller named none and holds access to several - there is no honest single
	answer then, and inventing one would misreport the scope.
	"""

	name: str | None
	properties: list[str]


def operational_search(
	query: str | None = None,
	property_name: str | None = None,
	limit: int = DEFAULT_LIMIT,
) -> dict:
	"""Search the five operational entities for one typed fragment.

	Returns the frozen response contract described in this module's docstring.
	Never raises for a query it cannot use - an empty, short or placeholder
	query is a normal state of a search box, not an error. It *does* raise when
	the caller names a property they may not operate in, because that is a
	refusal and not an empty result.
	"""
	limit = resolve_limit(limit)

	# Re-cleaned here rather than trusted from the API layer: this service is
	# also reachable from Desk and from jobs, and the placeholder texts a query
	# string produces ("undefined") must not become something we match on.
	query = clean_str(query)
	requested_property = clean_str(property_name)

	if not query or len(query) < MIN_QUERY_LENGTH:
		# No queries at all, not even the property resolution. A search box on
		# its first keystroke must cost the database nothing. The property is
		# echoed as asked for; nothing was scoped, so nothing was authorised
		# either, and the refusal arrives with the first usable keystroke.
		return _empty_response(query, requested_property, limit)

	scope = _resolve_scope(requested_property)

	if not scope.properties:
		# A user whose only permitted properties are inactive. The four scoped
		# entities have nothing to search, and running the Guest query alone
		# would make "this user can see nothing" look like "this guest exists".
		return _empty_response(query, scope.name, limit)

	results: list[dict] = []
	counts: dict[str, int] = {}
	truncated = False

	for doctype, search in _SEARCHERS.items():
		# `frappe.has_permission` is the question `require_permission` asks,
		# without its throw. Deliberate: a Night Auditor may read folios and a
		# Room Attendant may not, and a single global refusal would hand the
		# whole search to the union of every entity's permission - so a user
		# who legitimately holds four of the five would get a 403 for all five.
		#
		# Skipping is indistinguishable from finding nothing, on purpose: the
		# entity's key is still present in `counts` with 0, and its absence
		# from `results` is what "no matches" looks like too. So the response
		# cannot be used to probe which DocTypes the user holds - which matters
		# because that probe would otherwise work on any query at all.
		if not frappe.has_permission(doctype, ptype="read"):
			counts[doctype] = 0
			continue

		# One extra row, so "there were more" is a fact rather than a guess:
		# `len(rows) == limit` cannot tell a full page from an exact fit.
		rows = search(query, scope, limit + 1)

		if len(rows) > limit:
			truncated = True
			rows = rows[:limit]

		counts[doctype] = len(rows)
		results.extend(rows)

	return {
		"query": query,
		"property": scope.name,
		"min_length": MIN_QUERY_LENGTH,
		"limit": limit,
		"truncated": truncated,
		"counts": {doctype: counts.get(doctype, 0) for doctype in SEARCHABLE_TYPES},
		"results": results,
	}


def resolve_limit(limit) -> int:
	"""The per-entity cap, clamped to something a typeahead can afford.

	Clamped rather than refused: a client asking for 500 results has a bug, and
	failing its search is a worse outcome than quietly giving it ten.
	"""
	value = clean_int(limit, DEFAULT_LIMIT) or DEFAULT_LIMIT

	return max(1, min(value, MAX_LIMIT))


def _empty_response(query: str | None, property_name: str | None, limit: int) -> dict:
	"""The contract, with nothing in it.

	`query` is echoed as the empty string rather than None so the client's own
	length check ("did the server think this was too short?") never has to
	handle two types.
	"""
	return {
		"query": query or "",
		"property": property_name,
		"min_length": MIN_QUERY_LENGTH,
		"limit": limit,
		"truncated": False,
		"counts": {doctype: 0 for doctype in SEARCHABLE_TYPES},
		"results": [],
	}


def _resolve_scope(property_name: str | None) -> PropertyScope:
	"""Authorise the property being searched, or fall back to the permitted set.

	A named property goes through `resolve_property`, which refuses one the user
	may not operate in - a cross-property search is a refusal, never an empty
	result, because an empty result would read as "no such booking here" and the
	desk would act on it.

	When the caller names none, the search spans every property the user may
	operate in. `resolve_property(None)` is deliberately not used for that: it
	throws for a user holding several properties with no configured default,
	and a global search box that errors on a multi-property user is not usable.
	"""
	if property_name:
		resolved = resolve_property(property_name)

		return PropertyScope(resolved, [resolved])

	permitted = get_permitted_properties()

	return PropertyScope(permitted[0] if len(permitted) == 1 else None, permitted)


def _result(
	doctype: str,
	row,
	*,
	primary: str | None,
	secondary: str | None = "",
	property_name: str | None = None,
	status: str | None = "",
	summary: str | None = "",
) -> dict:
	"""The one place a search result is constructed.

	Every entity comes through here, so the response shape cannot drift between
	them and no searcher can add a key of its own. `primary_label` falls back to
	the docname because a record with no display name is still a record the desk
	needs to be able to click.

	`status` carries the stored value, untranslated: the client colours and
	groups by it, so it is data. Anything meant to be *read* - `secondary_label`,
	`safe_summary` - is translated by the caller before it gets here.
	"""
	return {
		"type": doctype,
		"id": row.name,
		"primary_label": primary or row.name,
		"secondary_label": secondary or "",
		"property": property_name,
		"status": status or "",
		"safe_summary": summary or "",
	}


def _property_filters(scope: PropertyScope) -> list[list]:
	"""The explicit property filter, alongside `get_list`'s own scoping."""
	return [["property", "in", scope.properties]]


def _stay_dates(row) -> str:
	"""Arrival and departure as one short, localised phrase."""
	if not (row.arrival_date and row.departure_date):
		return ""

	return _("{0} to {1}").format(formatdate(row.arrival_date), formatdate(row.departure_date))


# ---------------------------------------------------------------------------
# One searcher per entity. One query each.
# ---------------------------------------------------------------------------
#
# On patterns: `%fragment%` is used wherever the desk types the *middle* of a
# value, and `fragment%` wherever it types the start.
#
# Names are the leading-wildcard case and it is unavoidable. An agent types a
# surname, not a full name ("haddad", for "Layla Haddad"), and pastes a whole
# reference or reads out the tail of one ("00042", for
# HPMS-RES-2026-00042). A prefix pattern answers neither. The cost is a scan of
# an index rather than a seek, bounded by a hard LIMIT of six rows per entity on
# tables whose scale is one property's operational history - acceptable for a
# typeahead, and the reason the minimum query length exists at all. If this ever
# stops being acceptable the answer is a dedicated search index, not a wider
# scan; out of scope for this build.
#
# Room numbers are the prefix case: "10" means rooms 101-109, never "the 10 in
# 210", so `fragment%` is both cheaper and more correct here.


# --- why blacklisted guests are NOT hidden from these results ---------------
#
# This module first removed them for an uncleared caller, reasoning that presence
# in a result set is itself an inference channel. The channel is real, but hiding
# the row does not close it - it inverts it into something worse, and the code
# never implemented what its own comment claimed.
#
# The claim was "absent from both, or from neither": a guest hidden from the guest
# group had to be hidden from the reservation and stay groups too. Only the guest
# searcher was ever filtered, while `_search_reservations`, `_search_stays` and
# `_search_folios` all label their rows with `guest_name`. So a blacklisted guest
# with a booking produced `counts["Guest"] == 0` while that guest's name sat in
# the group underneath - absent here, present there, which is a *conclusive*
# one-bit disclosure rather than a partial one. The affected callers are Guest
# readers without permlevel 2: on this site, Accounts User and Finance Manager.
#
# Closing it by hiding the guest everywhere would mean withholding reservations,
# stays and folios from the finance roles whose job is to reconcile them. Closing
# it by returning the row costs nothing: `is_blacklisted` is never selected here,
# so there is no field to omit, and the row on its own says nothing.
#
# So this module redacts the *column* by never selecting it, exactly as
# `front_office._blacklist_flag` does for the boards. One field, one rule, both
# surfaces - and an Accounts User can find a guest by name again.


def _search_guests(query: str, scope: PropertyScope, limit: int) -> list[dict]:
	"""Guests by name, mobile or docname.

	**A Guest carries no property**, and none is invented for it. A guest is a
	global master record shared by every property in the estate (they stayed in
	Doha last year and are checking into Dubai today), so `property` on a guest
	result is None and no filter is applied. Joining through stays to synthesise
	a property scope was considered and rejected: it would hide a returning
	guest from the desk that is about to check them in, which is precisely the
	moment the search exists for.

	Blacklisted guests are returned like any other, and the flag is simply never
	selected - see the note above this function for why removing the row is worse
	than keeping it.

	Identification numbers are not searchable. Looking a guest up by passport
	goes through `api.guests.find_matches`, which is gated on permlevel 1 and
	is a POST so the number never reaches a URL or a proxy log.
	"""
	pattern = f"%{query}%"

	rows = frappe.get_list(
		GUEST,
		or_filters=[
			["name", "like", pattern],
			["guest_name", "like", pattern],
			["mobile_no", "like", pattern],
		],
		fields=["name", "guest_name", "mobile_no"],
		order_by="guest_name asc",
		limit=limit,
	)

	return [
		_result(
			GUEST,
			row,
			primary=row.guest_name,
			# The mobile is the field that tells two guests of the same name
			# apart at the counter, and it is the field the desk searched on.
			secondary=row.mobile_no,
		)
		for row in rows
	]


def _search_reservations(query: str, scope: PropertyScope, limit: int) -> list[dict]:
	"""Reservations by docname or guest name, within the permitted properties."""
	pattern = f"%{query}%"

	rows = frappe.get_list(
		RESERVATION,
		filters=_property_filters(scope),
		or_filters=[
			["name", "like", pattern],
			["guest_name", "like", pattern],
		],
		fields=[
			"name",
			"guest_name",
			"property",
			"reservation_status",
			"arrival_date",
			"departure_date",
		],
		# Most recently touched first: the booking someone is working on is the
		# one they are searching for. The sort runs over the matched rows only,
		# so an unindexed column costs nothing at this scale.
		order_by="modified desc",
		limit=limit,
	)

	return [
		_result(
			RESERVATION,
			row,
			primary=row.guest_name,
			secondary=_stay_dates(row),
			property_name=row.property,
			status=row.reservation_status,
		)
		for row in rows
	]


def _search_stays(query: str, scope: PropertyScope, limit: int) -> list[dict]:
	"""Stays by docname or guest name, within the permitted properties."""
	pattern = f"%{query}%"

	rows = frappe.get_list(
		STAY,
		filters=_property_filters(scope),
		or_filters=[
			["name", "like", pattern],
			["guest_name", "like", pattern],
		],
		fields=[
			"name",
			"guest_name",
			"property",
			"stay_status",
			"room",
			"arrival_date",
			"departure_date",
		],
		order_by="modified desc",
		limit=limit,
	)

	return [
		_result(
			STAY,
			row,
			primary=row.guest_name,
			# The room is what the desk needs next - to send someone up, or to
			# know which door the guest in front of them is talking about.
			secondary=row.room,
			property_name=row.property,
			status=row.stay_status,
			summary=_stay_dates(row),
		)
		for row in rows
	]


def _search_rooms(query: str, scope: PropertyScope, limit: int) -> list[dict]:
	"""Rooms by number or by room code.

	Both, because they are genuinely two different identifiers: `room_number`
	is what is on the door and what the desk says out loud, and `room_code` is
	the docname the rest of the system links to. An agent pasting a code from a
	report and an agent typing "101" are the same search.
	"""
	rows = frappe.get_list(
		HOTEL_ROOM,
		filters=_property_filters(scope),
		or_filters=[
			# The docname *is* the room code (`autoname: field:room_code`), so
			# one column answers both.
			["name", "like", f"%{query}%"],
			["room_number", "like", f"{query}%"],
		],
		fields=[
			"name",
			"room_number",
			"property",
			"room_type",
			"occupancy_status",
			"housekeeping_status",
		],
		order_by="room_number asc",
		limit=limit,
	)

	return [
		_result(
			HOTEL_ROOM,
			row,
			primary=row.room_number,
			secondary=row.room_type,
			property_name=row.property,
			status=row.occupancy_status,
			# Whether the room is sellable right now is the second thing anyone
			# asks about a room. A status, not a note - nothing free-text.
			summary=_(row.housekeeping_status) if row.housekeeping_status else "",
		)
		for row in rows
	]


def _search_folios(query: str, scope: PropertyScope, limit: int) -> list[dict]:
	"""Folios by docname or guest name, within the permitted properties.

	No money travels in the result. Not the balance, not the charge or payment
	rows, not the tax split, not the account heads and not the ERPNext document
	names: a search result is a way to *find* a folio, and everything monetary
	about it belongs to `api.folio.get_folio`, which authorises the folio the
	caller actually named. `safe_summary` is empty here for that reason and not
	because there was nothing to say.
	"""
	pattern = f"%{query}%"

	rows = frappe.get_list(
		GUEST_FOLIO,
		filters=_property_filters(scope),
		or_filters=[
			["name", "like", pattern],
			["guest_name", "like", pattern],
		],
		fields=["name", "guest_name", "property", "folio_status", "room"],
		order_by="modified desc",
		limit=limit,
	)

	return [
		_result(
			GUEST_FOLIO,
			row,
			primary=row.guest_name,
			secondary=row.room,
			property_name=row.property,
			status=row.folio_status,
		)
		for row in rows
	]


#: Dispatch table, iterated in order. A dict rather than a chain of calls so
#: `SEARCHABLE_TYPES`, `counts` and the result order cannot disagree with each
#: other, and so a sixth entity cannot be added without appearing here.
#: `test_no_arbitrary_doctype_can_be_searched` holds the two in step.
_SEARCHERS = {
	GUEST: _search_guests,
	RESERVATION: _search_reservations,
	STAY: _search_stays,
	HOTEL_ROOM: _search_rooms,
	GUEST_FOLIO: _search_folios,
}
