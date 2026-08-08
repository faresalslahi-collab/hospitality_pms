"""Key issuance and ID capture, independent of any hardware vendor.

`Hospitality Hardware Device` is a contract-only configuration (HPMS-DEC-020):
this module resolves whichever door lock or scanner adapter a property has
configured - real or, until one is chosen, the deterministic mock - and never
assumes a specific vendor's behaviour.

Two things this module deliberately does NOT do:

* Retry a failed hardware call through the integration failure queue. A guest
  is standing at the desk waiting for a key or waiting to be checked in; a
  failure has to surface to the agent immediately so they can try again or
  hand over a card manually, not be silently queued for a retry five minutes
  later.
* Decide what a scanned identity means. `scan_id` returns normalised fields
  and nothing else - see its docstring.
"""

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime

from hospitality_pms.integrations.hardware import get_door_lock_adapter, get_id_scanner_adapter
from hospitality_pms.services.base import lock_document
from hospitality_pms.services.exceptions import ConfigurationError, HospitalityPMSError, IntegrationError, throw
from hospitality_pms.services.property import get_property

KEY_CARD_DOCTYPE = "Hospitality Key Card"
STAY_DOCTYPE = "Hospitality Stay"
DEVICE_DOCTYPE = "Hospitality Hardware Device"

#: Stay states in which a key still makes sense to issue or matters to cancel.
LIVE_STAY_STATES = ("Expected", "In House", "Due Out")

#: Device types that can encode a room key. Modelled separately from ID
#: scanning because a property may run a dedicated encoder rather than a
#: lock controller that also encodes.
KEY_DEVICE_TYPES = ("Door Lock Controller", "Key Card Encoder")


# ---------------------------------------------------------------------------
# Device resolution
# ---------------------------------------------------------------------------


def _resolve_key_device(property_name: str) -> str:
	device = frappe.db.get_value(
		DEVICE_DOCTYPE,
		{"property": property_name, "is_active": 1, "device_type": ("in", KEY_DEVICE_TYPES)},
		"name",
	)

	if not device:
		throw(
			_("Property {0} has no active door lock or key card encoder device configured.").format(
				property_name
			),
			exc=ConfigurationError,
		)

	return device


def _resolve_scanner_device(property_name: str) -> str:
	device = frappe.db.get_value(
		DEVICE_DOCTYPE,
		{"property": property_name, "is_active": 1, "device_type": "ID Scanner"},
		"name",
	)

	if not device:
		throw(
			_("Property {0} has no active ID scanner device configured.").format(property_name),
			exc=ConfigurationError,
		)

	return device


def _default_valid_until(stay_doc) -> str:
	"""The stay's departure at the property's check-out time."""
	check_out_time = get_property(stay_doc.property).check_out_time
	return get_datetime(f"{stay_doc.departure_date} {check_out_time}")


# ---------------------------------------------------------------------------
# Key issuance
# ---------------------------------------------------------------------------


def issue_key(stay: str, valid_until=None, *, is_duplicate: bool = False) -> dict:
	"""Issue a key card for a stay through the property's configured device.

	A second call for the same stay is not refused: a lost or additional card
	is a normal front desk request, not an error. The caller says so with
	`is_duplicate` and the card carries that flag rather than hiding it
	(per the Hospitality Key Card doctype's own description).
	"""
	stay_doc = frappe.get_doc(STAY_DOCTYPE, stay)

	lock_document(STAY_DOCTYPE, stay)

	if stay_doc.stay_status not in LIVE_STAY_STATES:
		throw(
			_("Stay {0} is {1}; a key cannot be issued.").format(stay, _(stay_doc.stay_status)),
			exc=HospitalityPMSError,
		)

	if not stay_doc.room:
		throw(_("Stay {0} has no room assigned yet.").format(stay), exc=HospitalityPMSError)

	device = _resolve_key_device(stay_doc.property)

	valid_from = now_datetime()
	valid_until = get_datetime(valid_until) if valid_until else _default_valid_until(stay_doc)

	adapter = get_door_lock_adapter(device)
	result = adapter.encode_key(
		stay_doc.room,
		valid_from,
		valid_until,
		metadata={"stay": stay, "guest": stay_doc.guest, "room": stay_doc.room},
	)

	if not result.success:
		throw(
			_("Key encoding failed: {0}").format(result.failure_reason or _("unknown error")),
			exc=IntegrationError,
		)

	card = frappe.get_doc(
		{
			"doctype": KEY_CARD_DOCTYPE,
			"property": stay_doc.property,
			"stay": stay,
			"room": stay_doc.room,
			"guest": stay_doc.guest,
			"card_status": "Issued",
			"card_reference": result.card_reference,
			"device": device,
			"valid_from": valid_from,
			"valid_until": valid_until,
			"issued_by": frappe.session.user,
			"issued_on": now_datetime(),
			"is_duplicate": 1 if is_duplicate else 0,
		}
	).insert(ignore_permissions=True)

	frappe.db.set_value(
		STAY_DOCTYPE, stay, "key_cards_issued", int(stay_doc.key_cards_issued or 0) + 1, update_modified=False
	)

	return {
		"key_card": card.name,
		"card_reference": result.card_reference,
		"valid_from": str(valid_from),
		"valid_until": str(valid_until),
		"is_duplicate": bool(is_duplicate),
	}


def cancel_key(key_card: str, reason: str) -> dict:
	"""Invalidate one key card at the lock."""
	if not reason or not reason.strip():
		throw(_("A reason is required to cancel a key card."))

	doc = frappe.get_doc(KEY_CARD_DOCTYPE, key_card)

	lock_document(KEY_CARD_DOCTYPE, key_card)

	if doc.card_status == "Cancelled":
		return {"key_card": key_card, "card_status": "Cancelled", "duplicate": True}

	if doc.device and doc.card_reference:
		adapter = get_door_lock_adapter(doc.device)
		result = adapter.cancel_key(doc.card_reference)

		if not result.success:
			throw(
				_("Key cancellation failed: {0}").format(result.failure_reason or _("unknown error")),
				exc=IntegrationError,
			)

	frappe.db.set_value(
		KEY_CARD_DOCTYPE,
		key_card,
		{"card_status": "Cancelled", "cancelled_on": now_datetime(), "cancelled_by": frappe.session.user},
		update_modified=True,
	)

	return {"key_card": key_card, "card_status": "Cancelled", "duplicate": False, "reason": reason.strip()}


def cancel_keys_for_stay(stay: str, reason: str) -> list[dict]:
	"""Cancel every still-live key card for a stay. Called at checkout."""
	cards = frappe.get_all(
		KEY_CARD_DOCTYPE,
		filters={"stay": stay, "card_status": ("not in", ("Cancelled", "Expired"))},
		pluck="name",
	)

	return [cancel_key(card, reason) for card in cards]


# ---------------------------------------------------------------------------
# ID capture
# ---------------------------------------------------------------------------


def scan_id(property_name: str, payload: dict) -> dict:
	"""Run the property's ID scanner and return normalised identity fields.

	Deliberately does not write anything to a guest record. A scan can
	misread a document, and the front desk agent - not this function - is the
	one who sees the physical document and the guest in front of them and
	decides whether to accept the read, correct it, or reject it. Persisting
	the read here would let a bad scan silently overwrite a guest's real
	identity with no human in the loop.
	"""
	device = _resolve_scanner_device(property_name)

	adapter = get_id_scanner_adapter(device)
	result = adapter.scan(payload)

	if not result.success:
		throw(
			_("ID scan failed: {0}").format(result.failure_reason or _("unknown error")),
			exc=IntegrationError,
		)

	return {
		"first_name": result.first_name,
		"last_name": result.last_name,
		"nationality": result.nationality,
		"id_type": result.id_type,
		"id_number": result.id_number,
		"id_expiry": result.id_expiry,
		"date_of_birth": result.date_of_birth,
	}
