"""P1-14 — the evidence of a failed posting vanished with the failure.

`post_folio_invoice` claimed a Financial Posting Log row, tried to build the
invoice, and on failure called `_mark_failed` and re-raised. Both writes were in
the caller's transaction, so the rollback that followed took the Failed row with
it. Night Audit later looks for exactly those rows to decide whether the day's
revenue reached ERPNext — so the record of a posting failure disappeared
precisely when something depended on finding it.

The fix keeps the Financial Posting Log where it is. That row is a business
record: it says "this invoice exists", and it must roll back with the invoice or
it would lie. What is added alongside it is a durable operation record, written
on its own connection, which says something different — "we tried to post this
batch, and here is what happened". That one has to survive the rollback.

The Wave-2 batch fingerprint stays authoritative throughout: a retry recomputes
it from the folio's still-unposted rows, so it lands on the same logical
operation and cannot raise a second invoice for charges already invoiced.
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from hospitality_pms.services import durability
from hospitality_pms.services import posting as posting_service
from hospitality_pms.services import retry as retry_service
from hospitality_pms.services.exceptions import ConfigurationError
from hospitality_pms.tests.posting_world import PostingWorld, folio_invoices, invoice_totals

PRECISION = 2


class PostingRetryTestCase(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.world = PostingWorld("PRET", "PR")

	@classmethod
	def tearDownClass(cls):
		cls.world.teardown()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")
		durability.purge_operations(property_name=self.world.property)
		self.folio = self.world.folio()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		self._restore_laundry_tax(None)
		durability.purge_operations(property_name=self.world.property)

	def assertMoney(self, actual, expected, msg=None):
		self.assertAlmostEqual(flt(actual), flt(expected), places=PRECISION, msg=msg)

	# -- the misconfiguration used to force a failure ---------------------

	def _restore_laundry_tax(self, template):
		"""Point the Laundry charge type at a tax template, or at nothing.

		Laundry is mapped without one, so a Laundry line that carries tax has
		nowhere for the tax to go and posting refuses (Wave 2). That is a real,
		deterministic configuration failure - better for this test than a
		contrived exception, because it exercises the actual failure path.
		"""
		row = frappe.db.get_value(
			"Charge Item Map", {"parent": self.world.profile, "charge_type": "Laundry"}, "name"
		)
		frappe.db.set_value("Charge Item Map", row, "tax_template", template, update_modified=False)
		frappe.clear_document_cache("Posting Profile", self.world.profile)
		frappe.db.commit()

	def _misconfigured_charge(self, key: str):
		self.world.charge(self.folio, "Laundry", 100, 10, key)
		frappe.db.commit()


class TestPostingFailureDurability(PostingRetryTestCase):
	def test_failed_posting_record_survives_rollback(self):
		"""The heart of P1-14."""
		self._misconfigured_charge("p1")

		with self.assertRaises(ConfigurationError):
			posting_service.post_folio_invoice(self.folio)

		# The request dies, exactly as it did in the sweep.
		frappe.db.rollback()

		# Nothing half-posted.
		self.assertEqual(folio_invoices(self.folio), [])
		self.assertEqual(
			frappe.get_all(
				"Folio Charge", filters={"parent": self.folio, "is_posted_to_erp": 1}, pluck="name"
			),
			[],
		)

		# But the failure is still on record.
		failures = durability.operations_needing_attention(self.world.property, limit=50)
		durable = durability.find_operations(
			property_name=self.world.property, operation="post_folio_invoice"
		)

		self.assertEqual(
			len(durable), 1, msg=f"the posting failure did not survive the rollback: {durable}"
		)
		self.assertEqual(durable[0]["queue_status"], durability.RETRYING)
		self.assertIn("tax", durable[0]["last_error"].lower())
		self.assertEqual(durable[0]["reference_name"], self.folio)

	def test_failed_posting_is_visible_to_the_failed_postings_query(self):
		"""Night Audit asks this question; it must get a true answer.

		Not a Night Audit change - only that the query it already calls can see
		a failure whose Financial Posting Log row rolled back.
		"""
		self._misconfigured_charge("p2")

		with self.assertRaises(ConfigurationError):
			posting_service.post_folio_invoice(self.folio)

		frappe.db.rollback()

		failed = posting_service.get_failed_postings(self.world.property)

		self.assertTrue(
			any(row.get("folio") == self.folio for row in failed),
			msg=f"a failed posting was invisible to the failed-postings query: {failed}",
		)

	def test_successful_posting_records_no_failure(self):
		self.world.charge(self.folio, "Room Charge", 100, 10, "p3")

		posting_service.post_folio_invoice(self.folio)

		# Read through the ledger's own connection: this transaction's snapshot
		# predates the durable write, so `frappe.db` would not see it.
		records = durability.find_operations(
			property_name=self.world.property, operation="post_folio_invoice"
		)

		self.assertEqual(len(records), 1)
		self.assertEqual(records[0]["queue_status"], durability.RESOLVED)


class TestPostingRetry(PostingRetryTestCase):
	def test_failed_posting_retry_succeeds_once(self):
		"""Fix the configuration, retry, and the same batch posts - once."""
		self._misconfigured_charge("q1")

		with self.assertRaises(ConfigurationError):
			posting_service.post_folio_invoice(self.folio)

		frappe.db.rollback()

		# Someone maps the missing tax template and asks for it to be retried
		# now, rather than waiting out the backoff.
		self._restore_laundry_tax(self.world.room_tax_template)

		key = durability.find_operations(
			property_name=self.world.property, operation="post_folio_invoice"
		)[0]["operation_key"]
		durability.reschedule_now(key)

		results = retry_service.retry_due_operations(self.world.property, limit=10)

		self.assertTrue(results, msg="nothing was retried")
		self.assertEqual(
			[r["status"] for r in results],
			[durability.RESOLVED],
			msg=f"the retry did not perform the posting: {results}",
		)

		invoices = folio_invoices(self.folio)

		self.assertEqual(len(invoices), 1)
		self.assertMoney(invoice_totals(invoices[0])["grand_total"], 110)

	def test_posting_retry_does_not_duplicate_invoice(self):
		"""Retrying an operation that already succeeded raises nothing new."""
		self.world.charge(self.folio, "Room Charge", 100, 10, "q2")
		posting_service.post_folio_invoice(self.folio)
		frappe.db.commit()

		posting_service.post_folio_invoice(self.folio)
		retry_service.retry_due_operations(self.world.property, limit=10)

		self.assertEqual(
			len(folio_invoices(self.folio)),
			1,
			msg="the retry raised a second Sales Invoice for charges already invoiced",
		)

	def test_retry_stops_at_max_attempts(self):
		"""A configuration nobody fixes must stop, not cycle for ever."""
		self._misconfigured_charge("q3")

		with self.assertRaises(ConfigurationError):
			posting_service.post_folio_invoice(self.folio)

		frappe.db.rollback()

		key = durability.find_operations(
			property_name=self.world.property, operation="post_folio_invoice"
		)[0]["operation_key"]

		for _attempt in range(durability.DEFAULT_MAX_ATTEMPTS + 2):
			durability.fail_operation(key, error="still misconfigured", retry_in_minutes=0)
			retry_service.retry_due_operations(self.world.property, limit=10)

		record = durability.get_operation(key)

		self.assertEqual(
			record["queue_status"],
			durability.ABANDONED,
			msg=f"the posting retried past its limit: {record}",
		)
		self.assertIsNone(record["next_attempt_on"])

	def test_unknown_retry_operation_fails_safe(self):
		"""An operation with no handler is stopped and made visible."""
		durability.begin_operation(
			property_name=self.world.property,
			integration_type="Other",
			operation="teleport_guest",
			operation_key="wave3:unknown:1",
			payload={},
		)
		durability.fail_operation("wave3:unknown:1", error="boom", retry_in_minutes=0)

		results = retry_service.retry_due_operations(self.world.property, limit=10)

		self.assertEqual([r["status"] for r in results], [durability.ABANDONED])
		self.assertIn(
			"No retry handler",
			durability.get_operation("wave3:unknown:1")["last_error"],
		)


class TestPostingSuccessThenRollback(PostingRetryTestCase):
	"""P0 (FIN-1/CONC-1) — a same-database ERP posting whose recording
	transaction rolls back after `run_durably` committed the ledger row.

	The durable ledger lives on its own connection, so it keeps its Resolved row
	while the Sales Invoice / Payment Entry - created on the caller's connection -
	rolls back with the caller. Before the fix, the retry read that Resolved row
	and returned `duplicate: True` naming an invoice that was never committed: the
	folio's charges stayed unstamped, so it could never invoice or close, and the
	failure was invisible to every reconciliation query (the ledger said Resolved).
	"""

	def test_success_then_rollback_reposts_a_real_invoice_not_a_phantom(self):
		self.world.charge(self.folio, "Room Charge", 100, 10, "roll1")
		# Commit the charge so the rollback below discards only the invoice the
		# posting raises, not the charge itself (which is the guest's real bill).
		frappe.db.commit()

		posting_service.post_folio_invoice(self.folio)

		# The request dies after the invoice posted but before commit - a later
		# checkout step throwing, a deadlock in the operational release. The invoice
		# and its posting-log row roll back; the durable ledger row does not.
		frappe.db.rollback()

		self.assertEqual(
			folio_invoices(self.folio), [], msg="the invoice should have rolled back"
		)
		op = durability.find_operations(
			property_name=self.world.property, operation="post_folio_invoice"
		)[0]
		self.assertEqual(
			op["queue_status"],
			durability.RESOLVED,
			msg="premise: the durable ledger survives the rollback as Resolved",
		)

		# The retry must produce a real, live invoice - not a phantom duplicate.
		result = posting_service.post_folio_invoice(self.folio)
		frappe.db.commit()

		invoices = folio_invoices(self.folio)
		self.assertEqual(
			len(invoices), 1, msg="the retry did not raise a real invoice for the charges"
		)
		self.assertFalse(
			result.get("duplicate"),
			msg="the retry returned a phantom duplicate instead of re-posting",
		)
		self.assertMoney(invoice_totals(invoices[0])["grand_total"], 110)
		self.assertTrue(
			frappe.get_all(
				"Folio Charge", filters={"parent": self.folio, "is_posted_to_erp": 1}, pluck="name"
			),
			msg="the charge rows must be stamped so the folio can close",
		)
