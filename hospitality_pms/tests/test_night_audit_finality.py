"""16.7.5-R1F — the close-time set must be the set reconciliation claimed.

R1E established that a Night Audit could close over accounting that had been
withdrawn from the ledger after reconciliation accepted it, and added a
close-time guard. The guard was blocked in review, and it was right to be: it
rebuilt the set to check by calling `reconciliation_population()` again, and that
function selects folios on their **current** `folio_status`.

`checkout.reverse_checkout` is a supported operation that moves a Settled folio
to Under Review. So the escape was:

    folio settled -> reconciled -> reverse_checkout -> Under Review
                  -> finance cancels the invoice
                  -> the folio is no longer in the population
                  -> the close-time guard has nothing to look at
                  -> the business date closes over invalid accounting

The invariant this suite exists to hold is one sentence:

    THE SET CHECKED AT CLOSE = THE SET CLAIMED BY RECONCILIATION.

So reconciliation writes down the exact `Financial Posting Log` rows it
validated, and `close` re-checks those rows. Nothing about a folio's later
status can remove one of them from the check.

The second half of the suite is the recovery path. A refusal that leaves finance
with nothing they are permitted to do is not a control, it is a deadlock:
`mark_reconciled` refuses a stale row, `retry_posting` refuses it, and
`post_folio_invoice` cannot raise a replacement while the folio's rows are still
stamped. `withdraw_stale_posting` is the one supported way out, and the tests
here prove it opens and that it does not open anything else.
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt

from hospitality_pms.api import checkout as checkout_api
from hospitality_pms.services import checkout as checkout_service
from hospitality_pms.services import folio as folio_service
from hospitality_pms.services import night_audit as audit_service
from hospitality_pms.services import posting as posting_service
from hospitality_pms.services.exceptions import (
	NightAuditError,
	PermissionDeniedError,
	PostingError,
)
from hospitality_pms.tests.night_audit_world import NightAuditWorld
from hospitality_pms.tests.posting_world import folio_invoices

AUDIT = "Night Audit"
EVIDENCE = "Night Audit Reconciled Posting"


class FinalityTestCase(IntegrationTestCase):
	WORLD_CODE = "NF"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.world = NightAuditWorld(cls.__name__[:6].upper(), cls.WORLD_CODE)
		cls.world.check_in_guest(0)

	@classmethod
	def tearDownClass(cls):
		cls.world.teardown()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")
		# Evidence first: it links to the audits it belongs to.
		self.world.fixtures.reset_property_records(self.world.property, (EVIDENCE, AUDIT))

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	# -- premises ---------------------------------------------------------

	def _reconciled_audit(self) -> str:
		"""Review, post and reconcile: a day that is entitled to close."""
		audit = audit_service.start(self.world.property)

		audit_service.review(audit)
		audit_service.post_room_charges(audit)
		audit_service.reconcile(audit)

		return audit

	def _payment_entry(self, folio: str) -> str:
		return frappe.get_all(
			posting_service.POSTING_LOG,
			filters={
				"folio": folio,
				"posting_type": "Payment Entry",
				"posting_status": ("in", ("Posted", "Reconciled")),
			},
			fields=["erp_document"],
			order_by="creation asc",
			limit=1,
		)[0]["erp_document"]

	def _posting_log_for(self, folio: str, posting_type: str = "Sales Invoice") -> str:
		return frappe.get_all(
			posting_service.POSTING_LOG,
			filters={"folio": folio, "posting_type": posting_type},
			fields=["name"],
			order_by="creation asc",
			limit=1,
		)[0]["name"]

	def _status(self, audit: str) -> str:
		return frappe.db.get_value(AUDIT, audit, "audit_status")

	def assertRefusesClose(self, audit: str) -> str:
		"""The date must not move, and the audit must not read Closed."""
		before = self.world.business_date

		with self.assertRaises(NightAuditError) as caught:
			audit_service.close(audit)

		self.assertEqual(
			self.world.business_date,
			before,
			msg="the business date advanced over accounting the ledger no longer supports",
		)
		self.assertNotEqual(self._status(audit), audit_service.CLOSED)
		self.assertIsNone(frappe.db.get_value(AUDIT, audit, "closed_on"))

		return str(caught.exception)


class TestReconciledSetIsRecorded(FinalityTestCase):
	"""Reconciliation must write down what it validated, not merely that it ran."""

	WORLD_CODE = "F1"

	def test_reconciliation_records_the_postings_it_validated(self):
		folio = self.world.settled_folio(charge=120)
		invoice = folio_invoices(folio)[0]

		audit = self._reconciled_audit()

		evidence = audit_service.reconciled_postings(audit)
		documents = {row["erp_document"] for row in evidence}

		self.assertIn(invoice, documents, msg="reconciliation claimed nothing about its own invoice")
		self.assertIn(self._payment_entry(folio), documents)

	def test_the_recorded_set_survives_the_folio_leaving_the_population(self):
		"""The whole of R1F in one assertion.

		The folio moves out of `reconciliation_population`. The evidence does not
		move with it, because it is keyed on the posting log and not on the folio.
		"""
		folio = self.world.settled_folio(charge=125)
		invoice = folio_invoices(folio)[0]

		audit = self._reconciled_audit()

		folio_service.transition(folio, folio_service.UNDER_REVIEW, reason="Checkout reversed")

		self.assertNotIn(
			folio,
			audit_service.reconciliation_population(self.world.property, self.world.business_date),
			msg="premise: the folio must have left the population",
		)

		documents = {row["erp_document"] for row in audit_service.reconciled_postings(audit)}
		self.assertIn(invoice, documents)

	def test_re_reconciling_does_not_rebaseline_an_accepted_posting(self):
		"""Write-once. A second run must not adopt the damaged state as healthy."""
		folio = self.world.settled_folio(charge=126)
		invoice = folio_invoices(folio)[0]

		audit = self._reconciled_audit()

		self.world.credit_note(invoice)
		audit_service.reconcile(audit)

		recorded = [
			row for row in audit_service.reconciled_postings(audit) if row["erp_document"] == invoice
		]

		self.assertEqual(len(recorded), 1, msg="the evidence row was duplicated rather than kept")
		self.assertEqual(
			flt(recorded[0]["returned_total"]),
			0.0,
			msg="re-running reconciliation re-baselined the audit against the credit note",
		)


class TestCloseRefusesBrokenFinality(FinalityTestCase):
	"""Every shape of accounting change the close must catch."""

	WORLD_CODE = "F2"

	def test_original_blocker_invoice_cancelled_after_reconcile(self):
		"""Case 1 - the UAT blocker, reproduced without any folio movement."""
		folio = self.world.settled_folio(charge=130)
		invoice = folio_invoices(folio)[0]

		audit = self._reconciled_audit()

		frappe.get_doc("Sales Invoice", invoice).cancel()

		message = self.assertRefusesClose(audit)
		self.assertIn("reconcil", message.lower())

	def test_under_review_escape_settled_reconciled_then_reopened(self):
		"""Case 2 - the escape that blocked R1E.

		The folio is reconciled while Settled, then moved to Under Review, and
		only then is the invoice cancelled. R1E's guard passed this: the folio was
		no longer in the population it rebuilt, so it checked nothing.
		"""
		folio = self.world.settled_folio(charge=140)
		invoice = folio_invoices(folio)[0]

		audit = self._reconciled_audit()

		folio_service.transition(folio, folio_service.UNDER_REVIEW, reason="Checkout reversed")
		frappe.get_doc("Sales Invoice", invoice).cancel()

		self.assertNotIn(
			folio,
			audit_service.reconciliation_population(self.world.property, self.world.business_date),
			msg="premise: the escape needs the folio out of the population",
		)

		self.assertRefusesClose(audit)

	def test_reverse_checkout_then_finance_cancels_the_invoice(self):
		"""Case 3 - the same escape, through the supported operation that creates it."""
		checked_out = self.world.checked_out_stay(1, charge=95)
		folio = checked_out["folio"]
		invoice = folio_invoices(folio)[0]

		audit = self._reconciled_audit()

		reversal = checkout_service.reverse_checkout(checked_out["stay"], "Guest returned")

		self.assertEqual(
			frappe.db.get_value(folio_service.FOLIO_DOCTYPE, folio, "folio_status"),
			folio_service.UNDER_REVIEW,
			msg="premise: reverse_checkout must have reopened the folio",
		)
		self.assertIn(invoice, reversal["standing_invoices"])

		frappe.get_doc("Sales Invoice", invoice).cancel()

		self.assertRefusesClose(audit)

	def test_credit_note_leaves_the_invoice_standing_and_still_refuses(self):
		"""Case 8 - `docstatus == 1` is not proof of finality.

		ERPNext books a return's receivable against `return_against` unless
		`update_outstanding_for_self` is set, so the original invoice stays
		submitted while the money it charged is credited back.
		"""
		folio = self.world.settled_folio(charge=150)
		invoice = folio_invoices(folio)[0]

		audit = self._reconciled_audit()

		note = self.world.credit_note(invoice)

		self.assertEqual(
			frappe.db.get_value("Sales Invoice", invoice, "docstatus"),
			1,
			msg="premise: the original invoice must still be submitted",
		)
		self.assertEqual(frappe.db.get_value("Sales Invoice", note, "return_against"), invoice)

		self.assertRefusesClose(audit)

	def test_supplementary_batch_earlier_invoice_cancelled(self):
		"""Case 4 - every batch is checked, not only the newest."""
		folio = self.world.settled_folio(charge=200)

		folio_service.transition(folio, folio_service.UNDER_REVIEW, reason="Late charge")
		self.world.charge(folio, "Minibar", 30, 1.5, f"{self.world.tag}:f2-supp:{folio}")
		posting_service.post_folio_invoice(folio)
		payment = folio_service.post_payment(
			folio, 31.5, "Cash", idempotency_key=f"{self.world.tag}:f2-supp-pay:{folio}"
		)
		posting_service.post_folio_payment(folio, payment["row"])
		folio_service.transition(folio, folio_service.READY, reason="Checkout")
		folio_service.transition(folio, folio_service.SETTLED, reason="Settled")

		invoices = folio_invoices(folio)
		self.assertEqual(len(invoices), 2, msg="premise: supplementary batch missing")

		audit = self._reconciled_audit()

		frappe.get_doc("Sales Invoice", invoices[0]).cancel()

		self.assertRefusesClose(audit)

	def test_cancelled_payment_entry_after_reconcile(self):
		"""Case 5 - a settlement withdrawn is as fatal as an invoice withdrawn."""
		folio = self.world.settled_folio(charge=160)
		entry = self._payment_entry(folio)

		audit = self._reconciled_audit()

		frappe.get_doc("Payment Entry", entry).cancel()

		self.assertRefusesClose(audit)

	def test_missing_erp_document(self):
		"""Case 6 - a document that is not there at all."""
		folio = self.world.settled_folio(charge=170)
		invoice = folio_invoices(folio)[0]

		audit = self._reconciled_audit()

		frappe.db.delete("Sales Invoice", {"name": invoice})

		self.assertRefusesClose(audit)

	def test_draft_erp_document(self):
		"""Case 7 - a draft has never entered the ledger."""
		folio = self.world.settled_folio(charge=180)
		invoice = folio_invoices(folio)[0]

		audit = self._reconciled_audit()

		frappe.db.set_value("Sales Invoice", invoice, "docstatus", 0, update_modified=False)

		self.assertRefusesClose(audit)

	def test_log_row_redirected_to_another_document(self):
		"""The evidence names a document; the log must still name the same one."""
		folio = self.world.settled_folio(charge=185)
		log = self._posting_log_for(folio)

		audit = self._reconciled_audit()

		frappe.db.set_value(
			posting_service.POSTING_LOG, log, "erp_document", "SINV-NOT-THE-ONE", update_modified=False
		)

		self.assertRefusesClose(audit)

	def test_a_credit_note_raised_before_the_first_reconcile_is_still_refused(self):
		"""The baseline must not be derived from the read it is compared against.

		If it is, the credited-back arm can never fire on a first run: the folio
		leaves the population, the absolute folio check never happens, and the
		day closes with the invoice fully reversed and nothing anywhere to say so.
		"""
		folio = self.world.settled_folio(charge=145)
		invoice = folio_invoices(folio)[0]

		# Credited and moved out of the population *before* any reconciliation.
		self.world.credit_note(invoice)
		folio_service.transition(folio, folio_service.UNDER_REVIEW, reason="Checkout reversed")

		self.assertNotIn(
			folio,
			audit_service.reconciliation_population(self.world.property, self.world.business_date),
			msg="premise: the folio must be outside the population when reconciliation runs",
		)

		audit = self._reconciled_audit()

		recorded = [
			row for row in audit_service.reconciled_postings(audit) if row["erp_document"] == invoice
		]
		self.assertEqual(len(recorded), 1)
		self.assertEqual(
			flt(recorded[0]["returned_total"]),
			0.0,
			msg="an unexamined folio's credit note was recorded as the accepted state",
		)

		self.assertRefusesClose(audit)

	def test_cancelling_a_credit_note_raised_in_error_does_not_deadlock_the_close(self):
		"""The ledger becoming *more* correct must not refuse the day forever.

		Recorded credit moves back toward zero. Reconciling again cannot clear it
		- the baseline is written once - and the invoice is live and no longer
		credited, so a withdrawal is refused too. Tested as a delta with a
		direction rather than as inequality, precisely so this has an exit.
		"""
		folio = self.world.settled_folio(charge=147)
		invoice = folio_invoices(folio)[0]

		note = self.world.credit_note(invoice)
		folio_service.transition(folio, folio_service.UNDER_REVIEW, reason="Checkout reversed")

		audit = self._reconciled_audit()

		# The credit note is the only thing wrong with this day, and it refuses.
		self.assertRefusesClose(audit)

		# Finance decides the credit note was raised in error and cancels it. The
		# original invoice is whole again and the ledger is back to what
		# reconciliation accepted.
		frappe.get_doc("Sales Invoice", note).cancel()

		before = self.world.business_date
		audit_service.reconcile(audit)
		audit_service.close(audit)

		self.assertEqual(self._status(audit), audit_service.CLOSED)
		self.assertEqual(self.world.business_date, add_days(before, 1))

	def test_healthy_accounting_still_closes(self):
		"""Case 9 - the guard must cost a correct day nothing."""
		self.world.settled_folio(charge=190)

		audit = self._reconciled_audit()
		before = self.world.business_date

		result = audit_service.close(audit)

		self.assertEqual(self._status(audit), audit_service.CLOSED)
		self.assertEqual(self.world.business_date, add_days(before, 1))
		self.assertEqual(result["new_business_date"], str(add_days(before, 1)))

	def test_close_refuses_before_it_advances_anything(self):
		"""The refusal must land before the date moves, not be rolled back after."""
		folio = self.world.settled_folio(charge=195)
		invoice = folio_invoices(folio)[0]

		audit = self._reconciled_audit()
		frappe.get_doc("Sales Invoice", invoice).cancel()

		self.assertRefusesClose(audit)

		# The audit is still closable-shaped: nothing about the *audit* was
		# damaged by the refusal, only the accounting behind it.
		self.assertIsNotNone(frappe.db.get_value(AUDIT, audit, "reconciliation_completed_on"))


class TestReconciliationSeesTheBreakToo(FinalityTestCase):
	"""A refusal at close with silence at reconcile would be a trap."""

	WORLD_CODE = "F3"

	def test_re_reconciling_raises_a_blocking_exception_for_a_stale_posting(self):
		folio = self.world.settled_folio(charge=210)
		invoice = folio_invoices(folio)[0]

		audit = self._reconciled_audit()

		folio_service.transition(folio, folio_service.UNDER_REVIEW, reason="Checkout reversed")
		frappe.get_doc("Sales Invoice", invoice).cancel()

		result = audit_service.reconcile(audit)

		self.assertGreaterEqual(result["stale_postings"], 1)
		self.assertGreaterEqual(result["blocking"], 1)

		# The status is deliberately not asserted. `reconcile` promotes a clean
		# audit to Ready to Close and never demotes it again, so an audit that
		# reconciled clean first still reads Ready to Close here - which is the
		# R1D route, where the workflow status is precisely the thing that is not
		# evidence. What has to be true is that the close is refused.
		self.assertRefusesClose(audit)

	def test_a_reconciliation_exception_does_not_name_the_accounting_document(self):
		"""16.7.5-R1B: Night Audit is read by every operational role."""
		folio = self.world.settled_folio(charge=215)
		invoice = folio_invoices(folio)[0]

		audit = self._reconciled_audit()

		folio_service.transition(folio, folio_service.UNDER_REVIEW, reason="Checkout reversed")
		frappe.get_doc("Sales Invoice", invoice).cancel()
		audit_service.reconcile(audit)

		descriptions = frappe.get_all(
			"Night Audit Exception",
			filters={"parent": audit},
			pluck="description",
		)

		self.assertTrue(descriptions)

		for description in descriptions:
			self.assertNotIn(invoice, description)
			self.assertNotIn(folio, description)

	def test_credit_note_makes_the_folio_disagree_with_the_ledger(self):
		"""Reconciliation nets returns, so a credited folio is a variance."""
		folio = self.world.settled_folio(charge=220)
		invoice = folio_invoices(folio)[0]

		clean = posting_service.reconcile_folio(folio)
		self.assertTrue(clean["is_reconciled"], msg="premise: the folio starts reconciled")

		self.world.credit_note(invoice)

		after = posting_service.reconcile_folio(folio)

		self.assertFalse(after["is_reconciled"])
		self.assertNotEqual(flt(after["erp_returned"]), 0.0)
		self.assertNotEqual(flt(after["charge_variance"]), 0.0)


class TestRecoveryPath(FinalityTestCase):
	"""What finance is actually permitted to do about a refusal."""

	WORLD_CODE = "F4"

	def test_a_live_posting_cannot_be_withdrawn(self):
		"""The mechanism is not a way to disown a healthy invoice."""
		folio = self.world.settled_folio(charge=230)
		log = self._posting_log_for(folio)

		with self.assertRaises(PostingError):
			posting_service.withdraw_stale_posting(log, "no reason to")

	def test_withdrawal_requires_a_reason(self):
		folio = self.world.settled_folio(charge=235)
		invoice = folio_invoices(folio)[0]
		log = self._posting_log_for(folio)

		frappe.get_doc("Sales Invoice", invoice).cancel()

		with self.assertRaises(PostingError):
			posting_service.withdraw_stale_posting(log, "   ")

	def test_withdrawal_is_refused_to_a_night_auditor(self):
		"""Seeing the queue is not authority to write off a claim on the ledger."""
		folio = self.world.settled_folio(charge=240)
		invoice = folio_invoices(folio)[0]
		log = self._posting_log_for(folio)
		auditor = self.world.fixtures.user(
			"nf-auditor", ["Night Auditor"], properties=[self.world.property]
		)

		frappe.get_doc("Sales Invoice", invoice).cancel()

		try:
			frappe.set_user(auditor)

			with self.assertRaises(PermissionDeniedError):
				checkout_api.withdraw_posting(log=log, reason="written off")
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(
			frappe.db.get_value(posting_service.POSTING_LOG, log, "posting_status"), "Posted"
		)

	def test_withdrawal_alone_does_not_let_the_day_close(self):
		"""A withdrawal records that money left the ledger. It does not put it back.

		This is the guard on the recovery mechanism itself. Withdrawing is the one
		write finance may make against a stale claim, and if the Night Audit treated
		it as resolution then `withdraw_posting` would simply *be* the close button:
		cancel the invoice, write off the claim, close the day - with the charges
		still stamped against a document that is gone and no variance anywhere.
		"""
		folio = self.world.settled_folio(charge=250)
		invoice = folio_invoices(folio)[0]
		log = self._posting_log_for(folio)

		audit = self._reconciled_audit()

		frappe.get_doc("Sales Invoice", invoice).cancel()
		self.assertRefusesClose(audit)

		posting_service.withdraw_stale_posting(log, "Invoice cancelled in error by finance")

		self.assertEqual(
			frappe.db.get_value(posting_service.POSTING_LOG, log, "posting_status"), "Cancelled"
		)

		# The folio now disagrees with the ledger in plain terms, which is the honest
		# description of a folio whose invoice was cancelled - and the day still
		# cannot close over it.
		self.assertFalse(posting_service.reconcile_folio(folio)["is_reconciled"])
		self.assertRefusesClose(audit)

		# Nor does re-running reconciliation clear it.
		audit_service.reconcile(audit)
		self.assertRefusesClose(audit)

		# Nor does moving the folio out of the reconciliation population, which is
		# what R1E's guard was defeated by.
		folio_service.transition(folio, folio_service.UNDER_REVIEW, reason="Reconciliation")
		audit_service.reconcile(audit)
		self.assertRefusesClose(audit)

	def test_the_withdrawn_batch_cannot_be_re_posted_by_any_permitted_route(self):
		"""The open end of the recovery path, asserted rather than described.

		After a withdrawal the money is owed and not in the ledger, and putting it
		back means raising a fresh invoice for the same charge rows. Nothing
		permitted does that today: the rows are still stamped so there is no batch,
		retrying refuses a claim that is Cancelled, and even with the stamps cleared
		`_invoice_batch_key` reproduces the same fingerprint, so the durable ledger
		answers "already performed" and hands back the cancelled invoice.

		This test exists so that the gap is a recorded fact with a name, and so that
		whoever closes it has a red test to turn green.
		"""
		folio = self.world.settled_folio(charge=255)
		invoice = folio_invoices(folio)[0]
		log = self._posting_log_for(folio)

		frappe.get_doc("Sales Invoice", invoice).cancel()
		posting_service.withdraw_stale_posting(log, "Cancelled by finance")

		# Every charge row is still stamped, so there is no batch to raise.
		stamped = frappe.get_all(
			"Folio Charge", filters={"parent": folio}, fields=["is_posted_to_erp"]
		)
		self.assertTrue(stamped)
		self.assertTrue(all(row["is_posted_to_erp"] for row in stamped))

		with self.assertRaises(PostingError):
			posting_service.post_folio_invoice(folio)

		with self.assertRaises(PostingError):
			posting_service.retry_posting(log)

	def test_withdrawal_is_recorded_on_the_folio_audit_trail(self):
		folio = self.world.settled_folio(charge=260)
		invoice = folio_invoices(folio)[0]
		log = self._posting_log_for(folio)

		frappe.get_doc("Sales Invoice", invoice).cancel()
		posting_service.withdraw_stale_posting(log, "Cancelled by finance on 2026-08-15")

		actions = frappe.get_all("Folio Log", filters={"folio": folio}, pluck="action")

		self.assertIn("Posting claim withdrawn", actions)

	def test_a_credited_invoice_can_be_withdrawn_even_though_it_is_submitted(self):
		"""Otherwise the credit-note refusal would have no exit at all."""
		folio = self.world.settled_folio(charge=270)
		invoice = folio_invoices(folio)[0]
		log = self._posting_log_for(folio)

		self.world.credit_note(invoice)

		self.assertEqual(frappe.db.get_value("Sales Invoice", invoice, "docstatus"), 1)

		posting_service.withdraw_stale_posting(log, "Reversed by credit note")

		self.assertEqual(
			frappe.db.get_value(posting_service.POSTING_LOG, log, "posting_status"), "Cancelled"
		)


class TestFinalityReadsAreBatched(FinalityTestCase):
	"""R1E's reviewers refused a per-row locking read. This is the replacement."""

	WORLD_CODE = "F5"

	def test_close_reads_each_erp_doctype_once_not_once_per_document(self):
		for amount in (310, 320, 330, 340):
			self.world.settled_folio(charge=amount)

		audit = self._reconciled_audit()

		evidence = audit_service.reconciled_postings(audit)
		invoices = [row for row in evidence if row["erp_doctype"] == "Sales Invoice"]

		self.assertGreaterEqual(
			len(invoices), 4, msg="premise: the batching claim needs several documents"
		)

		reads: list[str] = []
		original = frappe.db.get_values

		def counting(doctype, *args, **kwargs):
			reads.append(doctype)
			return original(doctype, *args, **kwargs)

		frappe.db.get_values = counting
		try:
			audit_service.close(audit)
		finally:
			frappe.db.get_values = original

		# Two statements against Sales Invoice: one for `docstatus`, one for the
		# returns raised against the whole set. Both are batched, and neither
		# grows with the number of documents.
		self.assertLessEqual(
			reads.count("Sales Invoice"),
			2,
			msg=f"the close read Sales Invoice {reads.count('Sales Invoice')} times for "
			f"{len(invoices)} documents - that is the per-row pattern R1E was blocked for",
		)
		self.assertLessEqual(reads.count("Payment Entry"), 1)

	def test_the_locking_read_is_taken_only_at_close(self):
		"""Reconciliation must not hold ERP locks for the length of a night's run."""
		self.world.settled_folio(charge=350)

		locked: list[str] = []
		original = frappe.db.get_values

		def watching(doctype, *args, **kwargs):
			if kwargs.get("for_update"):
				locked.append(doctype)
			return original(doctype, *args, **kwargs)

		frappe.db.get_values = watching
		try:
			self._reconciled_audit()
		finally:
			frappe.db.get_values = original

		self.assertNotIn("Sales Invoice", locked)
		self.assertNotIn("Payment Entry", locked)


class TestVarianceGuardStillHolds(FinalityTestCase):
	"""16.7.5-R1D's route must still be refused, unchanged by any of this."""

	WORLD_CODE = "F6"

	def test_reconcile_clean_then_variance_then_reconcile_then_review_then_close(self):
		audit = self._reconciled_audit()

		self.assertEqual(self._status(audit), audit_service.READY_TO_CLOSE)

		self.world.folio_with_unposted_charge(45.0)

		audit_service.reconcile(audit)
		audit_service.review(audit)

		message = self.assertRefusesClose(audit)
		self.assertIn("exception", message.lower())


class TestReconciliationVarianceResolution(FinalityTestCase):
	"""P1 (F-NA2) — a reviewed and resolved folio variance must reach close.

	reconcile() rebuilds its Unposted Charge exceptions every run. It used to wipe
	resolved rows too, so a variance an auditor had explicitly resolved reappeared
	unresolved on the next reconcile and the audit could never leave Posting for
	Ready to Close. Resolutions for folio variances now survive the rerun; finality
	breaks still re-block (verified by TestCloseRefusesBrokenFinality).
	"""

	def _folio_variance_rows(self, audit: str) -> list:
		doc = frappe.get_doc(AUDIT, audit)
		return [
			row
			for row in doc.audit_exceptions
			if row.exception_type == "Unposted Charge"
			and row.reference_doctype == folio_service.FOLIO_DOCTYPE
		]

	def test_unresolved_variance_still_blocks_close(self):
		self.world.folio_with_unposted_charge(30)
		audit = self._reconciled_audit()

		self.assertTrue(self._folio_variance_rows(audit), msg="the variance was not raised")
		self.assertRefusesClose(audit)

	def test_resolved_variance_survives_reconcile_and_allows_close(self):
		self.world.folio_with_unposted_charge(30)
		audit = self._reconciled_audit()

		rows = self._folio_variance_rows(audit)
		self.assertTrue(rows)
		self.assertRefusesClose(audit)

		audit_service.resolve_exception(
			audit, rows[0].name, "reviewed with finance; discrepancy accepted"
		)

		# The supported rerun of reconcile must keep the resolution and grant
		# Ready to Close, instead of wiping it and trapping the day.
		audit_service.reconcile(audit)

		preserved = self._folio_variance_rows(audit)
		self.assertTrue(preserved, msg="the variance row disappeared entirely")
		self.assertTrue(
			all(row.is_resolved for row in preserved),
			msg="the resolution was wiped on the reconcile rerun (F-NA2)",
		)
		self.assertEqual(self._status(audit), audit_service.READY_TO_CLOSE)

		closed_date = self.world.business_date
		result = audit_service.close(audit)
		self.assertEqual(self._status(audit), audit_service.CLOSED)
		self.assertEqual(result["closed_business_date"], str(closed_date))
