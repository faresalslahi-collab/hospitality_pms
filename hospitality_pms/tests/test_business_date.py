"""The closed business date, and who is allowed to move it.

Three things this covers, all of them boundaries around a date the hotel has
already reported on:

* `PMS Settings.block_posting_after_close` was proven dead - the flag existed
  and was read nowhere, so a front-desk charge could be back-dated into a day
  whose Night Audit had closed and whose revenue had already been reported.
* Night Audit endpoints checked `Night Audit` write permission and nothing
  else, so neither the property boundary Wave 1 established nor the auditor
  role applied at the endpoint.
* Every field the close gate reads is `read_only` on the DocType, which hides
  it in a form and stops nothing else. The people holding Night Audit write are
  precisely the people the gate constrains, so those fields cannot also be
  theirs to fill in.
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days

from hospitality_pms.services import folio as folio_service
from hospitality_pms.services import night_audit as audit_service
from hospitality_pms.services.exceptions import (
	FolioError,
	NightAuditError,
	PermissionDeniedError,
)
from hospitality_pms.tests.night_audit_world import NightAuditWorld

AUDIT = "Night Audit"


class BusinessDateTestCase(IntegrationTestCase):
	WORLD_CODE = "BD"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.world = NightAuditWorld(cls.__name__[:6].upper(), cls.WORLD_CODE)
		cls.start_date = cls.world.business_date

	@classmethod
	def tearDownClass(cls):
		cls.world.teardown()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.delete("Night Audit Exception", {"parenttype": AUDIT})
		frappe.db.delete(AUDIT, {"property": self.world.property})
		self.world.set_business_date(self.start_date)
		self.world.fixtures.set_setting("block_posting_after_close", 0)
		frappe.db.commit()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def _close_a_day(self):
		"""Close the current business date and return the date that was closed."""
		closed = self.world.business_date
		audit = audit_service.start(self.world.property)

		audit_service.review(audit)
		audit_service.post_room_charges(audit)
		audit_service.reconcile(audit)
		audit_service.close(audit)

		frappe.db.commit()

		return closed


class TestBlockPostingAfterClose(BusinessDateTestCase):
	WORLD_CODE = "BC"

	def test_normal_charge_refused_on_closed_business_date(self):
		"""The setting the sweep found dead."""
		self.world.fixtures.set_setting("block_posting_after_close", 1)
		closed = self._close_a_day()

		guest = self.world.fixtures.guest("Backdater")
		folio = self.world.fixtures.folio(self.world.property, guest)

		with self.assertRaises(FolioError) as caught:
			folio_service.post_charge(
				folio,
				"Minibar",
				"Back-dated into a closed day",
				40,
				idempotency_key=f"{self.world.tag}:bd:1",
				business_date=closed,
			)

		self.assertIn("closed", str(caught.exception).lower())

	def test_normal_payment_refused_on_closed_business_date(self):
		self.world.fixtures.set_setting("block_posting_after_close", 1)
		closed = self._close_a_day()

		guest = self.world.fixtures.guest("Backpayer")
		folio = self.world.fixtures.folio(self.world.property, guest)

		with self.assertRaises(FolioError):
			folio_service.post_payment(
				folio,
				40,
				"Cash",
				idempotency_key=f"{self.world.tag}:bd:2",
				business_date=closed,
			)

	def test_charge_on_the_open_business_date_is_unaffected(self):
		"""Only the closed day is fenced off; today carries on as normal."""
		self.world.fixtures.set_setting("block_posting_after_close", 1)
		self._close_a_day()

		guest = self.world.fixtures.guest("Today")
		folio = self.world.fixtures.folio(self.world.property, guest)

		result = folio_service.post_charge(
			folio,
			"Minibar",
			"Today's water",
			40,
			idempotency_key=f"{self.world.tag}:bd:3",
		)

		self.assertFalse(result["duplicate"])

	def test_setting_disabled_preserves_allowed_behavior(self):
		"""With the switch off, nothing changes - existing role controls still apply."""
		self.world.fixtures.set_setting("block_posting_after_close", 0)
		closed = self._close_a_day()

		guest = self.world.fixtures.guest("Permitted")
		folio = self.world.fixtures.folio(self.world.property, guest)

		result = folio_service.post_charge(
			folio,
			"Minibar",
			"Back-dated, but permitted",
			40,
			idempotency_key=f"{self.world.tag}:bd:4",
			business_date=closed,
		)

		self.assertFalse(result["duplicate"])

	def test_privileged_adjustment_may_still_correct_a_closed_day(self):
		"""Corrections must stay possible, or a mistake becomes permanent.

		An adjustment already demands an elevated role and a written reason,
		which is the difference between correcting a closed day and quietly
		back-dating into one.
		"""
		self.world.fixtures.set_setting("block_posting_after_close", 1)
		closed = self._close_a_day()

		guest = self.world.fixtures.guest("Corrected")
		folio = self.world.fixtures.folio(self.world.property, guest)

		result = folio_service.post_charge(
			folio,
			"Adjustment",
			"Correcting a closed day",
			-25,
			idempotency_key=f"{self.world.tag}:bd:5",
			business_date=closed,
		)

		self.assertFalse(result["duplicate"])

	def test_another_propertys_closed_date_does_not_block(self):
		"""The fence is per property; one hotel's close is not another's."""
		self.world.fixtures.set_setting("block_posting_after_close", 1)
		closed = self._close_a_day()

		other = self.world.fixtures.property("BX")
		guest = self.world.fixtures.guest("Elsewhere")
		other_folio = self.world.fixtures.folio(other, guest)
		frappe.db.commit()

		result = folio_service.post_charge(
			other_folio,
			"Minibar",
			"A different hotel entirely",
			40,
			idempotency_key=f"{self.world.tag}:bd:6",
			business_date=closed,
		)

		self.assertFalse(result["duplicate"])


class TestNightAuditAuthorization(BusinessDateTestCase):
	WORLD_CODE = "BA"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()

		cls.auditor = cls.world.fixtures.user(
			"auditor", ["Night Auditor"], properties=[cls.world.property]
		)
		# Holds Night Audit write by the approved matrix, and is not an auditor.
		cls.finance = cls.world.fixtures.user(
			"finance", ["Finance Manager"], properties=[cls.world.property]
		)
		cls.front_desk = cls.world.fixtures.user(
			"desk", ["Front Office Agent"], properties=[cls.world.property]
		)

		frappe.db.commit()

	def test_unauthorized_role_cannot_close_or_reopen(self):
		"""Night Audit write is not the same authority as closing the day."""
		from hospitality_pms.api import night_audit as audit_api

		audit = audit_service.start(self.world.property)
		audit_service.review(audit)
		audit_service.post_room_charges(audit)
		audit_service.reconcile(audit)
		frappe.db.commit()

		frappe.set_user(self.finance)

		with self.assertRaises(PermissionDeniedError):
			audit_api.close(audit=audit)

	def test_front_desk_cannot_run_the_audit(self):
		from hospitality_pms.api import night_audit as audit_api

		audit = audit_service.start(self.world.property)
		frappe.db.commit()

		frappe.set_user(self.front_desk)

		with self.assertRaises(PermissionDeniedError):
			audit_api.review(audit=audit)

	def test_auditor_from_another_property_is_refused(self):
		"""Wave 1's property boundary applies to the audit endpoints too."""
		from hospitality_pms.api import night_audit as audit_api

		other = self.world.fixtures.property("BY")
		outsider = self.world.fixtures.user(
			"otheraud", ["Night Auditor"], properties=[other]
		)

		audit = audit_service.start(self.world.property)
		frappe.db.commit()

		frappe.set_user(outsider)

		with self.assertRaises((PermissionDeniedError, frappe.PermissionError)):
			audit_api.review(audit=audit)

	def test_the_auditor_can_run_the_audit(self):
		from hospitality_pms.api import night_audit as audit_api

		audit = audit_service.start(self.world.property)
		frappe.db.commit()

		frappe.set_user(self.auditor)

		result = audit_api.review(audit=audit)

		self.assertTrue(result["result"]["audit"])


class TestAuditDocumentIntegrity(BusinessDateTestCase):
	"""Part 14 — the close gate reads fields nobody may hand-write."""

	WORLD_CODE = "BI"

	def test_generic_save_cannot_fake_completion_markers(self):
		audit = audit_service.start(self.world.property)
		frappe.db.commit()

		doc = frappe.get_doc(AUDIT, audit)
		doc.posting_completed_on = frappe.utils.now_datetime()
		doc.reconciliation_completed_on = frappe.utils.now_datetime()

		with self.assertRaises(NightAuditError):
			doc.save(ignore_permissions=True)

		frappe.db.rollback()

		self.assertIsNone(frappe.db.get_value(AUDIT, audit, "posting_completed_on"))

	def test_generic_save_cannot_force_the_status(self):
		audit = audit_service.start(self.world.property)
		frappe.db.commit()

		doc = frappe.get_doc(AUDIT, audit)
		doc.audit_status = audit_service.READY_TO_CLOSE

		with self.assertRaises(NightAuditError):
			doc.save(ignore_permissions=True)

		frappe.db.rollback()

		self.assertEqual(frappe.db.get_value(AUDIT, audit, "audit_status"), audit_service.OPEN)

	def test_generic_save_cannot_rewrite_revenue(self):
		audit = audit_service.start(self.world.property)
		frappe.db.commit()

		doc = frappe.get_doc(AUDIT, audit)
		doc.room_revenue = 99999

		with self.assertRaises(NightAuditError):
			doc.save(ignore_permissions=True)

		frappe.db.rollback()

	def test_generic_save_cannot_move_the_audits_business_date(self):
		audit = audit_service.start(self.world.property)
		frappe.db.commit()

		doc = frappe.get_doc(AUDIT, audit)
		doc.business_date = add_days(self.world.business_date, -5)

		with self.assertRaises(NightAuditError):
			doc.save(ignore_permissions=True)

		frappe.db.rollback()

	def test_notes_remain_editable(self):
		"""The guard is narrow: annotating the day is not declaring it done."""
		audit = audit_service.start(self.world.property)
		frappe.db.commit()

		doc = frappe.get_doc(AUDIT, audit)
		doc.notes = "Handover: two late arrivals expected."
		doc.save(ignore_permissions=True)

		self.assertIn("Handover", frappe.db.get_value(AUDIT, audit, "notes"))

	def test_the_property_business_date_is_service_owned(self):
		"""Only the Night Audit may move it - the pre-existing Property guard."""
		from hospitality_pms.services.exceptions import ConfigurationError

		doc = frappe.get_doc("Property", self.world.property)
		doc.business_date = add_days(self.world.business_date, 3)

		with self.assertRaises(ConfigurationError):
			doc.save(ignore_permissions=True)

		frappe.db.rollback()
