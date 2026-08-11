# Copyright (c) 2026, Globcom Qatar and Contributors
# See license.txt

"""A booking that has already been partly consumed may not be ended.

`stays.check_in` moves a Reservation to `Checked In` only once every one of its
room lines is in house, so a three-room booking with one guest upstairs still
reads `Confirmed` at the header - and `Cancelled` and `No Show` are both legal
transitions from there. Cancelling in that state left two guests in rooms
attached to a cancelled booking, their Stays `In House` and their folios open,
released corporate credit for nights that had been slept, and stamped
`Cancelled` onto every room line so the party disappeared from the arrivals
board while the people were still in the hotel.

The guard lives in `reservations._assert_no_unfinished_stay`, beside the
existing `assert_transition` and inside the Reservation row lock, so every
caller - the API, the Vue screens, the night audit and the Arrivals drawer
16.7.1 is about to ship - inherits it.

Real data throughout: real reservations, real check-ins, real stays, real
corporate credit movements.
"""

import unittest

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from hospitality_pms.services import night_audit as audit_service
from hospitality_pms.services import reservations as reservation_service
from hospitality_pms.services import stays as stay_service
from hospitality_pms.services.exceptions import InvalidStateTransitionError
from hospitality_pms.tests.inventory_world import InventoryWorld

CANCEL_REASON = "guest asked to cancel the whole booking"
NO_SHOW_REASON = "nobody arrived"

#: Operational residue to clear between tests. Check-ins commit, so a stay left
#: behind by the previous test would satisfy - or violate - the next test's
#: premise before it started.
RESET = (
	"Folio Log",
	"Guest Folio",
	"Room Status Log",
	"Stay",
	"Night Audit",
	"Reservation Log",
	"Reservation",
)


class GuardTestCase(IntegrationTestCase):
	"""A property with enough rooms for a three-room booking and spares."""

	ROOMS = 6

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.world = InventoryWorld(cls.__name__[:6].upper(), cls.WORLD_CODE, rooms=cls.ROOMS)

	@classmethod
	def tearDownClass(cls):
		cls.world.teardown()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")
		self.world.fixtures.reset_property_records(self.world.property, RESET)

		for room in self.world.rooms:
			frappe.db.set_value("Hotel Room", room, "occupancy_status", "Vacant", update_modified=False)

		frappe.db.commit()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	# -- helpers ------------------------------------------------------------

	def status(self, reservation: str) -> str:
		return frappe.db.get_value("Reservation", reservation, "reservation_status")

	def line_statuses(self, reservation: str) -> list[str]:
		return frappe.get_all(
			"Reservation Room", filters={"parent": reservation}, pluck="reservation_status"
		)

	def close_stay(self, stay: str):
		"""Take a stay all the way to `Closed`, the one terminal state."""
		stay_service.transition(stay, stay_service.CHECKED_OUT, reason="test checkout")
		stay_service.transition(stay, stay_service.CLOSED, reason="test close")
		frappe.db.commit()


class TestCancellationGuard(GuardTestCase):
	WORLD_CODE = "CG"

	def test_cancel_refuses_when_a_room_is_already_checked_in(self):
		reservation = self.world.confirmed(rooms=3)
		self.world.check_in(reservation)

		with self.assertRaises(InvalidStateTransitionError):
			reservation_service.cancel(reservation, CANCEL_REASON)

		frappe.db.rollback()

		self.assertEqual(
			self.status(reservation),
			reservation_service.CONFIRMED,
			msg="a booking with a guest in a room was cancelled",
		)

	def test_no_show_refuses_when_a_room_is_already_checked_in(self):
		reservation = self.world.confirmed(rooms=3)
		self.world.check_in(reservation)

		with self.assertRaises(InvalidStateTransitionError):
			reservation_service.mark_no_show(reservation, reason=NO_SHOW_REASON)

		frappe.db.rollback()

		self.assertEqual(
			self.status(reservation),
			reservation_service.CONFIRMED,
			msg="a guest who had physically arrived was recorded as a no-show",
		)

	def test_cancel_still_allowed_when_no_stay_exists(self):
		"""The ordinary case, or the guard proves nothing."""
		reservation = self.world.confirmed(rooms=3)

		result = reservation_service.cancel(reservation, CANCEL_REASON)

		self.assertEqual(result["status"], reservation_service.CANCELLED)
		self.assertEqual(self.status(reservation), reservation_service.CANCELLED)

	def test_no_show_still_allowed_when_no_stay_exists(self):
		reservation = self.world.confirmed(rooms=3)

		result = reservation_service.mark_no_show(reservation, reason=NO_SHOW_REASON)

		self.assertEqual(result["status"], reservation_service.NO_SHOW)
		self.assertEqual(self.status(reservation), reservation_service.NO_SHOW)

	def test_cancel_allowed_when_every_stay_is_closed(self):
		"""`Closed` is history, not a live stay.

		One room of three arrived, departed and had its stay closed; the other
		two never came. Nothing of this booking is live, so the desk may still
		cancel it.
		"""
		reservation = self.world.confirmed(rooms=3)
		stay = self.world.check_in(reservation)["stay"]
		self.close_stay(stay)

		result = reservation_service.cancel(reservation, CANCEL_REASON)

		self.assertEqual(result["status"], reservation_service.CANCELLED)
		self.assertEqual(self.status(reservation), reservation_service.CANCELLED)

	def test_checked_out_but_unclosed_stay_still_blocks_a_cancel(self):
		"""The other half of the chosen set: `Checked Out` is not finished.

		The guest slept in the room and their folio is not yet put to bed, so
		cancelling the booking would still be a lie about a night that happened.
		"""
		reservation = self.world.confirmed(rooms=3)
		stay = self.world.check_in(reservation)["stay"]
		stay_service.transition(stay, stay_service.CHECKED_OUT, reason="test checkout")
		frappe.db.commit()

		with self.assertRaises(InvalidStateTransitionError):
			reservation_service.cancel(reservation, CANCEL_REASON)

		frappe.db.rollback()

		self.assertEqual(self.status(reservation), reservation_service.CONFIRMED)

	def test_room_lines_are_not_stamped_cancelled_on_a_refused_cancel(self):
		"""`_propagate_status` must not have run.

		This is what made the defect invisible to the desk: the lines carry the
		status the arrivals board filters on, so stamping them `Cancelled`
		removed the booking from the board while its guests were upstairs.
		"""
		reservation = self.world.confirmed(rooms=3)
		self.world.check_in(reservation)

		with self.assertRaises(InvalidStateTransitionError):
			reservation_service.cancel(reservation, CANCEL_REASON)

		frappe.db.rollback()

		statuses = self.line_statuses(reservation)

		self.assertEqual(len(statuses), 3)
		self.assertEqual(
			set(statuses),
			{reservation_service.CONFIRMED},
			msg=f"a refused cancellation still stamped the room lines: {statuses}",
		)


class TestGuardAndCorporateCredit(GuardTestCase):
	"""The side effect that made this dangerous rather than merely untidy."""

	WORLD_CODE = "CC"
	CREDIT_LIMIT = 10000.0

	def setUp(self):
		super().setUp()

		self.account = self.world.fixtures.corporate_account(
			self.world.property, credit_limit=self.CREDIT_LIMIT
		)
		frappe.db.set_value(
			"Corporate Account",
			self.account,
			{"credit_used": 0, "credit_available": self.CREDIT_LIMIT},
			update_modified=False,
		)
		frappe.db.delete("Corporate Credit Log", {"corporate_account": self.account})
		frappe.db.commit()

	def _corporate_reservation(self, *, rooms: int = 3) -> str:
		name = self.world.fixtures.reservation(
			self.world.property,
			self.world.room_type,
			self.world.fixtures.guest("Corporate"),
			rate_plan=self.world.rate_plan,
			arrival=self.world.business_date,
			nights=2,
			rooms=rooms,
			corporate_account=self.account,
		)
		reservation_service.confirm(name)
		frappe.db.commit()

		return name

	def _releases(self) -> list[dict]:
		return frappe.get_all(
			"Corporate Credit Log",
			filters={"corporate_account": self.account, "action": "Credit released"},
			fields=["action", "amount"],
		)

	def test_guard_does_not_release_corporate_credit_for_consumed_rooms(self):
		reservation = self._corporate_reservation()
		consumed = flt(frappe.db.get_value("Corporate Account", self.account, "credit_used"))

		self.assertGreater(consumed, 0, msg="fixture consumed no credit, so nothing is being proved")

		self.world.check_in(reservation)

		with self.assertRaises(InvalidStateTransitionError):
			reservation_service.cancel(reservation, CANCEL_REASON)

		frappe.db.rollback()

		self.assertEqual(
			self._releases(),
			[],
			msg="a refused cancellation released credit for rooms the guests were sleeping in",
		)
		self.assertEqual(
			flt(frappe.db.get_value("Corporate Account", self.account, "credit_used")),
			consumed,
			msg="the account balance moved on a refused cancellation",
		)


class TestNightAuditNoShowSweep(GuardTestCase):
	"""The night audit keeps working, and this is where it proves it.

	`night_audit.mark_no_shows` sweeps `reservations.get_unresolved_arrivals`,
	which selects on the *header* status - `Confirmed` or `Guaranteed` with an
	arrival on or before the business date. A partly-arrived multi-room booking
	is exactly that (its header does not move until the whole party is in
	house), so the sweep does reach it and the guard refuses it.

	That refusal used to propagate out of the loop and end the whole step. It is
	now contained per booking in a savepoint (`services/night_audit.py`), so a
	genuine no-show is still marked while the partly-arrived booking is skipped
	and left as an unresolved arrival - which `review` already raises as a
	*blocking* exception, so the day still cannot close until a human decides
	whether the rest of that party is coming.
	"""

	WORLD_CODE = "NS"

	def _sweep_world(self) -> tuple[str, str, str]:
		"""One genuine no-show, one partly-arrived booking, and an open audit."""
		genuine = self.world.confirmed(rooms=1)
		partly = self.world.confirmed(rooms=3)
		self.world.check_in(partly)

		audit = audit_service.start(self.world.property)
		frappe.db.commit()

		return genuine, partly, audit

	def test_the_sweep_reaches_a_partly_arrived_booking_at_all(self):
		"""Evidence for the escalation: the premise "it never sees one" is false."""
		genuine, partly, _audit = self._sweep_world()

		unresolved = [
			row["name"]
			for row in reservation_service.get_unresolved_arrivals(
				self.world.property, self.world.business_date
			)
		]

		self.assertIn(genuine, unresolved)
		self.assertIn(
			partly,
			unresolved,
			msg="a partly-arrived booking is presented to the no-show sweep as an unresolved arrival",
		)

	def test_night_audit_no_show_sweep_does_not_abort_on_a_refusal(self):
		"""The step completes and records a count, rather than raising.

		This is the regression guard for the containment: before it, the first
		refused booking ended the sweep and `no_shows` was never written.
		"""
		_genuine, _partly, audit = self._sweep_world()

		audit_service.mark_no_shows(audit)

		self.assertEqual(
			frappe.db.get_value("Night Audit", audit, "no_shows"),
			1,
			msg="the sweep did not record the genuine no-show it managed to mark",
		)

	def test_night_audit_no_show_sweep_still_marks_genuine_no_shows(self):
		"""A genuine no-show is marked; a partly-arrived booking is left alone.

		The whole point of containing the refusal: one booking the guard protects
		must not cost the property every other no-show of the night.
		"""
		genuine, partly, audit = self._sweep_world()

		marked = audit_service.mark_no_shows(audit)

		self.assertEqual(marked, [genuine])
		self.assertEqual(self.status(genuine), reservation_service.NO_SHOW)
		self.assertEqual(self.status(partly), reservation_service.CONFIRMED)

	def test_a_skipped_booking_remains_a_blocking_unresolved_arrival(self):
		"""Skipping hides nothing: the day still cannot close on it.

		`review` raises a blocking "Unresolved Arrival" exception for every
		reservation the sweep did not resolve, so the partly-arrived booking the
		guard refused is still in front of the auditor - which is the correct
		outcome, because only a human can decide whether the rest of that party
		is arriving.
		"""
		_genuine, partly, audit = self._sweep_world()

		audit_service.mark_no_shows(audit)
		audit_service.review(audit)

		blocking = frappe.get_all(
			"Night Audit Exception",
			filters={
				"parent": audit,
				"exception_type": "Unresolved Arrival",
				"reference_name": partly,
			},
			fields=["severity"],
		)

		self.assertTrue(blocking, msg="the skipped booking raised no unresolved-arrival exception")
		self.assertEqual(blocking[0]["severity"], "Blocking")
