"""P1-10 and P2-4 — what the Sales Invoice actually says, and how often.

P1-10: the folio's tax never reached ERPNext. `resolve_charge_item()` looked up
a tax template and `_build_and_submit_invoice()` never used it, so a folio of
100 net + 10 tax posted an invoice with `total_taxes_and_charges = 0` and
`grand_total = 100`. Ten riyals of output VAT simply did not exist in the
ledger.

P2-4: the invoice idempotency key was `folio-invoice:{folio}` for the whole
life of the folio, so once one invoice had posted no later charge could ever
reach ERPNext — the second call returned the first invoice as a duplicate and
the new row stayed `is_posted_to_erp = 0` forever.

These tests raise real Sales Invoices against a real chart of accounts and read
the answers back from ERPNext, including its GL Entries. Asserting on the
document we just built would only prove we can build a document.
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from hospitality_pms.services import folio as folio_service
from hospitality_pms.services import posting as posting_service
from hospitality_pms.services.exceptions import ConfigurationError, PostingError
from hospitality_pms.tests.concurrency import Worker, assert_all_ran, run_workers
from hospitality_pms.tests.posting_world import (
	PostingWorld,
	folio_invoices,
	gl_amount,
	invoice_tax_rows,
	invoice_totals,
)

#: ERPNext rounds currency to the company's precision; comparisons are made to
#: the same place rather than by exact binary equality.
PRECISION = 2

#: How long the holder keeps the Guest lock once the waiter has asked for it.
LOCK_SETTLE_SECONDS = 1.5


# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------


def _ensure_customer_holder(barrier, guest: str, company: str) -> dict:
	"""Create the Customer and hold the Guest lock until the waiter is waiting."""
	import time

	from hospitality_pms.services.guests import ensure_customer

	customer = ensure_customer(guest, company)

	barrier.signal("holder_created")
	barrier.wait("waiter_entering")

	time.sleep(LOCK_SETTLE_SECONDS)
	frappe.db.commit()

	return {"customer": customer}


def _ensure_customer_waiter(barrier, guest: str, company: str) -> dict:
	"""Open a transaction first, then ask for the same guest's Customer."""
	from hospitality_pms.services.guests import ensure_customer

	# A pre-lock snapshot in which the guest has no customer yet.
	frappe.db.sql("select customer from `tabGuest` where name = %s", guest)

	barrier.wait("holder_created")
	barrier.signal("waiter_entering")

	customer = ensure_customer(guest, company)
	frappe.db.commit()

	return {"customer": customer}


class PostingTestCase(IntegrationTestCase):
	"""Shared world. Subclasses get a configured, postable property."""

	WORLD_CODE = "PO"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.world = PostingWorld(cls.__name__[:6].upper(), cls.WORLD_CODE)

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


class TestInvoiceTax(PostingTestCase):
	"""P1-10 — the invoice must carry the folio's tax."""

	WORLD_CODE = "TX"

	def test_invoice_carries_folio_tax(self):
		"""Scenario A: net 100, tax 10, ERP grand total 110."""
		self.world.charge(self.folio, "Room Charge", 100, 10, "a1")

		result = posting_service.post_folio_invoice(self.folio)
		totals = invoice_totals(result["erp_document"])

		self.assertEqual(totals["docstatus"], 1, msg="the invoice must be submitted")
		self.assertMoney(totals["net_total"], 100)
		self.assertMoney(
			totals["total_taxes_and_charges"],
			10,
			msg="the folio's tax did not reach the invoice",
		)
		self.assertMoney(totals["grand_total"], 110)
		self.assertEqual(totals["currency"], self.world.currency)

	def test_tax_reaches_the_configured_tax_account_in_the_ledger(self):
		"""The tax must be in the GL, not merely on the document.

		A tax row that produced no ledger entry would satisfy every assertion
		about the invoice and still leave the hotel's VAT liability unrecorded.
		"""
		self.world.charge(self.folio, "Room Charge", 100, 10, "gl1")

		result = posting_service.post_folio_invoice(self.folio)

		self.assertMoney(
			gl_amount("Sales Invoice", result["erp_document"], self.world.room_tax_account),
			10,
			msg="no GL credit reached the configured tax account",
		)

	def test_mixed_tax_invoice_matches_folio_total(self):
		"""Scenario B: two charge types at different rates, one invoice.

		200 + 20 at 10%, and 30 + 1.50 at 5%. A single invoice-level rate
		cannot produce 21.50 from a net of 230, which is what makes this the
		test that a one-template design would fail.
		"""
		self.world.charge(self.folio, "Room Charge", 200, 20, "b1")
		self.world.charge(self.folio, "Minibar", 30, 1.50, "b2")

		result = posting_service.post_folio_invoice(self.folio)
		totals = invoice_totals(result["erp_document"])

		self.assertMoney(totals["net_total"], 230)
		self.assertMoney(totals["total_taxes_and_charges"], 21.50)
		self.assertMoney(totals["grand_total"], 251.50)

	def test_mixed_tax_reaches_each_configured_account(self):
		"""Each rate's tax lands in its own account head, not pooled."""
		self.world.charge(self.folio, "Room Charge", 200, 20, "b3")
		self.world.charge(self.folio, "Minibar", 30, 1.50, "b4")

		result = posting_service.post_folio_invoice(self.folio)
		invoice = result["erp_document"]

		self.assertMoney(gl_amount("Sales Invoice", invoice, self.world.room_tax_account), 20)
		self.assertMoney(gl_amount("Sales Invoice", invoice, self.world.minibar_tax_account), 1.50)

	def test_zero_tax_charge_posts_without_tax(self):
		"""Scenario C: a line with no tax must not acquire one."""
		self.world.charge(self.folio, "Laundry", 40, 0, "c1")

		result = posting_service.post_folio_invoice(self.folio)
		totals = invoice_totals(result["erp_document"])

		self.assertMoney(totals["net_total"], 40)
		self.assertMoney(totals["total_taxes_and_charges"], 0)
		self.assertMoney(totals["grand_total"], 40)
		self.assertEqual(invoice_tax_rows(result["erp_document"]), [])

	def test_taxed_and_untaxed_lines_on_one_invoice(self):
		"""A mixed folio where one line is exempt."""
		self.world.charge(self.folio, "Room Charge", 100, 10, "c2")
		self.world.charge(self.folio, "Laundry", 40, 0, "c3")

		result = posting_service.post_folio_invoice(self.folio)
		totals = invoice_totals(result["erp_document"])

		self.assertMoney(totals["net_total"], 140)
		self.assertMoney(totals["total_taxes_and_charges"], 10)
		self.assertMoney(totals["grand_total"], 150)

	def test_fractional_tax_is_not_lost_to_rounding(self):
		"""1.50 and 0.05 must both survive to the ledger."""
		self.world.charge(self.folio, "Minibar", 30, 1.50, "f1")
		self.world.charge(self.folio, "Minibar", 1, 0.05, "f2")

		result = posting_service.post_folio_invoice(self.folio)
		totals = invoice_totals(result["erp_document"])

		self.assertMoney(totals["net_total"], 31)
		self.assertMoney(totals["total_taxes_and_charges"], 1.55)
		self.assertMoney(totals["grand_total"], 32.55)

	def test_invoice_total_is_not_rounded_away_from_the_folio(self):
		"""A fractional folio must produce a fractional receivable.

		ERPNext rounds `grand_total` to the nearest whole unit by default and
		sets `outstanding_amount` from the rounded figure. A folio of 52.50 then
		became a 52.00 receivable - banker's rounding takes .50 to even - so the
		guest's bill and the hotel's ledger disagreed by half a riyal on every
		fractional invoice, and no reconciliation could ever close.
		"""
		self.world.charge(self.folio, "Minibar", 50, 2.50, "rt1")

		result = posting_service.post_folio_invoice(self.folio)
		totals = invoice_totals(result["erp_document"])

		self.assertMoney(totals["grand_total"], 52.50)
		self.assertMoney(
			totals["outstanding_amount"],
			52.50,
			msg="the receivable was rounded away from what the guest actually owes",
		)

	def test_posting_the_invoice_matches_the_folio_total(self):
		"""The Wave-2 invariant, stated directly."""
		self.world.charge(self.folio, "Room Charge", 200, 20, "i1")
		self.world.charge(self.folio, "Minibar", 30, 1.50, "i2")

		result = posting_service.post_folio_invoice(self.folio)

		self.assertMoney(
			invoice_totals(result["erp_document"])["grand_total"],
			flt(frappe.db.get_value("Guest Folio", self.folio, "total_charges")),
		)


class TestTaxConfigurationFailures(PostingTestCase):
	"""Posting must refuse rather than post a different number."""

	WORLD_CODE = "TF"

	def test_taxed_charge_with_no_tax_account_is_refused(self):
		"""A folio line bearing tax that maps to no tax head cannot post.

		Posting it without the tax would silently drop the money - which is
		exactly P1-10. Posting it against a guessed account would be worse.
		"""
		# Laundry is mapped without a tax template, but carries tax here.
		self.world.charge(self.folio, "Laundry", 40, 4, "n1")

		with self.assertRaises(ConfigurationError):
			posting_service.post_folio_invoice(self.folio)

		self.assertNoPartialPosting()

	def test_multi_head_tax_template_is_refused(self):
		"""One tax figure per folio line cannot be split across several heads.

		Apportioning it would be inventing an accounting allocation the folio
		never recorded, so the configuration is refused by name instead.
		"""
		multi = self.world.fixtures.multi_row_tax_template(
			self.world.company,
			"Split VAT",
			[self.world.room_tax_account, self.world.minibar_tax_account],
		)
		frappe.db.set_value(
			"Charge Item Map",
			frappe.db.get_value(
				"Charge Item Map",
				{"parent": self.world.profile, "charge_type": "Room Charge"},
				"name",
			),
			"tax_template",
			multi,
			update_modified=False,
		)
		frappe.clear_document_cache("Posting Profile", self.world.profile)
		frappe.db.commit()

		try:
			self.world.charge(self.folio, "Room Charge", 100, 10, "n2")

			with self.assertRaises(ConfigurationError) as caught:
				posting_service.post_folio_invoice(self.folio)

			self.assertIn(multi, str(caught.exception), msg="the refusal must name the template")
			self.assertNoPartialPosting()
		finally:
			frappe.db.set_value(
				"Charge Item Map",
				frappe.db.get_value(
					"Charge Item Map",
					{"parent": self.world.profile, "charge_type": "Room Charge"},
					"name",
				),
				"tax_template",
				self.world.room_tax_template,
				update_modified=False,
			)
			frappe.clear_document_cache("Posting Profile", self.world.profile)
			frappe.db.commit()

	def assertNoPartialPosting(self):
		"""A refused posting must leave no invoice and no posted rows."""
		frappe.db.rollback()

		self.assertEqual(folio_invoices(self.folio), [])
		self.assertEqual(
			frappe.get_all(
				"Folio Charge", filters={"parent": self.folio, "is_posted_to_erp": 1}, pluck="name"
			),
			[],
		)


class TestPostingBatches(PostingTestCase):
	"""P2-4 — one immutable batch of rows, one invoice; later rows get another."""

	WORLD_CODE = "PB"

	def test_retry_same_invoice_batch_is_idempotent(self):
		"""Scenario F: posting the same batch twice yields one invoice."""
		self.world.charge(self.folio, "Room Charge", 100, 10, "r1")

		first = posting_service.post_folio_invoice(self.folio)
		second = posting_service.post_folio_invoice(self.folio)

		self.assertEqual(first["erp_document"], second["erp_document"])
		self.assertTrue(second["duplicate"])
		self.assertEqual(len(folio_invoices(self.folio)), 1)

	def test_late_charge_creates_supplementary_invoice(self):
		"""Scenario E: reopen, add an authorised late charge, post again."""
		self.world.charge(self.folio, "Room Charge", 100, 10, "s1")
		first = posting_service.post_folio_invoice(self.folio)

		folio_service.transition(self.folio, folio_service.UNDER_REVIEW, reason="Late charge")
		self.world.charge(self.folio, "Minibar", 50, 2.50, "s2")

		second = posting_service.post_folio_invoice(self.folio)

		self.assertNotEqual(
			second["erp_document"],
			first["erp_document"],
			msg="the late charge was swallowed by the original invoice's key",
		)
		self.assertFalse(second["duplicate"])

		# The first invoice is untouched.
		self.assertMoney(invoice_totals(first["erp_document"])["grand_total"], 110)
		self.assertMoney(invoice_totals(second["erp_document"])["grand_total"], 52.50)

		# And the late row points at the supplementary invoice, not the first.
		late = frappe.db.get_value(
			"Folio Charge",
			{"parent": self.folio, "charge_type": "Minibar"},
			["is_posted_to_erp", "sales_invoice"],
			as_dict=True,
		)
		self.assertEqual(late["is_posted_to_erp"], 1)
		self.assertEqual(late["sales_invoice"], second["erp_document"])

	def test_retry_supplementary_batch_is_idempotent(self):
		self.world.charge(self.folio, "Room Charge", 100, 10, "t1")
		posting_service.post_folio_invoice(self.folio)

		folio_service.transition(self.folio, folio_service.UNDER_REVIEW, reason="Late charge")
		self.world.charge(self.folio, "Minibar", 50, 2.50, "t2")

		second = posting_service.post_folio_invoice(self.folio)
		third = posting_service.post_folio_invoice(self.folio)

		self.assertEqual(second["erp_document"], third["erp_document"])
		self.assertEqual(len(folio_invoices(self.folio)), 2)

	def test_folio_posted_total_equals_sum_of_erp_invoice_totals(self):
		"""The cross-cutting invariant, across a supplementary batch."""
		self.world.charge(self.folio, "Room Charge", 200, 20, "u1")
		posting_service.post_folio_invoice(self.folio)

		folio_service.transition(self.folio, folio_service.UNDER_REVIEW, reason="Late charge")
		self.world.charge(self.folio, "Minibar", 30, 1.50, "u2")
		posting_service.post_folio_invoice(self.folio)

		erp_total = sum(flt(invoice_totals(i)["grand_total"]) for i in folio_invoices(self.folio))

		self.assertMoney(
			erp_total, flt(frappe.db.get_value("Guest Folio", self.folio, "total_charges"))
		)

	def test_each_invoice_carries_only_its_own_rows(self):
		self.world.charge(self.folio, "Room Charge", 100, 10, "v1")
		first = posting_service.post_folio_invoice(self.folio)

		folio_service.transition(self.folio, folio_service.UNDER_REVIEW, reason="Late charge")
		self.world.charge(self.folio, "Minibar", 50, 2.50, "v2")
		second = posting_service.post_folio_invoice(self.folio)

		for invoice, expected_rows in ((first["erp_document"], 1), (second["erp_document"], 1)):
			self.assertEqual(
				len(frappe.get_all("Sales Invoice Item", filters={"parent": invoice})),
				expected_rows,
			)

	def test_posting_with_nothing_new_returns_the_existing_invoice(self):
		"""Nothing left to post is a no-op, not an error and not a new invoice."""
		self.world.charge(self.folio, "Room Charge", 100, 10, "w1")
		first = posting_service.post_folio_invoice(self.folio)

		again = posting_service.post_folio_invoice(self.folio)

		self.assertTrue(again["duplicate"])
		self.assertEqual(again["erp_document"], first["erp_document"])

	def test_folio_with_no_charges_still_refuses(self):
		with self.assertRaises(PostingError):
			posting_service.post_folio_invoice(self.folio)


class TestPostingParty(PostingTestCase):
	"""Part 9 — the Guest/Customer boundary is unchanged by this wave."""

	WORLD_CODE = "PC"

	def test_customer_is_created_only_when_financially_needed(self):
		"""A folio with no posting creates no Customer; posting creates one."""
		self.assertIsNone(
			frappe.db.get_value("Guest", self.world.guest, "customer"),
			msg="a Customer existed before any financial document was raised",
		)

		self.world.charge(self.folio, "Room Charge", 100, 10, "p1")
		result = posting_service.post_folio_invoice(self.folio)

		customer = frappe.db.get_value("Guest", self.world.guest, "customer")

		self.assertTrue(customer)
		self.assertEqual(
			frappe.db.get_value("Sales Invoice", result["erp_document"], "customer"), customer
		)

	def test_second_posting_reuses_the_same_customer(self):
		self.world.charge(self.folio, "Room Charge", 100, 10, "p2")
		posting_service.post_folio_invoice(self.folio)

		customer = frappe.db.get_value("Guest", self.world.guest, "customer")

		folio_service.transition(self.folio, folio_service.UNDER_REVIEW, reason="Late charge")
		self.world.charge(self.folio, "Minibar", 50, 2.50, "p3")
		second = posting_service.post_folio_invoice(self.folio)

		self.assertEqual(
			frappe.db.get_value("Sales Invoice", second["erp_document"], "customer"), customer
		)
		self.assertEqual(
			frappe.db.count("Customer", {"customer_name": frappe.db.get_value("Guest", self.world.guest, "guest_name")}),
			1,
			msg="posting created a duplicate Customer for the same guest",
		)

	def test_concurrent_postings_create_one_customer(self):
		"""Two processes invoicing the same guest must not each create a Customer.

		`ensure_customer` locks the Guest and then re-reads its `customer` link
		with a plain read, which under REPEATABLE READ is answered from the
		snapshot taken before the lock was granted (N1). The waiter therefore
		still sees no customer, and both create one - leaving the guest with two
		receivable accounts and the hotel's AR split across them.
		"""
		# Its own guest: the workers commit, so a Customer created here would
		# otherwise still be attached to the shared guest when the next test
		# asserts that none exists yet.
		guest = self.world.fixtures.guest("Racer")
		frappe.db.commit()

		results = run_workers(
			[
				Worker(
					f"{__name__}._ensure_customer_holder",
					{"guest": guest, "company": self.world.company},
				),
				Worker(
					f"{__name__}._ensure_customer_waiter",
					{"guest": guest, "company": self.world.company},
				),
			]
		)
		assert_all_ran(results)

		guest_name = frappe.db.get_value("Guest", guest, "guest_name")

		self.assertEqual(
			frappe.db.count("Customer", {"customer_name": guest_name}),
			1,
			msg=f"the guest ended with more than one Customer; workers returned {results}",
		)

		# One Customer is not enough on its own: ERPNext names a Customer after
		# the guest, so a second insert would collide on the primary key and
		# raise. That leaves exactly one Customer and a posting that failed,
		# which is not the guarantee this function is supposed to give its
		# callers - the invoice would simply not be raised.
		self.assertEqual(
			[r["status"] for r in results],
			["committed", "committed"],
			msg=f"a caller was refused a Customer that exists; got {results}",
		)
		self.assertEqual(
			results[0]["result"]["customer"],
			results[1]["result"]["customer"],
			msg=f"the two callers were given different Customers; got {results}",
		)

	def test_posting_uses_the_property_company_not_a_caller_supplied_one(self):
		"""Part 10 — company and profile come from the record, never the caller."""
		self.world.charge(self.folio, "Room Charge", 100, 10, "p4")
		result = posting_service.post_folio_invoice(self.folio)

		self.assertEqual(
			frappe.db.get_value("Sales Invoice", result["erp_document"], "company"),
			self.world.company,
		)

	def test_a_property_without_a_profile_cannot_borrow_another_ones(self):
		"""Posting resolves the profile from the record's own property.

		A fallback to "some active profile" would let one property's revenue
		land in another's company and accounts, which is the cross-property
		boundary Wave 1 established and this wave must not quietly reopen.
		"""
		other = self.world.fixtures.property("NP", require_id_at_check_in=0)
		other_folio = self.world.fixtures.folio(other, self.world.guest)
		frappe.db.commit()

		folio_service.post_charge(
			other_folio, "Room Charge", "unmapped property", 100, idempotency_key="PC:np1"
		)

		with self.assertRaises(ConfigurationError) as caught:
			posting_service.post_folio_invoice(other_folio)

		self.assertIn(other, str(caught.exception))
		self.assertEqual(folio_invoices(other_folio), [])

	def test_invoice_posting_date_is_the_folio_business_date(self):
		"""Part 11 — the accounting date is the business date, not `nowdate()`."""
		business_date = frappe.db.get_value("Property", self.world.property, "business_date")

		self.world.charge(self.folio, "Room Charge", 100, 10, "p5")
		result = posting_service.post_folio_invoice(self.folio)

		self.assertEqual(
			str(frappe.db.get_value("Sales Invoice", result["erp_document"], "posting_date")),
			str(business_date),
		)


class TestNegativeFolioActivity(PostingTestCase):
	"""F-FIN5 — discounts and reversals must reach the ledger under allow_negative_rates=0.

	A folio credit (a service-recovery Discount, stored negative; a reversal
	Adjustment, negative) reached the Sales Invoice as an item with a negative
	`rate`, which ERPNext refuses when `Selling Settings.allow_negative_rates_for_items`
	is 0. The folio then had no way to invoice or close.

	The fix keeps the invariant that the invoice equals the folio to the fils, but
	represents each credit the way ERPNext accepts it: a net-positive folio's
	credits become an invoice-level discount so item rates stay positive, and a
	reversal of an already-invoiced charge becomes a credit note against that
	invoice. States that cannot be one document are refused with a clear error
	rather than failing deep in ERPNext's submit.
	"""

	WORLD_CODE = "NG"

	def test_selling_settings_forbid_negative_rates(self):
		"""The precondition the whole finding rests on, asserted, not assumed."""
		self.assertEqual(
			frappe.db.get_single_value("Selling Settings", "allow_negative_rates_for_items"),
			0,
			msg="this suite only proves anything while ERPNext forbids negative item rates",
		)

	def test_discount_on_a_net_positive_folio_posts_and_matches_the_folio(self):
		"""A service-recovery Discount posts as a discount, not a negative-rate item."""
		self.world.charge(self.folio, "Room Charge", 100, 10, "d1")
		# A Discount is entered positive and stored negative (CREDIT_CHARGE_TYPES).
		self.world.charge(self.folio, "Discount", 20, 0, "d2")

		folio_total = flt(frappe.db.get_value("Guest Folio", self.folio, "total_charges"))
		self.assertMoney(folio_total, 90, msg="folio should be 100 + 10 tax - 20 discount")

		result = posting_service.post_folio_invoice(self.folio)
		totals = invoice_totals(result["erp_document"])

		self.assertEqual(totals["docstatus"], 1)
		self.assertMoney(totals["grand_total"], folio_total)
		self.assertMoney(totals["grand_total"], 90)
		# The room's output VAT still reaches its account in full; the discount
		# carried none and must not have invented or eaten any.
		self.assertMoney(
			gl_amount("Sales Invoice", result["erp_document"], self.world.room_tax_account),
			10,
			msg="the discount must not disturb the folio's output VAT",
		)

	def test_reversing_an_already_invoiced_charge_posts_as_a_credit_note(self):
		"""A reversal of a posted charge becomes an is_return credit note against it."""
		self.world.charge(self.folio, "Minibar", 50, 2.50, "r1")
		first = posting_service.post_folio_invoice(self.folio)
		original_row = frappe.db.get_value(
			"Folio Charge", {"parent": self.folio, "charge_type": "Minibar"}, "name"
		)

		folio_service.transition(self.folio, folio_service.UNDER_REVIEW, reason="Correction")
		folio_service.reverse_charge(self.folio, original_row, "Charged in error")

		second = posting_service.post_folio_invoice(self.folio)
		credit = frappe.db.get_value(
			"Sales Invoice",
			second["erp_document"],
			["docstatus", "is_return", "return_against", "grand_total"],
			as_dict=True,
		)

		self.assertEqual(credit["docstatus"], 1)
		self.assertEqual(credit["is_return"], 1, msg="a reversal must post as a credit note")
		self.assertEqual(
			credit["return_against"],
			first["erp_document"],
			msg="the credit note must name the invoice it reverses",
		)
		self.assertMoney(credit["grand_total"], -52.50)
		# The reversed output VAT is credited back at its own account.
		self.assertMoney(
			gl_amount("Sales Invoice", second["erp_document"], self.world.minibar_tax_account),
			-2.50,
		)

		# The two documents net to nothing, which is what the folio now says.
		net = sum(flt(invoice_totals(i)["grand_total"]) for i in folio_invoices(self.folio))
		self.assertMoney(net, 0)
		self.assertMoney(net, flt(frappe.db.get_value("Guest Folio", self.folio, "total_charges")))

	def test_reversal_before_any_posting_nets_out_in_one_invoice(self):
		"""A charge reversed before it was ever invoiced still posts (net zero)."""
		charge = self.world.charge(self.folio, "Minibar", 50, 2.50, "n1")

		folio_service.reverse_charge(self.folio, charge["row"], "Never consumed")

		self.assertMoney(frappe.db.get_value("Guest Folio", self.folio, "total_charges"), 0)

		result = posting_service.post_folio_invoice(self.folio)
		totals = invoice_totals(result["erp_document"])

		self.assertEqual(totals["docstatus"], 1)
		self.assertMoney(totals["grand_total"], 0)
		# Both rows are accounted for, so neither lingers for a later invoice.
		self.assertEqual(
			frappe.get_all(
				"Folio Charge",
				filters={"parent": self.folio, "is_posted_to_erp": 0},
				pluck="name",
			),
			[],
		)

	def test_credit_exceeding_charges_is_refused_early(self):
		"""A batch whose credits exceed its charges cannot be one positive invoice."""
		self.world.charge(self.folio, "Laundry", 50, 0, "x1")
		self.world.charge(self.folio, "Discount", 100, 0, "x2")

		with self.assertRaises(PostingError):
			posting_service.post_folio_invoice(self.folio)

		self._assert_no_partial()

	def test_reversal_mixed_with_new_charges_is_refused_early(self):
		"""Reversing a posted charge while adding new ones needs two documents, so refuse."""
		self.world.charge(self.folio, "Minibar", 50, 2.50, "m1")
		posting_service.post_folio_invoice(self.folio)
		posted_row = frappe.db.get_value(
			"Folio Charge", {"parent": self.folio, "charge_type": "Minibar"}, "name"
		)

		folio_service.transition(self.folio, folio_service.UNDER_REVIEW, reason="Correction")
		folio_service.reverse_charge(self.folio, posted_row, "Charged in error")
		self.world.charge(self.folio, "Room Charge", 200, 20, "m2")

		with self.assertRaises(PostingError):
			posting_service.post_folio_invoice(self.folio)

		frappe.db.rollback()

	def _assert_no_partial(self):
		frappe.db.rollback()
		self.assertEqual(folio_invoices(self.folio), [])
		self.assertEqual(
			frappe.get_all(
				"Folio Charge", filters={"parent": self.folio, "is_posted_to_erp": 1}, pluck="name"
			),
			[],
		)


class TestPostingProfileSetupValidation(PostingTestCase):
	"""The tax misconfiguration that stops posting is refused at *setup*.

	`_resolve_tax_head` refuses an unresolvable tax template at invoice-build
	time - during checkout or Night Audit - long after the profile was saved and
	away from whoever can fix it. `PostingProfile.validate` runs the *same*
	resolution when the profile is saved, so the person configuring the mapping
	is the person who sees the error, and the day's audit is not what discovers
	it. It shares posting's own `resolve_single_tax_head`, so setup accepts every
	mapping posting would accept and rejects only what posting would refuse.
	"""

	WORLD_CODE = "PV"

	def _profile(self, code: str, charge_map: list[dict], default_tax_template: str | None = None):
		"""Build (not insert) a throwaway Posting Profile on the world's property.

		Inactive, so it never competes with the world's own postable profile for
		the property; the validation under test does not depend on `is_active` of
		the profile. Rolled back by `tearDown`, so it is not tracked.
		"""
		return frappe.get_doc(
			{
				"doctype": "Posting Profile",
				"profile_code": code,
				"profile_name": f"Setup validation {code}",
				"property": self.world.property,
				"company": self.world.company,
				"is_active": 0,
				"default_item": self.world.room_item,
				"default_tax_template": default_tax_template,
				"default_income_account": frappe.db.get_value(
					"Account", {"company": self.world.company, "is_group": 0, "root_type": "Income"}, "name"
				),
				"default_cost_center": frappe.db.get_value(
					"Cost Center", {"company": self.world.company, "is_group": 0}, "name"
				),
				"charge_items": [{"is_active": 1, **row} for row in charge_map],
			}
		)

	def test_setup_refuses_active_mapping_with_unresolvable_tax_template(self):
		"""A charge type mapped to a multi-head template cannot post, so save refuses.

		This is the setup-time face of `test_multi_head_tax_template_is_refused`:
		the very template posting refuses at invoice-build is refused here at save,
		naming the template, before any charge is ever posted against it.
		"""
		multi = self.world.fixtures.multi_row_tax_template(
			self.world.company,
			"PV Split VAT",
			[self.world.room_tax_account, self.world.minibar_tax_account],
		)
		doc = self._profile(
			"PV-BAD",
			[{"charge_type": "Minibar", "item": self.world.minibar_item, "tax_template": multi}],
		)

		with self.assertRaises(ConfigurationError) as caught:
			doc.insert(ignore_permissions=True)

		self.assertIn(multi, str(caught.exception), msg="the refusal must name the template")
		self.assertFalse(frappe.db.exists("Posting Profile", "PV-BAD"))

	def test_setup_refuses_unresolvable_profile_default_tax_template(self):
		"""The profile default is used for unmapped charge types, so it too is checked."""
		multi = self.world.fixtures.multi_row_tax_template(
			self.world.company,
			"PV Split Default VAT",
			[self.world.room_tax_account, self.world.minibar_tax_account],
		)
		doc = self._profile(
			"PV-BADDEF",
			[{"charge_type": "Laundry", "item": self.world.laundry_item}],
			default_tax_template=multi,
		)

		with self.assertRaises(ConfigurationError) as caught:
			doc.insert(ignore_permissions=True)

		self.assertIn(multi, str(caught.exception))
		self.assertFalse(frappe.db.exists("Posting Profile", "PV-BADDEF"))

	def test_setup_accepts_single_head_tax_mapping(self):
		"""Positive control: a resolvable single-head mapping saves without complaint."""
		doc = self._profile(
			"PV-OK",
			[
				{
					"charge_type": "Minibar",
					"item": self.world.minibar_item,
					"tax_template": self.world.minibar_tax_template,
				}
			],
		)

		doc.insert(ignore_permissions=True)

		self.assertTrue(frappe.db.exists("Posting Profile", "PV-OK"))

	def test_setup_accepts_mapping_that_carries_no_tax(self):
		"""No false positive: a charge type with no tax template needs none.

		A Laundry line that carries no tax posts without a template (the runtime
		rule behind `test_taxed_charge_with_no_tax_account_is_refused`), so
		requiring one at setup would reject a legitimate, postable configuration.
		"""
		doc = self._profile(
			"PV-NOTAX",
			[{"charge_type": "Laundry", "item": self.world.laundry_item}],
		)

		doc.insert(ignore_permissions=True)

		self.assertTrue(frappe.db.exists("Posting Profile", "PV-NOTAX"))
