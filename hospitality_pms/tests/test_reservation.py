# Copyright (c) 2026, Globcom Qatar and Contributors
# See license.txt

"""Reservation regression suite.

Covers P1-4 (concurrent confirm/cancel against corporate credit) and P1-3
(overbooking authorization, reason and audit).

The P1-4 tests are genuinely concurrent - two OS processes, two connections,
two transactions, choreographed through a file barrier. They have to be: the
defect is that both workers evaluate their guards against a snapshot taken
before either acquired the lock, and a sequential test cannot produce that
state at all. A sequential version of these tests passes against the broken
code.
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt

from hospitality_pms.services import reservations as reservation_service
from hospitality_pms.services.exceptions import (
	AvailabilityError,
	HospitalityPMSError,
	InvalidStateTransitionError,
	PermissionDeniedError,
)
from hospitality_pms.tests.concurrency import Worker, assert_all_ran, run_workers
from hospitality_pms.tests.fixtures import Fixtures

#: 2 nights at 100 - the reservation total the credit movements must match.
ROOM_RATE = 100.0
NIGHTS = 2
RESERVATION_TOTAL = ROOM_RATE * NIGHTS


# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------


def _stale_start(barrier, reservation: str, tag: str, partner: str):
	"""Give this worker a pre-lock snapshot, then release both at once.

	Reading the reservation before the partner is allowed to proceed is what
	establishes the REPEATABLE-READ snapshot the defect depends on. Without it
	the loser might open its transaction after the winner had already
	committed, and see the right answer by luck rather than by design.
	"""
	frappe.db.sql("select reservation_status from `tabReservation` where name = %s", reservation)

	barrier.signal(f"ready_{tag}")
	barrier.wait(f"ready_{partner}")


def _confirm_worker(barrier, reservation: str, tag: str, partner: str) -> dict:
	_stale_start(barrier, reservation, tag, partner)

	status = reservation_service.confirm(reservation)
	frappe.db.commit()

	return {"op": "confirm", "status": status}


def _cancel_worker(barrier, reservation: str, tag: str, partner: str) -> dict:
	_stale_start(barrier, reservation, tag, partner)

	result = reservation_service.cancel(reservation, "concurrent cancel")
	frappe.db.commit()

	return {"op": "cancel", **result}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestReservationConcurrency(IntegrationTestCase):
	"""P1-4 - one reservation state change, one credit movement."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()

		cls.fixtures = Fixtures("RESC")
		cls.property = cls.fixtures.property("RC")
		cls.room_type = cls.fixtures.room_type(cls.property, base_rate=ROOM_RATE)
		cls.fixtures.rooms(cls.property, cls.room_type, count=4)
		cls.rate_plan = cls.fixtures.rate_plan(cls.property, cls.room_type, base_rate=ROOM_RATE)
		cls.guest = cls.fixtures.guest("Corporate")
		cls.account = cls.fixtures.corporate_account(cls.property, credit_limit=10000)

		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		cls.fixtures.teardown()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.set_value(
			"Corporate Account",
			self.account,
			{"credit_used": 0, "credit_available": 10000},
			update_modified=False,
		)
		# The ledger assertions count movements on the account, and the workers
		# commit theirs, so each test starts from an empty ledger rather than
		# inheriting the previous test's.
		frappe.db.delete("Corporate Credit Log", {"corporate_account": self.account})
		frappe.db.commit()

	def _reservation(self) -> str:
		name = self.fixtures.reservation(
			self.property,
			self.room_type,
			self.guest,
			rate_plan=self.rate_plan,
			nights=NIGHTS,
			corporate_account=self.account,
		)
		frappe.db.commit()

		self.assertEqual(
			flt(frappe.db.get_value("Reservation", name, "total_amount")),
			RESERVATION_TOTAL,
			msg="fixture priced differently than the test expects",
		)

		return name

	# -- helpers --------------------------------------------------------

	def _credit_movements(self, reservation: str) -> list[dict]:
		return frappe.get_all(
			"Corporate Credit Log",
			filters={"corporate_account": self.account},
			fields=["action", "amount", "credit_before", "credit_after"],
			order_by="creation asc",
		)

	def _consumptions(self, reservation: str) -> list[dict]:
		return [row for row in self._credit_movements(reservation) if row["action"].startswith("Credit consumed")]

	def _releases(self, reservation: str) -> list[dict]:
		return [row for row in self._credit_movements(reservation) if row["action"] == "Credit released"]

	def _transitions(self, reservation: str) -> list[dict]:
		return frappe.get_all(
			"Reservation Log",
			filters={"reservation": reservation},
			fields=["from_status", "to_status"],
			order_by="creation asc",
		)

	def _assert_ledger_agrees(self, reservation: str):
		"""The account balance and the sum of its movements must be the same number."""
		movements = self._credit_movements(reservation)

		net = sum(
			flt(row["amount"]) if row["action"].startswith("Credit consumed") else -flt(row["amount"])
			for row in movements
			if row["action"].startswith("Credit consumed") or row["action"] == "Credit released"
		)

		self.assertEqual(
			flt(net, 2),
			flt(frappe.db.get_value("Corporate Account", self.account, "credit_used"), 2),
			msg=f"ledger and account balance disagree; movements were {movements}",
		)

	# -- tests ----------------------------------------------------------

	def test_concurrent_confirm_consumes_credit_once(self):
		"""Two confirms racing: one wins, one is refused, credit moves once."""
		reservation = self._reservation()

		results = run_workers(
			[
				Worker(
					f"{__name__}._confirm_worker",
					{"reservation": reservation, "tag": "a", "partner": "b"},
				),
				Worker(
					f"{__name__}._confirm_worker",
					{"reservation": reservation, "tag": "b", "partner": "a"},
				),
			]
		)
		assert_all_ran(results)

		committed = [r for r in results if r["status"] == "committed"]

		self.assertEqual(
			len(committed),
			1,
			msg=f"exactly one confirm may take effect; got {results}",
		)

		self.assertEqual(
			frappe.db.get_value("Reservation", reservation, "reservation_status"),
			reservation_service.CONFIRMED,
		)

		self.assertEqual(
			len(self._transitions(reservation)),
			1,
			msg=f"exactly one logged transition expected; got {self._transitions(reservation)}",
		)

		self.assertEqual(
			len(self._consumptions(reservation)),
			1,
			msg=f"exactly one credit consumption expected; got {self._credit_movements(reservation)}",
		)

		self.assertEqual(
			flt(frappe.db.get_value("Corporate Account", self.account, "credit_used")),
			RESERVATION_TOTAL,
		)

		self._assert_ledger_agrees(reservation)

	def test_concurrent_confirm_cancel_settles_once(self):
		"""A cancel and a confirm racing must produce one valid serialisation.

		Two serialisations are legitimate, because cancelling a confirmed
		booking is a normal thing to do:

		  * cancel wins  -> Cancelled. The confirm is refused; a cancelled
		    reservation is terminal and must not be resurrected.
		  * confirm wins -> Confirmed, then cancelled. Credit is consumed and
		    then released, and the two cancel out.

		What must never happen is the third outcome the sweep observed: a
		cancellation committing and a confirm built on the pre-cancel snapshot
		then overwriting it, leaving a booking the guest cancelled holding
		both inventory and credit.
		"""
		reservation = self._reservation()

		results = run_workers(
			[
				Worker(
					f"{__name__}._confirm_worker",
					{"reservation": reservation, "tag": "a", "partner": "b"},
				),
				Worker(
					f"{__name__}._cancel_worker",
					{"reservation": reservation, "tag": "b", "partner": "a"},
				),
			]
		)
		assert_all_ran(results)

		final = frappe.db.get_value("Reservation", reservation, "reservation_status")
		transitions = self._transitions(reservation)
		ops = [r["result"]["op"] for r in results if r["status"] == "committed"]

		# No resurrection: nothing may follow a cancellation.
		statuses = [row["to_status"] for row in transitions]
		if reservation_service.CANCELLED in statuses:
			self.assertEqual(
				statuses[-1],
				reservation_service.CANCELLED,
				msg=f"a cancelled reservation was moved on again; log was {transitions}",
			)

		if "cancel" in ops:
			self.assertEqual(
				final,
				reservation_service.CANCELLED,
				msg=f"cancel committed but the reservation ended {final}; log was {transitions}",
			)
			# Whatever was consumed must have been given back.
			self.assertEqual(
				flt(frappe.db.get_value("Corporate Account", self.account, "credit_used")),
				0.0,
				msg="the cancelled booking is still holding corporate credit",
			)
			self.assertEqual(len(self._consumptions(reservation)), len(self._releases(reservation)))
		else:
			self.assertEqual(final, reservation_service.CONFIRMED)
			self.assertEqual(len(self._consumptions(reservation)), 1)
			self.assertEqual(
				flt(frappe.db.get_value("Corporate Account", self.account, "credit_used")),
				RESERVATION_TOTAL,
			)

		self.assertEqual(
			len(transitions),
			len(ops),
			msg=f"one logged transition per committed operation expected; got {transitions} for {ops}",
		)

		self._assert_ledger_agrees(reservation)

	def test_repeated_confirmation_does_not_consume_credit_twice(self):
		"""Sequential replay: the second confirm is refused and moves no money."""
		reservation = self._reservation()

		reservation_service.confirm(reservation)
		frappe.db.commit()

		with self.assertRaises(InvalidStateTransitionError):
			reservation_service.confirm(reservation)

		frappe.db.rollback()

		self.assertEqual(len(self._consumptions(reservation)), 1)
		self.assertEqual(
			flt(frappe.db.get_value("Corporate Account", self.account, "credit_used")),
			RESERVATION_TOTAL,
		)
		self._assert_ledger_agrees(reservation)

	def test_repeated_cancellation_does_not_release_credit_twice(self):
		"""Sequential replay: the second cancel is refused and releases nothing."""
		reservation = self._reservation()

		reservation_service.confirm(reservation)
		reservation_service.cancel(reservation, "first cancel")
		frappe.db.commit()

		self.assertEqual(len(self._releases(reservation)), 1)

		with self.assertRaises(InvalidStateTransitionError):
			reservation_service.cancel(reservation, "second cancel")

		frappe.db.rollback()

		self.assertEqual(
			len(self._releases(reservation)),
			1,
			msg="a second cancellation released the credit again",
		)
		self.assertEqual(flt(frappe.db.get_value("Corporate Account", self.account, "credit_used")), 0.0)
		self._assert_ledger_agrees(reservation)


class TestOverbookingAuthorization(IntegrationTestCase):
	"""P1-3 - the oversell arithmetic was right; the authority was missing.

	The configured numeric limit is already enforced correctly and is not
	touched here. What was absent is everything around it: the feature switch
	was dead code, any role could oversell, no reason was required, and nothing
	recorded that an override had been used at all.

	A one-room property makes every assertion unambiguous: the first
	confirmation fills the house, so the second can only succeed by overbooking.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()

		cls.fixtures = Fixtures("OVB")
		cls.property = cls.fixtures.property("OB", overbooking_limit=1)
		cls.room_type = cls.fixtures.room_type(cls.property, base_rate=ROOM_RATE)
		cls.fixtures.rooms(cls.property, cls.room_type, count=1)
		cls.rate_plan = cls.fixtures.rate_plan(cls.property, cls.room_type, base_rate=ROOM_RATE)
		cls.guest = cls.fixtures.guest("Oversold")

		cls.agent = cls.fixtures.user("resagent", ["Reservation Agent"], properties=[cls.property])
		cls.manager = cls.fixtures.user(
			"resmgr", ["Reservation Manager"], properties=[cls.property]
		)

		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		cls.fixtures.teardown()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")
		self.fixtures.set_setting("enable_overbooking", 1)

		# Confirmations commit, so without this the house arrives at the next
		# test already full - or already oversold - and every premise collapses.
		self.fixtures.reset_property_records(self.property, ("Reservation Log", "Reservation"))

		# Fill the only room, so anything further needs an override.
		self.filled = self._reservation()
		reservation_service.confirm(self.filled)
		frappe.db.commit()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def _reservation(self) -> str:
		name = self.fixtures.reservation(
			self.property, self.room_type, self.guest, rate_plan=self.rate_plan, nights=1
		)
		frappe.db.commit()

		return name

	def _log_for(self, reservation: str) -> list[dict]:
		return frappe.get_all(
			"Reservation Log",
			filters={"reservation": reservation},
			fields=["from_status", "to_status", "reason", "changed_by", "details", "property"],
			order_by="creation asc",
		)

	# -- the feature switch --------------------------------------------

	def test_normal_confirmation_without_overbooking_is_unchanged(self):
		"""The house is full, so an ordinary confirmation is refused as before."""
		frappe.set_user(self.manager)

		with self.assertRaises(AvailabilityError):
			reservation_service.confirm(self._reservation())

	def test_overbooking_disabled_setting_blocks_override(self):
		"""`enable_overbooking = 0` means no, to everyone, including a manager."""
		self.fixtures.set_setting("enable_overbooking", 0)

		frappe.set_user(self.manager)

		with self.assertRaises(HospitalityPMSError):
			reservation_service.confirm(
				self._reservation(), allow_overbooking=True, reason="Group arriving late"
			)

	def test_overbooking_disabled_setting_blocks_an_administrator_too(self):
		self.fixtures.set_setting("enable_overbooking", 0)

		with self.assertRaises(HospitalityPMSError):
			reservation_service.confirm(
				self._reservation(), allow_overbooking=True, reason="Group arriving late"
			)

	# -- role and reason -------------------------------------------------

	def test_overbooking_requires_an_elevated_role(self):
		"""An ordinary Reservation Agent oversold the house in the sweep."""
		frappe.set_user(self.agent)

		with self.assertRaises(PermissionDeniedError):
			reservation_service.confirm(
				self._reservation(), allow_overbooking=True, reason="Group arriving late"
			)

	def test_overbooking_requires_a_reason(self):
		frappe.set_user(self.manager)

		with self.assertRaises(HospitalityPMSError):
			reservation_service.confirm(self._reservation(), allow_overbooking=True)

		with self.assertRaises(HospitalityPMSError):
			reservation_service.confirm(self._reservation(), allow_overbooking=True, reason="   ")

	# -- the authorised override ----------------------------------------

	def test_authorized_manager_may_overbook_within_the_configured_limit(self):
		frappe.set_user(self.manager)

		reservation = self._reservation()

		self.assertEqual(
			reservation_service.confirm(
				reservation, allow_overbooking=True, reason="Airline crew, contracted"
			),
			reservation_service.CONFIRMED,
		)

	def test_overbooking_beyond_the_configured_limit_is_still_refused(self):
		"""The arithmetic is unchanged: one over is the limit, two is not."""
		frappe.set_user(self.manager)

		reservation_service.confirm(
			self._reservation(), allow_overbooking=True, reason="First override"
		)
		frappe.db.commit()

		with self.assertRaises(AvailabilityError):
			reservation_service.confirm(
				self._reservation(), allow_overbooking=True, reason="Second override"
			)

	def test_overbooking_override_is_audited(self):
		"""Someone must be able to find out that the house was oversold, and why.

		The transition was logged before; that an override was used, by whom,
		against what limit and for what reason was not.
		"""
		frappe.set_user(self.manager)

		reservation = self._reservation()
		reservation_service.confirm(
			reservation, allow_overbooking=True, reason="Airline crew, contracted"
		)

		entries = self._log_for(reservation)

		self.assertEqual(len(entries), 1)
		entry = entries[0]

		self.assertEqual(entry["changed_by"], self.manager)
		self.assertEqual(entry["property"], self.property)
		self.assertEqual(entry["reason"], "Airline crew, contracted")

		details = frappe.parse_json(entry["details"])

		self.assertTrue(details.get("overbooking_override"))
		self.assertEqual(details.get("overbooking_reason"), "Airline crew, contracted")
		self.assertEqual(details.get("overbooking_limit"), 1)
		self.assertEqual(details.get("overbooking_rooms"), 1)
		self.assertTrue(details.get("business_date"))

	def test_ordinary_confirmation_records_no_override(self):
		"""A booking that fitted must not look like an oversell in the audit.

		`self.filled` is the confirmation setUp made while the room was still
		free - an ordinary one, needing no flag and no authority.
		"""
		details = frappe.parse_json(self._log_for(self.filled)[0]["details"]) or {}

		self.assertFalse(details.get("overbooking_override"))
		self.assertNotIn("overbooking_reason", details)

	# -- the other surface that exposes the flag ------------------------

	def test_stay_extension_overbooking_requires_role_and_reason(self):
		"""`extend_stay` takes the same flag and needs the same authority.

		Only the authorisation is addressed here. Whether an extension is
		reflected in sellable inventory at all is P1-5, and belongs to the
		inventory wave.
		"""
		from hospitality_pms.services import stays as stay_service

		frappe.set_user(self.agent)

		with self.assertRaises(PermissionDeniedError):
			stay_service.extend_stay(
				"HPMS-STAY-DOES-NOT-EXIST",
				add_days(frappe.db.get_value("Property", self.property, "business_date"), 5),
				allow_overbooking=True,
				reason="Guest extended",
			)

	def test_stay_extension_overbooking_is_blocked_when_disabled(self):
		from hospitality_pms.services import stays as stay_service

		self.fixtures.set_setting("enable_overbooking", 0)
		frappe.set_user(self.manager)

		with self.assertRaises(HospitalityPMSError):
			stay_service.extend_stay(
				"HPMS-STAY-DOES-NOT-EXIST",
				add_days(frappe.db.get_value("Property", self.property, "business_date"), 5),
				allow_overbooking=True,
				reason="Guest extended",
			)


class TestNoShowReleasesCorporateCredit(IntegrationTestCase):
	"""P1 (RES-2) — a no-show must return the corporate credit it consumed.

	`cancel()` releases credit before its transition; `mark_no_show` did not, and
	because `_release_corporate_credit` early-returns once the status leaves the
	holding states, the sanctioned NO_SHOW -> CANCELLED follow-up released nothing
	either. The consumed credit was stranded, and enough no-shows locked the
	account out of every future booking for money the hotel will never bill.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.fixtures = Fixtures("RNSC")
		cls.property = cls.fixtures.property("NS")
		cls.room_type = cls.fixtures.room_type(cls.property, base_rate=ROOM_RATE)
		cls.fixtures.rooms(cls.property, cls.room_type, count=2)
		cls.rate_plan = cls.fixtures.rate_plan(cls.property, cls.room_type, base_rate=ROOM_RATE)
		cls.guest = cls.fixtures.guest("NoShow")
		cls.account = cls.fixtures.corporate_account(cls.property, credit_limit=10000)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		cls.fixtures.teardown()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.set_value(
			"Corporate Account",
			self.account,
			{"credit_used": 0, "credit_available": 10000},
			update_modified=False,
		)
		frappe.db.delete("Corporate Credit Log", {"corporate_account": self.account})
		frappe.db.commit()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_no_show_releases_the_consumed_credit(self):
		reservation = self.fixtures.reservation(
			self.property,
			self.room_type,
			self.guest,
			rate_plan=self.rate_plan,
			nights=NIGHTS,
			corporate_account=self.account,
		)
		reservation_service.confirm(reservation)
		frappe.db.commit()

		self.assertEqual(
			flt(frappe.db.get_value("Corporate Account", self.account, "credit_used")),
			RESERVATION_TOTAL,
			msg="confirmation should have consumed the booking's credit",
		)

		reservation_service.mark_no_show(reservation, reason="nobody arrived")

		self.assertEqual(
			flt(frappe.db.get_value("Corporate Account", self.account, "credit_used")),
			0.0,
			msg="the no-show did not release the consumed corporate credit",
		)
		released = frappe.get_all(
			"Corporate Credit Log",
			filters={"corporate_account": self.account, "action": "Credit released"},
			pluck="name",
		)
		self.assertTrue(released, msg="no credit-release movement was recorded for the no-show")


class TestDepositReceivedGuard(IntegrationTestCase):
	"""P0 (RES-1) — deposit_received is money the hotel holds and must not be
	settable through the document API.

	The field is read at check-in and converted, pound for pound, into a folio
	Deposit payment. It is read_only (a UI hint only) at permlevel 0, so nothing
	stopped a reservation-write role setting it via the create payload or a plain
	doc.save() and minting a payment the drawer never took. Its sanctioned writer
	is the payments service, which writes it directly (db.set_value), bypassing the
	controller - so the guard closes the fabrication without blocking that writer.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.fixtures = Fixtures("RDEP")
		cls.property = cls.fixtures.property("DP")
		cls.room_type = cls.fixtures.room_type(cls.property, base_rate=ROOM_RATE)
		cls.fixtures.rooms(cls.property, cls.room_type, count=2)
		cls.rate_plan = cls.fixtures.rate_plan(cls.property, cls.room_type, base_rate=ROOM_RATE)
		cls.guest = cls.fixtures.guest("Deposit")
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		cls.fixtures.teardown()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def _payload(self, deposit_received=None) -> dict:
		arrival = frappe.db.get_value("Property", self.property, "business_date")
		payload = {
			"doctype": "Reservation",
			"property": self.property,
			"reservation_status": "Draft",
			"reservation_type": "Individual",
			"guest": self.guest,
			"arrival_date": arrival,
			"departure_date": add_days(arrival, NIGHTS),
			"rate_plan": self.rate_plan,
			"rooms": [
				{
					"room_type": self.room_type,
					"rooms": 1,
					"adults": 1,
					"arrival_date": arrival,
					"departure_date": add_days(arrival, NIGHTS),
				}
			],
		}
		if deposit_received is not None:
			payload["deposit_received"] = deposit_received
		return payload

	def test_create_cannot_set_deposit_received(self):
		with self.assertRaises(InvalidStateTransitionError):
			frappe.get_doc(self._payload(deposit_received=500)).insert(ignore_permissions=True)

	def test_editing_deposit_received_is_refused(self):
		name = frappe.get_doc(self._payload()).insert(ignore_permissions=True).name
		frappe.db.commit()

		doc = frappe.get_doc("Reservation", name)
		doc.deposit_received = 300
		with self.assertRaises(InvalidStateTransitionError):
			doc.save(ignore_permissions=True)

	def test_payments_service_writer_still_works(self):
		# The sanctioned path is a direct write, which does not pass through the
		# controller guard; it must keep working.
		name = frappe.get_doc(self._payload()).insert(ignore_permissions=True).name
		frappe.db.set_value("Reservation", name, "deposit_received", 250, update_modified=False)
		self.assertEqual(flt(frappe.db.get_value("Reservation", name, "deposit_received")), 250.0)
