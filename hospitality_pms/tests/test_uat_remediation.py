"""Findings the first onboarding UAT raised against a configured property.

Four defects that the automated suites had no reason to look for, because each
one only shows up when a real operator does the natural thing:

* **UAT-001.** An adjustment demands a reason, checks it, and then throws it
  away. `post_adjustment` validates `reason` and calls `post_charge`, which has
  no `reason` parameter at all - so the audit row records the amount, the actor
  and the day, and never why. A discount cannot be justified afterwards.
* **UAT-002.** A second partial refund is impossible. Eligibility is
  `status == "Captured"`, so the first partial refund moves the transaction to
  `Partially Refunded` and locks the remaining balance away - even though the
  next line computes `refundable = amount - refunded_amount`, which by then can
  never be reached.
* **UAT-005.** The natural maintenance order breaks. Marking a room Out of
  Order the moment the fault is found, then starting work, fails: `start_work`
  moves the room to `Required`, and Out of Order does not go there. The ticket
  strands Open and the room stays unsellable with no supported way back.
* **UAT-004.** A Front Office Agent cannot check a guest out. Hospitality
  authorises the operation, then ERPNext's own Payment Entry validation reads
  the Sales Invoice and raises a bare `PermissionError` at a user who has no
  business holding accounting permissions.
"""

import os
import tempfile

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from hospitality_pms.services import folio as folio_service
from hospitality_pms.services import payments as payment_service
from hospitality_pms.tests import fake_provider
from hospitality_pms.tests.concurrency import Worker, assert_all_ran, run_workers
from hospitality_pms.tests.fixtures import Fixtures

CAPTURED = 300.0


def use_fake_provider():
	from hospitality_pms.integrations.payments import ADAPTERS

	ADAPTERS["Manual"] = "hospitality_pms.tests.fake_provider.RecordingAdapter"


def _refund_worker(barrier, transaction: str, amount: float, key: str, tag: str, partner: str) -> dict:
	"""One of two refunds issued against the same transaction at the same moment."""
	use_fake_provider()

	frappe.db.sql(
		"select refunded_amount from `tabPayment Transaction` where name = %s", transaction
	)

	barrier.signal(f"ready_{tag}")
	barrier.wait(f"ready_{partner}")

	try:
		payment_service.refund_payment(transaction, amount, "concurrent refund", idempotency_key=key)
		frappe.db.commit()
		return {"refunded": amount}
	except Exception as error:
		frappe.db.rollback()
		return {"refused": type(error).__name__}


# ---------------------------------------------------------------------------
# UAT-001 — the adjustment reason
# ---------------------------------------------------------------------------


class TestAdjustmentReasonIsAudited(IntegrationTestCase):
	"""A reason that is demanded and then discarded is not an audit trail."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.fixtures = Fixtures("UATA")
		cls.property = cls.fixtures.property("UA")
		cls.guest = cls.fixtures.guest("Adjust")
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		cls.fixtures.teardown()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")
		self.folio = self.fixtures.folio(self.property, self.guest)
		folio_service.post_charge(
			self.folio, "Minibar", "Something to discount", 100, idempotency_key=f"{self.folio}:c1"
		)
		frappe.db.commit()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def _logs(self) -> list[dict]:
		return frappe.get_all(
			"Folio Log",
			filters={"folio": self.folio},
			fields=["action", "reason", "amount", "changed_by", "changed_at", "property", "details"],
			order_by="creation",
		)

	def test_adjustment_reason_is_persisted(self):
		"""The reproduction: the reason existed only in the request."""
		folio_service.post_adjustment(
			self.folio, -25, "Goodwill", "Guest service recovery", idempotency_key=f"{self.folio}:adj1"
		)
		frappe.db.commit()

		# Read back from the database, not from the call's return value.
		frappe.db.rollback()
		logs = [row for row in self._logs() if "Adjustment" in (row["action"] or "")]

		self.assertTrue(logs, msg="the adjustment left no audit row at all")
		self.assertEqual(
			logs[-1]["reason"],
			"Guest service recovery",
			msg="the reason was demanded, validated, and then discarded",
		)

	def test_the_audit_row_carries_the_whole_story(self):
		"""Actor, amount, property, day and key, not just the reason."""
		from frappe.utils import getdate

		from hospitality_pms.services.property import get_business_date

		folio_service.post_adjustment(
			self.folio, -25, "Goodwill", "Guest service recovery", idempotency_key=f"{self.folio}:adj2"
		)
		frappe.db.commit()

		row = [r for r in self._logs() if "Adjustment" in (r["action"] or "")][-1]

		self.assertEqual(row["changed_by"], "Administrator")
		self.assertEqual(flt(row["amount"]), -25.0)
		self.assertEqual(row["property"], self.property)
		self.assertTrue(row["changed_at"])
		self.assertIn(f"{self.folio}:adj2", row["details"] or "")

		charge = frappe.get_all(
			"Folio Charge",
			filters={"parent": self.folio, "charge_type": "Adjustment"},
			fields=["business_date"],
			order_by="creation desc",
			limit=1,
		)
		self.assertEqual(getdate(charge[0]["business_date"]), getdate(get_business_date(self.property)))

	def test_adjustment_without_reason_is_refused(self):
		from hospitality_pms.services.exceptions import FolioError

		with self.assertRaises(FolioError):
			folio_service.post_adjustment(
				self.folio, -25, "Goodwill", "   ", idempotency_key=f"{self.folio}:adj3"
			)

	def test_adjustment_retry_does_not_duplicate_or_lose_reason(self):
		"""A replay must neither post twice nor blank the reason it already wrote."""
		key = f"{self.folio}:adj4"

		folio_service.post_adjustment(self.folio, -25, "Goodwill", "Guest service recovery", idempotency_key=key)
		frappe.db.commit()
		second = folio_service.post_adjustment(
			self.folio, -25, "Goodwill", "Guest service recovery", idempotency_key=key
		)
		frappe.db.commit()

		rows = frappe.db.count("Folio Charge", {"parent": self.folio, "charge_type": "Adjustment"})
		reasons = [r["reason"] for r in self._logs() if "Adjustment" in (r["action"] or "")]

		self.assertTrue(second.get("duplicate"))
		self.assertEqual(rows, 1, msg="the replay posted a second adjustment")
		self.assertIn("Guest service recovery", reasons)

	def test_unauthorized_adjustment_is_refused(self):
		from hospitality_pms.services.exceptions import PermissionDeniedError

		agent = self.fixtures.user("uatadj", ["Front Office Agent"], properties=[self.property])
		frappe.db.commit()
		frappe.set_user(agent)

		with self.assertRaises(PermissionDeniedError):
			folio_service.post_adjustment(
				self.folio, -25, "Goodwill", "Guest service recovery", idempotency_key=f"{self.folio}:adj5"
			)


# ---------------------------------------------------------------------------
# UAT-002 — refunding what is left
# ---------------------------------------------------------------------------


class TestPartialRefundsUntilExhausted(IntegrationTestCase):
	"""`Partially Refunded` is a state with money still in it."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.fixtures = Fixtures("UATR")
		cls.property = cls.fixtures.property("UR")
		cls.guest = cls.fixtures.guest("Refund")
		cls.provider = cls.fixtures.payment_provider(cls.property)
		cls._scratch = tempfile.TemporaryDirectory(prefix="hpms-uat-refund-")
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

	def _state(self):
		return frappe.db.get_value(
			"Payment Transaction", self.transaction, ["transaction_status", "refunded_amount"], as_dict=True
		)

	def test_second_partial_refund_allowed(self):
		"""The reproduction: 30 of 300 refunded, and the other 270 locked away."""
		payment_service.refund_payment(self.transaction, 30, "first", idempotency_key="r1")
		frappe.db.commit()

		self.assertEqual(self._state().transaction_status, "Partially Refunded")

		payment_service.refund_payment(self.transaction, 100, "second", idempotency_key="r2")
		frappe.db.commit()

		state = self._state()
		self.assertEqual(flt(state.refunded_amount), 130.0)
		self.assertEqual(state.transaction_status, "Partially Refunded")

	def test_multiple_partial_refunds_reach_refunded(self):
		"""The last refund that exhausts the capture settles the state."""
		for index, amount in enumerate((30, 100, 170), start=1):
			payment_service.refund_payment(self.transaction, amount, "step", idempotency_key=f"m{index}")
			frappe.db.commit()

		state = self._state()
		self.assertEqual(flt(state.refunded_amount), CAPTURED)
		self.assertEqual(state.transaction_status, "Refunded")

	def test_refund_refuses_amount_over_remaining(self):
		from hospitality_pms.services.exceptions import IntegrationError

		payment_service.refund_payment(self.transaction, 30, "first", idempotency_key="o1")
		frappe.db.commit()

		with self.assertRaises(IntegrationError):
			payment_service.refund_payment(self.transaction, 271, "too much", idempotency_key="o2")

		self.assertEqual(flt(self._state().refunded_amount), 30.0)

	def test_a_fully_refunded_transaction_refuses_one_more(self):
		payment_service.refund_payment(self.transaction, CAPTURED, "all of it", idempotency_key="f1")
		frappe.db.commit()

		self.assertEqual(self._state().transaction_status, "Refunded")

		from hospitality_pms.services.exceptions import IntegrationError

		with self.assertRaises(IntegrationError):
			payment_service.refund_payment(self.transaction, 1, "one more", idempotency_key="f2")

	def test_partial_refund_retry_is_idempotent(self):
		"""Wave 3's guarantee must survive the eligibility change."""
		payment_service.refund_payment(self.transaction, 30, "first", idempotency_key="i1")
		frappe.db.commit()
		calls = len(fake_provider.calls("refund"))

		result = payment_service.refund_payment(self.transaction, 30, "first", idempotency_key="i1")
		frappe.db.commit()

		self.assertTrue(result.get("duplicate"))
		self.assertEqual(len(fake_provider.calls("refund")), calls, msg="the provider was asked twice")
		self.assertEqual(flt(self._state().refunded_amount), 30.0)

	def test_partially_refunded_state_does_not_regress(self):
		"""Wave 6's precedence model must still refuse a stale failure."""
		payment_service.refund_payment(self.transaction, 30, "first", idempotency_key="p1")
		frappe.db.commit()

		reference = frappe.db.get_value("Payment Transaction", self.transaction, "provider_reference")
		payment_service.handle_callback(
			self.property, self.provider, {"provider_reference": reference, "status": "Failed"}, {}
		)
		frappe.db.commit()

		state = self._state()
		self.assertEqual(state.transaction_status, "Partially Refunded")
		self.assertEqual(flt(state.refunded_amount), 30.0)

	def test_concurrent_partial_refunds_do_not_overrefund(self):
		"""Two tills refunding at once must not exceed what is left."""
		payment_service.refund_payment(self.transaction, 30, "first", idempotency_key="c0")
		frappe.db.commit()

		results = run_workers(
			[
				Worker(
					f"{__name__}._refund_worker",
					{"transaction": self.transaction, "amount": 200, "key": "ca", "tag": "a", "partner": "b"},
				),
				Worker(
					f"{__name__}._refund_worker",
					{"transaction": self.transaction, "amount": 200, "key": "cb", "tag": "b", "partner": "a"},
				),
			]
		)
		assert_all_ran(results)

		refunded = flt(self._state().refunded_amount)
		at_provider = sum(flt(call["amount"]) for call in fake_provider.calls("refund"))

		self.assertLessEqual(
			refunded, CAPTURED, msg=f"aggregate refund exceeded the capture: {results}"
		)
		self.assertLessEqual(
			at_provider, CAPTURED, msg=f"the provider was asked to refund more than was captured: {results}"
		)


# ---------------------------------------------------------------------------
# UAT-005 — a room already out of order, and work starting on it
# ---------------------------------------------------------------------------


class TestMaintenanceOnAnAlreadyBlockedRoom(IntegrationTestCase):
	"""The order an engineer actually works in.

	A fault is found, the room comes out of sale *immediately* - that is the
	whole point of finding it - and only then does somebody start the repair.
	That order failed: `start_work` moved the maintenance dimension to
	`Required`, and `Out of Order` has no transition there, so the ticket
	stranded Open and the room had no supported way back into sale.

	`Required` was the wrong target anyway. It means "this room needs work",
	not "work is happening", and it is not in `BLOCKING_MAINTENANCE` - so on a
	healthy room, starting a repair left the room sellable while a technician
	had it open.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.fixtures = Fixtures("UATM")
		cls.property = cls.fixtures.property("UM")
		cls.room_type = cls.fixtures.room_type(cls.property, base_rate=100)
		cls.rooms = cls.fixtures.rooms(cls.property, cls.room_type, count=2)
		cls.manager = cls.fixtures.user(
			"uatmaint", ["Maintenance Manager", "Front Office Manager"], properties=[cls.property]
		)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		cls.fixtures.teardown()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")
		for room in self.rooms:
			frappe.db.set_value(
				"Hotel Room",
				room,
				{
					"maintenance_status": "Operational",
					"inventory_status": "Available",
					"occupancy_status": "Vacant",
					"housekeeping_status": "Clean",
				},
				update_modified=False,
			)
		# The tickets raise Room Blocks; clearing only the tickets would leave
		# the blocks behind and the next take_out_of_service would collide.
		frappe.db.delete("Room Block", {"property": self.property})
		frappe.db.delete("Maintenance Ticket", {"property": self.property})
		frappe.db.commit()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def _ticket(self, room: str) -> str:
		from hospitality_pms.services import maintenance as maintenance_service

		return maintenance_service.create_ticket(
			property_name=self.property,
			title="Air conditioning dead",
			description="Reported by the guest",
			room=room,
			category="HVAC",
		)

	def _maintenance(self, room: str) -> str:
		return frappe.db.get_value("Hotel Room", room, "maintenance_status")

	def _assignable(self, room: str) -> bool:
		from frappe.utils import add_days, getdate

		from hospitality_pms.services.availability import get_assignable_rooms
		from hospitality_pms.services.property import get_business_date

		day = getdate(get_business_date(self.property))

		return room in [
			r["name"] for r in get_assignable_rooms(self.property, self.room_type, day, add_days(day, 1))
		]

	def test_out_of_order_then_start_work_succeeds(self):
		"""The reproduction, in the order an engineer would use."""
		from hospitality_pms.services import maintenance as maintenance_service

		room = self.rooms[0]
		ticket = self._ticket(room)

		frappe.set_user(self.manager)
		maintenance_service.take_out_of_service(
			ticket, status="Out of Order", reason="Unsafe until repaired"
		)
		frappe.db.commit()

		self.assertEqual(self._maintenance(room), "Out of Order")

		maintenance_service.start_work(ticket)
		frappe.db.commit()

		self.assertEqual(
			frappe.db.get_value("Maintenance Ticket", ticket, "ticket_status"), "In Progress"
		)

	def test_room_remains_out_of_order_while_work_in_progress(self):
		"""The operator's severity marking is not downgraded by starting work."""
		from hospitality_pms.services import maintenance as maintenance_service

		room = self.rooms[0]
		ticket = self._ticket(room)

		frappe.set_user(self.manager)
		maintenance_service.take_out_of_service(ticket, status="Out of Order", reason="Unsafe")
		maintenance_service.start_work(ticket)
		frappe.db.commit()

		self.assertEqual(
			self._maintenance(room),
			"Out of Order",
			msg="starting the repair quietly downgraded how bad the room is",
		)

	def test_starting_work_on_a_healthy_room_takes_it_out_of_sale(self):
		"""A technician with the room open means the room cannot be sold."""
		from hospitality_pms.services import maintenance as maintenance_service
		from hospitality_pms.services.rooms import BLOCKING_MAINTENANCE

		room = self.rooms[1]
		ticket = self._ticket(room)

		self.assertTrue(self._assignable(room), msg="the fixture room should start sellable")

		frappe.set_user(self.manager)
		maintenance_service.start_work(ticket)
		frappe.db.commit()

		self.assertIn(
			self._maintenance(room),
			BLOCKING_MAINTENANCE,
			msg="a room under active repair was left in a sellable maintenance state",
		)

	def test_room_not_assignable_during_maintenance(self):
		from hospitality_pms.services import maintenance as maintenance_service

		room = self.rooms[0]
		ticket = self._ticket(room)

		frappe.set_user(self.manager)
		maintenance_service.take_out_of_service(ticket, status="Out of Order", reason="Unsafe")
		maintenance_service.start_work(ticket)
		frappe.db.commit()

		self.assertFalse(self._assignable(room))

	def test_complete_work_moves_to_existing_release_state(self):
		from hospitality_pms.services import maintenance as maintenance_service

		room = self.rooms[0]
		ticket = self._ticket(room)

		frappe.set_user(self.manager)
		maintenance_service.take_out_of_service(ticket, status="Out of Order", reason="Unsafe")
		maintenance_service.start_work(ticket)
		maintenance_service.complete_work(ticket, notes="Compressor replaced")
		frappe.db.commit()

		self.assertEqual(
			frappe.db.get_value("Maintenance Ticket", ticket, "ticket_status"), "Verification"
		)
		self.assertFalse(
			self._assignable(room), msg="the room was released before anyone verified the work"
		)

	def test_room_can_return_to_service_through_supported_flow(self):
		"""The whole loop, ending with the room sellable again."""
		from hospitality_pms.services import maintenance as maintenance_service

		room = self.rooms[0]
		ticket = self._ticket(room)

		frappe.set_user(self.manager)
		maintenance_service.take_out_of_service(ticket, status="Out of Order", reason="Unsafe")
		maintenance_service.start_work(ticket)
		maintenance_service.complete_work(ticket, notes="Compressor replaced")
		maintenance_service.verify_and_release(ticket, passed=True, notes="Cold air, signed off")
		frappe.db.commit()

		self.assertEqual(self._maintenance(room), "Operational")
		self.assertEqual(
			frappe.db.get_value("Maintenance Ticket", ticket, "ticket_status"), "Completed"
		)
		self.assertTrue(self._assignable(room), msg="the room never came back into sale")

	def test_start_work_retry_is_safe(self):
		"""Pressing start twice is a normal thing to do."""
		from hospitality_pms.services import maintenance as maintenance_service
		from hospitality_pms.services.exceptions import InvalidStateTransitionError

		room = self.rooms[0]
		ticket = self._ticket(room)

		frappe.set_user(self.manager)
		maintenance_service.take_out_of_service(ticket, status="Out of Order", reason="Unsafe")
		maintenance_service.start_work(ticket)
		frappe.db.commit()

		with self.assertRaises(InvalidStateTransitionError):
			maintenance_service.start_work(ticket)

		frappe.db.rollback()

		self.assertEqual(self._maintenance(room), "Out of Order")
		self.assertEqual(
			frappe.db.get_value("Maintenance Ticket", ticket, "ticket_status"), "In Progress"
		)


# ---------------------------------------------------------------------------
# UAT-004 — who is allowed to complete a checkout
# ---------------------------------------------------------------------------


class TestFrontOfficeCheckoutAuthority(IntegrationTestCase):
	"""A front desk agent checks guests out. That is the job.

	Hospitality authorised the operation correctly and then ERPNext refused it:
	building the Payment Entry reads the Sales Invoice it allocates against, and
	`check_doctype_permission` raised a bare `PermissionError` - no message, at a
	user with no accounting permissions and no reason to have any.

	The fix is not to hand the front desk accounting rights. It is that posting
	to ERPNext is the *system's* action on behalf of an operation the hotel has
	already authorised, so the elevation lives inside that one operation, bound
	to the folio's own property and company.

	These tests pin both halves: the agent can finish the checkout, and the
	agent still cannot read a single accounting document on their own.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()

		from hospitality_pms.tests.posting_world import PostingWorld

		cls.world = PostingWorld("UATC", "UC")
		cls.fixtures = cls.world.fixtures
		cls.property = cls.world.property
		cls.room_type = cls.fixtures.room_type(cls.property, base_rate=100)
		cls.rooms = cls.fixtures.rooms(cls.property, cls.room_type, count=2)
		cls.rate_plan = cls.fixtures.rate_plan(cls.property, cls.room_type, base_rate=100)
		cls.agent = cls.fixtures.user("uatfoa", ["Front Office Agent"], properties=[cls.property])

		# A second property the agent has no business touching.
		cls.other_property = cls.fixtures.property("UO")
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		cls.world.teardown()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")
		self.fixtures.reset_property_records(
			self.property,
			("Folio Log", "Guest Folio", "Room Status Log", "Stay", "Reservation Log", "Reservation"),
		)
		for room in self.rooms:
			# Housekeeping as well as occupancy: checkout leaves the room Dirty,
			# and a dirty room is not offered as a candidate, so the next test
			# would find no room to check into.
			frappe.db.set_value(
				"Hotel Room",
				room,
				{"occupancy_status": "Vacant", "housekeeping_status": "Clean"},
				update_modified=False,
			)
		frappe.db.delete("Housekeeping Task", {"property": self.property})
		frappe.db.commit()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def _checked_in_guest(self):
		from hospitality_pms.services import reservations as reservation_service
		from hospitality_pms.services import stays as stay_service
		from hospitality_pms.services.availability import get_assignable_rooms
		from hospitality_pms.services.property import get_business_date
		from frappe.utils import add_days, getdate

		day = getdate(get_business_date(self.property))
		guest = self.fixtures.guest("Checkout")
		reservation = self.fixtures.reservation(
			self.property, self.room_type, guest, rate_plan=self.rate_plan, arrival=day, nights=1
		)
		reservation_service.confirm(reservation)
		line = frappe.get_all("Reservation Room", filters={"parent": reservation}, pluck="name")[0]
		room = get_assignable_rooms(self.property, self.room_type, day, add_days(day, 1))[0]["name"]
		result = stay_service.check_in(reservation, line, room)
		frappe.db.commit()

		return result["stay"], result["folio"]

	def _settled_folio(self):
		"""A guest with a charge, paid in full, ready to leave."""
		stay, folio = self._checked_in_guest()
		folio_service.post_charge(
			folio, "Room Charge", "One night", 100, idempotency_key=f"{folio}:night"
		)
		balance = flt(frappe.db.get_value("Guest Folio", folio, "balance"))
		folio_service.post_payment(folio, balance, "Cash", idempotency_key=f"{folio}:settle")
		frappe.db.commit()

		return stay, folio

	# -- the operation the agent must be able to finish --------------------

	def test_front_office_checkout_uses_trusted_erp_service(self):
		"""The reproduction: authorised by Hospitality, refused by ERPNext."""
		from hospitality_pms.api import checkout as checkout_api

		stay, folio = self._settled_folio()

		frappe.set_user(self.agent)
		checkout_api.check_out(stay=stay)
		frappe.db.commit()

		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("Stay", stay, "stay_status"), "Checked Out")
		self.assertIn(
			frappe.db.get_value("Guest Folio", folio, "folio_status"), ("Settled", "Closed")
		)

	def test_the_accounting_documents_are_really_posted(self):
		"""Not "it worked" - the invoice and the payment entry exist and match."""
		from hospitality_pms.api import checkout as checkout_api
		from hospitality_pms.services import posting as posting_service

		stay, folio = self._settled_folio()

		frappe.set_user(self.agent)
		checkout_api.check_out(stay=stay)
		frappe.db.commit()
		frappe.set_user("Administrator")

		invoices = posting_service.folio_erp_documents(folio, "Sales Invoice")
		entries = posting_service.folio_erp_documents(folio, "Payment Entry")

		self.assertEqual(len(invoices), 1, msg=f"invoices={invoices}")
		self.assertEqual(len(entries), 1, msg=f"payment entries={entries}")
		self.assertEqual(frappe.db.get_value("Sales Invoice", invoices[0], "docstatus"), 1)
		self.assertEqual(frappe.db.get_value("Payment Entry", entries[0], "docstatus"), 1)
		self.assertEqual(
			flt(frappe.db.get_value("Sales Invoice", invoices[0], "outstanding_amount")), 0.0
		)

	# -- and the authority it must NOT confer -------------------------------

	def test_front_office_cannot_read_unrelated_sales_invoice(self):
		from hospitality_pms.api import checkout as checkout_api
		from hospitality_pms.services import posting as posting_service

		stay, folio = self._settled_folio()
		frappe.set_user(self.agent)
		checkout_api.check_out(stay=stay)
		frappe.db.commit()
		frappe.set_user("Administrator")

		invoice = posting_service.folio_erp_documents(folio, "Sales Invoice")[0]

		frappe.set_user(self.agent)
		self.assertFalse(
			frappe.has_permission("Sales Invoice", "read"),
			msg="the agent was granted blanket Sales Invoice read",
		)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc("Sales Invoice", invoice).check_permission("read")

	def test_front_office_cannot_read_unrelated_payment_entry(self):
		frappe.set_user(self.agent)

		self.assertFalse(frappe.has_permission("Payment Entry", "read"))
		self.assertFalse(frappe.has_permission("Payment Entry", "create"))
		self.assertFalse(frappe.has_permission("GL Entry", "read"))
		self.assertFalse(frappe.has_permission("Customer", "read"))

	def test_the_agent_holds_no_accounting_role(self):
		"""Proof the fix was not "give them Finance Manager"."""
		frappe.set_user(self.agent)
		roles = set(frappe.get_roles())

		self.assertEqual(roles & {"Accounts User", "Accounts Manager", "Finance Manager", "System Manager"}, set())
		self.assertIn("Front Office Agent", roles)

	def test_the_elevation_does_not_leak_past_the_operation(self):
		"""`ignore_permissions` must not still be set once checkout returns."""
		from hospitality_pms.api import checkout as checkout_api

		stay, _folio = self._settled_folio()

		frappe.set_user(self.agent)
		checkout_api.check_out(stay=stay)
		frappe.db.commit()

		self.assertFalse(
			frappe.flags.get("ignore_permissions"),
			msg="the trusted elevation was left switched on after the operation",
		)
		self.assertFalse(frappe.has_permission("Sales Invoice", "read"))

	def test_service_authority_is_bound_to_property(self):
		"""The trusted posting refuses a folio outside the caller's property."""
		from hospitality_pms.services import posting as posting_service
		from hospitality_pms.services.exceptions import PermissionDeniedError

		guest = self.fixtures.guest("Outsider")
		other_folio = self.fixtures.folio(self.other_property, guest)
		folio_service.post_charge(
			other_folio, "Room Charge", "Elsewhere", 100, idempotency_key=f"{other_folio}:x"
		)
		frappe.db.commit()

		frappe.set_user(self.agent)
		with self.assertRaises((PermissionDeniedError, frappe.PermissionError)):
			posting_service.post_folio_invoice(other_folio)

	def test_service_authority_cannot_redirect_company(self):
		"""The company posted to is the folio's property's company, not a caller's choice."""
		from hospitality_pms.services import posting as posting_service

		stay, folio = self._settled_folio()
		posting_service.post_folio_invoice(folio)
		frappe.db.commit()

		invoice = posting_service.folio_erp_documents(folio, "Sales Invoice")[0]
		expected = frappe.db.get_value("Property", self.property, "company")

		self.assertEqual(frappe.db.get_value("Sales Invoice", invoice, "company"), expected)

	def test_cross_property_checkout_still_refused(self):
		"""Wave 1's boundary is untouched by the new authority."""
		from hospitality_pms.api import checkout as checkout_api
		from hospitality_pms.services.exceptions import PermissionDeniedError

		outsider = self.fixtures.user("uatout", ["Front Office Agent"], properties=[self.other_property])
		stay, _folio = self._settled_folio()
		frappe.db.commit()

		frappe.set_user(outsider)
		with self.assertRaises((PermissionDeniedError, frappe.PermissionError)):
			checkout_api.check_out(stay=stay)

	def test_a_refused_checkout_says_something_useful(self):
		"""No blank PermissionError at the desk."""
		from hospitality_pms.api import checkout as checkout_api

		outsider = self.fixtures.user("uatout2", ["Front Office Agent"], properties=[self.other_property])
		stay, _folio = self._settled_folio()
		frappe.db.commit()

		frappe.set_user(outsider)
		try:
			checkout_api.check_out(stay=stay)
			self.fail("the cross-property checkout should have been refused")
		except Exception as error:
			message = frappe.utils.strip_html(str(error) or "").strip()
			self.assertTrue(
				message, msg=f"{type(error).__name__} carried no message for the user to act on"
			)


class TestPostingServiceIdentityIsBounded(IntegrationTestCase):
	"""The identity itself: what it holds, and that it is always given back.

	A trusted identity is only as good as the two things around it - how
	little it can do, and whether it is ever left switched on. Both are
	asserted here rather than assumed from reading the context manager.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()

		from hospitality_pms.tests.posting_world import PostingWorld

		cls.world = PostingWorld("UATS", "US")
		cls.fixtures = cls.world.fixtures
		cls.property = cls.world.property
		cls.agent = cls.fixtures.user("uatsvc", ["Front Office Agent"], properties=[cls.property])
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		cls.world.teardown()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_the_service_identity_holds_only_its_own_role(self):
		from hospitality_pms.setup.posting_service import POSTING_SERVICE_ROLE, POSTING_SERVICE_USER

		roles = set(frappe.get_all("Has Role", filters={"parent": POSTING_SERVICE_USER}, pluck="role"))

		self.assertEqual(roles, {POSTING_SERVICE_ROLE})
		self.assertEqual(
			roles & {"System Manager", "Accounts Manager", "Accounts User", "Finance Manager"},
			set(),
			msg="the posting identity has accumulated an administrative role",
		)

	def test_the_service_role_grants_read_and_nothing_else(self):
		"""No create, write, submit, cancel or delete - anywhere."""
		from hospitality_pms.setup.posting_service import POSTING_SERVICE_ROLE

		perms = frappe.get_all(
			"Custom DocPerm",
			filters={"role": POSTING_SERVICE_ROLE},
			fields=["parent", "read", "write", "create", "delete", "submit", "cancel", "amend", "export", "share"],
		)

		self.assertTrue(perms, msg="the service role has no permissions at all")

		for perm in perms:
			self.assertEqual(perm["read"], 1, msg=f"{perm['parent']} is granted without read")
			for right in ("write", "create", "delete", "submit", "cancel", "amend", "export", "share"):
				self.assertEqual(
					perm[right], 0, msg=f"{perm['parent']} grants {right} to the posting identity"
				)

	def test_the_service_identity_cannot_be_used_as_a_generic_proxy(self):
		"""Its one job is reachable only from inside a bound posting.

		`erp_posting_authority` is not whitelisted, and it authorises against
		the property before it elevates - so it cannot be called as an endpoint
		or pointed at a property the caller does not hold.
		"""
		from hospitality_pms.api import checkout as checkout_api
		from hospitality_pms.services import posting as posting_service

		self.assertFalse(
			getattr(posting_service.erp_posting_authority, "__wrapped__", posting_service.erp_posting_authority)
			.__dict__.get("whitelisted"),
			msg="the trust boundary is exposed as an endpoint",
		)
		self.assertFalse(hasattr(checkout_api, "erp_posting_authority"))

		# And entering it as a caller who does not hold the property is refused
		# before any identity change happens.
		from hospitality_pms.services.exceptions import PropertyAccessError

		other = self.fixtures.property("UZ")
		frappe.db.commit()
		frappe.set_user(self.agent)

		with self.assertRaises((PropertyAccessError, frappe.PermissionError)):
			with posting_service.erp_posting_authority(other, what="a probe"):
				self.fail("the authority was entered for a property the caller does not hold")

		self.assertEqual(frappe.session.user, self.agent, msg="identity changed despite the refusal")

	def test_identity_is_restored_after_success(self):
		from hospitality_pms.services import posting as posting_service
		from hospitality_pms.setup.posting_service import POSTING_SERVICE_USER

		frappe.set_user(self.agent)

		with posting_service.erp_posting_authority(self.property, what="a probe") as (company, actor):
			self.assertEqual(frappe.session.user, POSTING_SERVICE_USER, msg="the identity was not adopted")
			self.assertEqual(actor, self.agent)
			self.assertEqual(company, frappe.db.get_value("Property", self.property, "company"))

		self.assertEqual(frappe.session.user, self.agent)
		self.assertFalse(frappe.flags.get("ignore_permissions"))

	def test_identity_is_restored_after_exception(self):
		"""The case that matters: a posting that blows up mid-flight."""
		from hospitality_pms.services import posting as posting_service

		frappe.set_user(self.agent)

		with self.assertRaises(RuntimeError):
			with posting_service.erp_posting_authority(self.property, what="a probe"):
				raise RuntimeError("posting exploded")

		self.assertEqual(
			frappe.session.user,
			self.agent,
			msg="a failed posting left the session holding the service identity",
		)
		self.assertFalse(frappe.flags.get("ignore_permissions"))

	def test_both_identities_are_audited(self):
		"""The posting log names the human, and records who executed it."""
		import json

		from hospitality_pms.services import posting as posting_service
		from hospitality_pms.setup.posting_service import POSTING_SERVICE_USER

		guest = self.fixtures.guest("Audited")
		folio = self.fixtures.folio(self.property, guest)
		folio_service.post_charge(folio, "Room Charge", "night", 100, idempotency_key=f"{folio}:aud")
		frappe.db.commit()

		frappe.set_user(self.agent)
		posting_service.post_folio_invoice(folio)
		frappe.db.commit()
		frappe.set_user("Administrator")

		log = frappe.get_all(
			"Financial Posting Log",
			filters={"folio": folio, "posting_type": "Sales Invoice"},
			fields=["posted_by", "payload"],
			limit=1,
		)[0]

		self.assertEqual(log["posted_by"], self.agent, msg="the human actor was lost")

		authority = json.loads(log["payload"] or "{}").get("_authority") or {}
		self.assertEqual(authority.get("initiated_by"), self.agent)
		self.assertEqual(authority.get("executed_as"), POSTING_SERVICE_USER)
