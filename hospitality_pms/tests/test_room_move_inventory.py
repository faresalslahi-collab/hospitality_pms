"""A room move has to move the inventory row, not just the stay.

`Reservation Room` is the authoritative record of which physical room is promised
to whom, and `reservations._assert_room_free` reads only that table — a
checked-in guest is counted there because check-in does not move a booking out of
the holding states.

Until 16.7.2 `stays.change_room` updated the Stay, the two rooms' statuses and the
folio, and left the inventory row naming the room the guest had left. The
protection therefore guarded an empty room and reported the occupied one as free.
Found on the live bench during this build: one stay with the guest in 503 while its
row still said 504, and `_assert_room_free("DOHA01-503")` answering "free". The
next assignment of that room would have put two guests in it.

There was no `change_room` coverage anywhere in the suite before this file.
"""

import frappe
from frappe.tests import IntegrationTestCase

from hospitality_pms.services import reservations as reservation_service
from hospitality_pms.services import rooms as room_service
from hospitality_pms.services import stays as stay_service
from hospitality_pms.services.exceptions import HospitalityPMSError, RoomNotAssignableError
from hospitality_pms.tests.inventory_world import InventoryWorld


class TestRoomMoveKeepsInventoryTrue(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()

		# Sized for the whole class, not for one test: the world is built once in
		# `setUpClass` and every case confirms a booking against it, so a house of
		# three would be sold out by the third test and the failures would look
		# like availability bugs rather than an exhausted fixture.
		cls.world = InventoryWorld("RMOV", "RM", rooms=10)

	@classmethod
	def tearDownClass(cls):
		cls.world.fixtures.teardown()
		super().tearDownClass()

	#: Rooms are handed out in pairs, one pair per call, and never reused.
	#:
	#: The world is built once in `setUpClass` and the fixtures commit, so a guest
	#: checked in by one test is still in that room for the next. Allocating a
	#: fresh pair each time keeps every case independent without unpicking the
	#: fixture's own commits.
	_allocated = 0

	@classmethod
	def _take_rooms(cls) -> tuple[str, str]:
		start = cls._allocated
		cls._allocated += 2

		assert cls._allocated <= len(cls.world.rooms), "the fixture world needs more rooms"

		return cls.world.rooms[start], cls.world.rooms[start + 1]

	def _in_house(self):
		"""A guest checked into a room of their own, with a free room to move to."""
		occupied, vacant = self._take_rooms()

		reservation = self.world.confirmed(nights=3)
		line = self.world.lines(reservation)[0]["name"]

		reservation_service.assign_room(reservation, line, occupied)
		self.world.check_in(reservation, line=line, room=occupied)

		return line, occupied, vacant

	def _line(self, line: str) -> dict:
		return frappe.db.get_value(
			"Reservation Room",
			line,
			["assigned_room", "arrival_date", "departure_date"],
			as_dict=True,
		)

	def test_the_inventory_row_follows_the_guest(self):
		line, occupied, vacant = self._in_house()

		self.assertEqual(self._line(line)["assigned_room"], occupied)

		stay = frappe.db.get_value("Stay", {"reservation_room_line": line}, "name")
		stay_service.change_room(stay, vacant, "Guest asked for a quieter room")

		self.assertEqual(
			frappe.db.get_value("Stay", stay, "room"),
			vacant,
			msg="the stay did not move",
		)
		self.assertEqual(
			self._line(line)["assigned_room"],
			vacant,
			msg="the inventory row still names the room the guest left",
		)

	def test_the_room_the_guest_moved_into_is_no_longer_offered(self):
		"""The oversell this closes: a second booking must not get that room."""
		line, occupied, vacant = self._in_house()
		row = self._line(line)

		stay = frappe.db.get_value("Stay", {"reservation_room_line": line}, "name")
		stay_service.change_room(stay, vacant, "Maintenance in the original room")

		# The room the guest is now in refuses a second assignment.
		with self.assertRaises(HospitalityPMSError):
			reservation_service._assert_room_free(
				vacant, row["arrival_date"], row["departure_date"]
			)

		# And end to end, through the service a desk would actually call.
		other = self.world.confirmed(nights=3)
		other_line = self.world.lines(other)[0]["name"]

		with self.assertRaises(HospitalityPMSError):
			reservation_service.assign_room(other, other_line, vacant)

	def test_the_room_the_guest_left_becomes_available_again(self):
		"""The other half: the vacated room must stop being protected."""
		line, occupied, vacant = self._in_house()
		row = self._line(line)

		stay = frappe.db.get_value("Stay", {"reservation_room_line": line}, "name")
		stay_service.change_room(stay, vacant, "Guest moved")

		# Nothing *holds* the original room now, which is the inventory question
		# this fix is about, and the whole point of the move.
		reservation_service._assert_room_free(
			occupied, row["arrival_date"], row["departure_date"]
		)

		other = self.world.confirmed(nights=3)
		other_line = self.world.lines(other)[0]["name"]

		# Housekeeping is a different dimension and is deliberately not conflated
		# with it: the vacated room is Dirty, so `assign_room` refuses it until
		# housekeeping releases it. That refusal is correct and is not what this
		# test is about — the room being *unheld* is.
		with self.assertRaises(RoomNotAssignableError):
			reservation_service.assign_room(other, other_line, occupied)

		room_service.set_statuses(
			occupied,
			{room_service.HOUSEKEEPING: "Clean"},
			reason="Cleaned after the move",
		)

		reservation_service.assign_room(other, other_line, occupied)

		self.assertEqual(self._line(other_line)["assigned_room"], occupied)

	def test_the_move_is_still_recorded_against_the_stay(self):
		"""The fix must not disturb what the move already recorded."""
		line, occupied, vacant = self._in_house()

		stay = frappe.db.get_value("Stay", {"reservation_room_line": line}, "name")
		stay_service.change_room(stay, vacant, "Air conditioning fault")

		doc = frappe.get_doc("Stay", stay)
		move = doc.room_moves[-1]

		self.assertEqual(move.from_room, occupied)
		self.assertEqual(move.to_room, vacant)
		self.assertEqual(move.reason, "Air conditioning fault")

		# The vacated room is dirty and the new one occupied, as before.
		self.assertEqual(
			frappe.db.get_value("Hotel Room", occupied, "housekeeping_status"), "Dirty"
		)
		self.assertEqual(
			frappe.db.get_value("Hotel Room", vacant, "occupancy_status"), "Occupied"
		)

		# And the folio followed the guest.
		if doc.folio:
			self.assertEqual(
				frappe.db.get_value("Guest Folio", doc.folio, "room"), vacant
			)

	def test_a_stay_with_no_inventory_row_still_moves(self):
		"""A walk-in has no reservation line; the move must not require one."""
		line, occupied, vacant = self._in_house()
		stay = frappe.db.get_value("Stay", {"reservation_room_line": line}, "name")

		# Detach the line the way a walk-in stay is created without one.
		frappe.db.set_value(
			"Stay", stay, "reservation_room_line", None, update_modified=False
		)

		result = stay_service.change_room(stay, vacant, "No line on this stay")

		self.assertEqual(result["to_room"], vacant)
		self.assertEqual(frappe.db.get_value("Stay", stay, "room"), vacant)
