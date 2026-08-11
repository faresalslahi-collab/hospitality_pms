"""N8 — the room picker offered rooms that were already promised.

`get_assignable_rooms` filtered on the room's own state: sellable, unblocked,
clean. It never asked the one question room assignment exists to answer - is
this room already promised to somebody for these dates? So the list happily
offered the room an in-house guest was sleeping in, and the room the 3pm
arrival had been assigned that morning.

The list is advisory: a front desk agent picks from it. `assign_room` is the
authority, and it re-checks everything under a lock, because between rendering
a list and clicking a room somebody else can take it. What the list must not do
is offer a choice that assignment will then refuse - that is not a safety
failure, it is a usability one, and it is how rooms get double-promised in
practice.
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days

from hospitality_pms.services import reservations as reservation_service
from hospitality_pms.services.availability import get_assignable_rooms
from hospitality_pms.services.exceptions import HospitalityPMSError, RoomNotAssignableError
from hospitality_pms.tests.concurrency import Worker, assert_all_ran, run_workers
from hospitality_pms.tests.inventory_world import InventoryWorld


def _assign_worker(barrier, reservation: str, line: str, room: str, tag: str, partner: str) -> dict:
	"""Two agents clicking the same room at the same moment."""
	frappe.db.sql("select assigned_room from `tabReservation Room` where name = %s", line)

	barrier.signal(f"ready_{tag}")
	barrier.wait(f"ready_{partner}")

	reservation_service.assign_room(reservation, line, room)
	frappe.db.commit()

	return {"assigned": room}


class RoomAssignmentTestCase(IntegrationTestCase):
	ROOMS = 3

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
			frappe.db.set_value(
				"Hotel Room",
				room,
				{
					"occupancy_status": "Vacant",
					"housekeeping_status": "Clean",
					"maintenance_status": "Operational",
					"inventory_status": "Available",
				},
				update_modified=False,
			)
		frappe.db.commit()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def _offered(self, start: int, end: int, **kwargs) -> set[str]:
		return {
			row["name"]
			for row in get_assignable_rooms(
				self.world.property, self.world.room_type, self.world.day(start), self.world.day(end), **kwargs
			)
		}


class TestAssignableRooms(RoomAssignmentTestCase):
	WORLD_CODE = "RA"

	def test_all_rooms_are_offered_when_the_house_is_empty(self):
		self.assertEqual(self._offered(0, 2), set(self.world.rooms))

	def test_a_room_promised_to_an_overlapping_stay_is_not_offered(self):
		"""The reproduction: the picker ignored existing assignments."""
		reservation = self.world.confirmed(nights=4)
		line = self.world.lines(reservation)[0]["name"]
		reservation_service.assign_room(reservation, line, self.world.rooms[0])
		frappe.db.commit()

		self.assertNotIn(
			self.world.rooms[0],
			self._offered(1, 3),
			msg="a room already promised for these dates was offered again",
		)

	def test_a_room_promised_outside_the_interval_is_still_offered(self):
		"""Same-day turnover is normal hotel work, not a conflict."""
		reservation = self.world.confirmed(nights=2)
		line = self.world.lines(reservation)[0]["name"]
		reservation_service.assign_room(reservation, line, self.world.rooms[0])
		frappe.db.commit()

		self.assertIn(self.world.rooms[0], self._offered(2, 4))

	def test_a_room_promised_to_a_cancelled_line_is_offered(self):
		reservation = self.world.confirmed(nights=4)
		line = self.world.lines(reservation)[0]["name"]
		reservation_service.assign_room(reservation, line, self.world.rooms[0])
		reservation_service.cancel(reservation, "guest changed their mind")
		frappe.db.commit()

		self.assertIn(self.world.rooms[0], self._offered(1, 3))

	def test_an_occupied_room_is_not_offered_for_an_arrival_today(self):
		reservation = self.world.confirmed(nights=4)
		self.world.check_in(reservation, room=self.world.rooms[0])

		self.assertNotIn(
			self.world.rooms[0],
			self._offered(0, 2),
			msg="the room an in-house guest is sleeping in was offered",
		)

	def test_a_room_free_again_by_the_arrival_date_is_offered(self):
		"""Occupied today says nothing about a stay that starts next week."""
		reservation = self.world.confirmed(nights=2)
		self.world.check_in(reservation, room=self.world.rooms[0])

		self.assertIn(self.world.rooms[0], self._offered(4, 6))

	def test_excluding_a_line_lets_it_keep_its_own_room(self):
		"""Re-picking for a line must not treat that line as its own rival."""
		reservation = self.world.confirmed(nights=4)
		line = self.world.lines(reservation)[0]["name"]
		reservation_service.assign_room(reservation, line, self.world.rooms[0])
		frappe.db.commit()

		self.assertIn(self.world.rooms[0], self._offered(0, 4, exclude_line=line))

	def test_out_of_order_rooms_are_never_offered(self):
		frappe.db.set_value(
			"Hotel Room", self.world.rooms[0], "maintenance_status", "Out of Order", update_modified=False
		)
		frappe.db.commit()

		self.assertNotIn(self.world.rooms[0], self._offered(0, 2))

	def test_every_offered_room_can_actually_be_assigned(self):
		"""The list and the authority must agree, or the agent picks a lie."""
		held = self.world.confirmed(nights=4)
		reservation_service.assign_room(held, self.world.lines(held)[0]["name"], self.world.rooms[0])

		occupied = self.world.confirmed(nights=4)
		self.world.check_in(occupied, room=self.world.rooms[1])
		frappe.db.commit()

		booking = self.world.confirmed(nights=2)
		line = self.world.lines(booking)[0]["name"]

		offered = self._offered(0, 2)
		self.assertTrue(offered, msg="the fixture should leave at least one room free")

		for room in offered:
			reservation_service.assign_room(booking, line, room)


class TestAssignRoomAuthority(RoomAssignmentTestCase):
	"""The list may be stale; assignment may not."""

	WORLD_CODE = "RT"

	def test_assigning_a_promised_room_is_refused(self):
		first = self.world.confirmed(nights=4)
		reservation_service.assign_room(first, self.world.lines(first)[0]["name"], self.world.rooms[0])
		frappe.db.commit()

		second = self.world.confirmed(nights=2, arrival=self.world.day(1))

		with self.assertRaises(HospitalityPMSError):
			reservation_service.assign_room(
				second, self.world.lines(second)[0]["name"], self.world.rooms[0]
			)

	def test_assigning_a_room_with_an_in_house_guest_is_refused(self):
		"""Two mechanisms would each refuse this; the guest is what matters."""
		occupied = self.world.confirmed(nights=4)
		self.world.check_in(occupied, room=self.world.rooms[0])
		frappe.db.commit()

		booking = self.world.confirmed(nights=2)

		with self.assertRaises(HospitalityPMSError):
			reservation_service.assign_room(
				booking, self.world.lines(booking)[0]["name"], self.world.rooms[0]
			)

	def test_a_house_use_room_cannot_be_taken_today(self):
		"""Occupancy on its own, with no reservation interval behind it.

		A room put into House Use holds no inventory line, so the interval
		check has nothing to say about it and the occupancy check is the only
		thing standing between it and today's arrival.
		"""
		frappe.db.set_value(
			"Hotel Room", self.world.rooms[0], "occupancy_status", "House Use", update_modified=False
		)
		frappe.db.commit()

		booking = self.world.confirmed(nights=2)

		with self.assertRaises(RoomNotAssignableError):
			reservation_service.assign_room(
				booking, self.world.lines(booking)[0]["name"], self.world.rooms[0]
			)

	def test_a_house_use_room_may_be_promised_for_a_future_arrival(self):
		"""The counterpart: a full house must still pre-assign next week.

		Whether the room is free by then is the inventory interval's question,
		not a status field's - and the interval is checked either way.
		"""
		frappe.db.set_value(
			"Hotel Room", self.world.rooms[0], "occupancy_status", "House Use", update_modified=False
		)
		frappe.db.commit()

		booking = self.world.confirmed(nights=2, arrival=self.world.day(5))
		line = self.world.lines(booking)[0]["name"]

		reservation_service.assign_room(booking, line, self.world.rooms[0])

		self.assertEqual(
			frappe.db.get_value("Reservation Room", line, "assigned_room"), self.world.rooms[0]
		)

	def test_out_of_order_cannot_be_assigned_and_the_setting_cannot_permit_it(self):
		"""Part 17 — the flag is descriptive; out of order is absolute."""
		self.world.fixtures.set_setting("block_assignment_for_out_of_order", 0)
		frappe.db.set_value(
			"Hotel Room", self.world.rooms[0], "maintenance_status", "Out of Order", update_modified=False
		)
		frappe.db.commit()

		booking = self.world.confirmed(nights=2)

		with self.assertRaises(RoomNotAssignableError):
			reservation_service.assign_room(
				booking, self.world.lines(booking)[0]["name"], self.world.rooms[0]
			)

	def test_reassigning_the_same_line_to_its_own_room_is_allowed(self):
		booking = self.world.confirmed(nights=4)
		line = self.world.lines(booking)[0]["name"]

		reservation_service.assign_room(booking, line, self.world.rooms[0])
		reservation_service.assign_room(booking, line, self.world.rooms[0])

		self.assertEqual(
			frappe.db.get_value("Reservation Room", line, "assigned_room"), self.world.rooms[0]
		)

	def test_a_line_of_another_property_cannot_take_this_rooms(self):
		other = self.world.fixtures.property("RZ")
		frappe.db.commit()

		booking = self.world.confirmed(nights=2)
		line = self.world.lines(booking)[0]["name"]
		other_room = self.world.fixtures.rooms(
			other, self.world.fixtures.room_type(other, base_rate=100), count=1
		)[0]
		frappe.db.commit()

		with self.assertRaises(HospitalityPMSError):
			reservation_service.assign_room(booking, line, other_room)


class TestAssignmentConcurrency(RoomAssignmentTestCase):
	WORLD_CODE = "RC"

	def test_two_lines_cannot_take_the_same_room(self):
		"""The list said yes to both; only one may actually get it."""
		booking = self.world.confirmed(nights=4, rooms=2)
		lines = self.world.lines(booking)
		room = self.world.rooms[0]

		results = run_workers(
			[
				Worker(
					f"{__name__}._assign_worker",
					{
						"reservation": booking,
						"line": lines[0]["name"],
						"room": room,
						"tag": "a",
						"partner": "b",
					},
				),
				Worker(
					f"{__name__}._assign_worker",
					{
						"reservation": booking,
						"line": lines[1]["name"],
						"room": room,
						"tag": "b",
						"partner": "a",
					},
				),
			]
		)
		assert_all_ran(results)

		holders = frappe.get_all(
			"Reservation Room", filters={"assigned_room": room, "parent": booking}, pluck="name"
		)

		self.assertEqual(
			len(holders), 1, msg=f"the same room was promised to {len(holders)} lines: {results}"
		)
