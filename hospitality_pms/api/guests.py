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
from hospitality_pms.utils.params import clean_bool, clean_int, clean_str

GUEST_DOCTYPE = "Guest"

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

#: The only fields the operational frontend may write on a guest.
#:
#: An allow list rather than a deny list: a field added to the Guest DocType in
#: a later build is not silently writable from the front desk just because
#: nobody remembered to exclude it. `create_guest` and `update_guest` share the
#: constant so the two paths cannot drift — a field the desk may set on day one
#: is the same field it may correct on day two.
#:
#: `guest_name` is absent on purpose: the controller composes it from the name
#: parts on every save. A caller that echoes it back from `get_guest` is not
#: attempting anything, so it is dropped quietly rather than refused.
GUEST_WRITABLE_FIELDS = (
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
	"dietary_requirements",
	"allergies",
	"accessibility_requirements",
	"notes",
	"originating_property",
	"preferences",
)

#: Writable only by a user cleared for permlevel 1 (see `_may_write_identifications`).
IDENTIFICATION_FIELD = "identifications"

#: Fields the frontend may never write, whatever it sends.
#:
#: These are not "fields we forgot to expose"; each one is owned elsewhere and
#: writing it here would route around that owner. The blacklist fields belong to
#: the controller's audited transition (`apply_blacklist_rules`), `customer` to
#: `services.guests.ensure_customer` (HPMS-DEC-012), and the stay statistics to
#: the roll-up that later builds run from stays and folios.
GUEST_PROTECTED_FIELDS = frozenset(
	{
		"customer",
		"total_stays",
		"total_nights",
		"last_stay_on",
		"lifetime_value",
		"is_blacklisted",
		"blacklist_reason",
		"blacklisted_by",
		"blacklisted_on",
	}
)

#: Columns accepted on an inbound preference row. `get_guest` publishes the
#: category as `category`, so the round trip (read a guest, edit it, send it
#: back) has to be accepted as well as the DocType's own `preference_category`.
PREFERENCE_COLUMNS = ("preference_category", "preference", "notes")

#: Columns accepted on an inbound identification row. `verified_by` and
#: `verified_on` are absent deliberately: the controller stamps them from the
#: session when `verified` flips, and a caller-supplied value would be a claim
#: about who checked the document rather than a record of it.
IDENTIFICATION_COLUMNS = (
	"id_type",
	"id_number",
	"issuing_country",
	"issue_date",
	"expiry_date",
	"is_primary",
	"verified",
	# Not editable from the operational frontend, but carried through: an update
	# replaces the table with what the caller was shown, so a column missing from
	# the round trip is a column the next save erases.
	"id_image",
)


@frappe.whitelist(methods=["GET"])
def search_guests(query: str | None = None, limit: int = 20) -> list[dict]:
	"""Type-ahead guest search for the front desk.

	Searches name, email and mobile. Identification numbers are deliberately
	not searchable here; looking a guest up by passport number goes through
	`find_matches`, which is gated on the identification permission level.

	An empty query is the list view, not a search for nothing: it returns the
	most recently touched guests. `clean_str` is what makes that true — a GET
	parameter that was `undefined` on the client arrives as the literal text
	"undefined", and matching `%undefined%` would return an empty list on every
	first load.
	"""
	require_permission(GUEST_DOCTYPE, "read")

	limit = min(clean_int(limit, 20) or 20, 50)
	query = clean_str(query)

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
		# `name` travels with each child row so an edit can hand the same row
		# back and have it updated in place rather than recreated.
		"preferences": [
			{
				"name": row.name,
				"category": row.preference_category,
				"preference": row.preference,
				"notes": row.notes,
			}
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
				"name": row.name,
				"id_type": row.id_type,
				"id_number": row.id_number,
				"issuing_country": row.issuing_country,
				"issue_date": row.issue_date,
				"expiry_date": row.expiry_date,
				"is_primary": row.is_primary,
				"verified": row.verified,
				"id_image": row.id_image,
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


def _may_write_identifications() -> bool:
	"""Whether this user may both see and change identification documents.

	Read *and* write, because a caller who can write level 1 but not read it
	would be posting rows blind over a table it cannot verify. Front desk roles
	hold both; roles that only audit hold read alone.
	"""
	meta = frappe.get_meta(GUEST_DOCTYPE)

	return 1 in meta.get_permlevel_access("read") and 1 in meta.get_permlevel_access("write")


def _child_rows(value, columns: tuple[str, ...], existing: dict[str, dict] | None = None) -> list[dict]:
	"""Inbound child rows reduced to the columns we accept.

	Anything else on the row — `parent`, `idx`, a stray field a future frontend
	adds — is discarded rather than passed to the ORM, so a child table cannot
	become a side door into fields the parent allow list closed.

	Saving a child table replaces it wholesale, which makes an edit a lossy
	operation twice over: a row the frontend recreates looks brand new to the
	controller (and a verified passport would be re-stamped with whoever last
	fixed a spelling), and every column the frontend was never shown — an
	attached scan, the verification stamps — is written back as empty.

	`existing` closes both. It maps the identifiers of the rows this guest
	already holds to their stored values; a row naming one of them is merged
	over its stored self, so it updates in place and keeps what the caller never
	saw. An identifier that is not in the map is ignored rather than honoured —
	naming a row must never be a way to adopt another guest's document.
	"""
	rows = frappe.parse_json(value) if isinstance(value, str) else value

	if not isinstance(rows, list):
		return []

	existing = existing or {}
	cleaned = []

	for row in rows:
		if not isinstance(row, dict):
			continue

		# `column in row`, not a truthiness test: a field the caller sent as
		# empty is a field being cleared, and must survive the merge below.
		supplied = {column: row.get(column) for column in columns if column in row}
		stored = existing.get(row.get("name"))

		if stored:
			cleaned.append({**stored, **supplied})
			continue

		# A new row the user added from the form and never filled in.
		if not any(supplied.values()):
			continue

		cleaned.append(supplied)

	return cleaned


def _preference_rows(value, existing: dict[str, dict] | None = None) -> list[dict]:
	"""Preference rows, accepting the shape `get_guest` publishes."""
	rows = frappe.parse_json(value) if isinstance(value, str) else value

	if not isinstance(rows, list):
		return []

	normalised = []

	for row in rows:
		if not isinstance(row, dict):
			continue

		row = dict(row)

		# `get_guest` renames `preference_category` to `category` for the screen;
		# accept the name it handed out so an edit round trip keeps the category.
		if "category" in row and not row.get("preference_category"):
			row["preference_category"] = row.get("category")

		normalised.append(row)

	return _child_rows(normalised, PREFERENCE_COLUMNS, existing)


def _existing_rows(doc, fieldname: str) -> dict[str, dict]:
	"""The rows this guest already holds in `fieldname`, keyed by identifier.

	`no_default_fields` keeps `parent`, `idx`, `creation` and the rest of the
	framework columns out of the merge — those belong to the ORM, and handing it
	back its own bookkeeping is how a save writes a stale `modified`.
	"""
	if not doc:
		return {}

	return {row.name: {"name": row.name, **row.as_dict(no_default_fields=True)} for row in doc.get(fieldname) or []}


def _sanitise_guest_payload(payload, refuse_protected: bool, doc=None) -> dict:
	"""Reduce a caller payload to the fields it is actually allowed to write.

	`refuse_protected` is the difference between the two entry points. On create
	the payload is a fresh form and a protected field in it is noise, so it is
	dropped and the guest is created without it — the safe outcome. On update the
	caller is naming a field on an existing record it wants changed, and silently
	saving something other than what was asked for is worse than refusing: a
	blacklist that appears not to have been lifted is a decision someone will act
	on.
	"""
	data = frappe.parse_json(payload) if isinstance(payload, str) else dict(payload or {})

	if refuse_protected:
		refused = sorted(GUEST_PROTECTED_FIELDS.intersection(data))

		if refused:
			frappe.throw(
				_("These fields cannot be changed here: {0}").format(", ".join(_(field) for field in refused)),
				frappe.PermissionError,
			)

	clean: dict = {}

	for field in GUEST_WRITABLE_FIELDS:
		if field not in data:
			continue

		if field == "preferences":
			clean[field] = _preference_rows(data[field], _existing_rows(doc, field))
		else:
			clean[field] = data[field]

	# Identification is permlevel 1. A user who is not cleared for it never saw
	# the field in `get_guest` either, so dropping it is consistent with what
	# they were shown — throwing would leak that the section exists.
	if IDENTIFICATION_FIELD in data and _may_write_identifications():
		clean[IDENTIFICATION_FIELD] = _child_rows(
			data[IDENTIFICATION_FIELD],
			IDENTIFICATION_COLUMNS,
			_existing_rows(doc, IDENTIFICATION_FIELD),
		)

	return clean


def _primary_id_number(payload: dict) -> str | None:
	"""The identification number to match duplicates on, if we have one.

	Only ever reached from an already-sanitised payload, so the rows are present
	only when the caller is cleared for permlevel 1 — which is the same clearance
	`find_matches` requires to search by identification number.
	"""
	rows = payload.get(IDENTIFICATION_FIELD) or []

	for row in rows:
		if row.get("is_primary") and row.get("id_number"):
			return row["id_number"]

	return next((row["id_number"] for row in rows if row.get("id_number")), None)


@frappe.whitelist(methods=["POST"])
def create_guest(guest: dict | str, ignore_duplicates: int = 0) -> dict:
	"""Register a new guest from the front desk.

	Returns `{"created": False, "duplicates": [...]}` instead of inserting when
	the details look like a guest we already hold. The desk decides: open the
	existing record, or send the same payload back with `ignore_duplicates` to
	create anyway. Nothing is ever merged automatically — merging the wrong two
	people rewrites reservation and folio history, and is far more expensive to
	undo than a duplicate record is to live with.

	No ERPNext Customer is created here; that happens only when money has to
	move (HPMS-DEC-012).
	"""
	require_permission(GUEST_DOCTYPE, "create")

	payload = _sanitise_guest_payload(guest, refuse_protected=False)
	payload["doctype"] = GUEST_DOCTYPE

	if not clean_bool(ignore_duplicates):
		duplicates = find_duplicates(
			first_name=payload.get("first_name"),
			last_name=payload.get("last_name"),
			email_id=payload.get("email_id"),
			mobile_no=payload.get("mobile_no"),
			id_number=_primary_id_number(payload),
			date_of_birth=payload.get("date_of_birth"),
		)

		if duplicates:
			return {"created": False, "duplicates": duplicates}

	# Normal permissions: the ORM enforces create rights and permlevel writes,
	# and the controller composes the name, normalises contacts and validates
	# the identification rows. None of that is re-implemented here.
	doc = frappe.get_doc(payload).insert()

	return {"created": True, "guest": get_guest(doc.name)}


@frappe.whitelist(methods=["POST"])
def update_guest(guest: str, changes: dict | str) -> dict:
	"""Correct an existing guest record.

	Loads the real document rather than writing fields straight to the database:
	the controller owns the derived name, the contact normalisation and the
	identification rules, and a `db.set_value` shortcut would skip all three.
	"""
	require_permission(GUEST_DOCTYPE, "write")

	doc = frappe.get_doc(GUEST_DOCTYPE, guest)
	doc.check_permission("write")

	for field, value in _sanitise_guest_payload(changes, refuse_protected=True, doc=doc).items():
		doc.set(field, value)

	# Plain `save()`: permlevel enforcement belongs to Frappe, and Frappe's
	# answer is the authoritative one.
	doc.save()

	return get_guest(doc.name)


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
