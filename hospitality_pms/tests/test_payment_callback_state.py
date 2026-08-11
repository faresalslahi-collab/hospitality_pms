"""P2-2 — a payment's state was whatever callback happened to arrive last.

The original claim was that a Captured transaction could regress to Failed. It
does not: `Captured` is in `TERMINAL_STATES` and a later callback is refused.
Two real defects reproduce instead, and they are the same mistake seen from two
sides — "terminal" was being used to mean "final", when the two are different
things.

**Failed then Captured.** A provider sends a failure for one attempt and a
capture for the retry that worked, and they arrive in that order. `Failed` is
terminal, so the capture is discarded as a duplicate. The provider has the
guest's money and the folio is never credited. The hotel's books say the guest
owes for a room they have paid for.

**Partially Refunded then Failed.** `Partially Refunded` is *not* in the
terminal list, so a stale failure overwrites it while `refunded_amount` stays
populated — a transaction that failed and yet refunded money.

The fix is to stop asking "is this state terminal?" and start asking "is this
transition allowed?". Economic settlement outranks a preliminary failure signal;
nothing outranks settlement afterwards. Arrival order is not evidence.
"""

import os
import tempfile

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from hospitality_pms.services import durability
from hospitality_pms.services import payments as payment_service
from hospitality_pms.tests import fake_provider
from hospitality_pms.tests.concurrency import Worker, assert_all_ran, run_workers
from hospitality_pms.tests.fixtures import Fixtures

AMOUNT = 250.0
TRANSACTION = "Payment Transaction"


def use_fake_provider():
	from hospitality_pms.integrations.payments import ADAPTERS

	ADAPTERS["Manual"] = "hospitality_pms.tests.fake_provider.RecordingAdapter"


def _callback_worker(barrier, property_name: str, provider: str, reference: str, status: str, tag: str, partner: str) -> dict:
	"""One provider callback, delivered at the same moment as another."""
	use_fake_provider()

	frappe.db.sql(
		"select transaction_status from `tabPayment Transaction` where provider_reference = %s",
		reference,
	)

	barrier.signal(f"ready_{tag}")
	barrier.wait(f"ready_{partner}")

	result = payment_service.handle_callback(
		property_name,
		provider,
		{"provider_reference": reference, "status": status, "amount": AMOUNT},
		{},
	)
	frappe.db.commit()

	return {"status": result.get("transaction_status"), "duplicate": result.get("duplicate")}


class CallbackStateTestCase(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()

		cls.fixtures = Fixtures("CBS")
		cls.property = cls.fixtures.property("CB")
		cls.guest = cls.fixtures.guest("Callback")
		cls.provider = cls.fixtures.payment_provider(cls.property)

		cls._scratch = tempfile.TemporaryDirectory(prefix="hpms-callback-")
		os.environ[fake_provider.CALL_LOG_ENV] = os.path.join(cls._scratch.name, "calls.jsonl")

		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		os.environ.pop(fake_provider.CALL_LOG_ENV, None)
		cls._scratch.cleanup()
		cls.fixtures.teardown()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")
		use_fake_provider()
		fake_provider.reset()

		self.folio = self.fixtures.folio(self.property, self.guest)
		frappe.db.commit()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	# -- the world -------------------------------------------------------

	def _transaction(self, status: str, *, refunded: float = 0, folio: str | None = None) -> tuple[str, str]:
		"""A transaction sitting in `status`, and the provider's reference for it."""
		reference = f"FAKE-CB-{frappe.generate_hash(length=10)}"

		doc = frappe.get_doc(
			{
				"doctype": TRANSACTION,
				"property": self.property,
				"provider": self.provider,
				"transaction_status": status,
				"transaction_type": "Payment",
				"idempotency_key": f"cb:{self.fixtures.tag}:{frappe.generate_hash(length=10)}",
				"folio": folio if folio is not None else self.folio,
				"guest": self.guest,
				"amount": AMOUNT,
				"refunded_amount": refunded,
				"provider_reference": reference,
			}
		).insert(ignore_permissions=True)

		self.fixtures.track(TRANSACTION, doc.name)
		frappe.db.commit()

		return doc.name, reference

	def _callback(self, reference: str, status: str, **extra) -> dict:
		return payment_service.handle_callback(
			self.property,
			self.provider,
			{"provider_reference": reference, "status": status, "amount": AMOUNT, **extra},
			{},
		)

	def _status(self, transaction: str) -> str:
		return frappe.db.get_value(TRANSACTION, transaction, "transaction_status")

	def _folio_credited(self, folio: str | None = None) -> float:
		return flt(
			frappe.db.sql(
				"select coalesce(sum(amount), 0) from `tabFolio Payment` where parent = %s",
				folio or self.folio,
			)[0][0]
		)

	def _folio_rows(self, folio: str | None = None) -> int:
		return frappe.db.count("Folio Payment", {"parent": folio or self.folio})


class TestSettlementOutranksFailure(CallbackStateTestCase):
	"""The half of P2-2 that loses the hotel money."""

	def test_failed_then_captured_settles_once(self):
		"""The reproduction: the capture was thrown away as a duplicate."""
		transaction, reference = self._transaction("Failed")

		result = self._callback(reference, "Captured")

		self.assertEqual(
			self._status(transaction),
			"Captured",
			msg="a proven capture was discarded because an earlier failure was called terminal",
		)
		self.assertFalse(result.get("duplicate"))
		self.assertEqual(
			self._folio_credited(), AMOUNT, msg="the provider took the money and the folio was never credited"
		)
		self.assertEqual(self._folio_rows(), 1)

	def test_pending_then_captured_settles(self):
		transaction, reference = self._transaction("Pending")

		self._callback(reference, "Captured")

		self.assertEqual(self._status(transaction), "Captured")
		self.assertEqual(self._folio_credited(), AMOUNT)

	def test_authorised_then_captured_settles(self):
		transaction, reference = self._transaction("Authorised")

		self._callback(reference, "Captured")

		self.assertEqual(self._status(transaction), "Captured")
		self.assertEqual(self._folio_credited(), AMOUNT)

	def test_cancelled_then_captured_settles(self):
		"""A cancellation the guest then completed anyway is still money in."""
		transaction, reference = self._transaction("Cancelled")

		self._callback(reference, "Captured")

		self.assertEqual(self._status(transaction), "Captured")
		self.assertEqual(self._folio_credited(), AMOUNT)

	def test_failed_then_captured_then_failed_stays_captured(self):
		"""Recovery must not be undone by the next stale retry of the failure."""
		transaction, reference = self._transaction("Failed")

		self._callback(reference, "Captured")
		self._callback(reference, "Failed")

		self.assertEqual(self._status(transaction), "Captured")
		self.assertEqual(self._folio_credited(), AMOUNT)


class TestSettledStatesDoNotRegress(CallbackStateTestCase):
	"""The other half: stale signals must not unwind real economic state."""

	def test_captured_then_failed_does_not_regress(self):
		transaction, reference = self._transaction("Captured")

		result = self._callback(reference, "Failed")

		self.assertEqual(self._status(transaction), "Captured")
		self.assertTrue(result.get("duplicate") or result.get("ignored"))

	def test_partially_refunded_does_not_regress_to_failed(self):
		"""The reproduction: a failed transaction that had refunded money."""
		transaction, reference = self._transaction("Partially Refunded", refunded=100)

		self._callback(reference, "Failed")

		self.assertEqual(
			self._status(transaction),
			"Partially Refunded",
			msg="a stale failure unwound a refund that had actually happened",
		)
		self.assertEqual(flt(frappe.db.get_value(TRANSACTION, transaction, "refunded_amount")), 100)

	def test_partially_refunded_does_not_regress_to_captured(self):
		"""Nor may a replayed capture erase the refund that followed it."""
		transaction, reference = self._transaction("Partially Refunded", refunded=100)

		self._callback(reference, "Captured")

		self.assertEqual(self._status(transaction), "Partially Refunded")

	def test_refunded_does_not_regress_to_failed(self):
		transaction, reference = self._transaction("Refunded", refunded=AMOUNT)

		self._callback(reference, "Failed")

		self.assertEqual(self._status(transaction), "Refunded")

	def test_refunded_does_not_regress_to_partially_refunded(self):
		transaction, reference = self._transaction("Refunded", refunded=AMOUNT)

		self._callback(reference, "Partially Refunded")

		self.assertEqual(self._status(transaction), "Refunded")

	def test_captured_may_still_become_refunded(self):
		"""The guard is about regression, not about standing still."""
		transaction, reference = self._transaction("Captured")

		self._callback(reference, "Refunded")

		self.assertEqual(self._status(transaction), "Refunded")


class TestCallbackIdempotency(CallbackStateTestCase):
	def test_duplicate_captured_callback_posts_one_folio_payment(self):
		transaction, reference = self._transaction("Pending")

		self._callback(reference, "Captured")
		result = self._callback(reference, "Captured")

		self.assertEqual(self._folio_rows(), 1, msg="the guest was credited twice")
		self.assertEqual(self._folio_credited(), AMOUNT)
		self.assertTrue(result.get("duplicate"))

	def test_failed_then_captured_twice_posts_one_folio_payment(self):
		"""Recovery is exactly once, however many times it is delivered."""
		transaction, reference = self._transaction("Failed")

		self._callback(reference, "Captured")
		self._callback(reference, "Captured")
		self._callback(reference, "Captured")

		self.assertEqual(self._folio_rows(), 1)
		self.assertEqual(self._folio_credited(), AMOUNT)

	def test_repeated_failure_callbacks_stay_failed(self):
		transaction, reference = self._transaction("Pending")

		self._callback(reference, "Failed")
		self._callback(reference, "Failed")

		self.assertEqual(self._status(transaction), "Failed")
		self.assertEqual(self._folio_rows(), 0)

	def test_an_unknown_status_is_refused_without_touching_state(self):
		"""Part 1, G — a status the model does not know is not a state change."""
		transaction, reference = self._transaction("Pending")

		result = self._callback(reference, "Marsupial")

		self.assertEqual(self._status(transaction), "Pending")
		self.assertFalse(result.get("applied"))
		self.assertEqual(self._folio_rows(), 0)

	def test_an_unmatched_callback_does_not_touch_another_transaction(self):
		"""Provider identity scopes the effect; a stray event changes nothing."""
		transaction, _reference = self._transaction("Pending")

		result = self._callback(f"FAKE-CB-NOBODY-{frappe.generate_hash(length=6)}", "Captured")

		self.assertFalse(result["matched"])
		self.assertEqual(self._status(transaction), "Pending")
		self.assertEqual(self._folio_rows(), 0)

	def test_a_transaction_with_no_folio_settles_without_a_folio_payment(self):
		transaction, reference = self._transaction("Failed", folio="")

		self._callback(reference, "Captured")

		self.assertEqual(self._status(transaction), "Captured")


class TestStatusSyncUsesTheSameModel(CallbackStateTestCase):
	"""The lost-callback path writes the same field and needs the same rules.

	`sync_status` asks the provider directly, which makes it authoritative
	about the *capture* and says nothing about a refund the hotel issued
	afterwards. Writing its answer straight over local state is the same
	invalid-state hazard as the stale callback, arriving by a different door.
	"""

	def test_sync_does_not_unwind_a_refund(self):
		"""The fake gateway reports Captured; the hotel has already refunded."""
		transaction, _reference = self._transaction("Partially Refunded", refunded=100)

		payment_service.sync_status(transaction)

		self.assertEqual(self._status(transaction), "Partially Refunded")
		self.assertEqual(flt(frappe.db.get_value(TRANSACTION, transaction, "refunded_amount")), 100)

	def test_sync_still_settles_a_transaction_the_provider_captured(self):
		"""The reason the path exists: a callback that never arrived."""
		transaction, _reference = self._transaction("Pending")

		payment_service.sync_status(transaction)

		self.assertEqual(self._status(transaction), "Captured")
		self.assertEqual(self._folio_credited(), AMOUNT)

	def test_sync_recovers_a_transaction_wrongly_left_failed(self):
		transaction, _reference = self._transaction("Failed")

		payment_service.sync_status(transaction)

		self.assertEqual(self._status(transaction), "Captured")
		self.assertEqual(self._folio_credited(), AMOUNT)

	def test_repeated_sync_credits_the_folio_once(self):
		transaction, _reference = self._transaction("Pending")

		payment_service.sync_status(transaction)
		payment_service.sync_status(transaction)

		self.assertEqual(self._folio_rows(), 1)


class TestCallbackResolvesDurableOperation(CallbackStateTestCase):
	"""Part 2 — a conclusive callback finishes what the lost answer started.

	Wave 3 parks an operation in `Needs Reconciliation` when the provider's
	answer was lost, precisely so nobody re-issues it. A callback that then
	proves what happened is that answer arriving late. Leaving the ledger
	waiting for a human afterwards is not safety, it is a queue that never
	drains.
	"""

	def _operation_for(self, transaction: str) -> str:
		key = frappe.db.get_value(TRANSACTION, transaction, "idempotency_key")

		durability.begin_operation(
			property_name=self.property,
			integration_type="Payment",
			operation="initiate_payment",
			operation_key=key,
			provider=self.provider,
			reference_doctype=TRANSACTION,
			reference_name=transaction,
			payload={"transaction": transaction},
		)
		durability.flag_for_reconciliation(key, error="The gateway timed out; outcome unknown.")

		return key

	def tearDown(self):
		frappe.set_user("Administrator")
		durability.purge_operations(property_name=self.property)
		super().tearDown()

	def test_a_capture_callback_resolves_the_pending_operation(self):
		transaction, reference = self._transaction("Pending")
		key = self._operation_for(transaction)

		self.assertEqual(
			durability.get_operation(key)["queue_status"], durability.NEEDS_RECONCILIATION
		)

		self._callback(reference, "Captured")

		self.assertEqual(
			durability.get_operation(key)["queue_status"],
			durability.RESOLVED,
			msg="the callback proved the outcome and the ledger still waited for a human",
		)

	def test_a_failure_callback_also_resolves_the_operation(self):
		"""Conclusive is conclusive; a proven failure is not an open question."""
		transaction, reference = self._transaction("Pending")
		key = self._operation_for(transaction)

		self._callback(reference, "Failed")

		self.assertEqual(durability.get_operation(key)["queue_status"], durability.RESOLVED)

	def test_a_refused_stale_callback_does_not_resolve_the_operation(self):
		"""A callback the state machine rejected proves nothing about the ledger."""
		transaction, reference = self._transaction("Captured")
		key = self._operation_for(transaction)

		self._callback(reference, "Failed")

		self.assertEqual(
			durability.get_operation(key)["queue_status"], durability.NEEDS_RECONCILIATION
		)

	def test_an_operation_that_is_not_stuck_is_left_alone(self):
		"""Only Needs Reconciliation is this path's business."""
		transaction, reference = self._transaction("Pending")
		key = frappe.db.get_value(TRANSACTION, transaction, "idempotency_key")

		durability.begin_operation(
			property_name=self.property,
			integration_type="Payment",
			operation="initiate_payment",
			operation_key=key,
			provider=self.provider,
			payload={"transaction": transaction},
		)

		self._callback(reference, "Captured")

		self.assertEqual(durability.get_operation(key)["queue_status"], durability.EXECUTING)


class TestCallbackConcurrency(CallbackStateTestCase):
	"""Out of order is the normal case; two at once is the hard one."""

	def test_simultaneous_failure_and_capture_settle_on_the_capture(self):
		transaction, reference = self._transaction("Pending")

		results = run_workers(
			[
				Worker(
					f"{__name__}._callback_worker",
					{
						"property_name": self.property,
						"provider": self.provider,
						"reference": reference,
						"status": "Failed",
						"tag": "a",
						"partner": "b",
					},
				),
				Worker(
					f"{__name__}._callback_worker",
					{
						"property_name": self.property,
						"provider": self.provider,
						"reference": reference,
						"status": "Captured",
						"tag": "b",
						"partner": "a",
					},
				),
			]
		)
		assert_all_ran(results)

		self.assertEqual(
			self._status(transaction),
			"Captured",
			msg=f"the final state followed arrival order rather than economic truth: {results}",
		)
		self.assertEqual(self._folio_rows(), 1, msg="the folio was credited more than once")
		self.assertEqual(self._folio_credited(), AMOUNT)

	def test_two_simultaneous_captures_credit_the_folio_once(self):
		transaction, reference = self._transaction("Pending")

		results = run_workers(
			[
				Worker(
					f"{__name__}._callback_worker",
					{
						"property_name": self.property,
						"provider": self.provider,
						"reference": reference,
						"status": "Captured",
						"tag": "a",
						"partner": "b",
					},
				),
				Worker(
					f"{__name__}._callback_worker",
					{
						"property_name": self.property,
						"provider": self.provider,
						"reference": reference,
						"status": "Captured",
						"tag": "b",
						"partner": "a",
					},
				),
			]
		)
		assert_all_ran(results)

		self.assertEqual(self._status(transaction), "Captured")
		self.assertEqual(self._folio_rows(), 1, msg=f"the guest was credited twice: {results}")
