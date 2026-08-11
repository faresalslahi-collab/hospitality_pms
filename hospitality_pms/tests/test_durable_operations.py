"""The durability primitive every Wave-3 fix is built on.

The defect behind P1-13, P1-14 and the residual half of P1-12 is one sentence
long: **failure evidence is written inside the transaction that is about to be
rolled back.** The provider is called, it fails or times out, a row is written
to say so, the exception propagates, and the rollback takes the row with it.
The system ends up with no record that it ever contacted anyone.

No amount of care inside that transaction can fix it, because the transaction
is doomed by definition. The record has to be committed by something the
rollback cannot reach.

Two candidates were considered and rejected:

* `frappe.db.commit()` in the service - forbidden, and wrong anyway: it would
  commit the caller's half-finished business work along with the evidence.
* `frappe.db.after_rollback` - fires on the right connection at the right
  moment, but whatever it writes is then itself uncommitted, and in a request
  that is about to end nothing ever commits it.

What is used instead is a second database connection, which has its own
transaction and is therefore untouched by anything the caller's transaction
does. These tests prove both halves of that: the operation record survives the
caller's rollback, and the caller's own work still does not.
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_to_date, now_datetime

from hospitality_pms.services import durability
from hospitality_pms.tests.concurrency import Worker, assert_all_ran, run_workers
from hospitality_pms.tests.fixtures import Fixtures

LEDGER = "PMS Integration Failure Queue"


# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------


def _claim_worker(barrier, property_name: str, tag: str, partner: str) -> dict:
	"""Two of these race for the same due operation; only one may win it."""
	frappe.db.sql(
		"select name from `tabPMS Integration Failure Queue` where property = %s", property_name
	)

	barrier.signal(f"ready_{tag}")
	barrier.wait(f"ready_{partner}")

	claimed = durability.claim_due_operations(property_name, limit=10)
	frappe.db.commit()

	return {"claimed": [row["operation_key"] for row in claimed]}


class TestDurableWrite(IntegrationTestCase):
	"""The primitive itself."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.fixtures = Fixtures("DUR")
		cls.property = cls.fixtures.property("DU")
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		cls.fixtures.teardown()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		durability.purge_operations(property_name=self.property)

	def _begin(self, key: str, **overrides) -> dict:
		return durability.begin_operation(
			property_name=self.property,
			integration_type="Payment",
			operation="initiate_payment",
			operation_key=key,
			payload={"amount": 100},
			**overrides,
		)

	# -- the core guarantee ----------------------------------------------

	def test_operation_record_survives_caller_rollback(self):
		"""P1-13 and P1-14 in one assertion."""
		self._begin("wave3:survive:1")

		frappe.db.rollback()

		record = durability.get_operation("wave3:survive:1")

		self.assertIsNotNone(record, msg="the operation record died with the caller's transaction")
		self.assertEqual(record["queue_status"], durability.EXECUTING)

	def test_failure_record_survives_caller_rollback(self):
		"""The exact shape of the defect: mark failed, then the request dies."""
		self._begin("wave3:survive:2")
		durability.fail_operation("wave3:survive:2", error="provider refused")

		frappe.db.rollback()

		record = durability.get_operation("wave3:survive:2")

		self.assertIsNotNone(record)
		self.assertEqual(record["queue_status"], durability.RETRYING)
		self.assertIn("provider refused", record["last_error"])

	def test_durable_write_does_not_commit_the_callers_work(self):
		"""The other half, and the reason this is not a disguised commit.

		A durability mechanism that also committed the caller's half-finished
		business transaction would be far worse than the defect it replaces: a
		failed check-in would leave a real Stay behind. The operation record
		must survive and the caller's work must not.
		"""
		guest = frappe.get_doc(
			{"doctype": "Guest", "first_name": "Uncommitted", "last_name": "Work"}
		).insert(ignore_permissions=True)

		self._begin("wave3:isolation:1")

		frappe.db.rollback()

		self.assertIsNotNone(durability.get_operation("wave3:isolation:1"))
		self.assertFalse(
			frappe.db.exists("Guest", guest.name),
			msg="the durable write committed the caller's transaction as well",
		)

	def test_success_is_recorded_durably(self):
		self._begin("wave3:success:1")
		durability.complete_operation("wave3:success:1", external_reference="PROV-123")

		frappe.db.rollback()

		record = durability.get_operation("wave3:success:1")

		self.assertEqual(record["queue_status"], durability.RESOLVED)
		self.assertEqual(record["external_reference"], "PROV-123")
		self.assertTrue(record["resolved_on"])

	def test_ambiguous_outcome_is_flagged_for_reconciliation(self):
		"""A timeout is not a failure: the provider may well have succeeded."""
		self._begin("wave3:ambiguous:1")
		durability.flag_for_reconciliation("wave3:ambiguous:1", error="read timeout")

		frappe.db.rollback()

		record = durability.get_operation("wave3:ambiguous:1")

		self.assertEqual(record["queue_status"], durability.NEEDS_RECONCILIATION)

	# -- one row per logical operation ------------------------------------

	def test_repeating_an_operation_reuses_one_row(self):
		"""N7 in miniature: the same logical work is one record, not a pile."""
		for _ in range(5):
			self._begin("wave3:reuse:1")
			durability.fail_operation("wave3:reuse:1", error="still down")

		frappe.db.rollback()

		self.assertEqual(
			frappe.db.count(LEDGER, {"operation_key": "wave3:reuse:1"}),
			1,
			msg="each attempt created another row instead of updating the operation",
		)
		self.assertEqual(durability.get_operation("wave3:reuse:1")["attempts"], 5)

	def test_attempts_are_bounded_and_end_in_a_terminal_state(self):
		key = "wave3:bounded:1"

		for _ in range(durability.DEFAULT_MAX_ATTEMPTS + 3):
			self._begin(key)
			durability.fail_operation(key, error="still down")

		record = durability.get_operation(key)

		self.assertEqual(
			record["queue_status"],
			durability.ABANDONED,
			msg=f"the operation retried past its limit: {record}",
		)
		self.assertLessEqual(record["attempts"], durability.DEFAULT_MAX_ATTEMPTS + 1)

	def test_abandoned_operations_are_not_reopened(self):
		"""A terminal state must not silently regress into another attempt."""
		key = "wave3:terminal:1"

		self._begin(key)
		durability.abandon_operation(key, reason="manual review")

		self._begin(key)

		self.assertEqual(durability.get_operation(key)["queue_status"], durability.ABANDONED)

	def test_resolved_operations_are_not_reopened(self):
		key = "wave3:terminal:2"

		self._begin(key)
		durability.complete_operation(key, external_reference="PROV-1")

		self._begin(key)

		self.assertEqual(durability.get_operation(key)["queue_status"], durability.RESOLVED)

	# -- Part 12: the retry must not be redirected -------------------------

	def test_operation_property_context_is_immutable(self):
		"""A retry cannot be pointed at another property, company or provider.

		Retry runs in a background context with no interactive permission check,
		so the persisted context is the only thing standing between a replayed
		payload and another property's money.
		"""
		other = self.fixtures.property("DV")
		frappe.db.commit()

		self._begin("wave3:scope:1", provider="alpha")
		durability.begin_operation(
			property_name=other,
			integration_type="Payment",
			operation="refund_payment",
			operation_key="wave3:scope:1",
			provider="beta",
			payload={"amount": 999},
		)

		record = durability.get_operation("wave3:scope:1")

		self.assertEqual(record["property"], self.property)
		self.assertEqual(record["operation"], "initiate_payment")
		self.assertEqual(record["provider"], "alpha")


class TestDurableClaiming(IntegrationTestCase):
	"""Part 2 - exactly one worker may execute an operation."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.fixtures = Fixtures("CLM")
		cls.property = cls.fixtures.property("CL")
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		cls.fixtures.teardown()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")
		durability.purge_operations(property_name=self.property)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		durability.purge_operations(property_name=self.property)

	def _due_operation(self, key: str):
		durability.begin_operation(
			property_name=self.property,
			integration_type="Channel",
			operation="push_availability",
			operation_key=key,
			payload={},
		)
		durability.fail_operation(key, error="channel down", retry_in_minutes=0)

	def test_only_due_operations_are_claimed(self):
		self._due_operation("wave3:claim:due")

		durability.begin_operation(
			property_name=self.property,
			integration_type="Channel",
			operation="push_rates",
			operation_key="wave3:claim:later",
			payload={},
		)
		durability.fail_operation("wave3:claim:later", error="down", retry_in_minutes=60)

		claimed = [row["operation_key"] for row in durability.claim_due_operations(self.property, 10)]

		self.assertIn("wave3:claim:due", claimed)
		self.assertNotIn("wave3:claim:later", claimed)

	def test_terminal_operations_are_never_claimed(self):
		self._due_operation("wave3:claim:done")
		durability.complete_operation("wave3:claim:done", external_reference="x")

		self._due_operation("wave3:claim:dead")
		durability.abandon_operation("wave3:claim:dead", reason="limit")

		claimed = [row["operation_key"] for row in durability.claim_due_operations(self.property, 10)]

		self.assertEqual(claimed, [])

	def test_only_one_worker_claims_operation(self):
		"""Two schedulers, one due operation, one execution.

		Genuinely concurrent: a claim that merely filtered on status would let
		both workers read the same Pending row before either wrote to it, and
		the provider would be called twice.
		"""
		for index in range(4):
			self._due_operation(f"wave3:race:{index}")

		frappe.db.commit()

		results = run_workers(
			[
				Worker(
					f"{__name__}._claim_worker",
					{"property_name": self.property, "tag": "a", "partner": "b"},
				),
				Worker(
					f"{__name__}._claim_worker",
					{"property_name": self.property, "tag": "b", "partner": "a"},
				),
			]
		)
		assert_all_ran(results)

		claimed = [key for r in results if r["status"] == "committed" for key in r["result"]["claimed"]]

		self.assertEqual(
			sorted(claimed),
			sorted(set(claimed)),
			msg=f"the same operation was claimed by both workers: {results}",
		)
		self.assertEqual(len(claimed), 4, msg=f"every due operation should be claimed once: {results}")


class TestLegacyQueueMaintenance(IntegrationTestCase):
	"""Part 15 - the backlog is closed out, never deleted.

	A site upgrading into this wave arrives with thousands of rows the old
	queue accumulated. They are integration evidence: what was attempted, when,
	and what came back. The maintenance command retires them so the new model
	can take over, and keeps every one of them.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.fixtures = Fixtures("LEG")
		cls.property = cls.fixtures.property("LG")
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.db.delete(LEDGER, {"property": cls.property})
		frappe.db.commit()
		cls.fixtures.teardown()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.delete(LEDGER, {"property": self.property})

		# Legacy shape: no operation_key, several rows for one logical push.
		for index in range(4):
			frappe.get_doc(
				{
					"doctype": LEDGER,
					"property": self.property,
					"integration_type": "Channel",
					"operation": "push_availability",
					"idempotency_key": "legacy:channel:availability",
					"payload": '{"rows": []}',
					"queue_status": "Pending",
					"attempts": index,
					"last_error": "channel unavailable",
				}
			).insert(ignore_permissions=True)

		frappe.get_doc(
			{
				"doctype": LEDGER,
				"property": self.property,
				"integration_type": "Channel",
				"operation": "import_reservation",
				"idempotency_key": "legacy:import:1",
				"payload": "{}",
				"queue_status": "Retrying",
				"attempts": 2,
			}
		).insert(ignore_permissions=True)

		frappe.db.commit()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		frappe.db.delete(LEDGER, {"property": self.property})
		frappe.db.commit()

	def _rows(self, **filters) -> int:
		return frappe.db.count(LEDGER, {"property": self.property, **filters})

	def test_report_changes_nothing(self):
		from hospitality_pms.setup import queue_maintenance

		before = self._rows()
		queue_maintenance.report()

		self.assertEqual(self._rows(), before)
		self.assertEqual(self._rows(queue_status="Pending"), 4)

	def test_dry_run_changes_nothing(self):
		from hospitality_pms.setup import queue_maintenance

		result = queue_maintenance.adopt(dry_run=1)

		self.assertTrue(result["dry_run"])
		self.assertEqual(self._rows(queue_status="Pending"), 4)

	def test_adopt_retires_the_backlog_without_deleting_it(self):
		from hospitality_pms.setup import queue_maintenance

		before = self._rows()

		queue_maintenance.adopt(dry_run=0)

		self.assertEqual(
			self._rows(), before, msg="the maintenance command deleted integration history"
		)
		self.assertEqual(self._rows(queue_status=durability.ABANDONED), 4)
		self.assertEqual(self._rows(queue_status=durability.NEEDS_RECONCILIATION), 1)

		# The original evidence is untouched.
		retired = frappe.get_all(
			LEDGER,
			filters={"property": self.property, "operation": "push_availability"},
			fields=["idempotency_key", "last_error", "notes"],
			limit=1,
		)[0]

		self.assertEqual(retired["idempotency_key"], "legacy:channel:availability")
		self.assertEqual(retired["last_error"], "channel unavailable")
		self.assertIn("Superseded", retired["notes"])

	def test_adopt_leaves_new_model_operations_alone(self):
		"""Only rows written by the old queue are touched."""
		from hospitality_pms.setup import queue_maintenance

		durability.begin_operation(
			property_name=self.property,
			integration_type="Channel",
			operation="push_rates",
			operation_key="wave3:current:1",
			payload={},
		)
		durability.fail_operation("wave3:current:1", error="down")

		queue_maintenance.adopt(dry_run=0)

		self.assertEqual(
			durability.get_operation("wave3:current:1")["queue_status"], durability.RETRYING
		)
