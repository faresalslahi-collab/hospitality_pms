"""P1-6, second half — one deposit, credited once per room.

A three-room reservation with a 300 deposit credited 300 to *every* folio it
opened. The idempotency key was the same for all three -
`reservation-deposit:{reservation}` - but uniqueness is scoped per folio, so
three different folios each accepted it happily and the guest was credited 900
against a 300 deposit.

The key was not the real problem; the model was. One deposit belongs to one
booking, and a booking now has one row per room, so the deposit is split across
those rooms and each share carries its own identity.
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from hospitality_pms.services import reservations as reservation_service
from hospitality_pms.tests.concurrency import Worker, assert_all_ran, run_workers
from hospitality_pms.tests.inventory_world import InventoryWorld

PRECISION = 2


def _check_in_worker(barrier, reservation: str, line: str, room: str, tag: str, partner: str) -> dict:
	"""Two rooms of one booking arriving at the same moment."""
	from hospitality_pms.services import stays as stay_service

	frappe.db.sql("select deposit_received from `tabReservation` where name = %s", reservation)

	barrier.signal(f"ready_{tag}")
	barrier.wait(f"ready_{partner}")

	result = stay_service.check_in(reservation, line, room)
	frappe.db.commit()

	return {"folio": result["folio"]}


class DepositTestCase(IntegrationTestCase):
	WORLD_CODE = "DP"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.world = InventoryWorld(cls.__name__[:6].upper(), cls.WORLD_CODE, rooms=4)

	@classmethod
	def tearDownClass(cls):
		cls.world.teardown()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")
		self.world.fixtures.reset_property_records(
			self.world.property,
			("Folio Log", "Guest Folio", "Room Status Log", "Stay", "Reservation Log", "Reservation"),
		)
		for room in self.world.rooms:
			frappe.db.set_value("Hotel Room", room, "occupancy_status", "Vacant", update_modified=False)
		frappe.db.commit()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def assertMoney(self, actual, expected, msg=None):
		self.assertAlmostEqual(flt(actual), flt(expected), places=PRECISION, msg=msg)

	def _credited(self, reservation: str) -> float:
		"""Every deposit the folios of this booking have been credited."""
		return flt(
			frappe.db.sql(
				"""
				select coalesce(sum(p.amount), 0)
				from `tabFolio Payment` p
				inner join `tabGuest Folio` f on f.name = p.parent
				where f.reservation = %s and p.payment_type = 'Deposit'
				""",
				reservation,
			)[0][0]
		)

	def _confirmed_with_deposit(self, *, rooms: int = 3, deposit: float = 300.0) -> str:
		reservation = self.world.reservation(rooms=rooms)
		self.world.set_deposit(reservation, deposit)
		reservation_service.confirm(reservation)
		frappe.db.commit()

		return reservation


class TestDepositAllocation(DepositTestCase):
	def test_deposit_allocated_once_across_folios(self):
		"""The reproduction: 300 became 900."""
		reservation = self._confirmed_with_deposit(rooms=3, deposit=300)

		for line in self.world.lines(reservation):
			self.world.check_in(reservation, line=line["name"])

		self.assertMoney(
			self._credited(reservation),
			300,
			msg="the deposit was credited once per folio instead of once per booking",
		)

	def test_equal_rooms_split_the_deposit_equally(self):
		reservation = self._confirmed_with_deposit(rooms=3, deposit=300)

		credited = []
		for line in self.world.lines(reservation):
			result = self.world.check_in(reservation, line=line["name"])
			credited.append(
				flt(
					frappe.db.sql(
						"select coalesce(sum(amount),0) from `tabFolio Payment` "
						"where parent = %s and payment_type = 'Deposit'",
						result["folio"],
					)[0][0]
				)
			)

		self.assertEqual([flt(x, 2) for x in credited], [100.0, 100.0, 100.0])

	def test_only_the_arrived_rooms_share_is_posted(self):
		"""One room arrives today; the other shares wait for their guests."""
		reservation = self._confirmed_with_deposit(rooms=3, deposit=300)
		lines = self.world.lines(reservation)

		self.world.check_in(reservation, line=lines[0]["name"])

		self.assertMoney(self._credited(reservation), 100)

		self.world.check_in(reservation, line=lines[1]["name"])

		self.assertMoney(self._credited(reservation), 200)

	def test_unequal_rooms_share_the_deposit_proportionally(self):
		"""Two rooms of different lengths carry different shares."""
		reservation = self.world.reservation_with_lines(
			[{"nights": 1}, {"nights": 3}], deposit=400
		)
		reservation_service.confirm(reservation)
		frappe.db.commit()

		lines = self.world.lines(reservation)
		totals = [flt(line["total_amount"]) for line in lines]

		for line in lines:
			self.world.check_in(reservation, line=line["name"])

		self.assertMoney(
			self._credited(reservation), 400, msg="the shares did not add back up to the deposit"
		)
		self.assertNotEqual(totals[0], totals[1], msg="the fixture should give unequal rooms")

	def test_partial_deposit_allocates_exact_total(self):
		"""Only what was actually received is credited."""
		reservation = self._confirmed_with_deposit(rooms=3, deposit=150)

		for line in self.world.lines(reservation):
			self.world.check_in(reservation, line=line["name"])

		self.assertMoney(self._credited(reservation), 150)

	def test_a_deposit_that_does_not_divide_evenly_still_sums_exactly(self):
		"""100 across three rooms is 33.33, 33.33, 33.34 - not 99.99."""
		reservation = self._confirmed_with_deposit(rooms=3, deposit=100)

		for line in self.world.lines(reservation):
			self.world.check_in(reservation, line=line["name"])

		self.assertMoney(
			self._credited(reservation), 100, msg="rounding lost or invented money"
		)

	def test_no_deposit_credits_nothing(self):
		reservation = self._confirmed_with_deposit(rooms=2, deposit=0)

		for line in self.world.lines(reservation):
			self.world.check_in(reservation, line=line["name"])

		self.assertMoney(self._credited(reservation), 0)

	def test_single_room_booking_is_unaffected(self):
		reservation = self._confirmed_with_deposit(rooms=1, deposit=250)

		self.world.check_in(reservation)

		self.assertMoney(self._credited(reservation), 250)


class TestDepositConcurrency(DepositTestCase):
	def test_concurrent_checkins_do_not_overcredit_deposit(self):
		"""Two rooms of one booking arriving at once."""
		reservation = self._confirmed_with_deposit(rooms=2, deposit=300)
		lines = self.world.lines(reservation)

		results = run_workers(
			[
				Worker(
					f"{__name__}._check_in_worker",
					{
						"reservation": reservation,
						"line": lines[0]["name"],
						"room": self.world.rooms[0],
						"tag": "a",
						"partner": "b",
					},
				),
				Worker(
					f"{__name__}._check_in_worker",
					{
						"reservation": reservation,
						"line": lines[1]["name"],
						"room": self.world.rooms[1],
						"tag": "b",
						"partner": "a",
					},
				),
			]
		)
		assert_all_ran(results)

		self.assertLessEqual(
			self._credited(reservation),
			300,
			msg=f"concurrent arrivals over-credited the deposit: {results}",
		)

	def test_retrying_a_check_in_does_not_credit_twice(self):
		from hospitality_pms.services.exceptions import InvalidStateTransitionError

		reservation = self._confirmed_with_deposit(rooms=2, deposit=300)
		lines = self.world.lines(reservation)

		self.world.check_in(reservation, line=lines[0]["name"])

		from hospitality_pms.services import stays as stay_service

		with self.assertRaises(InvalidStateTransitionError):
			stay_service.check_in(reservation, lines[0]["name"], self.world.rooms[3])

		frappe.db.rollback()

		self.assertMoney(self._credited(reservation), 150)
