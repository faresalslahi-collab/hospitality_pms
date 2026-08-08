"""Hardware adapter registry.

`HardwareService` never imports a concrete adapter. It calls `get_door_lock_adapter`
or `get_id_scanner_adapter` and talks to the interface in `base.py`, so
choosing a vendor is a new adapter module plus a registry entry here - never a
change to `HardwareService`, the Stay controller or the check-in flow
(HPMS-DEC-020).

`Hospitality Hardware Device.provider` is a free-text field: no vendor has
been selected, so there is nothing to constrain it to yet. A device whose
provider is blank, or does not match a registered vendor adapter, resolves to
the deterministic mock - the property can be configured, checked in against,
and issue keys, before a vendor contract exists.
"""

import frappe

DEVICE_DOCTYPE = "Hospitality Hardware Device"

MOCK_DOOR_LOCK_ADAPTER = "hospitality_pms.integrations.hardware.mock.MockDoorLockAdapter"
MOCK_ID_SCANNER_ADAPTER = "hospitality_pms.integrations.hardware.mock.MockIDScannerAdapter"

#: `Hospitality Hardware Device.provider` -> adapter class path. Empty until a
#: real vendor is contracted; every device falls back to the mock below.
DOOR_LOCK_ADAPTERS: dict[str, str] = {}

#: Same idea for ID scanners.
ID_SCANNER_ADAPTERS: dict[str, str] = {}


def get_door_lock_adapter(device: str):
	"""Instantiate the door lock / key encoder adapter configured for a device."""
	config = frappe.get_cached_doc(DEVICE_DOCTYPE, device)
	path = DOOR_LOCK_ADAPTERS.get(config.provider) or MOCK_DOOR_LOCK_ADAPTER

	return frappe.get_attr(path)(config)


def get_id_scanner_adapter(device: str):
	"""Instantiate the ID scanner adapter configured for a device."""
	config = frappe.get_cached_doc(DEVICE_DOCTYPE, device)
	path = ID_SCANNER_ADAPTERS.get(config.provider) or MOCK_ID_SCANNER_ADAPTER

	return frappe.get_attr(path)(config)
