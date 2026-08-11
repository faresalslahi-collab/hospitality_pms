"""Every PMS Setting has to be one of four things, and say which.

Phase 1 found five settings that looked like operational controls and did
nothing. Three were real defects and are wired: `enable_overbooking` in Wave 1,
`block_posting_after_close` in Wave 4, and `block_assignment_for_out_of_order`
turned out to be descriptive of a rule that was always enforced.

The two that remain are not defects, and the difference matters. A setting is
only a bug when some existing behaviour was supposed to consult it. Wiring one
that nothing ever asked for is inventing a feature, and the feature invented
that way is always slightly wrong.

* **`reservation_hold_minutes`** would expire a hold. `Tentative` is a real
  status, but it is not in `HOLDING_RESERVATION_STATES` - a tentative booking
  holds no inventory. There is nothing for a timer to release.
* **`cancellation_grace_hours`** would waive a cancellation charge inside a
  grace period. That decision is already made, per policy, by
  `Rate Policy.free_cancellation_hours`, which the code does read. A
  second global rule for the same question would not add a control; it would
  create an ambiguity about which one wins.

So this suite does not test behaviour. It tests that no setting is left
looking operational while doing nothing silently: each one is either read by
production code, or its own description says it is not yet in effect.
"""

import json
import pathlib
import re

import frappe
from frappe.tests import IntegrationTestCase

SETTINGS_DOCTYPE = "PMS Settings"

#: Disposition of every field on PMS Settings.
#:
#: WIRED       production code reads it and behaviour changes with it.
#: DESCRIPTIVE it documents a rule that is always enforced; it cannot be turned off.
#: PLACEHOLDER reserved for behaviour that does not exist yet. Must say so.
#: CONFIG      plain configuration consumed where it is needed.
WIRED = "WIRED"
DESCRIPTIVE = "DESCRIPTIVE"
PLACEHOLDER = "PLACEHOLDER"
CONFIG = "CONFIG"

DISPOSITION = {
	"default_property": CONFIG,
	"enable_multi_property": WIRED,
	"enable_overbooking": WIRED,
	"block_posting_after_close": WIRED,
	"auto_create_housekeeping_task_on_checkout": WIRED,
	"require_inspection_before_release": WIRED,
	"guest_id_image_retention_days": WIRED,
	"integration_log_retention_days": WIRED,
	"temporary_payload_retention_days": WIRED,
	"block_assignment_for_out_of_order": DESCRIPTIVE,
	"retention_note": DESCRIPTIVE,
	# Nothing expires a hold, because nothing holds: Tentative is outside
	# HOLDING_RESERVATION_STATES.
	"reservation_hold_minutes": PLACEHOLDER,
	# Superseded by Rate Policy.free_cancellation_hours, which is read.
	"cancellation_grace_hours": PLACEHOLDER,
	# No publish_realtime call exists anywhere in the app.
	"enable_realtime_updates": PLACEHOLDER,
	# No scheduled Night Audit exists; the audit is run deliberately.
	"night_audit_run_time": PLACEHOLDER,
	# Nothing reads it when a reservation is created.
	"default_reservation_source": PLACEHOLDER,
}

#: A placeholder's description must say this much, in these words, so the
#: person reading the form knows the control is inert.
RESERVED_MARKER = "not yet in effect"

STRUCTURAL = ("Section Break", "Column Break", "Tab Break", "HTML")

APP = pathlib.Path(frappe.get_app_path("hospitality_pms"))

#: Where production code lives. DocType controllers count - `enable_multi_property`
#: is enforced in `Property.validate` and the retention windows in
#: `PMS Settings.validate`, which are as much production as a service is.
SOURCE_DIRECTORIES = (
	"services",
	"api",
	"setup",
	"integrations",
	"utils",
	"tasks.py",
	"hooks.py",
	"hospitality_setup",
	"hospitality_front_office",
	"hospitality_reservations",
	"hospitality_folio",
	"hospitality_rates",
	"hospitality_rooms",
	"hospitality_guests",
	"hospitality_housekeeping",
	"hospitality_night_audit",
	"hospitality_integrations",
	"hospitality_sales",
	"hospitality_services",
	"hospitality_maintenance",
)


def _fields() -> list[dict]:
	path = APP / "hospitality_setup" / "doctype" / "pms_settings" / "pms_settings.json"
	definition = json.loads(path.read_text())

	return [f for f in definition["fields"] if f["fieldtype"] not in STRUCTURAL]


def _production_sources() -> list[pathlib.Path]:
	"""App source that runs in production: no tests, no fixtures."""
	paths: list[pathlib.Path] = []

	for entry in SOURCE_DIRECTORIES:
		target = APP / entry

		if target.is_file():
			paths.append(target)
		elif target.is_dir():
			paths.extend(p for p in target.rglob("*.py") if "__pycache__" not in p.parts)

	return paths


def _is_read_in_production(fieldname: str) -> bool:
	pattern = re.compile(rf"\b{re.escape(fieldname)}\b")

	return any(pattern.search(path.read_text()) for path in _production_sources())


class TestSettingsDisposition(IntegrationTestCase):
	def test_every_setting_has_a_recorded_disposition(self):
		"""A new setting cannot be added without deciding what it is."""
		undeclared = [f["fieldname"] for f in _fields() if f["fieldname"] not in DISPOSITION]

		self.assertFalse(
			undeclared,
			msg=f"these settings have no disposition recorded in this suite: {undeclared}",
		)

	def test_remaining_setting_disposition_is_explicit(self):
		"""No setting looks operational while silently doing nothing.

		The Phase-1 complaint, as an assertion: a control is either read by
		production code, or it tells the reader it is not.
		"""
		silent = []

		for field in _fields():
			name = field["fieldname"]
			disposition = DISPOSITION.get(name)

			if disposition in (WIRED, CONFIG, DESCRIPTIVE):
				continue

			description = (field.get("description") or "").lower()

			if RESERVED_MARKER not in description:
				silent.append(name)

		self.assertFalse(
			silent,
			msg=f"these settings do nothing and do not say so: {silent}",
		)

	def test_wired_settings_are_actually_read(self):
		"""The other direction: a setting called wired must really be consulted."""
		unread = [
			name
			for name, disposition in DISPOSITION.items()
			if disposition == WIRED and not _is_read_in_production(name)
		]

		self.assertFalse(unread, msg=f"declared WIRED but read nowhere in production: {unread}")

	def test_placeholders_are_not_read(self):
		"""And a placeholder must not have quietly grown a caller.

		If one does, it has become behaviour and needs tests and a disposition
		change - not a silent promotion.
		"""
		read = [
			name
			for name, disposition in DISPOSITION.items()
			if disposition == PLACEHOLDER and _is_read_in_production(name)
		]

		self.assertFalse(read, msg=f"declared PLACEHOLDER but read in production: {read}")

	def test_no_tentative_reservation_holds_inventory(self):
		"""The evidence behind `reservation_hold_minutes` being a placeholder.

		A hold timer exists to release held inventory. If Tentative ever starts
		holding inventory, this fails and the setting stops being a placeholder.
		"""
		from hospitality_pms.services.availability import HOLDING_RESERVATION_STATES
		from hospitality_pms.services.reservations import TENTATIVE

		self.assertNotIn(
			TENTATIVE,
			HOLDING_RESERVATION_STATES,
			msg="Tentative now holds inventory, so a hold lifecycle exists and needs expiry",
		)

	def test_cancellation_grace_is_governed_per_policy(self):
		"""The evidence behind `cancellation_grace_hours` being a placeholder."""
		# The grace period is a property of the rate policy being cancelled,
		# which is the level at which a hotel actually negotiates one.
		meta = frappe.get_meta("Rate Policy")

		self.assertTrue(
			meta.has_field("free_cancellation_hours"),
			msg="the per-policy grace field is what the code reads; if it is gone, revisit the setting",
		)
		self.assertTrue(_is_read_in_production("free_cancellation_hours"))

	def test_descriptive_settings_are_read_only(self):
		"""A rule that cannot be turned off must not offer a switch."""
		by_name = {f["fieldname"]: f for f in _fields()}

		for name, disposition in DISPOSITION.items():
			if disposition != DESCRIPTIVE:
				continue

			self.assertTrue(
				by_name[name].get("read_only"),
				msg=f"{name} describes an unconditional rule but is presented as editable",
			)
