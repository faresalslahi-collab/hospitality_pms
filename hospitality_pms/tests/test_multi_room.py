"""P1-6, first half — three rooms booked, one room usable.

A three-room booking was one `Reservation Room` row carrying `rooms = 3`.
Inventory counted that correctly, and everything operational broke on it: one
row can hold one assigned room, produce one Stay and open one Folio, so the
second and third rooms could never be checked in — and the reservation was
marked fully Checked In the moment the first guest arrived, because every row it
had was accounted for.

The fix is not to teach check-in to consume one row three times. It is to stop
representing three rooms as one row: at confirmation, a quantity is normalised
into one operational row per physical room, each with `rooms = 1`.

A quantity remains a perfectly good way to *ask* for three rooms while the
booking is still a draft. It is not a way to *run* three rooms.
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from hospitality_pms.services import reservations as reservation_service
from hospitality_pms.services import stays as stay_service
from hospitality_pms.services.exceptions import AvailabilityError
from hospitality_pms.tests.inventory_world import InventoryWorld

PRECISION = 2


class MultiRoomTestCase(IntegrationTestCase):
	ROOMS = 4

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


class TestNormalization(MultiRoomTestCase):
	WORLD_CODE = "MN"

	def test_draft_may_still_ask_for_a_quantity(self):
		"""Nothing is taken away from the way a booking is made."""
		reservation = self.world.reservation(rooms=3)

		lines = self.world.lines(reservation)

		self.assertEqual(len(lines), 1)
		self.assertEqual(lines[0]["rooms"], 3)

	def test_confirm_normalizes_multi_room_quantity(self):
		reservation = self.world.confirmed(rooms=3)

		lines = self.world.lines(reservation)

		self.assertEqual(
			len(lines), 3, msg=f"three rooms should be three operational rows; got {lines}"
		)
		self.assertEqual(
			[line["rooms"] for line in lines],
			[1, 1, 1],
			msg="a confirmed booking must not carry a quantity",
		)

	def test_normalization_is_idempotent(self):
		reservation = self.world.confirmed(rooms=3)

		# Re-running the normalisation must not multiply the rows again.
		doc = frappe.get_doc("Reservation", reservation)
		reservation_service.normalise_room_lines(doc)
		doc.save(ignore_permissions=True)

		self.assertEqual(len(self.world.lines(reservation)), 3)

	def test_normalization_preserves_reservation_total(self):
		"""Splitting the row must not multiply the price."""
		draft = self.world.reservation(rooms=3)
		before = flt(frappe.db.get_value("Reservation", draft, "total_amount"))

		reservation_service.confirm(draft)

		after = flt(frappe.db.get_value("Reservation", draft, "total_amount"))
		lines = self.world.lines(draft)

		self.assertMoney(after, before, msg="normalisation changed what the guest was quoted")
		self.assertMoney(sum(flt(line["total_amount"]) for line in lines), after)

	def test_normalization_preserves_occupancy_totals(self):
		draft = self.world.reservation(rooms=3)
		before = frappe.db.get_value(
			"Reservation", draft, ["total_rooms", "total_adults"], as_dict=True
		)

		reservation_service.confirm(draft)

		after = frappe.db.get_value(
			"Reservation", draft, ["total_rooms", "total_adults"], as_dict=True
		)

		self.assertEqual(after["total_rooms"], before["total_rooms"])
		self.assertEqual(after["total_adults"], before["total_adults"])

	def test_a_single_room_booking_is_unchanged(self):
		reservation = self.world.confirmed(rooms=1)

		lines = self.world.lines(reservation)

		self.assertEqual(len(lines), 1)
		self.assertEqual(lines[0]["rooms"], 1)

	def test_inventory_still_holds_the_whole_quantity(self):
		"""Three rows must sell exactly what one row of three sold."""
		self.world.confirmed(rooms=3)

		self.assertEqual(self.world.sold(0, 2), 3)
		self.assertEqual(self.world.available(0, 2), 1)

	def test_confirmation_refuses_a_quantity_the_house_cannot_hold(self):
		"""Three separate checks for one room each must not pass for three rooms.

		The aggregate is what matters: splitting the request into rows must not
		split the capacity question along with it.
		"""
		draft = self.world.reservation(rooms=5)

		with self.assertRaises(AvailabilityError):
			reservation_service.confirm(draft)

		self.assertNotEqual(
			frappe.db.get_value("Reservation", draft, "reservation_status"),
			reservation_service.CONFIRMED,
		)


class TestMultiRoomCheckIn(MultiRoomTestCase):
	"""Each booked room arrives on its own."""

	WORLD_CODE = "MC"

	def test_three_room_reservation_creates_three_operational_lines(self):
		reservation = self.world.confirmed(rooms=3)

		self.assertEqual(len(self.world.lines(reservation)), 3)

	def test_check_in_all_rooms_requires_three_stays(self):
		reservation = self.world.confirmed(rooms=3)
		lines = self.world.lines(reservation)

		self.world.check_in(reservation, line=lines[0]["name"])
		self.assertEqual(self._stay_count(reservation), 1)
		self.assertEqual(
			frappe.db.get_value("Reservation", reservation, "reservation_status"),
			reservation_service.CONFIRMED,
			msg="the booking was marked fully checked in after only one room arrived",
		)

		self.world.check_in(reservation, line=lines[1]["name"])
		self.assertEqual(self._stay_count(reservation), 2)
		self.assertEqual(
			frappe.db.get_value("Reservation", reservation, "reservation_status"),
			reservation_service.CONFIRMED,
		)

		self.world.check_in(reservation, line=lines[2]["name"])
		self.assertEqual(self._stay_count(reservation), 3)
		self.assertEqual(
			frappe.db.get_value("Reservation", reservation, "reservation_status"),
			reservation_service.CHECKED_IN,
		)

	def test_each_room_gets_its_own_physical_room_and_folio(self):
		reservation = self.world.confirmed(rooms=3)
		lines = self.world.lines(reservation)

		results = [self.world.check_in(reservation, line=line["name"]) for line in lines]

		self.assertEqual(len({r["room"] for r in results}), 3, msg="rooms were reused")
		self.assertEqual(len({r["folio"] for r in results}), 3, msg="folios were reused")

		occupied = frappe.get_all(
			"Hotel Room",
			filters={"name": ("in", [r["room"] for r in results])},
			fields=["name", "occupancy_status"],
		)
		self.assertTrue(all(row["occupancy_status"] == "Occupied" for row in occupied))

	def test_checking_the_same_line_in_twice_is_refused(self):
		from hospitality_pms.services.exceptions import InvalidStateTransitionError

		reservation = self.world.confirmed(rooms=3)
		lines = self.world.lines(reservation)

		self.world.check_in(reservation, line=lines[0]["name"])

		with self.assertRaises(InvalidStateTransitionError):
			stay_service.check_in(reservation, lines[0]["name"], self.world.rooms[3])

	def test_cancelling_releases_every_normalised_line(self):
		"""Part 12 — a full cancel still frees the whole booking."""
		reservation = self.world.confirmed(rooms=3)

		self.assertEqual(self.world.sold(0, 2), 3)

		reservation_service.cancel(reservation, "guest cancelled the whole booking")

		self.assertEqual(self.world.sold(0, 2), 0)
		self.assertEqual(self.world.available(0, 2), 4)

	def _stay_count(self, reservation: str) -> int:
		return frappe.db.count("Stay", {"reservation": reservation})
