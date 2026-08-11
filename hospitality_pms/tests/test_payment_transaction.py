"""P1-12 - concurrent refunds must never over-refund at the provider.

What the sweep found
--------------------
`refund_payment` read the transaction with `frappe.get_doc` *before* taking the
lock, validated the refundable amount against that pre-lock snapshot, and
called the provider before any durable state changed. Two processes therefore
both saw `refunded_amount = 0`, both concluded 100 was refundable, and the
provider refunded 200 against a 100 capture. The losing worker then failed on
an unrelated timestamp conflict *after* the provider call, so the second 100
left the merchant account with no PMS record at all.

Scope
-----
These tests close the concurrency half. The remaining risk - the provider
succeeding and the database transaction then failing, leaving real money moved
with no local record - is a durability problem shared with P1-13 and P1-14 and
is deferred to the wave that decides the mechanism once. `test_...` names below
say which is which, and no test here asserts durability.

No real gateway is contacted: the provider is `tests.fake_provider`, which
records every call to a file so calls made by separate processes can be counted.
"""

import os
import tempfile

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from hospitality_pms.services import payments as payment_service
from hospitality_pms.services.exceptions import IntegrationError
from hospitality_pms.tests import fake_provider
from hospitality_pms.tests.concurrency import Worker, assert_all_ran, run_workers
from hospitality_pms.tests.fixtures import Fixtures

CAPTURED = 100.0


def use_fake_provider():
	"""Point the adapter registry at the recording adapter, in this process.

	Mutates the in-memory registry only, so nothing test-only is written to the
	site or shipped in the production adapter table. Every worker process calls
	this for itself.
	"""
	from hospitality_pms.integrations.payments import ADAPTERS

	ADAPTERS["Manual"] = "hospitality_pms.tests.fake_provider.RecordingAdapter"


# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------


def _refund_worker(barrier, transaction: str, amount: float, key: str, tag: str, partner: str) -> dict:
	use_fake_provider()

	# A pre-lock snapshot, which is the state the defect decided from.
	frappe.db.sql(
		"select refunded_amount from `tabPayment Transaction` where name = %s", transaction
	)

	barrier.signal(f"ready_{tag}")
	barrier.wait(f"ready_{partner}")

	result = payment_service.refund_payment(
		transaction, amount, "concurrent refund", idempotency_key=key
	)
	frappe.db.commit()

	return result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRefundConcurrency(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()

		cls.fixtures = Fixtures("PAY")
		cls.property = cls.fixtures.property("PY")
		cls.guest = cls.fixtures.guest("Refund")
		cls.provider = cls.fixtures.payment_provider(cls.property)

		cls._scratch = tempfile.TemporaryDirectory(prefix="hpms-provider-")
		# Inherited by every worker process, which is how their calls land in
		# one file that the parent can count.
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
		self.transaction = self.fixtures.captured_payment(
			self.property, self.provider, amount=CAPTURED, folio=self.folio
		)
		frappe.db.commit()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	# -- helpers --------------------------------------------------------

	def _refunded_at_provider(self) -> float:
		return sum(flt(call["amount"]) for call in fake_provider.calls("refund"))

	def _refunded_in_pms(self) -> float:
		return flt(frappe.db.get_value("Payment Transaction", self.transaction, "refunded_amount"))

	def _race(self, amount: float, keys: tuple[str, str]) -> list[dict]:
		results = run_workers(
			[
				Worker(
					f"{__name__}._refund_worker",
					{
						"transaction": self.transaction,
						"amount": amount,
						"key": keys[0],
						"tag": "a",
						"partner": "b",
					},
				),
				Worker(
					f"{__name__}._refund_worker",
					{
						"transaction": self.transaction,
						"amount": amount,
						"key": keys[1],
						"tag": "b",
						"partner": "a",
					},
				),
			]
		)
		assert_all_ran(results)

		return results

	# -- the race --------------------------------------------------------

	def test_concurrent_refunds_never_exceed_capture(self):
		"""Two full refunds of the whole capture, at the same instant."""
		results = self._race(CAPTURED, ("refund:full:a", "refund:full:b"))

		self.assertLessEqual(
			self._refunded_at_provider(),
			CAPTURED,
			msg=(
				f"the provider was asked to refund more than was captured; "
				f"calls were {fake_provider.calls('refund')}, workers returned {results}"
			),
		)

		self.assertLessEqual(self._refunded_in_pms(), CAPTURED)
		self.assertEqual(
			self._refunded_in_pms(),
			self._refunded_at_provider(),
			msg="the PMS and the provider disagree about how much was refunded",
		)

	def test_concurrent_partial_refunds_never_exceed_capture(self):
		"""60 + 60 against a capture of 100 - the subtler shape of the same bug."""
		results = self._race(60.0, ("refund:part:a", "refund:part:b"))

		self.assertLessEqual(
			self._refunded_at_provider(),
			CAPTURED,
			msg=(
				f"the provider refunded past the capture; calls were "
				f"{fake_provider.calls('refund')}, workers returned {results}"
			),
		)
		self.assertEqual(self._refunded_in_pms(), self._refunded_at_provider())

	def test_losing_worker_does_not_call_the_provider(self):
		"""Beginning with a stale refundable balance must not be enough to spend it.

		The strongest statement of the fix: the loser is refused *before* the
		provider call, not reconciled afterwards. One capture, one provider
		refund.
		"""
		self._race(CAPTURED, ("refund:once:a", "refund:once:b"))

		self.assertEqual(
			len(fake_provider.calls("refund")),
			1,
			msg=f"expected exactly one provider call; got {fake_provider.calls('refund')}",
		)

	def test_waiting_worker_sees_committed_refund_state(self):
		"""The loser's refusal must cite current state, not its own snapshot."""
		results = self._race(CAPTURED, ("refund:state:a", "refund:state:b"))

		failed = [r for r in results if r["status"] == "failed"]

		self.assertEqual(len(failed), 1, msg=f"exactly one worker should be refused; got {results}")
		self.assertIn(
			"IntegrationError",
			failed[0]["error"],
			msg=f"the loser must be refused by the refundable-amount guard; got {failed[0]['error']}",
		)

	# -- idempotency -----------------------------------------------------

	def test_same_refund_key_calls_provider_once(self):
		"""A retried refund is the same refund, and reaches the provider once."""
		first = payment_service.refund_payment(
			self.transaction, 40, "duplicate key", idempotency_key="refund:dup:1"
		)
		frappe.db.commit()

		second = payment_service.refund_payment(
			self.transaction, 40, "duplicate key", idempotency_key="refund:dup:1"
		)
		frappe.db.commit()

		self.assertEqual(
			len(fake_provider.calls("refund")),
			1,
			msg=f"one key must be one provider operation; got {fake_provider.calls('refund')}",
		)

		self.assertTrue(second["duplicate"])
		self.assertEqual(flt(first["refunded_amount"]), flt(second["refunded_amount"]))
		self.assertEqual(self._refunded_in_pms(), 40.0)

	def test_concurrent_same_refund_key_calls_provider_once(self):
		"""The same key from two processes at once."""
		self._race(40.0, ("refund:samekey", "refund:samekey"))

		self.assertEqual(
			len(fake_provider.calls("refund")),
			1,
			msg=f"one key must be one provider operation; got {fake_provider.calls('refund')}",
		)
		self.assertEqual(self._refunded_in_pms(), 40.0)

	# -- ordinary behaviour must survive ----------------------------------

	def test_a_single_refund_still_works_end_to_end(self):
		result = payment_service.refund_payment(
			self.transaction, CAPTURED, "guest cancelled", idempotency_key="refund:normal"
		)

		self.assertEqual(flt(result["refunded_amount"]), CAPTURED)
		self.assertEqual(len(fake_provider.calls("refund")), 1)
		self.assertEqual(
			frappe.db.get_value("Payment Transaction", self.transaction, "transaction_status"),
			"Refunded",
		)

		# The refund reaches the folio, once.
		rows = frappe.get_all(
			"Folio Payment",
			filters={"parent": self.folio, "payment_type": "Refund"},
			fields=["amount"],
		)
		self.assertEqual(len(rows), 1)
		self.assertEqual(flt(rows[0]["amount"]), -CAPTURED)

	def test_refund_beyond_the_capture_is_refused(self):
		with self.assertRaises(IntegrationError):
			payment_service.refund_payment(
				self.transaction, CAPTURED + 1, "too much", idempotency_key="refund:toomuch"
			)

		self.assertEqual(fake_provider.calls("refund"), [])

	def test_refund_requires_a_reason(self):
		with self.assertRaises(IntegrationError):
			payment_service.refund_payment(
				self.transaction, 10, "   ", idempotency_key="refund:noreason"
			)

		self.assertEqual(fake_provider.calls("refund"), [])
