"""Guest Folio regression suite - the financial boundary.

Covers:

* **P1-1** money may only be created through an approved financial service,
  never by appending a child row to the folio document.
* **N4** an ordinary charge type may not carry a negative amount; negative
  money belongs to the privileged adjustment / reversal / discount workflows.
* **N5** the idempotency key is unique in the database, not merely checked in
  application code.
* **P2-3** a retried request carrying the same operation key posts once, and a
  genuinely new operation still posts.
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt, nowdate

from hospitality_pms.services import folio as folio_service
from hospitality_pms.services.exceptions import (
	FolioError,
	HospitalityPMSError,
	PermissionDeniedError,
)
from hospitality_pms.tests.concurrency import Worker, assert_all_ran, run_workers
from hospitality_pms.tests.fixtures import Fixtures

FOLIO = "Guest Folio"


def _charge_row(**overrides) -> dict:
	"""A complete charge row, so a refusal is the guard and not a missing field.

	The sweep's first attempt failed only on a `MandatoryError` for
	`charge_date` / `business_date`, which reads like a control but is not one.
	Supplying every field is what makes the assertion meaningful.
	"""
	return {
		"charge_date": nowdate(),
		"business_date": nowdate(),
		"charge_type": "Room Charge",
		"description": "fabricated",
		"quantity": 1,
		"unit_price": 500,
		"amount": 500,
		"tax_amount": 0,
		"total_amount": 500,
		"payer": "Guest",
		**overrides,
	}


def _payment_row(**overrides) -> dict:
	return {
		"payment_date": nowdate(),
		"business_date": nowdate(),
		"payment_type": "Payment",
		"payment_method": "Cash",
		"amount": 10000,
		"payer": "Guest",
		**overrides,
	}


# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------


def _post_charge_holder(barrier, folio: str, key: str) -> dict:
	"""Post the charge and hold the folio lock until the waiter is inside too.

	Left to chance, the two processes rarely overlap: one finishes its whole
	transaction before the other starts, and the test passes without ever
	exercising the race. Holding the lock open until the waiter has committed
	to entering `post_charge` makes the overlap certain.
	"""
	import time

	frappe.db.sql("select name from `tabFolio Charge` where parent = %s", folio)

	result = folio_service.post_charge(folio, "Minibar", "concurrent", 75, idempotency_key=key)

	barrier.signal("holder_posted")
	barrier.wait("waiter_entering")

	time.sleep(1.5)
	frappe.db.commit()

	return result


def _post_charge_waiter(barrier, folio: str, key: str) -> dict:
	"""Open a transaction first, then post the same key behind the holder's lock."""
	# Snapshot established before the holder writes: the loser must not be able
	# to conclude "no row with this key" from it.
	frappe.db.sql("select name from `tabFolio Charge` where parent = %s", folio)

	barrier.wait("holder_posted")
	barrier.signal("waiter_entering")

	result = folio_service.post_charge(folio, "Minibar", "concurrent", 75, idempotency_key=key)
	frappe.db.commit()

	return result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGuestFolioBoundary(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()

		cls.fixtures = Fixtures("FOL")
		cls.property = cls.fixtures.property("FO")
		cls.guest = cls.fixtures.guest("Folio")
		cls.agent = cls.fixtures.user(
			"agent", ["Front Office Agent"], properties=[cls.property]
		)
		cls.manager = cls.fixtures.user(
			"fomgr", ["Front Office Manager"], properties=[cls.property]
		)

		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		cls.fixtures.teardown()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")
		self.folio = self.fixtures.folio(self.property, self.guest)
		frappe.db.commit()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def _charges(self) -> list[dict]:
		return frappe.get_all(
			"Folio Charge",
			filters={"parent": self.folio},
			fields=["name", "amount", "charge_type", "idempotency_key", "posted_by"],
		)

	def _payments(self) -> list[dict]:
		return frappe.get_all(
			"Folio Payment",
			filters={"parent": self.folio},
			fields=["name", "amount", "payment_type", "idempotency_key", "received_by"],
		)

	# -- P1-1 -----------------------------------------------------------

	def test_direct_child_row_append_is_refused(self):
		"""A charge appended to the document, not posted through the service."""
		frappe.set_user(self.agent)

		doc = frappe.get_doc(FOLIO, self.folio)
		doc.append("charges", _charge_row())

		with self.assertRaises(PermissionDeniedError):
			doc.save()

		frappe.db.rollback()
		self.assertEqual(self._charges(), [])

	def test_direct_payment_row_append_is_refused(self):
		frappe.set_user(self.agent)

		doc = frappe.get_doc(FOLIO, self.folio)
		doc.append("payments", _payment_row())

		with self.assertRaises(PermissionDeniedError):
			doc.save()

		frappe.db.rollback()
		self.assertEqual(self._payments(), [])

	def test_direct_append_is_refused_for_an_administrator_too(self):
		"""The boundary is about the path taken, not about who is asking.

		An administrator has every permission there is and still must not
		manufacture a charge outside the service, because it is the service -
		not the permission - that supplies the actor, the business date, the
		audit row and the idempotency key.
		"""
		doc = frappe.get_doc(FOLIO, self.folio)
		doc.append("charges", _charge_row(charge_type="Discount", amount=999))

		with self.assertRaises(PermissionDeniedError):
			doc.save()

		frappe.db.rollback()
		self.assertEqual(self._charges(), [])

	def test_backdated_direct_append_is_refused(self):
		"""The sweep's exact shape: a row back-dated into a closed business date."""
		frappe.set_user(self.agent)

		doc = frappe.get_doc(FOLIO, self.folio)
		doc.append("charges", _charge_row(business_date="2026-08-01", amount=-500))

		with self.assertRaises(PermissionDeniedError):
			doc.save()

		frappe.db.rollback()
		self.assertEqual(self._charges(), [])

	def test_nonfinancial_folio_edit_is_still_allowed(self):
		"""The folio must not become unwritable; only its money is protected."""
		frappe.set_user(self.agent)

		doc = frappe.get_doc(FOLIO, self.folio)
		doc.billing_instructions = "Bill to room"
		doc.save()

		frappe.db.commit()

		self.assertEqual(
			frappe.db.get_value(FOLIO, self.folio, "billing_instructions"), "Bill to room"
		)

	def test_service_posting_still_works_and_is_attributed(self):
		"""The approved path keeps working, with actor, audit and key intact."""
		frappe.set_user(self.agent)

		folio_service.post_charge(
			self.folio, "Minibar", "Two waters", 30, idempotency_key="op:test:1"
		)

		charges = self._charges()

		self.assertEqual(len(charges), 1)
		self.assertEqual(flt(charges[0]["amount"]), 30.0)
		self.assertEqual(charges[0]["posted_by"], self.agent)
		self.assertEqual(charges[0]["idempotency_key"], "op:test:1")

		self.assertTrue(
			frappe.db.exists("Folio Log", {"folio": self.folio, "action": "Charge posted: Minibar"}),
			msg="the approved path must still write its audit row",
		)

	# -- N4 -------------------------------------------------------------

	def test_negative_ordinary_charge_is_refused(self):
		"""A Front Office Agent may not post Room Charge -100."""
		frappe.set_user(self.agent)

		with self.assertRaises(FolioError):
			folio_service.post_charge(
				self.folio, "Room Charge", "negative", -100, idempotency_key="op:test:neg"
			)

		frappe.db.rollback()
		self.assertEqual(self._charges(), [])

	def test_negative_ordinary_charge_is_refused_for_a_manager_too(self):
		"""Elevated rank does not make an ordinary charge type signed.

		A manager who needs to reduce a balance has `post_adjustment` and
		`reverse_charge`, both of which demand a reason and leave a trail. A
		negative `Room Charge` would leave neither.
		"""
		frappe.set_user(self.manager)

		with self.assertRaises(FolioError):
			folio_service.post_charge(
				self.folio, "Room Charge", "negative", -100, idempotency_key="op:test:neg2"
			)

		frappe.db.rollback()

	def test_positive_ordinary_charge_is_accepted(self):
		frappe.set_user(self.agent)

		folio_service.post_charge(
			self.folio, "Room Charge", "one night", 100, idempotency_key="op:test:pos"
		)

		self.assertEqual(len(self._charges()), 1)

	def test_authorized_adjustment_may_reduce_the_balance(self):
		"""The privileged workflow that negative money is supposed to use."""
		frappe.set_user(self.manager)

		folio_service.post_adjustment(
			self.folio,
			-50,
			"Goodwill",
			"Guest complaint, approved by duty manager",
			idempotency_key="op:test:adj",
		)

		charges = self._charges()

		self.assertEqual(len(charges), 1)
		self.assertEqual(flt(charges[0]["amount"]), -50.0)
		self.assertEqual(charges[0]["charge_type"], "Adjustment")

	def test_adjustment_still_requires_an_elevated_role(self):
		frappe.set_user(self.agent)

		with self.assertRaises(PermissionDeniedError):
			folio_service.post_adjustment(
				self.folio, -50, "Goodwill", "no authority", idempotency_key="op:test:adj2"
			)

	def test_reversal_still_posts_its_negative_adjustment(self):
		"""N4 must not break the one path that legitimately writes a negative row."""
		frappe.set_user("Administrator")

		posted = folio_service.post_charge(
			self.folio, "Minibar", "Wrongly charged", 40, idempotency_key="op:test:rev"
		)

		folio_service.reverse_charge(self.folio, posted["row"], "Charged to the wrong folio")

		amounts = sorted(flt(row["amount"]) for row in self._charges())

		self.assertEqual(amounts, [-40.0, 40.0])
		self.assertEqual(flt(frappe.db.get_value(FOLIO, self.folio, "balance")), 0.0)

	def test_discount_is_still_stored_as_a_credit(self):
		"""A Discount entered positive is stored negative, as operators expect."""
		frappe.set_user(self.manager)

		folio_service.post_charge(
			self.folio, "Discount", "Loyalty", 25, idempotency_key="op:test:disc"
		)

		self.assertEqual(flt(self._charges()[0]["amount"]), -25.0)

	# -- N5 / P2-3 ------------------------------------------------------

	def test_retried_charge_request_posts_once(self):
		"""The same operation key twice - a lost response and a retry."""
		frappe.set_user(self.agent)

		first = folio_service.post_charge(
			self.folio, "Minibar", "Water", 75, idempotency_key="op:retry:1"
		)
		second = folio_service.post_charge(
			self.folio, "Minibar", "Water", 75, idempotency_key="op:retry:1"
		)

		self.assertFalse(first["duplicate"])
		self.assertTrue(second["duplicate"])
		self.assertEqual(first["row"], second["row"])

		self.assertEqual(len(self._charges()), 1)
		self.assertEqual(flt(frappe.db.get_value(FOLIO, self.folio, "total_charges")), 75.0)

	def test_new_operation_key_posts_a_second_identical_charge(self):
		"""Two genuinely separate minibar waters are two charges, not one.

		This is why identity is an explicit operation key rather than a hash of
		the payload: the two requests are byte-identical apart from the key.
		"""
		frappe.set_user(self.agent)

		folio_service.post_charge(
			self.folio, "Minibar", "Water", 75, idempotency_key="op:distinct:1"
		)
		folio_service.post_charge(
			self.folio, "Minibar", "Water", 75, idempotency_key="op:distinct:2"
		)

		self.assertEqual(len(self._charges()), 2)
		self.assertEqual(flt(frappe.db.get_value(FOLIO, self.folio, "total_charges")), 150.0)

	def test_duplicate_financial_key_is_database_safe(self):
		"""The last line of defence: the database itself refuses the second row.

		Application-level read-before-insert is not enough, because two
		transactions can both read "no such key" before either has committed.
		Written with raw SQL so it tests the constraint and nothing else.
		"""
		frappe.set_user("Administrator")

		folio_service.post_charge(
			self.folio, "Minibar", "Water", 75, idempotency_key="op:unique:1"
		)
		frappe.db.commit()

		row = self._charges()[0]

		with self.assertRaises(Exception) as caught:
			frappe.db.sql(
				"""
				insert into `tabFolio Charge`
					(name, parent, parenttype, parentfield, idx, creation, modified, owner,
					 modified_by, charge_date, business_date, charge_type, description,
					 quantity, unit_price, amount, tax_amount, total_amount, idempotency_key)
				select %(name)s, parent, parenttype, parentfield, idx + 1, now(), now(), owner,
					 modified_by, charge_date, business_date, charge_type, description,
					 quantity, unit_price, amount, tax_amount, total_amount, idempotency_key
				from `tabFolio Charge` where name = %(source)s
				""",
				{"name": frappe.generate_hash(length=10), "source": row["name"]},
			)

		self.assertTrue(
			frappe.db.is_unique_key_violation(caught.exception),
			msg=f"expected the unique index to reject the row, got {caught.exception!r}",
		)

		frappe.db.rollback()

	def test_duplicate_payment_key_is_database_safe(self):
		frappe.set_user("Administrator")

		folio_service.post_payment(
			self.folio, 200, "Cash", idempotency_key="op:unique:pay"
		)
		frappe.db.commit()

		row = self._payments()[0]

		with self.assertRaises(Exception) as caught:
			frappe.db.sql(
				"""
				insert into `tabFolio Payment`
					(name, parent, parenttype, parentfield, idx, creation, modified, owner,
					 modified_by, payment_date, business_date, payment_type, payment_method,
					 amount, idempotency_key)
				select %(name)s, parent, parenttype, parentfield, idx + 1, now(), now(), owner,
					 modified_by, payment_date, business_date, payment_type, payment_method,
					 amount, idempotency_key
				from `tabFolio Payment` where name = %(source)s
				""",
				{"name": frappe.generate_hash(length=10), "source": row["name"]},
			)

		self.assertTrue(
			frappe.db.is_unique_key_violation(caught.exception),
			msg=f"expected the unique index to reject the row, got {caught.exception!r}",
		)

		frappe.db.rollback()

	def test_the_same_key_on_another_folio_is_a_different_operation(self):
		"""Uniqueness is per folio, so two guests' keys cannot collide."""
		frappe.set_user("Administrator")

		other = self.fixtures.folio(self.property, self.guest, folio_type="Split", parent_folio=self.folio)

		folio_service.post_charge(self.folio, "Minibar", "Water", 75, idempotency_key="op:shared")
		folio_service.post_charge(other, "Minibar", "Water", 75, idempotency_key="op:shared")

		self.assertEqual(len(self._charges()), 1)
		self.assertEqual(
			len(frappe.get_all("Folio Charge", filters={"parent": other})), 1
		)

	# -- P2-3, at the HTTP boundary where the defect actually lived --------

	def test_api_refuses_a_charge_with_no_operation_key(self):
		"""The endpoint must not invent an identity the caller did not give it.

		This is the whole of P2-3. The endpoint used to fall back to
		`manual:{folio}:{random}`, so the retry of a request whose response was
		lost arrived under a different key and posted a second charge.

		Two shapes a real client can produce: the parameter left out, and the
		parameter sent empty. Neither may reach the folio.
		"""
		from hospitality_pms.api import folio as folio_api

		frappe.set_user(self.agent)

		with self.assertRaises(TypeError):
			folio_api.post_charge(
				folio=self.folio, charge_type="Minibar", description="Water", amount=75
			)

		with self.assertRaises(HospitalityPMSError):
			folio_api.post_charge(
				folio=self.folio,
				charge_type="Minibar",
				description="Water",
				amount=75,
				idempotency_key="",
			)

		self.assertEqual(self._charges(), [])

	def test_api_refuses_a_payment_with_no_operation_key(self):
		from hospitality_pms.api import folio as folio_api

		frappe.set_user(self.agent)

		with self.assertRaises(HospitalityPMSError):
			folio_api.post_payment(
				folio=self.folio, amount=50, payment_method="Cash", idempotency_key="   "
			)

		self.assertEqual(self._payments(), [])

	def test_api_retry_with_the_same_operation_key_posts_once(self):
		"""The lost-response scenario, end to end through the endpoint."""
		from hospitality_pms.api import folio as folio_api

		frappe.set_user(self.agent)

		key = "charge:9f2b41c8-1d6e-4a55-9d0a-7c1f2e3b4a5d"

		first = folio_api.post_charge(
			folio=self.folio,
			charge_type="Minibar",
			description="Water",
			amount=75,
			idempotency_key=key,
		)
		# The client never saw `first`; it retries the identical request.
		second = folio_api.post_charge(
			folio=self.folio,
			charge_type="Minibar",
			description="Water",
			amount=75,
			idempotency_key=key,
		)

		self.assertEqual(first["row"], second["row"])
		self.assertTrue(second["duplicate"])

		self.assertEqual(len(self._charges()), 1)
		self.assertEqual(flt(frappe.db.get_value(FOLIO, self.folio, "total_charges")), 75.0)

	def test_api_rejects_an_overlong_operation_key(self):
		"""A key longer than the column would be truncated into a collision."""
		from hospitality_pms.api import folio as folio_api

		frappe.set_user(self.agent)

		with self.assertRaises(HospitalityPMSError):
			folio_api.post_charge(
				folio=self.folio,
				charge_type="Minibar",
				description="Water",
				amount=75,
				idempotency_key="k" * 200,
			)

	def test_concurrent_same_charge_key_posts_once(self):
		"""Two processes, one key: one row, and the loser reports the duplicate.

		Both halves matter. One row is the money guarantee. The loser
		*succeeding* and reporting `duplicate` is the retry guarantee - a
		client whose request was serialised behind an identical one must get
		the original result back, not a crash it will interpret as "not posted"
		and try again.
		"""
		frappe.db.commit()

		results = run_workers(
			[
				Worker(f"{__name__}._post_charge_holder", {"folio": self.folio, "key": "op:race:1"}),
				Worker(f"{__name__}._post_charge_waiter", {"folio": self.folio, "key": "op:race:1"}),
			]
		)
		assert_all_ran(results)

		self.assertEqual(
			len(self._charges()),
			1,
			msg=f"one key must produce one row; workers returned {results}",
		)
		self.assertEqual(flt(frappe.db.get_value(FOLIO, self.folio, "total_charges")), 75.0)

		self.assertEqual(
			[r["status"] for r in results],
			["committed", "committed"],
			msg=f"both callers must get an answer, not an error; got {results}",
		)

		duplicates = [r["result"]["duplicate"] for r in results]

		self.assertEqual(
			sorted(duplicates),
			[False, True],
			msg=f"exactly one caller should be told it posted; got {results}",
		)

		rows = {r["result"]["row"] for r in results}
		self.assertEqual(len(rows), 1, msg=f"both callers must be pointed at the same row; got {results}")
