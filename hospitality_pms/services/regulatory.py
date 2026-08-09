"""Country-specific regulatory reporting, activated only where confirmed legal (HPMS-DEC-025).

`Regulatory Profile` is per-property configuration, not code: a
new country needs a profile row with the right flags, never a change here.
`get_profile` is the single point where "is this feature switched on for this
property" is decided, and every other function in this module goes through
it and no-ops cleanly when the answer is no - a property with no profile, or
with a requirement flag off, gets no registrations, no exports and no errors,
which is what "activated only where legally confirmed" has to mean in code.

Statutory snapshot
-------------------
`register_guest` deliberately copies identity fields onto the registration
record instead of pointing at the guest. What was reported to an authority at
check-in must not silently change if the guest profile is corrected next
week; only a fresh registration reflects a correction (see the doctype's own
description).
"""

import json

import frappe
from frappe import _
from frappe.utils import getdate, now_datetime

from hospitality_pms.services.base import lock_document, require_role
from hospitality_pms.services.exceptions import ConfigurationError, HospitalityPMSError, throw
from hospitality_pms.services.property import get_business_date

PROFILE_DOCTYPE = "Regulatory Profile"
EXPORT_DOCTYPE = "Regulatory Export"
REGISTRATION_DOCTYPE = "Guest Registration"
STAY_DOCTYPE = "Stay"
GUEST_DOCTYPE = "Guest"

#: Export types this build knows how to collect records for. The doctype
#: offers more (Tourism Levy, VAT Return, E-Invoice, Municipality Report,
#: Audit Export) because a profile may need to describe them, but nothing yet
#: produces their data - generating one of those raises a clear configuration
#: error instead of silently emitting an empty file.
SOURCED_EXPORT_TYPES = ("Guest Registration", "Police Report")

#: Which profile endpoint field a submission goes to, by export type.
ENDPOINT_FIELD_BY_EXPORT_TYPE = {
	"Guest Registration": "guest_registration_endpoint",
	"Police Report": "police_endpoint",
}

#: Submitting to an authority is a management or finance act, not a desk one.
SUBMIT_ROLES = (
	"Finance Manager",
	"Night Auditor",
	"Hotel Manager",
	"General Manager",
	"Hospitality Administrator",
	"System Manager",
)


# ---------------------------------------------------------------------------
# Activation
# ---------------------------------------------------------------------------


def get_profile(property_name: str):
	"""The active regulatory profile for a property, or None.

	None is a legitimate, expected answer - most properties in a
	multi-country deployment will not need one - and every caller in this
	module treats it as "nothing to do" rather than an error.
	"""
	name = frappe.db.get_value(PROFILE_DOCTYPE, {"property": property_name, "is_active": 1}, "name")

	if not name:
		return None

	return frappe.get_cached_doc(PROFILE_DOCTYPE, name)


# ---------------------------------------------------------------------------
# Guest registration
# ---------------------------------------------------------------------------


def register_guest(stay: str) -> dict:
	"""Create the statutory registration snapshot for a stay's guest.

	Idempotent per stay: a second call finds the existing registration and
	returns it rather than creating a duplicate statutory record.
	"""
	stay_doc = frappe.get_doc(STAY_DOCTYPE, stay)

	profile = get_profile(stay_doc.property)

	if not profile or not profile.requires_guest_registration:
		return {"created": False, "registration": None, "duplicate": False}

	lock_document(STAY_DOCTYPE, stay)

	existing = frappe.db.get_value(REGISTRATION_DOCTYPE, {"stay": stay}, "name")

	if existing:
		return {"created": False, "registration": existing, "duplicate": True}

	if not stay_doc.guest:
		throw(_("Stay {0} has no guest to register.").format(stay), exc=HospitalityPMSError)

	guest_doc = frappe.get_doc(GUEST_DOCTYPE, stay_doc.guest)
	identification = _primary_identification(guest_doc)

	registration = frappe.get_doc(
		{
			"doctype": REGISTRATION_DOCTYPE,
			"property": stay_doc.property,
			"guest": guest_doc.name,
			"stay": stay,
			"room": stay_doc.room,
			"registration_status": "Pending",
			"arrival_date": stay_doc.arrival_date,
			"departure_date": stay_doc.departure_date,
			"nationality": guest_doc.nationality,
			"id_type": identification.id_type if identification else None,
			"id_number": identification.id_number if identification else None,
			"id_expiry": identification.expiry_date if identification else None,
			"date_of_birth": guest_doc.date_of_birth,
		}
	).insert(ignore_permissions=True)

	return {"created": True, "registration": registration.name, "duplicate": False}


def _primary_identification(guest_doc):
	if not guest_doc.identifications:
		return None

	return next((row for row in guest_doc.identifications if row.is_primary), guest_doc.identifications[0])


def register_arrivals(property_name: str, business_date=None) -> list[str]:
	"""Register every guest whose stay arrived on a business date.

	Called by the Night Audit; a no-op wherever `register_guest` is a no-op
	(no profile, or the requirement is off), and idempotent through it either way.
	"""
	business_date = getdate(business_date or get_business_date(property_name))

	registered = []

	for stay in frappe.get_all(
		STAY_DOCTYPE,
		filters={
			"property": property_name,
			"arrival_date": business_date,
			"stay_status": ("in", ("In House", "Due Out", "Checked Out")),
		},
		pluck="name",
	):
		result = register_guest(stay)

		if result.get("created"):
			registered.append(result["registration"])

	return registered


def get_pending_registrations(property_name: str) -> list[dict]:
	"""Registrations not yet submitted, for the operations dashboard."""
	profile = get_profile(property_name)

	if not profile or not profile.requires_guest_registration:
		return []

	return frappe.get_all(
		REGISTRATION_DOCTYPE,
		filters={"property": property_name, "registration_status": "Pending"},
		fields=["name", "guest", "stay", "room", "arrival_date", "departure_date", "nationality", "id_type"],
		order_by="arrival_date asc",
		limit_page_length=0,
	)


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------


def generate_export(property_name: str, export_type: str, from_date, to_date) -> dict:
	"""Build one export for a reporting period.

	Keyed by property, type and period so re-running the same request - a
	retried scheduler job, a double click - returns the export already built
	instead of a second one covering the same ground.
	"""
	profile = get_profile(property_name)

	if not profile:
		return {"created": False, "export": None, "duplicate": False}

	from_date = getdate(from_date)
	to_date = getdate(to_date)
	key = f"{property_name}:{export_type}:{from_date}:{to_date}"

	existing = frappe.db.get_value(
		EXPORT_DOCTYPE, {"idempotency_key": key}, ["name", "export_status", "record_count"], as_dict=True
	)

	if existing:
		return {**existing, "created": False, "duplicate": True}

	records = _collect_records(property_name, export_type, from_date, to_date)

	export = frappe.get_doc(
		{
			"doctype": EXPORT_DOCTYPE,
			"property": property_name,
			"regulatory_profile": profile.name,
			"export_type": export_type,
			"export_status": "Generated",
			"from_date": from_date,
			"to_date": to_date,
			"business_date": get_business_date(property_name),
			"idempotency_key": key,
			"record_count": len(records),
			"generated_on": now_datetime(),
			"generated_by": frappe.session.user,
			"payload": json.dumps(records, default=str),
		}
	).insert(ignore_permissions=True)

	# Link the source registrations to the export that carried them, so a
	# registration's own record shows where it was reported.
	for record in records:
		frappe.db.set_value(
			REGISTRATION_DOCTYPE, record["name"], "regulatory_export", export.name, update_modified=False
		)

	return {"created": True, "export": export.name, "record_count": len(records), "duplicate": False}


def _collect_records(property_name: str, export_type: str, from_date, to_date) -> list[dict]:
	if export_type not in SOURCED_EXPORT_TYPES:
		throw(
			_("Export type {0} has no data source configured yet.").format(_(export_type)),
			exc=ConfigurationError,
		)

	return frappe.get_all(
		REGISTRATION_DOCTYPE,
		filters={"property": property_name, "arrival_date": ("between", [from_date, to_date])},
		fields=[
			"name",
			"guest",
			"stay",
			"room",
			"arrival_date",
			"departure_date",
			"nationality",
			"id_type",
			"id_number",
			"id_expiry",
			"date_of_birth",
			"purpose_of_visit",
		],
		order_by="arrival_date asc",
		limit_page_length=0,
	)


def submit_export(export: str, *, acknowledgement_reference: str | None = None) -> dict:
	"""Submit a generated export to its regulatory authority.

	Nothing in this build talks HTTP to a police, tourism or tax authority -
	only channel and hardware adapters are contracted so far (this build's
	scope). Where a profile names an endpoint, this marks the export
	Submitted so the operator's manual or external dispatch has somewhere to
	land its acknowledgement; where it does not, the export is left Generated
	and the returned dict says so plainly rather than pretending anything was
	sent.
	"""
	require_role(SUBMIT_ROLES)

	doc = frappe.get_doc(EXPORT_DOCTYPE, export)

	lock_document(EXPORT_DOCTYPE, export)

	if doc.export_status in ("Submitted", "Acknowledged"):
		return {"export": export, "export_status": doc.export_status, "submitted": True, "duplicate": True}

	if doc.export_status != "Generated":
		throw(
			_("Export {0} is {1} and cannot be submitted.").format(export, _(doc.export_status)),
			exc=HospitalityPMSError,
		)

	profile = frappe.get_cached_doc(PROFILE_DOCTYPE, doc.regulatory_profile)
	endpoint_field = ENDPOINT_FIELD_BY_EXPORT_TYPE.get(doc.export_type)
	endpoint = getattr(profile, endpoint_field, None) if endpoint_field else None

	if not endpoint:
		return {
			"export": export,
			"export_status": "Generated",
			"submitted": False,
			"duplicate": False,
			"message": _(
				"No submission endpoint is configured for {0} on profile {1}; the export remains "
				"Generated. Submit it to the authority through the property's own channel and record "
				"the acknowledgement here manually."
			).format(_(doc.export_type), profile.name),
		}

	frappe.db.set_value(
		EXPORT_DOCTYPE,
		export,
		{
			"export_status": "Submitted",
			"submitted_on": now_datetime(),
			"submitted_by": frappe.session.user,
			"acknowledgement_reference": acknowledgement_reference,
		},
		update_modified=True,
	)

	if doc.export_type in SOURCED_EXPORT_TYPES:
		for registration in frappe.get_all(REGISTRATION_DOCTYPE, filters={"regulatory_export": export}, pluck="name"):
			frappe.db.set_value(
				REGISTRATION_DOCTYPE,
				registration,
				{
					"registration_status": "Submitted",
					"submitted_on": now_datetime(),
					"acknowledgement_reference": acknowledgement_reference,
				},
				update_modified=True,
			)

	return {
		"export": export,
		"export_status": "Submitted",
		"submitted": True,
		"duplicate": False,
		"message": _("Export {0} marked submitted to {1}.").format(export, endpoint),
	}
