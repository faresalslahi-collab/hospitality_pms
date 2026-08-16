"""P1-12 residual and P1-13 — the provider acted and the request then died.

Wave 1 stopped two concurrent refunds from both reaching the provider. What it
could not stop is the sequence that has nothing to do with concurrency:

    claim the funds  ->  provider refunds  ->  the request fails

Everything local rolls back. The Payment Transaction's `refunded_amount` goes
back to what it was, the refund claim row vanishes, the failure record written
on the way out vanishes with it — and the guest's money has left the merchant
account with nothing in the PMS to say so. The next attempt sees a fully
refundable transaction and refunds it again.

The same shape breaks payment initiation (P1-13): the provider is contacted,
something fails afterwards, and the rollback erases both the failure queue row
and the Payment Transaction's failed state.

These tests use the recording fake provider, which can be told to apply a
refund and *then* time out — the only way to reproduce "the money moved and we
do not know it" without a real gateway.
"""

import os
import tempfile

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from hospitality_pms.services import durability
from hospitality_pms.services import payments as payment_service
from hospitality_pms.services.exceptions import IntegrationAmbiguousError, IntegrationError
from hospitality_pms.tests import fake_provider
from hospitality_pms.tests.fixtures import Fixtures

PRECISION = 2
CAPTURED = 100.0


def use_fake_provider():
	from hospitality_pms.integrations.payments import ADAPTERS

	ADAPTERS["Manual"] = "hospitality_pms.tests.fake_provider.RecordingAdapter"


class PaymentDurabilityTestCase(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()

		cls.fixtures = Fixtures("PDUR")
		cls.property = cls.fixtures.property("PD")
		cls.guest = cls.fixtures.guest("Durable")
		cls.provider = cls.fixtures.payment_provider(cls.property)

		cls._scratch = tempfile.TemporaryDirectory(prefix="hpms-durable-")
		os.environ[fake_provider.CALL_LOG_ENV] = os.path.join(cls._scratch.name, "calls.jsonl")

		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		os.environ.pop(fake_provider.CALL_LOG_ENV, None)
		os.environ.pop(fake_provider.MODE_ENV, None)
		cls._scratch.cleanup()
		cls.fixtures.teardown()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")
		use_fake_provider()
		fake_provider.reset()
		durability.purge_operations(property_name=self.property)

		self.folio = self.fixtures.folio(self.property, self.guest)
		self.transaction = self.fixtures.captured_payment(
			self.property, self.provider, amount=CAPTURED, folio=self.folio
		)
		frappe.db.commit()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		durability.purge_operations(property_name=self.property)

	def assertMoney(self, actual, expected, msg=None):
		self.assertAlmostEqual(flt(actual), flt(expected), places=PRECISION, msg=msg)

	def _refund_calls(self) -> list[dict]:
		return fake_provider.calls("refund")


class TestRefundDurability(PaymentDurabilityTestCase):
	def test_refund_operation_survives_post_provider_failure(self):
		"""The provider refunded and the request then rolled back.

		Nothing local remains — but the durable ledger says the refund reached
		the provider, which is the difference between a recoverable state and a
		silently duplicated refund.
		"""
		payment_service.refund_payment(
			self.transaction, CAPTURED, "guest cancelled", idempotency_key="dur:refund:1"
		)

		# The request dies after the provider call, exactly as in the sweep.
		frappe.db.rollback()

		record = durability.get_operation("dur:refund:1")

		self.assertIsNotNone(record, msg="no evidence the provider was ever contacted")
		self.assertEqual(record["queue_status"], durability.RESOLVED)
		self.assertEqual(record["property"], self.property)

		# And the local business state really did roll back, so this is the
		# genuine divergence rather than a test that proved nothing.
		self.assertMoney(
			frappe.db.get_value("Payment Transaction", self.transaction, "refunded_amount"), 0
		)

	def test_retry_after_post_provider_failure_does_not_refund_again(self):
		"""The whole point: one provider refund, however the request ended."""
		payment_service.refund_payment(
			self.transaction, CAPTURED, "guest cancelled", idempotency_key="dur:refund:2"
		)
		frappe.db.rollback()

		self.assertEqual(len(self._refund_calls()), 1)

		# The desk tries again, seeing a transaction that looks fully refundable.
		payment_service.refund_payment(
			self.transaction, CAPTURED, "guest cancelled", idempotency_key="dur:refund:2"
		)

		self.assertEqual(
			len(self._refund_calls()),
			1,
			msg=f"the guest was refunded twice: {self._refund_calls()}",
		)

	def test_retry_after_post_provider_failure_repairs_local_state(self):
		"""Recovering must also bring the PMS back into line with the provider."""
		payment_service.refund_payment(
			self.transaction, CAPTURED, "guest cancelled", idempotency_key="dur:refund:3"
		)
		frappe.db.rollback()

		result = payment_service.refund_payment(
			self.transaction, CAPTURED, "guest cancelled", idempotency_key="dur:refund:3"
		)

		self.assertMoney(result["refunded_amount"], CAPTURED)
		self.assertMoney(
			frappe.db.get_value("Payment Transaction", self.transaction, "refunded_amount"),
			CAPTURED,
			msg="local state was never brought back into line with the provider",
		)

	def test_refund_timeout_does_not_double_refund(self):
		"""The provider applied it; only the answer was lost."""
		fake_provider.set_mode(fake_provider.MODE_TIMEOUT_AFTER_APPLY)

		with self.assertRaises(IntegrationAmbiguousError):
			payment_service.refund_payment(
				self.transaction, 60, "guest cancelled", idempotency_key="dur:timeout:1"
			)

		frappe.db.rollback()

		record = durability.get_operation("dur:timeout:1")

		self.assertEqual(
			record["queue_status"],
			durability.NEEDS_RECONCILIATION,
			msg="an unknown outcome was recorded as a plain failure, which invites a blind retry",
		)

		# Even with the provider healthy again, the same operation must not be
		# re-issued while its first outcome is unknown.
		fake_provider.set_mode(fake_provider.MODE_OK)

		with self.assertRaises(IntegrationError):
			payment_service.refund_payment(
				self.transaction, 60, "guest cancelled", idempotency_key="dur:timeout:1"
			)

		self.assertEqual(
			len(self._refund_calls()), 1, msg=f"a second refund was issued: {self._refund_calls()}"
		)

	def test_refund_reconciliation_completes_local_state(self):
		"""Ask the provider what happened, then finish the job locally."""
		fake_provider.set_mode(fake_provider.MODE_TIMEOUT_AFTER_APPLY)

		with self.assertRaises(IntegrationAmbiguousError):
			payment_service.refund_payment(
				self.transaction, CAPTURED, "guest cancelled", idempotency_key="dur:recon:1"
			)

		frappe.db.rollback()
		fake_provider.set_mode(fake_provider.MODE_OK)

		outcome = payment_service.reconcile_operation("dur:recon:1")

		self.assertEqual(outcome["status"], durability.RESOLVED)
		self.assertEqual(
			len(self._refund_calls()),
			1,
			msg="reconciliation re-issued the refund instead of looking it up",
		)
		self.assertMoney(
			frappe.db.get_value("Payment Transaction", self.transaction, "refunded_amount"),
			CAPTURED,
		)

	def test_reconciliation_of_an_operation_the_provider_never_applied(self):
		"""A request that never arrived becomes retryable, not resolved."""
		fake_provider.set_mode(fake_provider.MODE_TIMEOUT_BEFORE_APPLY)

		with self.assertRaises(IntegrationAmbiguousError):
			payment_service.refund_payment(
				self.transaction, 30, "guest cancelled", idempotency_key="dur:recon:2"
			)

		frappe.db.rollback()
		fake_provider.set_mode(fake_provider.MODE_OK)

		outcome = payment_service.reconcile_operation("dur:recon:2")

		self.assertEqual(outcome["status"], durability.RETRYING)
		self.assertEqual(self._refund_calls(), [])

	def test_explicit_provider_failure_is_durably_retryable(self):
		"""A refusal is safe to retry, and must survive the rollback to be retried."""
		fake_provider.set_mode(fake_provider.MODE_REFUSE)

		with self.assertRaises(IntegrationError):
			payment_service.refund_payment(
				self.transaction, 40, "guest cancelled", idempotency_key="dur:refuse:1"
			)

		frappe.db.rollback()

		record = durability.get_operation("dur:refuse:1")

		self.assertEqual(record["queue_status"], durability.RETRYING)
		self.assertIn("refused", record["last_error"])
		self.assertTrue(record["next_attempt_on"])


class TestPaymentInitiationDurability(PaymentDurabilityTestCase):
	"""P1-13 — the failure record must outlive the failed request."""

	def test_payment_failure_record_survives_request_rollback(self):
		fake_provider.set_mode(fake_provider.MODE_REFUSE)

		with self.assertRaises(IntegrationError):
			payment_service.initiate_payment(
				self.folio, 250, idempotency_key="dur:init:1", provider=self.provider
			)

		frappe.db.rollback()

		record = durability.get_operation("dur:init:1")

		self.assertIsNotNone(
			record, msg="the failure queue row rolled back with the request, as before"
		)
		self.assertEqual(record["queue_status"], durability.RETRYING)
		self.assertEqual(record["operation"], "initiate_payment")
		self.assertEqual(record["property"], self.property)

	def test_successful_initiation_is_recorded_durably(self):
		result = payment_service.initiate_payment(
			self.folio, 250, idempotency_key="dur:init:2", provider=self.provider
		)

		record = durability.get_operation("dur:init:2")

		self.assertEqual(record["queue_status"], durability.RESOLVED)
		self.assertTrue(result["name"])

	def test_ambiguous_initiation_is_not_blindly_retried(self):
		fake_provider.set_mode(fake_provider.MODE_TIMEOUT_AFTER_APPLY)

		with self.assertRaises(IntegrationAmbiguousError):
			payment_service.initiate_payment(
				self.folio, 250, idempotency_key="dur:init:3", provider=self.provider
			)

		frappe.db.rollback()

		self.assertEqual(
			durability.get_operation("dur:init:3")["queue_status"],
			durability.NEEDS_RECONCILIATION,
		)

		fake_provider.set_mode(fake_provider.MODE_OK)

		with self.assertRaises(IntegrationError):
			payment_service.initiate_payment(
				self.folio, 250, idempotency_key="dur:init:3", provider=self.provider
			)

		self.assertEqual(len(fake_provider.calls("initiate_payment")), 1)


class TestRefundAgainstClosedFolio(PaymentDurabilityTestCase):
	"""P1 (F-FIN2) — a provider refund against a departed guest's closed folio.

	Refunding a guest who has checked out is the ordinary refund case: their folio
	is closed precisely because they left. post_payment refuses a closed folio, and
	before the fix that refusal rolled the whole refund back while the durable
	ledger said the provider had paid it - money out of the merchant account, no
	local record, and every retry refusing again. The provider fact is now parked
	as a durable Needs Reconciliation item instead of being discarded.
	"""

	def test_refund_against_closed_folio_is_parked_not_lost(self):
		frappe.db.set_value(
			"Guest Folio", self.folio, "folio_status", "Closed", update_modified=False
		)
		frappe.db.commit()

		# Must not raise, and must not roll the provider refund back.
		payment_service.refund_payment(
			self.transaction, CAPTURED, "guest disputes a charge", idempotency_key="closed:refund:1"
		)
		frappe.db.commit()

		self.assertEqual(len(self._refund_calls()), 1, msg="the provider was not asked to refund once")
		self.assertMoney(
			frappe.db.get_value("Payment Transaction", self.transaction, "refunded_amount"),
			CAPTURED,
			msg="the refund was not recorded on the transaction",
		)

		parked = durability.get_operation("closed-folio-payment:gateway-refund:closed:refund:1")
		self.assertIsNotNone(
			parked, msg="the refund against the closed folio was silently discarded (F-FIN2)"
		)
		self.assertEqual(parked["queue_status"], durability.NEEDS_RECONCILIATION)
		self.assertEqual(parked["reference_name"], self.folio)
