"""A Posted log row is not evidence once ERPNext has withdrawn the document.

The posting log records what posting did *at the time*. Nothing carries an
ERPNext cancellation back the other way: there is no `on_cancel` hook, and no
code in this app cancels an ERP document at all, because
`checkout.reverse_checkout` deliberately leaves a submitted invoice standing for
finance to decide on. So finance cancelling an invoice out of band is expected
operation, and every reader of the log used to treat `posting_status = Posted`
as proof the ledger still held it.

Measured on `mysite.localhost` before this suite existed: six `Financial Posting
Log` rows Posted against `docstatus = 2` documents, four `Folio Charge` and three
`Folio Payment` rows stamped `is_posted_to_erp = 1` against them, and a folio
carrying 820 of charges that no route could post, because:

- `post_folio_invoice` answered `{"duplicate": True}` and named the cancelled
  invoice as its reason,
- `checkout.post_folio` answered `{"invoice": None, "payments": []}` - nothing to
  do - because every row was stamped,
- `retry_posting` answered `{"retried": False}` on the authority of the cancelled
  document,
- `reconcile_folio` reported the 820 variance correctly and simultaneously
  reported `unposted_charges: []` and `erp_invoices: []`, two statements that
  cannot both be true, with nothing in the payload to reconcile them,
- and `mark_reconciled` would have stamped the whole condition `Reconciled`,
  which `_claim` treats as interchangeable with Posted.

What every test here asserts is a **refusal**, never a repair. The charge rows
are still stamped, so there is no coherent batch to re-post; clearing those
stamps is a correction with its own approval and audit trail, and a read path
must not perform it. The third answer - posted, then withdrawn - is what these
tests are for.
"""

import frappe
from frappe.tests import IntegrationTestCase

from hospitality_pms.services import posting as posting_service
from hospitality_pms.services.exceptions import ReconciliationError
from hospitality_pms.tests.posting_world import PostingWorld, folio_invoices


class CancelledErpTestCase(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.world = PostingWorld("STALE", "SP")

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

	# -- building the condition ------------------------------------------

	def _post_an_invoice(self, amount: float = 500.0) -> str:
		"""One charge, one submitted invoice. The healthy starting point."""
		self.world.charge(self.folio, "Laundry", amount, 0, "stale-charge")
		result = posting_service.post_folio_invoice(self.folio)

		invoice = result["erp_document"]
		self.assertEqual(frappe.db.get_value("Sales Invoice", invoice, "docstatus"), 1)

		return invoice

	def _cancel(self, doctype: str, name: str):
		"""Withdraw a document the way finance does - through the ORM."""
		frappe.get_doc(doctype, name).cancel()
		self.assertEqual(frappe.db.get_value(doctype, name, "docstatus"), 2)

	def _stale_invoice(self) -> str:
		invoice = self._post_an_invoice()
		self._cancel("Sales Invoice", invoice)

		return invoice

	def _log_for(self, erp_document: str) -> str:
		return frappe.db.get_value(
			posting_service.POSTING_LOG, {"folio": self.folio, "erp_document": erp_document}, "name"
		)

	def _invoice_count(self) -> int:
		return frappe.db.count("Sales Invoice", {"remarks": ("like", f"%{self.folio}%")})

	def _log_count(self) -> int:
		return frappe.db.count(posting_service.POSTING_LOG, {"folio": self.folio})


class TestPostingRefusesToActOnAWithdrawnDocument(CancelledErpTestCase):
	def test_posting_an_invoice_again_refuses_instead_of_reporting_duplicate(self):
		"""The answer that was `{"duplicate": True}` and a cancelled name."""
		invoice = self._stale_invoice()

		with self.assertRaises(ReconciliationError) as caught:
			posting_service.post_folio_invoice(self.folio)

		message = str(caught.exception)
		self.assertIn("reconciliation", message.lower())
		self.assertIn(self._log_for(invoice), message, msg="the log name is what finance acts on")

		# 16.7.5-R1D, security review. The refusal travels to the browser in
		# `_server_messages` and nothing catches it, so it must not name the
		# accounting document: `api/checkout.retry_posting` reaches this throw for
		# Night Auditor, Hotel Manager and General Manager, none of whom hold
		# `Sales Invoice` read, and whose success path on that same endpoint exists
		# only to withhold that name from them (R1B).
		self.assertNotIn(invoice, message, msg="the refusal disclosed a Sales Invoice name")

	def test_the_refusal_creates_no_second_invoice(self):
		"""A refusal, not a repair. Nothing new reaches the ledger."""
		self._stale_invoice()

		invoices_before = self._invoice_count()
		logs_before = self._log_count()

		with self.assertRaises(ReconciliationError):
			posting_service.post_folio_invoice(self.folio)

		self.assertEqual(self._invoice_count(), invoices_before)
		self.assertEqual(self._log_count(), logs_before)

	def test_the_charge_stamps_are_left_alone(self):
		"""Un-stamping the rows is a correction, and this is a read path."""
		self._stale_invoice()

		with self.assertRaises(ReconciliationError):
			posting_service.post_folio_invoice(self.folio)

		doc = frappe.get_doc(posting_service.FOLIO_DOCTYPE, self.folio)
		self.assertTrue(all(row.is_posted_to_erp for row in doc.charges))

	def test_a_payment_whose_entry_was_cancelled_refuses_under_its_own_key(self):
		"""`_claim` is the root fix, so the payment path inherits it."""
		self._post_an_invoice()

		row = self.world.payment(self.folio, 100.0, "stale-pay")["row"]
		entry = posting_service.post_folio_payment(self.folio, row)["erp_document"]

		self._cancel("Payment Entry", entry)

		entries_before = frappe.db.count("Payment Entry", {"docstatus": 1})

		with self.assertRaises(ReconciliationError) as caught:
			posting_service.post_folio_payment(self.folio, row)

		self.assertNotIn(entry, str(caught.exception), msg="the refusal named a Payment Entry")
		self.assertEqual(frappe.db.count("Payment Entry", {"docstatus": 1}), entries_before)

	def test_retrying_a_stale_posting_refuses_instead_of_reporting_it_healthy(self):
		invoice = self._post_an_invoice()
		log = frappe.db.get_value(
			posting_service.POSTING_LOG, {"folio": self.folio, "erp_document": invoice}, "name"
		)

		# Healthy: the refusal to retry a Posted row is the correct answer.
		self.assertEqual(posting_service.retry_posting(log)["retried"], False)

		self._cancel("Sales Invoice", invoice)

		with self.assertRaises(ReconciliationError) as caught:
			posting_service.retry_posting(log)

		message = str(caught.exception)
		self.assertIn(log, message)
		self.assertNotIn(invoice, message, msg="the refusal disclosed a Sales Invoice name")

	def test_finance_cannot_sign_off_a_posting_whose_document_has_gone(self):
		"""The one write that would have made the condition unrecoverable.

		`Reconciled` is treated as interchangeable with `Posted` by `_claim`,
		`_latest_invoice_posting` and `folio_erp_documents`, so stamping a stale row
		would launder it past every other guard in this suite for ever.
		"""
		invoice = self._post_an_invoice()
		log = frappe.db.get_value(
			posting_service.POSTING_LOG, {"folio": self.folio, "erp_document": invoice}, "name"
		)

		self._cancel("Sales Invoice", invoice)

		with self.assertRaises(ReconciliationError):
			posting_service.mark_reconciled(log)

		self.assertEqual(
			frappe.db.get_value(posting_service.POSTING_LOG, log, "posting_status"),
			posting_service.POSTED,
		)

	def test_a_healthy_posting_is_still_signed_off_and_still_never_re_sent(self):
		"""The guard must not cost the behaviour it is protecting."""
		invoice = self._post_an_invoice()
		log = frappe.db.get_value(
			posting_service.POSTING_LOG, {"folio": self.folio, "erp_document": invoice}, "name"
		)

		self.assertEqual(posting_service.mark_reconciled(log), posting_service.RECONCILED)

		# Reconciled, and still exactly one invoice: replay is a no-op, not a second
		# document.
		replay = posting_service.post_folio_invoice(self.folio)

		self.assertTrue(replay["duplicate"])
		self.assertEqual(replay["erp_document"], invoice)
		self.assertEqual(len(folio_invoices(self.folio)), 1)


	def test_no_refusal_on_any_path_names_the_accounting_document(self):
		"""One assertion for the rule, so a fourth raise site cannot quietly break it.

		Three routes reach a stale-posting refusal and all three surface as an HTTP
		error message. Checked together rather than one per test, because the failure
		mode is a *new* raise site being added with the document interpolated back in.
		"""
		invoice = self._post_an_invoice()
		log = self._log_for(invoice)
		self._cancel("Sales Invoice", invoice)

		refusals = []

		for call in (
			lambda: posting_service.post_folio_invoice(self.folio),
			lambda: posting_service.retry_posting(log),
			lambda: posting_service.mark_reconciled(log),
		):
			with self.assertRaises(ReconciliationError) as caught:
				call()

			refusals.append(str(caught.exception))

		for message in refusals:
			self.assertNotIn(invoice, message, msg=f"document name disclosed: {message}")
			self.assertNotIn("ACC-SINV", message, msg=f"document name disclosed: {message}")
			self.assertIn(log, message, msg=f"the posting log must be named: {message}")

	def test_a_posting_log_naming_a_doctype_that_no_longer_exists_does_not_raise(self):
		"""Stored data must fail closed, not take reconciliation down.

		`erp_doctype` is a Link to DocType written at posting time. A DocType renamed
		or removed by a later patch leaves rows naming the old one, and an unguarded
		`get_value` raises ProgrammingError(1146) on the missing table - inside
		`reconcile_folio`, which `night_audit.reconcile` runs over every folio on the
		property. One unreadable row would take down the whole day.
		"""
		self.assertFalse(posting_service._erp_document_is_live("HPMS Renamed Away", "X-1"))

		invoice = self._post_an_invoice()
		frappe.db.set_value(
			posting_service.POSTING_LOG,
			self._log_for(invoice),
			"erp_doctype",
			"HPMS Renamed Away",
			update_modified=False,
		)

		# Does not raise, and reports the row as needing reconciliation rather than
		# silently counting it as posted.
		result = posting_service.reconcile_folio(self.folio)

		self.assertTrue(result["needs_erp_reconciliation"])


class TestReconciliationNamesTheRealProblem(CancelledErpTestCase):
	def test_a_withdrawn_document_is_reported_as_needing_reconciliation(self):
		invoice = self._stale_invoice()

		result = posting_service.reconcile_folio(self.folio)

		self.assertTrue(result["needs_erp_reconciliation"])
		self.assertFalse(result["is_reconciled"])

		stale = result["stale_postings"]
		self.assertEqual(len(stale), 1)
		self.assertEqual(stale[0]["erp_document"], invoice)
		self.assertEqual(stale[0]["erp_doctype"], "Sales Invoice")
		self.assertEqual(stale[0]["posting_status"], posting_service.POSTED)

	def test_the_report_no_longer_contradicts_itself(self):
		"""820 missing beside zero unposted charges, with nothing to explain it.

		Both statements were true and neither was the answer. `stale_postings` is
		the field that reconciles them, so it must be populated in exactly the case
		where the two disagree.
		"""
		self._stale_invoice()

		result = posting_service.reconcile_folio(self.folio)

		self.assertEqual(result["unposted_charges"], [])
		self.assertEqual(result["erp_invoices"], [])
		self.assertNotEqual(result["charge_variance"], 0)
		self.assertTrue(result["stale_postings"])

	def test_a_reconciled_folio_reports_no_stale_postings(self):
		self.world.charge(self.folio, "Laundry", 500.0, 0, "clean-charge")
		posting_service.post_folio_invoice(self.folio)

		row = self.world.payment(self.folio, 500.0, "clean-pay")["row"]
		posting_service.post_folio_payment(self.folio, row)

		result = posting_service.reconcile_folio(self.folio)

		self.assertEqual(result["stale_postings"], [])
		self.assertFalse(result["needs_erp_reconciliation"])
		self.assertTrue(result["is_reconciled"], result)

	def test_a_failed_posting_is_not_reported_as_stale(self):
		"""The two are different problems and must not be conflated.

		A Failed row names no ERP document. It is retryable and belongs in
		`failed_postings`; calling it stale would tell finance an accounting
		decision is needed where a retry would do.
		"""
		self._post_an_invoice()

		log = frappe.db.get_value(
			posting_service.POSTING_LOG, {"folio": self.folio}, "name", order_by="creation desc"
		)
		frappe.db.set_value(
			posting_service.POSTING_LOG,
			log,
			{"posting_status": posting_service.FAILED, "erp_document": None, "erp_doctype": None},
			update_modified=False,
		)

		result = posting_service.reconcile_folio(self.folio)

		self.assertEqual(result["stale_postings"], [])
		self.assertEqual([row["name"] for row in result["failed_postings"]], [log])


class TestTheDocumentListSeparatesWhatHappenedFromWhatHolds(CancelledErpTestCase):
	def test_a_cancelled_document_is_not_listed_as_posted(self):
		self._stale_invoice()

		self.assertEqual(posting_service.folio_erp_documents(self.folio, "Sales Invoice"), [])

	def test_the_reconciliation_report_can_still_see_what_was_posted(self):
		"""`live_only=False` is what lets the report say *which* document went."""
		invoice = self._stale_invoice()

		self.assertEqual(
			posting_service.folio_erp_documents(self.folio, "Sales Invoice", live_only=False),
			[invoice],
		)

	def test_a_submitted_document_is_listed_either_way(self):
		invoice = self._post_an_invoice()

		self.assertEqual(
			posting_service.folio_erp_documents(self.folio, "Sales Invoice"), [invoice]
		)
		self.assertEqual(
			posting_service.folio_erp_documents(self.folio, "Sales Invoice", live_only=False),
			[invoice],
		)

	def test_a_draft_document_is_no_more_evidence_than_a_cancelled_one(self):
		"""`docstatus == 1`, not `!= 2`. A draft has never entered the ledger."""
		invoice = self._post_an_invoice()

		frappe.db.set_value("Sales Invoice", invoice, "docstatus", 0, update_modified=False)

		self.assertEqual(posting_service.folio_erp_documents(self.folio, "Sales Invoice"), [])
		self.assertFalse(posting_service._erp_document_is_live("Sales Invoice", invoice))

	def test_a_document_that_no_longer_exists_is_not_live(self):
		self.assertFalse(
			posting_service._erp_document_is_live("Sales Invoice", "ACC-SINV-DOES-NOT-EXIST")
		)
		self.assertFalse(posting_service._erp_document_is_live("Sales Invoice", None))
		self.assertFalse(posting_service._erp_document_is_live(None, None))
