"""P1-7, P1-9 and P2-1 — the Night Audit closed on trust.

**P1-7.** `close()` checked the workflow status and the exception list, and
nothing else. `review()` moved the audit to Reviewing; Reviewing may legally
reach Ready to Close; so review-then-close advanced the property's business date
with `charges_posted = 0`, `room_revenue = 0` and no nightly room charge on any
folio. The audit treated *having a status* as proof that the accounting behind
that status had happened.

**P1-9.** Reconciliation examined `limit=200` folios ordered by `modified desc`.
The ordering is deterministic, which is what makes it a systematic blind spot
rather than a lottery: the oldest folios are never looked at, and a variance
sitting in one of them closes the day undetected.

**P2-1.** Room-charge posting was idempotent in the folio and not in the audit.
A retry posted nothing, so `revenue` accumulated nothing, and `room_revenue` was
overwritten with that nothing. ADR and RevPAR were computed from
`doc.room_revenue` in `review()` and `reconcile()` - never after posting - so
they were a step behind whatever the posting run had just done.
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, getdate

from hospitality_pms.services import folio as folio_service
from hospitality_pms.services import night_audit as audit_service
from hospitality_pms.services.exceptions import NightAuditError
from hospitality_pms.tests.night_audit_world import NightAuditWorld

AUDIT = "Night Audit"
PRECISION = 2


class NightAuditTestCase(IntegrationTestCase):
	WORLD_CODE = "NA"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.world = NightAuditWorld(cls.__name__[:6].upper(), cls.WORLD_CODE)

	@classmethod
	def tearDownClass(cls):
		cls.world.teardown()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")
		self._clear_audits()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def _clear_audits(self):
		frappe.db.delete("Night Audit Exception", {"parenttype": AUDIT})
		frappe.db.delete(AUDIT, {"property": self.world.property})
		frappe.db.commit()

	def _audit(self) -> str:
		return audit_service.start(self.world.property)

	def _field(self, audit: str, fieldname: str):
		return frappe.db.get_value(AUDIT, audit, fieldname)

	def assertMoney(self, actual, expected, msg=None):
		self.assertAlmostEqual(flt(actual), flt(expected), places=PRECISION, msg=msg)


class TestCloseGate(NightAuditTestCase):
	"""P1-7 — the business date moves only on durable proof of the work."""

	WORLD_CODE = "NC"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.world.check_in_guest(0)

	def test_close_after_review_only_is_refused(self):
		"""The exact reproduction: review, then close, and the day rolls over."""
		audit = self._audit()
		before = self.world.business_date

		audit_service.review(audit)

		with self.assertRaises(NightAuditError):
			audit_service.close(audit)

		self.assertEqual(
			self.world.business_date,
			before,
			msg="the business date advanced without the day's charges being posted",
		)
		self.assertNotEqual(self._field(audit, "audit_status"), audit_service.CLOSED)

	def test_close_without_reconciliation_is_refused(self):
		audit = self._audit()
		audit_service.review(audit)
		audit_service.post_room_charges(audit)

		with self.assertRaises(NightAuditError):
			audit_service.close(audit)

	def test_close_without_posting_is_refused(self):
		audit = self._audit()
		audit_service.review(audit)
		audit_service.reconcile(audit)

		with self.assertRaises(NightAuditError):
			audit_service.close(audit)

	def test_close_requires_review_posting_and_reconciliation(self):
		"""The whole sequence, and only then does the date move."""
		audit = self._audit()
		before = self.world.business_date

		audit_service.review(audit)
		audit_service.post_room_charges(audit)
		audit_service.reconcile(audit)

		result = audit_service.close(audit)

		self.assertEqual(getdate(result["new_business_date"]), add_days(before, 1))
		self.assertEqual(self.world.business_date, add_days(before, 1))
		self.assertEqual(self._field(audit, "audit_status"), audit_service.CLOSED)

	def test_close_advances_exactly_one_day(self):
		audit = self._audit()
		before = self.world.business_date

		audit_service.review(audit)
		audit_service.post_room_charges(audit)
		audit_service.reconcile(audit)
		audit_service.close(audit)

		self.assertEqual(self.world.business_date, add_days(before, 1))

	def test_close_refuses_stale_reconciliation(self):
		"""Money posted after the reconciliation invalidates it.

		A count of zero variances is only worth anything against the money that
		was there when it was counted. A late charge on the audit date changes
		the answer, so the audit must be reconciled again rather than closing on
		the earlier result.
		"""
		audit = self._audit()

		audit_service.review(audit)
		audit_service.post_room_charges(audit)
		audit_service.reconcile(audit)

		# A legitimate late charge, on the very date being closed.
		stay = frappe.get_all(
			"Stay", filters={"property": self.world.property}, fields=["folio"], limit=1
		)[0]
		folio_service.post_charge(
			stay["folio"],
			"Minibar",
			"Late minibar",
			20,
			idempotency_key=f"{self.world.tag}:late:1",
			business_date=self.world.business_date,
		)

		with self.assertRaises(NightAuditError) as caught:
			audit_service.close(audit)

		self.assertIn("reconcil", str(caught.exception).lower())

		# Reconciling again clears it.
		audit_service.reconcile(audit)
		audit_service.close(audit)

		self.assertEqual(self._field(audit, "audit_status"), audit_service.CLOSED)

	def test_close_refuses_unresolved_blocking_exception(self):
		audit = self._audit()
		audit_service.review(audit)
		audit_service.post_room_charges(audit)
		audit_service.reconcile(audit)

		doc = frappe.get_doc(AUDIT, audit)
		doc.append(
			"audit_exceptions",
			{
				"exception_type": "Failed Posting",
				"description": "planted",
				"severity": audit_service.BLOCKING,
			},
		)
		doc.flags.hpms_night_audit_service = True
		doc.save(ignore_permissions=True)

		with self.assertRaises(NightAuditError):
			audit_service.close(audit)

	def test_close_refuses_durable_failed_posting(self):
		"""Wave 3's durable failure evidence blocks the close.

		The Financial Posting Log row for a posting that took its transaction
		down with it does not exist - that was P1-14. The durable operation
		ledger is the authority now, and the audit reads it.
		"""
		from hospitality_pms.services import durability

		audit = self._audit()
		audit_service.review(audit)
		audit_service.post_room_charges(audit)
		audit_service.reconcile(audit)

		durability.begin_operation(
			property_name=self.world.property,
			integration_type="Other",
			operation="post_folio_invoice",
			operation_key=f"{self.world.tag}:na:failed:1",
			payload={"folio": "whatever"},
		)
		durability.fail_operation(f"{self.world.tag}:na:failed:1", error="ERP refused")

		try:
			with self.assertRaises(NightAuditError) as caught:
				audit_service.close(audit)

			self.assertIn("posting", str(caught.exception).lower())
		finally:
			durability.purge_operations(property_name=self.world.property)

	def test_review_posting_and_reconciliation_are_recorded_durably(self):
		"""A counter of zero cannot say whether a step ran. A timestamp can."""
		audit = self._audit()

		self.assertIsNone(self._field(audit, "review_completed_on"))

		audit_service.review(audit)
		self.assertIsNotNone(self._field(audit, "review_completed_on"))
		self.assertIsNone(self._field(audit, "posting_completed_on"))

		audit_service.post_room_charges(audit)
		self.assertIsNotNone(self._field(audit, "posting_completed_on"))
		self.assertIsNone(self._field(audit, "reconciliation_completed_on"))

		audit_service.reconcile(audit)
		self.assertIsNotNone(self._field(audit, "reconciliation_completed_on"))


class TestRoomChargeRetry(NightAuditTestCase):
	"""P2-1 — the figures must be facts, not a diff of the last run."""

	WORLD_CODE = "NR"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.world.check_in_guest(0)
		cls.world.check_in_guest(1)

	def _metrics(self, audit: str) -> dict:
		return frappe.db.get_value(
			AUDIT,
			audit,
			["rooms_charged", "charges_posted", "room_revenue", "total_revenue", "adr", "revpar"],
			as_dict=True,
		)

	def test_room_charge_retry_preserves_revenue(self):
		audit = self._audit()
		audit_service.review(audit)

		audit_service.post_room_charges(audit)
		first = self._metrics(audit)

		audit_service.post_room_charges(audit)
		second = self._metrics(audit)

		self.assertMoney(first["room_revenue"], 200, msg="two rooms at 100 should be 200")
		self.assertMoney(
			second["room_revenue"],
			first["room_revenue"],
			msg="the retry overwrote the day's revenue with the delta from a run that posted nothing",
		)
		self.assertEqual(second["rooms_charged"], first["rooms_charged"])

	def test_room_charge_retry_preserves_adr_revpar(self):
		audit = self._audit()
		audit_service.review(audit)

		audit_service.post_room_charges(audit)
		first = self._metrics(audit)

		audit_service.post_room_charges(audit)
		second = self._metrics(audit)

		self.assertMoney(second["adr"], first["adr"])
		self.assertMoney(second["revpar"], first["revpar"])

	def test_figures_reflect_the_posting_that_just_happened(self):
		"""ADR and RevPAR were computed before room revenue was resolved."""
		audit = self._audit()
		audit_service.review(audit)
		audit_service.post_room_charges(audit)

		metrics = self._metrics(audit)

		# 200 of revenue over 2 occupied rooms, and over 4 sellable ones.
		self.assertMoney(metrics["room_revenue"], 200)
		self.assertMoney(metrics["adr"], 100, msg="ADR was a step behind the posting run")
		self.assertMoney(metrics["revpar"], 50, msg="RevPAR was a step behind the posting run")

	def test_retry_creates_no_second_charge_row(self):
		audit = self._audit()
		audit_service.review(audit)

		audit_service.post_room_charges(audit)
		audit_service.post_room_charges(audit)

		rows = frappe.db.sql(
			"""
			select count(*) from `tabFolio Charge` c
			inner join `tabGuest Folio` f on f.name = c.parent
			where f.property = %s and c.charge_type = 'Room Charge' and c.business_date = %s
			""",
			(self.world.property, self.world.business_date),
		)[0][0]

		self.assertEqual(rows, 2, msg="the retry duplicated the night's room charges")


class TestExhaustiveReconciliation(NightAuditTestCase):
	"""P1-9 — reconciliation must look at all of its population."""

	WORLD_CODE = "NX"

	def test_reconciliation_examines_more_than_200_folios(self):
		self.world.bulk_settled_folios(205)

		audit = self._audit()
		audit_service.review(audit)
		audit_service.post_room_charges(audit)
		result = audit_service.reconcile(audit)

		self.assertGreaterEqual(
			result["population"],
			205,
			msg=f"reconciliation stopped short of its population: {result}",
		)
		self.assertEqual(
			self._field(audit, "reconciliation_population"),
			result["population"],
			msg="the population examined must be recorded, so zero variances can be interpreted",
		)

	def test_oldest_variance_blocks_close(self):
		"""The variance the 200-row cap could never reach.

		Created first, so it is the oldest by every ordering, and then buried
		under more than two hundred later folios.
		"""
		self.world.folio_with_unposted_charge(25)
		self.world.bulk_settled_folios(210)

		audit = self._audit()
		audit_service.review(audit)
		audit_service.post_room_charges(audit)
		result = audit_service.reconcile(audit)

		self.assertGreaterEqual(
			result["variances"], 1, msg=f"the oldest folio's variance was never examined: {result}"
		)

		with self.assertRaises(NightAuditError):
			audit_service.close(audit)

	def test_reconciliation_records_what_it_examined(self):
		"""Zero variances over zero folios is not zero variances over two hundred."""
		audit = self._audit()
		audit_service.review(audit)
		audit_service.post_room_charges(audit)
		audit_service.reconcile(audit)

		self.assertIsNotNone(self._field(audit, "reconciliation_completed_on"))
		self.assertIsNotNone(self._field(audit, "reconciliation_population"))
