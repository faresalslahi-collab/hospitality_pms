"""Guest identity: naming, duplicate detection, Customer linking and merging.

Guest is the primary guest record (HPMS-DEC-011). An ERPNext
Customer is created or linked only when money has to move (HPMS-DEC-012), so
most guests never get one.
"""

import json

import frappe
from frappe import _
from frappe.utils import now_datetime

from hospitality_pms.services.base import lock_and_read, lock_document, require_role
from hospitality_pms.services.exceptions import ConfigurationError, HospitalityPMSError, throw

GUEST_DOCTYPE = "Guest"
MERGE_LOG_DOCTYPE = "Guest Merge Log"

#: Roles allowed to merge guest records. A merge rewrites history across
#: reservations, stays and folios, so it is not an everyday front desk action.
MERGE_ROLES = ("Hospitality Administrator", "System Manager", "Hotel Manager", "Guest Relations Officer")


# ---------------------------------------------------------------------------
# Naming
# ---------------------------------------------------------------------------


def compose_guest_name(first_name: str | None, middle_name: str | None, last_name: str | None) -> str:
	"""Build the display name from its parts.

	Kept here rather than in the controller so imports, channel bookings and
	the merge service all produce identical names.
	"""
	parts = [(first_name or "").strip(), (middle_name or "").strip(), (last_name or "").strip()]

	return " ".join(part for part in parts if part)


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------

#: Confidence weights. An identity document or a contact channel is a much
#: stronger signal than a common name, so they are scored far higher.
MATCH_WEIGHTS = {
	"id_number": 60,
	"email_id": 30,
	"mobile_no": 30,
	"name_and_dob": 25,
	"name_only": 10,
}

DUPLICATE_THRESHOLD = 30


def find_duplicates(
	first_name: str | None = None,
	last_name: str | None = None,
	email_id: str | None = None,
	mobile_no: str | None = None,
	id_number: str | None = None,
	date_of_birth=None,
	exclude: str | None = None,
	limit: int = 10,
) -> list[dict]:
	"""Candidate existing guests for the details being entered.

	Returns scored candidates rather than deciding: merging the wrong two
	guests is far more damaging than creating a duplicate, so a human confirms.
	"""
	scores: dict[str, int] = {}
	reasons: dict[str, list[str]] = {}

	def add(guest: str, weight: int, reason: str):
		if not guest or guest == exclude:
			return
		scores[guest] = scores.get(guest, 0) + weight
		reasons.setdefault(guest, []).append(reason)

	if id_number:
		rows = frappe.get_all(
			"Guest Identification",
			filters={"id_number": id_number.strip(), "parenttype": GUEST_DOCTYPE},
			fields=["parent"],
			limit=limit * 2,
		)
		for row in rows:
			add(row["parent"], MATCH_WEIGHTS["id_number"], _("Same identification number"))

	if email_id:
		for guest in frappe.get_all(
			GUEST_DOCTYPE, filters={"email_id": email_id.strip()}, pluck="name", limit=limit * 2
		):
			add(guest, MATCH_WEIGHTS["email_id"], _("Same email address"))

	if mobile_no:
		for guest in frappe.get_all(
			GUEST_DOCTYPE, filters={"mobile_no": mobile_no.strip()}, pluck="name", limit=limit * 2
		):
			add(guest, MATCH_WEIGHTS["mobile_no"], _("Same mobile number"))

	if first_name and last_name:
		filters = {"first_name": first_name.strip(), "last_name": last_name.strip()}
		name_matches = frappe.get_all(
			GUEST_DOCTYPE, filters=filters, fields=["name", "date_of_birth"], limit=limit * 2
		)

		for row in name_matches:
			if date_of_birth and row.get("date_of_birth") and str(row["date_of_birth"]) == str(date_of_birth):
				add(row["name"], MATCH_WEIGHTS["name_and_dob"], _("Same name and date of birth"))
			else:
				add(row["name"], MATCH_WEIGHTS["name_only"], _("Same name"))

	candidates = [guest for guest, score in scores.items() if score >= DUPLICATE_THRESHOLD]

	if not candidates:
		return []

	details = frappe.get_all(
		GUEST_DOCTYPE,
		filters={"name": ("in", candidates)},
		fields=["name", "guest_name", "email_id", "mobile_no", "nationality", "total_stays", "last_stay_on"],
	)

	for row in details:
		row["match_score"] = scores[row["name"]]
		row["match_reasons"] = reasons[row["name"]]

	return sorted(details, key=lambda row: row["match_score"], reverse=True)[:limit]


# ---------------------------------------------------------------------------
# ERPNext Customer linking
# ---------------------------------------------------------------------------


def ensure_customer(guest: str, company: str | None = None) -> str:
	"""Return the guest's ERPNext Customer, creating one if needed.

	Called only when a financial document is about to be raised. Creating a
	Customer for every walk-in would pollute the receivables ledger with
	records that never carry a balance.
	"""
	# Locked and read in one operation. Locking and then re-reading with a
	# plain `get_value` answered from the pre-lock snapshot (N1): the waiter
	# still saw no customer after the winner had committed one, and tried to
	# create a second. ERPNext names a Customer after the guest, so that second
	# insert collides on the primary key - and the posting that needed the
	# customer fails, for a customer that exists.
	existing = lock_and_read(GUEST_DOCTYPE, guest, "customer")["customer"]

	if existing:
		return existing

	doc = frappe.get_doc(GUEST_DOCTYPE, guest)

	customer = frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": doc.guest_name,
			"customer_type": "Individual",
			"customer_group": _default_customer_group(),
			"territory": _default_territory(),
			"mobile_no": doc.mobile_no,
			"email_id": doc.email_id,
		}
	).insert(ignore_permissions=True)

	frappe.db.set_value(GUEST_DOCTYPE, guest, "customer", customer.name, update_modified=False)

	return customer.name


def _default_customer_group() -> str:
	group = frappe.db.get_single_value("Selling Settings", "customer_group")

	if group:
		return group

	default = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")

	if not default:
		throw(_("No Customer Group is configured in ERPNext."), exc=ConfigurationError)

	return default


def _default_territory() -> str:
	territory = frappe.db.get_single_value("Selling Settings", "territory")

	if territory:
		return territory

	default = frappe.db.get_value("Territory", {"is_group": 0}, "name")

	if not default:
		throw(_("No Territory is configured in ERPNext."), exc=ConfigurationError)

	return default


# ---------------------------------------------------------------------------
# Merging
# ---------------------------------------------------------------------------


def get_guest_link_fields() -> list[tuple[str, str]]:
	"""Every (doctype, fieldname) that links to Guest.

	Discovered from the schema rather than hard-coded, so a merge keeps working
	as reservations, stays, folios and guest requests are added in later builds
	without anyone remembering to update this list.
	"""
	rows = frappe.get_all(
		"DocField",
		filters={"fieldtype": "Link", "options": GUEST_DOCTYPE},
		fields=["parent", "fieldname"],
	)

	custom = frappe.get_all(
		"Custom Field",
		filters={"fieldtype": "Link", "options": GUEST_DOCTYPE},
		fields=["dt as parent", "fieldname"],
	)

	seen = set()
	fields = []

	for row in list(rows) + list(custom):
		key = (row["parent"], row["fieldname"])

		# Skip the guest DocType's own self-references and anything whose table
		# does not exist yet.
		if key in seen or row["parent"] == GUEST_DOCTYPE:
			continue

		seen.add(key)
		fields.append(key)

	return fields


def merge_guests(source: str, target: str, reason: str) -> dict:
	"""Merge `source` into `target`, repointing every reference.

	The source record is kept and marked merged rather than deleted: reservation
	and folio history must stay auditable for the ten year retention period
	(SAS section 8), and a deleted guest would strand it.
	"""
	require_role(MERGE_ROLES)

	if source == target:
		throw(_("A guest cannot be merged into itself."))

	if not reason or not reason.strip():
		throw(_("A reason is required to merge guest records."))

	# Lock in a deterministic order so two simultaneous merges of the same pair
	# cannot interleave.
	for guest in sorted([source, target]):
		lock_document(GUEST_DOCTYPE, guest)

	source_doc = frappe.get_doc(GUEST_DOCTYPE, source)
	frappe.get_doc(GUEST_DOCTYPE, target)  # existence check

	snapshot = json.dumps(source_doc.as_dict(no_nulls=True), default=str, indent=1)

	moved = {}
	for doctype, fieldname in get_guest_link_fields():
		if not frappe.db.table_exists(doctype):
			continue

		affected = frappe.get_all(doctype, filters={fieldname: source}, pluck="name")
		if not affected:
			continue

		for record in affected:
			frappe.db.set_value(doctype, record, fieldname, target, update_modified=False)

		moved[f"{doctype}.{fieldname}"] = len(affected)

	frappe.get_doc(
		{
			"doctype": MERGE_LOG_DOCTYPE,
			"merged_into": target,
			"merged_from": source,
			"merged_from_name": source_doc.guest_name,
			"merged_by": frappe.session.user,
			"merged_at": now_datetime(),
			"reason": reason.strip(),
			"merged_fields": snapshot,
		}
	).insert(ignore_permissions=True)

	# The merged record stays readable but is taken out of operational use.
	frappe.db.set_value(
		GUEST_DOCTYPE,
		source,
		{"notes": _("Merged into {0} on {1}.").format(target, now_datetime())},
		update_modified=True,
	)

	return {"source": source, "target": target, "references_moved": moved}


# ---------------------------------------------------------------------------
# Operational checks
# ---------------------------------------------------------------------------


def assert_not_blacklisted(guest: str):
	"""Refuse an operation for a blacklisted guest, without saying why (P2-6).

	`blacklist_reason` sits at permlevel 3 precisely so it does not reach a
	front desk screen: it can carry incident detail, police references or HR
	material, and the agent needs to know *that* they must refuse, not what the
	guest is alleged to have done. `is_blacklisted` is permlevel 2, which the
	front office does hold, and that is the part the agent needs.

	This function used to read both fields with `frappe.db.get_value` - which
	applies no permlevel filtering at all, being a raw column read - and
	interpolate the reason straight into the message. The permlevel design was
	correct and this one call defeated it.

	Only the flag is read now. Whoever needs the reason reads the Guest record
	through the ordinary document path, where the permlevel applies and the
	roles that own blacklisting can see it.
	"""
	if not frappe.db.get_value(GUEST_DOCTYPE, guest, "is_blacklisted"):
		return

	throw(
		_(
			"This guest cannot be checked in. Please contact a manager, who can review the "
			"guest's record."
		),
		exc=HospitalityPMSError,
	)


def get_active_alerts(guest: str) -> list[dict]:
	"""Alerts a front desk agent must see when serving this guest."""
	doc = frappe.get_cached_doc(GUEST_DOCTYPE, guest)
	today = frappe.utils.getdate()

	return [
		{
			"alert_type": row.alert_type,
			"severity": row.severity,
			"alert": row.alert,
			"valid_upto": row.valid_upto,
		}
		for row in doc.alerts
		if row.is_active and (not row.valid_upto or frappe.utils.getdate(row.valid_upto) >= today)
	]
