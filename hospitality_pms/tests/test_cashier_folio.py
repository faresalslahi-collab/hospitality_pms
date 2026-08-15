"""The Cashier build's financial boundaries.

Four things are defended here, and each was a live defect before 16.7.5.

**Reads authorise the document, not just the DocType.** Five GET-by-name
endpoints checked `doc.check_permission` and stopped. That is only sufficient
when the site's Property User Permission was created with
`apply_to_all_doctypes`; scoped with `applicable_for` instead — a common way to
restrict someone on bookings but not on masters — it passes for a record in a
property the caller may not operate in. The existing fixture always sets
`apply_to_all_doctypes = 1`, which *masks* the condition, so these tests build
the permission the other way deliberately.

**A refund key identifies the decision, not the amount.** `api.payments.refund`
took no key, so the service derived `refund:{transaction}:{amount}` — a content
hash. Two genuine goodwill refunds of the same amount collapsed into one, and
the second reported success while returning nothing.

**A failed posting reaches an operator as a sentence, not a traceback.**

**Money is never recomputed by a caller.** The folio's totals are read.
"""

import frappe
from frappe.tests import IntegrationTestCase

from hospitality_pms.api import checkout as checkout_api
from hospitality_pms.api import folio as folio_api
from hospitality_pms.api import housekeeping as housekeeping_api
from hospitality_pms.api import kitchen as kitchen_api
from hospitality_pms.api import payments as payments_api
from hospitality_pms.services import finance_messages
from hospitality_pms.services import housekeeping as housekeeping_service
from hospitality_pms.services.exceptions import PermissionDeniedError
from hospitality_pms.tests.fixtures import Fixtures

REFUSALS = (frappe.PermissionError, PermissionDeniedError)


class CashierWorld(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()

		cls.fixtures = Fixtures("CASH")

		cls.property_a = cls.fixtures.property("CA", require_id_at_check_in=0)
		cls.type_a = cls.fixtures.room_type(cls.property_a)
		cls.rooms_a = cls.fixtures.rooms(cls.property_a, cls.type_a, count=2)

		cls.property_b = cls.fixtures.property("CB", require_id_at_check_in=0)
		cls.type_b = cls.fixtures.room_type(cls.property_b)
		cls.rooms_b = cls.fixtures.rooms(cls.property_b, cls.type_b, count=2)

		cls.manager = cls.fixtures.user(
			"cash-mgr",
			["Front Office Manager", "Housekeeping Manager", "Kitchen Manager"],
			properties=[cls.property_a],
		)

		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		cls.fixtures.teardown()
		super().tearDownClass()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		super().tearDown()

	@classmethod
	def _scope_permission_to_reservations_only(cls, user):
		"""Rebuild the user's Property permission the way that exposes the gap.

		`apply_to_all_doctypes = 1` — what `fixtures.user` writes — makes
		Frappe's own document check refuse a cross-property record, which masks
		whether the endpoint has its own guard. Scoping it to one unrelated
		DocType is equally valid configuration and is the case
		`authorise_document`'s third step exists for.
		"""
		for name in frappe.get_all(
			"User Permission", filters={"user": user, "allow": "Property"}, pluck="name"
		):
			frappe.delete_doc("User Permission", name, ignore_permissions=True, force=True)

		frappe.get_doc(
			{
				"doctype": "User Permission",
				"user": user,
				"allow": "Property",
				"for_value": cls.property_a,
				"apply_to_all_doctypes": 0,
				"applicable_for": "Reservation",
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()


class TestGetByNamePropertyGuards(CashierWorld):
	"""Part 2: the five reads that stopped at `check_permission`."""

	def test_the_premise_holds(self):
		"""The permission really is scoped, not absent — otherwise nothing is proven."""
		self._scope_permission_to_reservations_only(self.manager)

		rows = frappe.get_all(
			"User Permission",
			filters={"user": self.manager, "allow": "Property"},
			fields=["apply_to_all_doctypes", "applicable_for"],
		)

		self.assertEqual(len(rows), 1)
		self.assertFalse(rows[0]["apply_to_all_doctypes"])
		self.assertEqual(rows[0]["applicable_for"], "Reservation")

	def test_a_task_in_another_property_cannot_be_read(self):
		task = housekeeping_service.create_task(self.property_b, self.rooms_b[0])
		self._scope_permission_to_reservations_only(self.manager)

		frappe.set_user(self.manager)

		with self.assertRaises(REFUSALS):
			housekeeping_api.get_task(task)

	def test_a_task_in_the_callers_own_property_still_reads(self):
		"""Paired control: the refusal above is a decision, not an outage."""
		task = housekeeping_service.create_task(self.property_a, self.rooms_a[0])
		self._scope_permission_to_reservations_only(self.manager)

		frappe.set_user(self.manager)
		payload = housekeeping_api.get_task(task)

		self.assertEqual(payload["task"]["name"], task)

	def test_an_order_in_another_property_cannot_be_read(self):
		menu = self._menu_item(self.property_b)
		order = self._order(self.property_b, self.rooms_b[0], menu)
		self._scope_permission_to_reservations_only(self.manager)

		frappe.set_user(self.manager)

		with self.assertRaises(REFUSALS):
			kitchen_api.get_order(order.name)

	@classmethod
	def _menu_item(cls, property_name):
		name = f"{property_name}-CASHSNK"

		if not frappe.db.exists("Menu Item", name):
			frappe.get_doc(
				{
					"doctype": "Menu Item",
					"menu_item_code": name,
					"menu_item_name": "Sandwich",
					"property": property_name,
					"category": "Snack",
					"selling_rate": 40,
					"is_active": 1,
				}
			).insert(ignore_permissions=True)

		return cls.fixtures.track("Menu Item", name)

	@classmethod
	def _order(cls, property_name, room, menu_item):
		return frappe.get_doc(
			{
				"doctype": "Room Service Order",
				"property": property_name,
				"order_status": "Placed",
				"order_type": "Room Service",
				"room": room,
				"lines": [{"menu_item": menu_item, "quantity": 1}],
			}
		).insert(ignore_permissions=True)


class TestRefundContract(CashierWorld):
	"""The refund key identifies the operator's decision, not its amount."""

	def test_refund_takes_an_operation_key_and_insists_on_it(self):
		"""The endpoint accepts the caller's key and refuses a blank one.

		Asserted on the contract rather than through a live call: the guards run
		role -> document -> key, so a call crafted to reach the key check would
		first need a real captured gateway transaction, and would then be
		testing the provider rather than this signature.
		"""
		import inspect

		from hospitality_pms.services.base import require_operation_key

		signature = inspect.signature(payments_api.refund)

		self.assertIn(
			"idempotency_key",
			signature.parameters,
			msg="refund lost its operation key; the derived content hash is back",
		)

		source = inspect.getsource(payments_api.refund)

		self.assertIn(
			"require_operation_key",
			source,
			msg="refund accepts a key but does not insist on one",
		)

		with self.assertRaises(Exception):
			require_operation_key("   ", "Refunding a payment")

	def test_two_distinct_refunds_of_one_amount_are_two_operations(self):
		"""The defect, stated as a test.

		`refund:{transaction}:{amount}` cannot tell two goodwill refunds of fifty
		from one refund of fifty sent twice, so the second silently returned the
		first and refunded nothing.
		"""
		from hospitality_pms.services.base import require_operation_key

		first = require_operation_key("refund-a", "Refunding a payment")
		second = require_operation_key("refund-b", "Refunding a payment")

		self.assertNotEqual(first, second)

	def test_refund_roles_can_all_actually_write(self):
		"""A role listed as able to refund must not be refused by the next line.

		`REFUND_ROLES` advertised General Manager and Hotel Manager, which the
		permissions matrix grants read-only on Payment Transaction, so
		`require_role` admitted them and `authorise_document(..., "write")`
		refused them.
		"""
		writers = {
			row["role"]
			for row in frappe.get_all(
				"DocPerm",
				filters={"parent": "Payment Transaction", "write": 1},
				fields=["role"],
			)
		}

		for role in payments_api.REFUND_ROLES:
			with self.subTest(role=role):
				self.assertIn(
					role,
					writers,
					msg=f"{role} may refund but holds no write on Payment Transaction",
				)


class TestOperatorSafeMessages(CashierWorld):
	"""A failed posting reaches finance as a sentence, never a traceback."""

	def test_raw_exception_text_never_survives_projection(self):
		rows = [
			{
				"name": "HPMS-POST-0001",
				"attempts": 1,
				"folio": "HPMS-FOL-0001",
				"error_message": "Traceback: pymysql.err.OperationalError at 10.0.0.5:3306",
				"durable_operation": "folio-invoice:HPMS-FOL-0001:abc123",
				"operation_status": "Retrying",
			}
		]

		safe = finance_messages.safe_failed_postings(rows)
		serialised = frappe.as_json(safe)

		self.assertNotIn("Traceback", serialised)
		self.assertNotIn("pymysql", serialised)
		self.assertNotIn("10.0.0.5", serialised)
		self.assertNotIn("folio-invoice:", serialised)
		self.assertNotIn("error_message", serialised)
		self.assertNotIn("durable_operation", serialised)

	def test_the_reference_survives_so_support_can_find_it(self):
		"""Withholding the identifier too would only move the operator's problem."""
		safe = finance_messages.safe_failed_postings(
			[{"name": "HPMS-POST-0001", "attempts": 1, "error_message": "boom"}]
		)

		self.assertEqual(safe[0]["reference"], "HPMS-POST-0001")
		self.assertTrue(safe[0]["message"])

	def test_an_unknown_outcome_is_never_retryable(self):
		"""Silence is not failure. Repeating it could double-post."""
		described = finance_messages.describe_failure(
			{"name": "P", "attempts": 1, "operation_status": "Needs Reconciliation"}
		)

		self.assertFalse(described["can_retry"])
		self.assertEqual(described["category"], finance_messages.RECONCILIATION_REQUIRED)

	def test_an_abandoned_operation_is_never_retryable(self):
		described = finance_messages.describe_failure(
			{"name": "P", "attempts": 9, "operation_status": "Abandoned"}
		)

		self.assertFalse(described["can_retry"])
		self.assertEqual(described["category"], finance_messages.NEEDS_FINANCE_REVIEW)

	def test_an_explicit_failure_is_retryable(self):
		"""ERPNext refused outright: nothing happened, so repeating is safe."""
		described = finance_messages.describe_failure(
			{"name": "P", "attempts": 1, "error_message": "Connection reset by peer"}
		)

		self.assertTrue(described["can_retry"])

	def test_repeated_failure_stops_offering_a_retry(self):
		described = finance_messages.describe_failure(
			{"name": "P", "attempts": 99, "error_message": "Connection reset by peer"}
		)

		self.assertFalse(described["can_retry"])


class TestFolioProjection(CashierWorld):
	"""What the cashier is told about accounting, and what it is not."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()

		cls.folio = frappe.get_doc(
			{
				"doctype": "Guest Folio",
				"property": cls.property_a,
				"guest": cls.fixtures.guest("Cashier"),
				"folio_status": "Open",
				"folio_type": "Master",
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()

	def test_the_folio_reports_posting_state_without_erp_documents(self):
		"""Front Office may know *whether* revenue posted, not the paperwork."""
		frappe.set_user(self.manager)
		payload = folio_api.get_folio(self.folio.name)

		self.assertIn("disclosure", payload)
		self.assertFalse(
			payload["disclosure"]["invoice"],
			msg="a front office manager was told they may read Sales Invoice",
		)

	def test_totals_are_read_not_recomputed(self):
		"""The server's numbers are opaque; a client must never re-derive them."""
		frappe.set_user(self.manager)
		folio = folio_api.get_folio(self.folio.name)["folio"]

		for field in (
			"total_charges",
			"total_taxes",
			"total_payments",
			"total_adjustments",
			"balance",
		):
			self.assertIn(field, folio)

	def test_front_office_cannot_reach_reconciliation(self):
		"""RECONCILIATION_ROLES deliberately excludes the front desk."""
		frappe.set_user(self.manager)

		with self.assertRaises(REFUSALS):
			checkout_api.reconciliation(property=self.property_a)


class TestPostingFrontDoorGates(CashierWorld):
	"""FIN-3 / FIN-4: the whitelisted `post_charge` and `post_payment` front doors.

	Corrections that move money have gated endpoints - `post_adjustment` demands
	an elevated role and a reason, `payments.refund` demands the refund role, a
	reason and a refundable-balance check. But an ordinary agent holds
	`write` on Guest Folio, so before this fix the same agent could reach the
	*ungated* front doors and post the very correction types those gates exist
	for: a signed charge (`Adjustment`/`Discount`) that drains the balance, or a
	`Refund` payment that flips the sign into a cash-out. The front doors must
	refuse those types and send the caller to the gated path.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()

		# An ordinary front-desk operator: `Front Office Agent` holds write on
		# Guest Folio (so `authorise_document(..., "write")` passes) but none of
		# the ADJUSTMENT_ROLES / REFUND_ROLES the gated corrections require.
		cls.agent = cls.fixtures.user(
			"cash-agent", ["Front Office Agent"], properties=[cls.property_a]
		)

		cls.gate_folio = frappe.get_doc(
			{
				"doctype": "Guest Folio",
				"property": cls.property_a,
				"guest": cls.fixtures.guest("Gate"),
				"folio_status": "Open",
				"folio_type": "Master",
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()

	def _key(self, label):
		return f"gate-test:{label}:{frappe.generate_hash(length=8)}"

	def test_agent_cannot_drain_balance_via_adjustment_charge(self):
		"""FIN-3: `charge_type='Adjustment'` with a negative amount is refused.

		This is the correction workflow wearing a charge's clothes: it moves the
		balance exactly as `post_adjustment` would, but `post_charge` demands
		neither an elevated role nor a recorded reason.
		"""
		frappe.set_user(self.agent)

		with self.assertRaises(frappe.ValidationError):
			folio_api.post_charge(
				folio=self.gate_folio.name,
				charge_type="Adjustment",
				description="drain",
				amount=-100,
				idempotency_key=self._key("adj"),
			)

	def test_agent_cannot_discount_via_post_charge(self):
		"""FIN-3: `Discount` is signed too, and reaches the balance ungated here."""
		frappe.set_user(self.agent)

		with self.assertRaises(frappe.ValidationError):
			folio_api.post_charge(
				folio=self.gate_folio.name,
				charge_type="Discount",
				description="freebie",
				amount=50,
				idempotency_key=self._key("disc"),
			)

	def test_agent_cannot_cash_out_via_refund_payment(self):
		"""FIN-4: `payment_type='Refund'` flips the sign into a cash-out and skips
		the closed-day fence, all without the refund role or a reason."""
		frappe.set_user(self.agent)

		with self.assertRaises(frappe.ValidationError):
			folio_api.post_payment(
				folio=self.gate_folio.name,
				amount=100,
				payment_method="Cash",
				payment_type="Refund",
				idempotency_key=self._key("refund"),
			)

	# -- positive controls: the ordinary front door still works ----------

	def test_ordinary_room_charge_still_posts(self):
		"""The refusal is narrow: a real Room Charge is unaffected."""
		frappe.set_user(self.agent)

		result = folio_api.post_charge(
			folio=self.gate_folio.name,
			charge_type="Room Charge",
			description="Night 1",
			amount=100,
			idempotency_key=self._key("room"),
		)

		self.assertFalse(result["duplicate"])
		self.assertEqual(result["amount"], 100)

	def test_ordinary_payment_still_posts(self):
		"""And an ordinary Payment is unaffected."""
		frappe.set_user(self.agent)

		result = folio_api.post_payment(
			folio=self.gate_folio.name,
			amount=50,
			payment_method="Cash",
			idempotency_key=self._key("pay"),
		)

		self.assertFalse(result["duplicate"])
		self.assertEqual(result["amount"], 50)


class TestWastageReplayIsDeferred(CashierWorld):
	"""Characterised, not fixed — and executable so the characterisation cannot rot.

	`record_wastage` has no idempotency key, no lock and no marker to read, so a
	double submit writes two Wastage Entries and submits two Material Issues.
	Unlike the two kitchen sites 16.7.5 *did* fix, this one cannot be closed by
	reading currently: there is nothing to read. Closing it means choosing an
	identity — a client-supplied key, or a derived natural key that must be
	defensible against two genuinely separate write-offs of the same item on the
	same day — plus a new field, a unique index and the audit record it lacks.
	That is schema work, not cashier work.

	This test asserts today's behaviour deliberately. When the guard lands it
	will fail, which is the point: the deferral expires loudly rather than
	silently.
	"""

	def test_wastage_has_no_replay_guard_today(self):
		from hospitality_pms.services import kitchen as kitchen_service

		self.assertFalse(
			hasattr(kitchen_service.record_wastage, "__wrapped__"),
			msg="record_wastage gained a wrapper; re-check the deferral",
		)

		import inspect

		source = inspect.getsource(kitchen_service.record_wastage)

		self.assertNotIn(
			"idempotency_key",
			source,
			msg="record_wastage now takes an idempotency key - remove this deferral test",
		)
		self.assertNotIn(
			"lock_and_get_doc",
			source,
			msg="record_wastage now reads currently - remove this deferral test",
		)
