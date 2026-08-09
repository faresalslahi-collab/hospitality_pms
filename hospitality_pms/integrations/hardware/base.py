"""Hardware adapter interfaces: contracts only (HPMS-DEC-020).

No vendor door lock, key encoder or ID scanner has been chosen. What is fixed
here is the shape `HardwareService` (`services/hardware.py`) is written
against, so that:

* Check-in, key issuance and ID capture can be built and tested now, against
  the deterministic mock adapters in `mock.py`, without waiting on a vendor.
* Choosing a vendor later means writing one adapter module and adding it to
  the registry in `__init__.py` - never touching `HardwareService`, the Stay
  or Guest Registration doctypes, or the check-in flow.

Both adapter families share the same plumbing (`get_secret`, `log_request`)
via `HardwareAdapter`; they differ only in the `integration_type` they log
under and the capability methods they contract for.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import frappe
from frappe.utils import now_datetime

INTEGRATION_LOG = "PMS Integration Log"


@dataclass
class KeyResult:
	"""What a door lock controller says happened to one key operation."""

	success: bool
	card_reference: str | None = None
	status: str | None = None
	failure_reason: str | None = None
	raw: dict = field(default_factory=dict)


@dataclass
class IdentityResult:
	"""Identity fields read off a travel document, normalised to one shape.

	Every scanner vendor returns something different; this is the shape every
	adapter translates into, matching the "as reported" fields on
	`Guest Registration` and `Guest Identification`.
	"""

	success: bool
	first_name: str | None = None
	last_name: str | None = None
	nationality: str | None = None
	id_type: str | None = None
	id_number: str | None = None
	id_expiry: str | None = None
	date_of_birth: str | None = None
	failure_reason: str | None = None
	raw: dict = field(default_factory=dict)


class HardwareAdapter(ABC):
	"""Shared plumbing for every hardware adapter, door lock or scanner alike."""

	#: Adapter name as it appears in the integration log.
	name: str = ""

	#: Set by each concrete family (`Door Lock`, `ID Scanner`) so the shared
	#: `log_request` writes to the correct integration type without every
	#: adapter having to pass it in on every call.
	integration_type: str = ""

	def __init__(self, config):
		self.config = config
		self.property = config.property

	def get_secret(self, fieldname: str) -> str | None:
		"""Read an encrypted credential off the device configuration row."""
		return self.config.get_password(fieldname, raise_exception=False)

	def log_request(
		self,
		*,
		direction: str,
		endpoint: str | None,
		method: str | None,
		request_payload=None,
		response_payload=None,
		status_code: int | None = None,
		is_success: bool = True,
		error_message: str | None = None,
		reference_doctype: str | None = None,
		reference_name: str | None = None,
		duration_ms: int | None = None,
	):
		"""Record a call in the integration log.

		Inserted with `ignore_permissions` because the log records what the
		system did, not what the user is allowed to write.
		"""
		import json

		frappe.get_doc(
			{
				"doctype": INTEGRATION_LOG,
				"property": self.property,
				"integration_type": self.integration_type,
				"provider": self.name or self.config.provider,
				"direction": direction,
				"endpoint": endpoint,
				"method": method,
				"reference_doctype": reference_doctype,
				"reference_name": reference_name,
				"request_payload": json.dumps(request_payload, default=str) if request_payload else None,
				"response_payload": json.dumps(response_payload, default=str) if response_payload else None,
				"status_code": status_code,
				"is_success": 1 if is_success else 0,
				"error_message": error_message,
				"duration_ms": duration_ms,
				"requested_on": now_datetime(),
			}
		).insert(ignore_permissions=True)


class DoorLockAdapter(HardwareAdapter):
	"""Base class for a door lock controller / key card encoder adapter."""

	integration_type = "Door Lock"

	@abstractmethod
	def encode_key(self, room: str, valid_from, valid_until, metadata: dict | None = None) -> KeyResult:
		"""Encode a physical or mobile key valid for one room over a date range."""

	@abstractmethod
	def cancel_key(self, card_reference: str) -> KeyResult:
		"""Invalidate a previously issued key at the lock, immediately."""

	@abstractmethod
	def read_key(self, card_reference: str) -> KeyResult:
		"""Ask the controller what a card is currently encoded for.

		Used to confirm a card was really cancelled, or to diagnose a guest's
		complaint that a key stopped working.
		"""


class IDScannerAdapter(HardwareAdapter):
	"""Base class for an ID / passport scanner adapter."""

	integration_type = "ID Scanner"

	@abstractmethod
	def scan(self, payload: dict) -> IdentityResult:
		"""Extract identity fields from a scanned document.

		`payload` is whatever the capture device or upstream client sent (an
		image reference, an MRZ string, a vendor SDK response) - the adapter's
		job is entirely to normalise it to `IdentityResult`, never to decide
		what happens with the result.
		"""
