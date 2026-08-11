"""P1-11 — a folio payment must settle the invoice it was taken against.

The Payment Entry was submitted with `references = []`. ERPNext therefore had
no idea which invoice the money was for: `total_allocated_amount` was 0, the
whole 110 sat in `unallocated_amount`, the Sales Invoice stayed fully
outstanding, and the Payment Ledger treated a guest who had paid their bill in
full as holding an unapplied customer advance.

Everything here is read back from ERPNext after submission — the reference
rows, the allocated amount, and the invoice's own `outstanding_amount`.
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from hospitality_pms.services import posting as posting_service
from hospitality_pms.tests.posting_world import (
	PostingWorld,
	folio_invoices,
	invoice_totals,
	payment_references,
	payment_totals,
)

PRECISION = 2


class PaymentPostingTestCase(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.world = PostingWorld("PAYP", "PP")

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

	# -- helpers ---------------------------------------------------------

	def _invoice_of(self, net: float, tax: float, key: str) -> str:
		"""Charge the folio and post the invoice, returning its ERP name."""
		self.world.charge(self.folio, "Room Charge", net, tax, key)

		return posting_service.post_folio_invoice(self.folio)["erp_document"]

	def _pay(self, amount: float, key: str) -> dict:
		"""Take a folio payment and post it to ERPNext."""
		row = self.world.payment(self.folio, amount, key)["row"]

		return posting_service.post_folio_payment(self.folio, row)

	def _outstanding(self, invoice: str) -> float:
		return flt(frappe.db.get_value("Sales Invoice", invoice, "outstanding_amount"))


class TestPaymentAllocation(PaymentPostingTestCase):
	def test_payment_entry_allocates_against_invoice(self):
		"""Scenario A: 110 invoiced, 110 paid, nothing outstanding."""
		invoice = self._invoice_of(100, 10, "a1")
		self.assertMoney(self._outstanding(invoice), 110)

		result = self._pay(110, "a2")
		totals = payment_totals(result["erp_document"])

		self.assertEqual(totals["docstatus"], 1)
		self.assertMoney(totals["paid_amount"], 110)
		self.assertMoney(
			totals["total_allocated_amount"],
			110,
			msg="the payment settled nothing; it was recorded as an unapplied advance",
		)
		self.assertMoney(totals["unallocated_amount"], 0)
		self.assertMoney(self._outstanding(invoice), 0)

	def test_payment_entry_references_the_correct_sales_invoice(self):
		invoice = self._invoice_of(100, 10, "b1")
		result = self._pay(110, "b2")

		references = payment_references(result["erp_document"])

		self.assertEqual(len(references), 1)
		self.assertEqual(references[0]["reference_doctype"], "Sales Invoice")
		self.assertEqual(references[0]["reference_name"], invoice)
		self.assertMoney(references[0]["allocated_amount"], 110)

	def test_partial_payment_reduces_outstanding(self):
		"""Scenario C, first half: 110 invoiced, 50 paid."""
		invoice = self._invoice_of(100, 10, "c1")

		result = self._pay(50, "c2")

		self.assertMoney(payment_totals(result["erp_document"])["total_allocated_amount"], 50)
		self.assertMoney(self._outstanding(invoice), 60)

	def test_second_payment_settles_invoice(self):
		"""Scenario C, second half: the remaining 60 clears it."""
		invoice = self._invoice_of(100, 10, "d1")

		self._pay(50, "d2")
		second = self._pay(60, "d3")

		self.assertMoney(payment_totals(second["erp_document"])["total_allocated_amount"], 60)
		self.assertMoney(self._outstanding(invoice), 0)

	def test_overpayment_leaves_only_surplus_unallocated(self):
		"""Scenario D: 100 invoiced, 120 paid, 20 remains a deliberate advance."""
		invoice = self._invoice_of(100, 0, "e1")

		result = self._pay(120, "e2")
		totals = payment_totals(result["erp_document"])

		self.assertMoney(
			totals["total_allocated_amount"],
			100,
			msg="more was allocated than the invoice was outstanding",
		)
		self.assertMoney(totals["unallocated_amount"], 20)
		self.assertMoney(self._outstanding(invoice), 0)

	def test_overpayment_surplus_is_reported_to_the_caller(self):
		"""The surplus must be deliberate and visible, not merely present in ERP."""
		self._invoice_of(100, 0, "f1")

		result = self._pay(120, "f2")

		self.assertMoney(result["allocated_amount"], 100)
		self.assertMoney(result["unallocated_amount"], 20)

	def test_repeated_posting_creates_no_second_payment_entry(self):
		"""Scenario F: the same folio payment row posts once."""
		self._invoice_of(100, 10, "g1")

		row = self.world.payment(self.folio, 110, "g2")["row"]

		first = posting_service.post_folio_payment(self.folio, row)
		second = posting_service.post_folio_payment(self.folio, row)

		self.assertEqual(first["erp_document"], second["erp_document"])
		self.assertTrue(second["duplicate"])
		self.assertEqual(
			frappe.db.count("Payment Entry", {"name": first["erp_document"]}),
			1,
		)

	def test_payment_with_no_invoice_yet_remains_an_advance(self):
		"""A deposit taken before anything is invoiced has nothing to settle.

		ERPNext's own answer for that is an unallocated customer advance, which
		is correct and must not be forced onto an invoice that does not exist.
		"""
		result = self._pay(200, "h1")
		totals = payment_totals(result["erp_document"])

		self.assertMoney(totals["total_allocated_amount"], 0)
		self.assertMoney(totals["unallocated_amount"], 200)
		self.assertEqual(payment_references(result["erp_document"]), [])

	def test_refund_is_not_allocated_against_a_sales_invoice(self):
		"""Money going out is not a settlement of money owed."""
		from hospitality_pms.services import folio as folio_service

		self._invoice_of(100, 10, "i1")
		self._pay(110, "i2")

		refund_row = folio_service.post_payment(
			self.folio, 40, "Cash", payment_type="Refund", idempotency_key="PAYP:i3"
		)["row"]

		result = posting_service.post_folio_payment(self.folio, refund_row)

		self.assertEqual(
			frappe.db.get_value("Payment Entry", result["erp_document"], "payment_type"), "Pay"
		)
		self.assertEqual(payment_references(result["erp_document"]), [])


class TestAllocationAcrossBatches(PaymentPostingTestCase):
	"""A folio can hold more than one invoice once late charges are posted."""

	def test_payment_allocates_to_the_oldest_outstanding_invoice_first(self):
		from hospitality_pms.services import folio as folio_service

		first = self._invoice_of(100, 10, "j1")

		folio_service.transition(self.folio, folio_service.UNDER_REVIEW, reason="Late charge")
		self.world.charge(self.folio, "Minibar", 50, 2.50, "j2")
		second = posting_service.post_folio_invoice(self.folio)["erp_document"]

		# Enough to clear the first invoice and no more.
		result = self._pay(110, "j3")
		references = payment_references(result["erp_document"])

		self.assertEqual([r["reference_name"] for r in references], [first])
		self.assertMoney(self._outstanding(first), 0)
		self.assertMoney(self._outstanding(second), 52.50)

	def test_payment_spans_two_invoices_when_it_covers_both(self):
		from hospitality_pms.services import folio as folio_service

		first = self._invoice_of(100, 10, "k1")

		folio_service.transition(self.folio, folio_service.UNDER_REVIEW, reason="Late charge")
		self.world.charge(self.folio, "Minibar", 50, 2.50, "k2")
		second = posting_service.post_folio_invoice(self.folio)["erp_document"]

		result = self._pay(162.50, "k3")
		references = payment_references(result["erp_document"])

		self.assertEqual(
			[r["reference_name"] for r in references],
			[first, second],
			msg="allocation must follow posting order, oldest first",
		)
		self.assertMoney(self._outstanding(first), 0)
		self.assertMoney(self._outstanding(second), 0)
		self.assertMoney(payment_totals(result["erp_document"])["unallocated_amount"], 0)

	def test_every_invoice_for_the_folio_is_settled_by_the_total_paid(self):
		"""The cross-cutting settlement invariant across batches."""
		from hospitality_pms.services import folio as folio_service

		self._invoice_of(200, 20, "l1")

		folio_service.transition(self.folio, folio_service.UNDER_REVIEW, reason="Late charge")
		self.world.charge(self.folio, "Minibar", 30, 1.50, "l2")
		posting_service.post_folio_invoice(self.folio)

		folio_total = flt(frappe.db.get_value("Guest Folio", self.folio, "total_charges"))
		self._pay(folio_total, "l3")

		outstanding = sum(
			flt(invoice_totals(i)["outstanding_amount"]) for i in folio_invoices(self.folio)
		)

		self.assertMoney(outstanding, 0)


class TestCheckoutPostingPath(PaymentPostingTestCase):
	"""The path checkout actually uses, end to end, including a second invoice."""

	def test_checkout_posting_invoices_and_settles_in_one_call(self):
		from hospitality_pms.api import checkout as checkout_api

		self.world.charge(self.folio, "Room Charge", 100, 10, "m1")
		self.world.payment(self.folio, 110, "m2")

		result = checkout_api.post_folio(folio=self.folio)

		self.assertTrue(result["invoice"])
		self.assertEqual(len(result["payments"]), 1)

		invoice = result["invoice"]["erp_document"]

		self.assertMoney(invoice_totals(invoice)["grand_total"], 110)
		self.assertMoney(
			self._outstanding(invoice),
			0,
			msg="checkout raised the invoice but the payment did not settle it",
		)

	def test_checkout_posting_handles_a_supplementary_invoice(self):
		"""A late charge posted through the same path gets its own invoice.

		The first invoice and the payment that settled it must be left alone:
		the guest already paid that bill, and re-touching it at checkout is how
		a settled invoice ends up reopened.
		"""
		from hospitality_pms.api import checkout as checkout_api
		from hospitality_pms.services import folio as folio_service

		self.world.charge(self.folio, "Room Charge", 100, 10, "n1")
		self.world.payment(self.folio, 110, "n2")
		first = checkout_api.post_folio(folio=self.folio)["invoice"]["erp_document"]

		folio_service.transition(self.folio, folio_service.UNDER_REVIEW, reason="Late charge")
		self.world.charge(self.folio, "Minibar", 50, 2.50, "n3")
		self.world.payment(self.folio, 52.50, "n4")

		second_run = checkout_api.post_folio(folio=self.folio)
		second = second_run["invoice"]["erp_document"]

		self.assertNotEqual(first, second)
		self.assertMoney(self._outstanding(first), 0)
		self.assertMoney(self._outstanding(second), 0)

		# Both invoices together are the folio, and nothing is owed.
		self.assertMoney(
			sum(flt(invoice_totals(i)["grand_total"]) for i in folio_invoices(self.folio)),
			flt(frappe.db.get_value("Guest Folio", self.folio, "total_charges")),
		)

	def test_checkout_posting_is_idempotent(self):
		from hospitality_pms.api import checkout as checkout_api

		self.world.charge(self.folio, "Room Charge", 100, 10, "o1")
		self.world.payment(self.folio, 110, "o2")

		checkout_api.post_folio(folio=self.folio)
		checkout_api.post_folio(folio=self.folio)

		self.assertEqual(len(folio_invoices(self.folio)), 1)
		self.assertEqual(
			frappe.db.count(
				"Financial Posting Log",
				{"folio": self.folio, "posting_type": "Payment Entry", "posting_status": "Posted"},
			),
			1,
		)
