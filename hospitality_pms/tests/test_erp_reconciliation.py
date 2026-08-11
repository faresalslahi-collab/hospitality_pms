"""Reconciliation must read ERPNext, not the folio's opinion of ERPNext.

The old `reconcile_folio` computed "erp_invoiced" by walking the folio's own
charge rows and adding up any whose `sales_invoice` link pointed at a submitted
document. That is circular: it asks the folio whether the folio was invoiced.

It is also exactly what masked P1-10. A folio of 100 net + 10 tax posted an
invoice whose `grand_total` was 100, and reconciliation reported
`erp_invoiced = 110`, `variance = 0`, `is_reconciled = True` — because the row
carrying the tax had a Sales Invoice reference on it. The one report whose job
was to catch the missing money confirmed it was there.

Every figure asserted here is read out of ERPNext: `grand_total`,
`outstanding_amount`, `docstatus`, and Payment Entry allocations.
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from hospitality_pms.services import folio as folio_service
from hospitality_pms.services import posting as posting_service
from hospitality_pms.tests.posting_world import PostingWorld

PRECISION = 2


class ReconciliationTestCase(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.world = PostingWorld("RECO", "RC")

	@classmethod
	def tearDownClass(cls):
		cls.world.teardown()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")
		self.folio = self.world.folio()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def assertMoney(self, actual, expected, msg=None):
		self.assertAlmostEqual(flt(actual), flt(expected), places=PRECISION, msg=msg)

	def _reconcile(self) -> dict:
		return posting_service.reconcile_folio(self.folio)

	def _pay_and_post(self, amount: float, key: str) -> dict:
		row = self.world.payment(self.folio, amount, key)["row"]

		return posting_service.post_folio_payment(self.folio, row)


class TestChargeReconciliation(ReconciliationTestCase):
	def test_reconciliation_reads_actual_erp_invoice_total(self):
		"""Scenario A: folio 110, invoice 110, nothing between them."""
		self.world.charge(self.folio, "Room Charge", 100, 10, "a1")
		posting_service.post_folio_invoice(self.folio)
		self._pay_and_post(110, "a2")

		report = self._reconcile()

		self.assertMoney(report["folio_charges"], 110)
		self.assertMoney(report["erp_invoiced"], 110)
		self.assertMoney(report["charge_variance"], 0)
		self.assertTrue(report["is_reconciled"], msg=report)

	def test_tax_mismatch_does_not_reconcile(self):
		"""The P1-10 masking case, reproduced exactly.

		A charge row is stamped as posted and pointed at a real submitted
		invoice that does not actually include it. The old report added the
		row's own amount and declared the folio reconciled; the ERP total is
		what proves it is not.
		"""
		self.world.charge(self.folio, "Room Charge", 100, 0, "b1")
		result = posting_service.post_folio_invoice(self.folio)

		# A row that claims to be on that invoice, and is not.
		orphan = self.world.charge(self.folio, "Laundry", 10, 0, "b2")["row"]
		frappe.db.set_value(
			"Folio Charge",
			orphan,
			{"is_posted_to_erp": 1, "sales_invoice": result["erp_document"]},
			update_modified=False,
		)

		report = self._reconcile()

		self.assertMoney(report["folio_charges"], 110)
		self.assertMoney(
			report["erp_invoiced"],
			100,
			msg="reconciliation counted a folio row instead of reading the invoice",
		)
		self.assertMoney(report["charge_variance"], 10)
		self.assertFalse(report["is_reconciled"], msg=report)

	def test_unposted_charge_is_not_reconciled(self):
		self.world.charge(self.folio, "Room Charge", 100, 10, "c1")
		posting_service.post_folio_invoice(self.folio)
		self._pay_and_post(110, "c2")

		self.world.charge(self.folio, "Minibar", 20, 1, "c3")

		report = self._reconcile()

		self.assertEqual(len(report["unposted_charges"]), 1)
		self.assertFalse(report["is_reconciled"], msg=report)

	def test_reconciliation_rejects_cancelled_erp_documents(self):
		"""Scenario E: a cancelled invoice is not a posted invoice."""
		self.world.charge(self.folio, "Room Charge", 100, 10, "d1")
		result = posting_service.post_folio_invoice(self.folio)

		invoice = frappe.get_doc("Sales Invoice", result["erp_document"])
		invoice.flags.ignore_permissions = True
		invoice.cancel()

		report = self._reconcile()

		self.assertMoney(
			report["erp_invoiced"], 0, msg="a cancelled invoice was counted as posted revenue"
		)
		self.assertMoney(report["charge_variance"], 110)
		self.assertFalse(report["is_reconciled"], msg=report)

	def test_reconciliation_rejects_draft_erp_documents(self):
		"""Scenario F: a draft invoice has not reached the ledger."""
		self.world.charge(self.folio, "Room Charge", 100, 10, "e1")
		posting_service.post_folio_invoice(self.folio, submit=False)

		report = self._reconcile()

		self.assertMoney(
			report["erp_invoiced"], 0, msg="a draft invoice was counted as posted revenue"
		)
		self.assertFalse(report["is_reconciled"], msg=report)

	def test_supplementary_invoices_are_summed(self):
		self.world.charge(self.folio, "Room Charge", 200, 20, "f1")
		posting_service.post_folio_invoice(self.folio)

		folio_service.transition(self.folio, folio_service.UNDER_REVIEW, reason="Late charge")
		self.world.charge(self.folio, "Minibar", 30, 1.50, "f2")
		posting_service.post_folio_invoice(self.folio)

		self._pay_and_post(251.50, "f3")

		report = self._reconcile()

		self.assertMoney(report["erp_invoiced"], 251.50)
		self.assertMoney(report["charge_variance"], 0)
		self.assertTrue(report["is_reconciled"], msg=report)


class TestPaymentReconciliation(ReconciliationTestCase):
	def test_payment_reconciliation_uses_allocated_amount(self):
		"""Scenario C: the payment settled the invoice, so nothing is outstanding."""
		self.world.charge(self.folio, "Room Charge", 100, 10, "g1")
		posting_service.post_folio_invoice(self.folio)
		self._pay_and_post(110, "g2")

		report = self._reconcile()

		self.assertMoney(report["folio_payments"], 110)
		self.assertMoney(report["erp_allocated_payments"], 110)
		self.assertMoney(report["payment_variance"], 0)
		self.assertMoney(report["invoice_outstanding"], 0)
		self.assertTrue(report["is_reconciled"], msg=report)

	def test_unallocated_payment_is_not_reconciled(self):
		"""Scenario D: the money reached ERPNext but settled nothing.

		Posting the payment before the invoice exists leaves it as a customer
		advance - which is what P1-11 produced for *every* payment. The money
		is in ERPNext, so a report that only checked "was a Payment Entry
		submitted" would call this reconciled while the invoice stands fully
		unpaid.
		"""
		self.world.charge(self.folio, "Room Charge", 100, 10, "h1")
		self._pay_and_post(110, "h2")
		posting_service.post_folio_invoice(self.folio)

		report = self._reconcile()

		self.assertMoney(report["erp_paid"], 110, msg="the money did reach ERPNext")
		self.assertMoney(
			report["erp_allocated_payments"], 0, msg="but it settled nothing"
		)
		self.assertMoney(report["invoice_outstanding"], 110)
		self.assertFalse(
			report["is_reconciled"],
			msg=f"an unapplied advance was reported as a settled folio: {report}",
		)

	def test_partial_payment_reconciles_against_the_remaining_balance(self):
		"""A half-paid folio is consistent, not broken: ERP owes what the folio owes."""
		self.world.charge(self.folio, "Room Charge", 100, 10, "i1")
		posting_service.post_folio_invoice(self.folio)
		self._pay_and_post(50, "i2")

		report = self._reconcile()

		self.assertMoney(report["erp_allocated_payments"], 50)
		self.assertMoney(report["invoice_outstanding"], 60)
		self.assertTrue(
			report["is_reconciled"],
			msg=f"ERP outstanding matches the folio balance, so this agrees: {report}",
		)

	def test_overpayment_reconciles_with_a_visible_surplus(self):
		"""Scenario D of the payment matrix: 20 advance is deliberate, not a variance."""
		self.world.charge(self.folio, "Room Charge", 100, 0, "j1")
		posting_service.post_folio_invoice(self.folio)
		self._pay_and_post(120, "j2")

		report = self._reconcile()

		self.assertMoney(report["erp_allocated_payments"], 100)
		self.assertMoney(report["unallocated_payments"], 20)
		self.assertMoney(report["invoice_outstanding"], 0)
		self.assertTrue(report["is_reconciled"], msg=report)

	def test_cancelled_payment_entry_is_not_counted(self):
		self.world.charge(self.folio, "Room Charge", 100, 10, "k1")
		posting_service.post_folio_invoice(self.folio)
		result = self._pay_and_post(110, "k2")

		entry = frappe.get_doc("Payment Entry", result["erp_document"])
		entry.flags.ignore_permissions = True
		entry.cancel()

		report = self._reconcile()

		self.assertMoney(report["erp_paid"], 0)
		self.assertMoney(report["erp_allocated_payments"], 0)
		self.assertFalse(report["is_reconciled"], msg=report)

	def test_response_keeps_its_existing_shape(self):
		"""Callers of the reconciliation endpoint must not break."""
		self.world.charge(self.folio, "Room Charge", 100, 10, "l1")
		posting_service.post_folio_invoice(self.folio)

		report = self._reconcile()

		for key in (
			"folio",
			"folio_charges",
			"folio_payments",
			"erp_invoiced",
			"erp_paid",
			"charge_variance",
			"payment_variance",
			"unposted_charges",
			"unposted_payments",
			"failed_postings",
			"is_reconciled",
		):
			self.assertIn(key, report)
