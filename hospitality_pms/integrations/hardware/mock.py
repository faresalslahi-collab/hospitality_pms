"""Deterministic mock hardware adapters.

No door lock or ID scanner vendor has been chosen yet (HPMS-DEC-020). These
adapters exist so that check-in, key issuance and ID capture can be built and
tested *now*: they always succeed, never touch a network, and echo back
predictable values, so a test can assert on the exact card reference or
identity fields it will get without depending on any real device. They are
registered as the default in `__init__.py` and are expected to be swapped for
a real vendor per property once one is selected - nothing above this layer
changes when that happens.
"""

import frappe

from hospitality_pms.integrations.hardware.base import DoorLockAdapter, IdentityResult, IDScannerAdapter, KeyResult


class MockDoorLockAdapter(DoorLockAdapter):
	"""Always-succeeds door lock adapter with no real hardware behind it.

	Card references are generated locally rather than returned by any
	controller, so they are stable and inspectable in tests.
	"""

	name = "Mock"

	def encode_key(self, room: str, valid_from, valid_until, metadata: dict | None = None) -> KeyResult:
		card_reference = f"MOCK-{frappe.generate_hash(length=10).upper()}"

		self.log_request(
			direction="Outbound",
			endpoint=None,
			method=None,
			request_payload={"room": room, "valid_from": str(valid_from), "valid_until": str(valid_until), "metadata": metadata},
			response_payload={"card_reference": card_reference, "status": "Issued"},
			is_success=True,
		)

		return KeyResult(success=True, card_reference=card_reference, status="Issued", raw={"room": room})

	def cancel_key(self, card_reference: str) -> KeyResult:
		self.log_request(
			direction="Outbound",
			endpoint=None,
			method=None,
			request_payload={"card_reference": card_reference},
			response_payload={"status": "Cancelled"},
			is_success=True,
		)

		return KeyResult(success=True, card_reference=card_reference, status="Cancelled")

	def read_key(self, card_reference: str) -> KeyResult:
		self.log_request(
			direction="Outbound",
			endpoint=None,
			method=None,
			request_payload={"card_reference": card_reference},
			response_payload={"status": "Active"},
			is_success=True,
		)

		return KeyResult(success=True, card_reference=card_reference, status="Active")


class MockIDScannerAdapter(IDScannerAdapter):
	"""Always-succeeds ID scanner adapter with no real capture device behind it.

	Rather than fabricate identity data, it echoes back whatever identity
	fields the caller already put in `payload` - which is exactly what a test
	(or a manual-entry fallback UI) needs: full control over what "the
	scanner" reports, so check-in and Guest Registration logic can be
	exercised deterministically before a real scanner exists.
	"""

	name = "Mock"

	def scan(self, payload: dict) -> IdentityResult:
		self.log_request(
			direction="Outbound",
			endpoint=None,
			method=None,
			request_payload={k: v for k, v in payload.items() if k != "image"},
			response_payload=payload,
			is_success=True,
		)

		return IdentityResult(
			success=True,
			first_name=payload.get("first_name"),
			last_name=payload.get("last_name"),
			nationality=payload.get("nationality"),
			id_type=payload.get("id_type"),
			id_number=payload.get("id_number"),
			id_expiry=payload.get("id_expiry"),
			date_of_birth=payload.get("date_of_birth"),
			raw=payload,
		)
