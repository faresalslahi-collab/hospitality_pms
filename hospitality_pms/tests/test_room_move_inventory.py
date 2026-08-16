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
from hospitality_pms.services.availability import get_availability
from hospitality_pms.services.exceptions import (
	AvailabilityError,
	HospitalityPMSError,
	RoomNotAssignableError,
)
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


class TestCrossTypeRoomMove(IntegrationTestCase):
	"""A move into a room of another type has to move the type with it.

	16.7.2 fixed `assigned_room` and deliberately left `room_type` behind, because
	what a cross-type move does to the *rate* was an open question. The answer
	16.7.3 gives is "nothing": a room move is operational, the guest has already
	been quoted, and `Stay.room_rate` - which is what the night audit posts - is
	not derived from the line's type. That settles the pricing question without
	touching a price, and lets the inventory record tell the truth.

	The stale type was wrong twice on every remaining night. `_sold_by_night`
	counts a line against `Reservation Room.room_type`, while supply comes from
	`Hotel Room.room_type`, so the origin type kept a room it no longer held and
	the destination type offered one that had a guest asleep in it. Occupancy is
	not an input to `get_availability`, so nothing downstream caught it.
	"""

	SUITE_RATE = 250.0

	@classmethod
	def setUpClass(cls):
		super().setUpClass()

		# Sized for the whole class: the world is built once and the fixtures
		# commit, so a guest checked in by one test is still in that room for the
		# next. Every case takes fresh rooms rather than unpicking those commits.
		cls.world = InventoryWorld("RMXT", "RX", rooms=12)

		# A second type, and rooms of it. `InventoryWorld` builds a single-type
		# house, which is why every 16.7.2 move test was a same-type move and why
		# this defect had no coverage at all.
		cls.suite_type = cls.world.fixtures.room_type(
			cls.world.property, "SUITE", base_rate=cls.SUITE_RATE
		)
		cls.suites = cls.world.fixtures.rooms(cls.world.property, cls.suite_type, count=8)

		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		cls.world.fixtures.teardown()
		super().tearDownClass()

	_allocated = 0
	_suites_allocated = 0

	@classmethod
	def _take_room(cls) -> str:
		assert cls._allocated < len(cls.world.rooms), "the fixture world needs more rooms"

		room = cls.world.rooms[cls._allocated]
		cls._allocated += 1

		return room

	@classmethod
	def _take_suite(cls) -> str:
		assert cls._suites_allocated < len(cls.suites), "the fixture world needs more suites"

		suite = cls.suites[cls._suites_allocated]
		cls._suites_allocated += 1

		return suite

	def _in_house(self):
		"""A guest checked into a standard room, and a free suite to move into."""
		room = self._take_room()

		reservation = self.world.confirmed(nights=3)
		line = self.world.lines(reservation)[0]["name"]

		reservation_service.assign_room(reservation, line, room)
		self.world.check_in(reservation, line=line, room=room)

		stay = frappe.db.get_value("Stay", {"reservation_room_line": line}, "name")

		return reservation, line, stay, room

	def _line(self, line: str) -> dict:
		return frappe.db.get_value(
			"Reservation Room",
			line,
			["assigned_room", "room_type", "room_rate", "total_amount", "rate_plan", "nights"],
			as_dict=True,
		)

	def _available(self, room_type: str) -> int:
		"""Lowest availability of one type across the booked interval."""
		availability = get_availability(
			self.world.property, self.world.day(0), self.world.day(3), room_type
		)

		return int(availability["room_types"][room_type]["min_available"])

	def test_cross_type_room_move_updates_reservation_room_type(self):
		"""Stay, physical room and inventory row must describe one room."""
		_, line, stay, room = self._in_house()
		suite = self._take_suite()

		self.assertEqual(self._line(line)["room_type"], self.world.room_type)

		stay_service.change_room(stay, suite, "Upgraded after a fault in the standard room")

		physical_type = frappe.db.get_value("Hotel Room", suite, "room_type")
		stay_row = frappe.db.get_value("Stay", stay, ["room", "room_type"], as_dict=True)
		row = self._line(line)

		self.assertEqual(stay_row["room"], suite)
		self.assertEqual(stay_row["room_type"], physical_type)
		self.assertEqual(row["assigned_room"], suite)
		self.assertEqual(
			row["room_type"],
			physical_type,
			msg="the inventory row still names the type the booking was made for",
		)
		self.assertNotEqual(row["room_type"], self.world.room_type)

	def test_cross_type_move_does_not_reprice_booking(self):
		"""Operational move, quoted price. Nothing about the money may shift."""
		reservation, line, stay, _ = self._in_house()
		suite = self._take_suite()

		before = self._line(line)
		reservation_before = frappe.db.get_value(
			"Reservation", reservation, ["total_amount", "room_charges_total"], as_dict=True
		)
		stay_rate_before = frappe.db.get_value("Stay", stay, "room_rate")

		stay_service.change_room(stay, suite, "Moved into a suite, at the booked rate")

		after = self._line(line)

		# The line's own rate snapshot, which the suite's higher base rate must
		# not have reached.
		self.assertEqual(after["room_rate"], before["room_rate"])
		self.assertEqual(after["total_amount"], before["total_amount"])
		self.assertEqual(after["rate_plan"], before["rate_plan"])
		self.assertNotEqual(
			after["room_rate"],
			self.SUITE_RATE,
			msg="the guest was repriced onto the suite's rate",
		)

		# The header totals.
		self.assertEqual(
			frappe.db.get_value(
				"Reservation", reservation, ["total_amount", "room_charges_total"], as_dict=True
			),
			reservation_before,
		)

		# And the figure the night audit actually posts.
		self.assertEqual(frappe.db.get_value("Stay", stay, "room_rate"), stay_rate_before)

	def test_cross_type_move_preserves_inventory(self):
		"""The night moves from one type's sold count to the other's."""
		_, _, stay, _ = self._in_house()
		suite = self._take_suite()

		standard_before = self._available(self.world.room_type)
		suite_before = self._available(self.suite_type)

		stay_service.change_room(stay, suite, "Moved for a maintenance fault")

		self.assertEqual(
			self._available(self.world.room_type),
			standard_before + 1,
			msg="the standard room the guest left is still counted as sold",
		)
		self.assertEqual(
			self._available(self.suite_type),
			suite_before - 1,
			msg="the suite the guest is asleep in is still being offered for sale",
		)

	def test_cross_type_move_conflict_is_refused(self):
		"""A suite already promised to somebody is not free to move into."""
		_, _, first_stay, _ = self._in_house()
		_, second_line, second_stay, second_room = self._in_house()
		suite = self._take_suite()

		stay_service.change_room(first_stay, suite, "First guest upgraded")

		with self.assertRaises(HospitalityPMSError):
			stay_service.change_room(second_stay, suite, "Second guest wants the same suite")

		# The refusal left the second guest exactly where they were, type included.
		row = self._line(second_line)

		self.assertEqual(frappe.db.get_value("Stay", second_stay, "room"), second_room)
		self.assertEqual(row["assigned_room"], second_room)
		self.assertEqual(row["room_type"], self.world.room_type)

	def test_cross_type_move_history_is_coherent(self):
		"""The move is recorded against the stay and against the booking."""
		reservation, _, stay, room = self._in_house()
		suite = self._take_suite()

		stay_service.change_room(stay, suite, "Suite offered after a long delay at check-in")

		move = frappe.get_doc("Stay", stay).room_moves[-1]

		self.assertEqual(move.from_room, room)
		self.assertEqual(move.to_room, suite)
		self.assertEqual(move.reason, "Suite offered after a long delay at check-in")

		# `change_room` was the one inventory service that wrote nothing to the
		# booking's own history, so a line silently changed type.
		logs = frappe.get_all(
			"Reservation Log",
			filters={"reservation": reservation},
			fields=["details", "reason"],
			order_by="creation desc",
			limit=1,
		)

		self.assertTrue(logs, msg="the cross-type move left no trace on the reservation")

		details = frappe.parse_json(logs[0]["details"])

		self.assertEqual(details["from"], self.world.room_type)
		self.assertEqual(details["to"], frappe.db.get_value("Hotel Room", suite, "room_type"))
		self.assertEqual(details["assigned_room"], suite)

	def test_a_same_type_move_writes_no_room_type_history(self):
		"""The ordinary move is unchanged, and adds no row that says nothing."""
		reservation, line, stay, _ = self._in_house()
		destination = self._take_room()

		before = frappe.db.count("Reservation Log", {"reservation": reservation})

		stay_service.change_room(stay, destination, "Quieter room, same type")

		self.assertEqual(
			frappe.db.count("Reservation Log", {"reservation": reservation}),
			before,
			msg="a same-type move logged a room type change that did not happen",
		)
		self.assertEqual(self._line(line)["room_type"], self.world.room_type)
		self.assertEqual(self._line(line)["assigned_room"], destination)


class TestCrossTypeAndPresetAssignment(IntegrationTestCase):
	"""RES-3 and RES-4 — inventory and validation gaps around room assignment.

	RES-3: a cross-type room move updates the line's room_type but never checked the
	destination type had a room for the nights the line still holds, so a move into a
	physically-free room of a sold-out type oversold that type. RES-4: a pre-set
	assigned_room (create payload / channel import / Desk) reached confirm and check-in
	without the clash/property/type checks assign_room applies.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.world = InventoryWorld("XTYPE", "XT", rooms=6)
		# A second type with a single room, so it can be sold out deterministically.
		cls.dlx_type = cls.world.fixtures.room_type(cls.world.property, "DLX")
		cls.dlx_rooms = cls.world.fixtures.rooms(cls.world.property, cls.dlx_type, count=1)
		# The fixture rate plan is one-per-property and was built for Standard only;
		# extend it to cover the Deluxe type so a Deluxe booking can be priced.
		rate_plan = frappe.get_doc("Rate Plan", cls.world.rate_plan)
		rate_plan.append("room_types", {"room_type": cls.dlx_type, "base_rate": 100.0, "is_active": 1})
		rate_plan.save(ignore_permissions=True)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		cls.world.fixtures.teardown()
		super().tearDownClass()

	_alloc = 0

	@classmethod
	def _std_room(cls) -> str:
		room = cls.world.rooms[cls._alloc]
		cls._alloc += 1
		return room

	def _dlx_reservation(self, *, nights=3) -> str:
		guest = self.world.fixtures.guest("Dlx")
		res = self.world.fixtures.reservation(
			self.world.property, self.dlx_type, guest, rate_plan=self.world.rate_plan, nights=nights
		)
		return res

	# -- RES-3 --------------------------------------------------------------

	def test_cross_type_move_into_a_sold_out_type_is_refused(self):
		# Sell the single DLX room for the nights (a confirmed hold, not assigned to
		# the specific room - so the physical room is free but the type is full).
		filler = self._dlx_reservation()
		reservation_service.confirm(filler)

		# A guest checked into a Standard room.
		occupied = self._std_room()
		std_res = self.world.confirmed(nights=3)
		std_line = self.world.lines(std_res)[0]["name"]
		reservation_service.assign_room(std_res, std_line, occupied)
		self.world.check_in(std_res, line=std_line, room=occupied)
		std_stay = frappe.db.get_value("Stay", {"reservation_room_line": std_line}, "name")

		# Moving them into the DLX room oversells the DLX type: the room is free but
		# the type has no capacity for these nights.
		with self.assertRaises(AvailabilityError):
			stay_service.change_room(std_stay, self.dlx_rooms[0], "guest upgrade request")

		# Same-type-open control: a move within Standard still works.
		vacant_std = self._std_room()
		stay_service.change_room(std_stay, vacant_std, "noisy corridor")
		self.assertEqual(frappe.db.get_value("Stay", std_stay, "room"), vacant_std)

	# -- RES-4 --------------------------------------------------------------

	def test_confirm_refuses_a_preset_assigned_room_of_the_wrong_type(self):
		res = self.world.reservation(nights=2)  # Standard line
		line = self.world.lines(res)[0]["name"]
		# A DLX room smuggled onto a Standard line, the way a create payload or import
		# could, bypassing assign_room.
		frappe.db.set_value("Reservation Room", line, "assigned_room", self.dlx_rooms[0])
		frappe.db.commit()

		with self.assertRaises((HospitalityPMSError, frappe.ValidationError)):
			reservation_service.confirm(res)

	def test_confirm_refuses_a_preset_assigned_room_already_promised(self):
		# One booking legitimately holds a Standard room.
		first = self.world.confirmed(nights=2)
		first_line = self.world.lines(first)[0]["name"]
		held = self._std_room()
		reservation_service.assign_room(first, first_line, held)

		# A second booking is created pre-assigned the same physical room.
		second = self.world.reservation(nights=2)
		second_line = self.world.lines(second)[0]["name"]
		frappe.db.set_value("Reservation Room", second_line, "assigned_room", held)
		frappe.db.commit()

		with self.assertRaises((HospitalityPMSError, RoomNotAssignableError, frappe.ValidationError)):
			reservation_service.confirm(second)

	def test_confirm_accepts_a_valid_preset_assigned_room(self):
		res = self.world.reservation(nights=2)
		line = self.world.lines(res)[0]["name"]
		room = self._std_room()
		frappe.db.set_value("Reservation Room", line, "assigned_room", room)
		frappe.db.commit()

		reservation_service.confirm(res)  # must not raise
		self.assertEqual(
			frappe.db.get_value("Reservation", res, "reservation_status"),
			reservation_service.CONFIRMED,
		)
