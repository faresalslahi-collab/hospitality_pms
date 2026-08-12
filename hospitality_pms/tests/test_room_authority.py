"""HPMS-UAT-16.7.5-B01 — a guest's room was offered to somebody else.

The defect as filed reads "Hotel Room occupancy is persisted Vacant while a
guest is still in the room". That is real, and it is the *artifact*. Room 402's
own status log says what actually happened:

    17:37:40  Occupancy  Vacant   -> Occupied   Stay 00037 (Guest checked in)
    17:37:41  Occupancy  Occupied -> Due Out    Stay 00037 (Departing on 08-11)
    19:11:33  Occupancy  Due Out  -> Occupied   Stay 00617 (Guest checked in)   <-- second guest
    19:21:27  Occupancy  Occupied -> Vacant     Stay 00617 (Guest checked out)  <-- left it Vacant

Stay 00037 never checked out. The room read `Vacant` afterwards because the
*second* guest's checkout set it that way. So the stale flag is a consequence of
the double occupancy, not its cause.

The cause is that on a guest's departure day, both authorities stop seeing them:

* `rooms.OCCUPIED_STATES` is `{"Occupied", "House Use"}` and does not contain
  `"Due Out"` - which is precisely the state `stays.mark_due_out` puts the room
  in, from the Night Audit, every morning. From then on the room's own
  denormalised state does not read as occupied.
* `reservations._assert_room_free` and `availability._promised_rooms` test
  reservation overlap, `arrival < other.departure AND departure > other.arrival`.
  Departure-exclusive is correct for selling nights - one guest leaves on the
  12th, another arrives on the 12th - and wrong as a test of who is physically
  in the room, because a stay whose departure date is today does not overlap an
  assignment starting today.

Neither authority consults `Stay` at all. So between the Night Audit and the
guest actually leaving, their room is offered to the house - and if the desk
takes it, the second guest's eventual checkout marks the room Vacant while the
first guest is still in it. That is room 402.

These tests therefore reproduce the defect twice: once with nothing tampered at
all (the systemic path, a Due Out guest on their departure day), and once with
the room flag forced to `Vacant` (the persisted state the report found). Both
must be refused, and refused by the *mutations*, not only by the picker.
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days

from hospitality_pms.services import reservations as reservation_service
from hospitality_pms.services import rooms as room_service
from hospitality_pms.services import stays as stay_service
from hospitality_pms.services import walk_in as walk_in_service
from hospitality_pms.services.availability import get_assignable_rooms
from hospitality_pms.services.exceptions import (
	HospitalityPMSError,
	RoomNotAssignableError,
)
from hospitality_pms.tests.inventory_world import InventoryWorld


class RoomAuthorityTestCase(IntegrationTestCase):
	"""A property with three rooms and a guest who is due out today."""

	ROOMS = 3

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.world = InventoryWorld(cls.__name__[:6].upper(), cls.WORLD_CODE, rooms=cls.ROOMS)
		cls.opening_date = cls.world.business_date

	@classmethod
	def tearDownClass(cls):
		cls.world.teardown()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")
		self.world.set_business_date(self.opening_date)
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

	# -- premises ---------------------------------------------------------

	def _guest_due_out_today(self, room: str, *, force_room_vacant: bool = False) -> dict:
		"""A guest checked in yesterday, departing today, still in the room.

		Built entirely through the approved services and then advanced a day the
		way the Night Audit advances it, so the state under test is state the
		product produces on its own. Nothing is forced unless the caller asks.

		`force_room_vacant` adds the one thing the product did *not* do by
		itself: it writes the room's occupancy flag straight to `Vacant`. That
		completes room 402's persisted state, where the second guest's checkout
		had already left the flag that way while the first guest was still in
		the room. Written with `set_value` on purpose - the invariant under test
		is that it holds when the denormalised flag is wrong, so the test has to
		be able to make it wrong without going through the service that would
		keep it honest.

		Leaves the property's business date on the guest's departure date, which
		is the situation room 402 was in.
		"""
		reservation = self.world.confirmed(nights=1)
		line = self.world.lines(reservation)[0]["name"]
		checked_in = stay_service.check_in(reservation, line, room)

		# Tomorrow becomes today: the guest's departure date is now the business
		# date, and they have not left.
		self.world.set_business_date(add_days(self.opening_date, 1))

		# What the Night Audit does every morning, through its own service.
		due = stay_service.mark_due_out(self.world.property)
		frappe.db.commit()

		self.assertIn(checked_in["stay"], due, msg="the fixture did not become Due Out")

		if force_room_vacant:
			frappe.db.set_value("Hotel Room", room, "occupancy_status", "Vacant", update_modified=False)
			frappe.db.commit()

		# The premise, asserted rather than assumed: the stay is active, has no
		# checkout timestamp, and the room's own flag does not say occupied.
		self.assertEqual(
			frappe.db.get_value("Stay", checked_in["stay"], "stay_status"), stay_service.DUE_OUT
		)
		self.assertIsNone(frappe.db.get_value("Stay", checked_in["stay"], "checked_out_on"))
		self.assertNotIn(
			frappe.db.get_value("Hotel Room", room, "occupancy_status"),
			room_service.OCCUPIED_STATES,
			msg="the fixture's premise is gone: the room now reads as occupied on its own",
		)

		return checked_in

	def _guest_in_house_mid_stay(self, room: str) -> dict:
		"""An In House guest three nights into a stay, room flag forced Vacant.

		Kept as a guard-rail rather than as B01 evidence. This case is *already*
		refused before the fix, because the guest's reservation line still has
		two nights to run and the interval authority sees it. Which is the
		finding: a stale `Vacant` flag on its own does not open the door. It
		takes the stale flag *and* an interval that no longer overlaps - the
		guest's departure day - to blind both authorities at once, and that is
		what `_guest_due_out_today` builds.
		"""
		reservation = self.world.confirmed(nights=3)
		line = self.world.lines(reservation)[0]["name"]
		checked_in = stay_service.check_in(reservation, line, room)

		frappe.db.set_value("Hotel Room", room, "occupancy_status", "Vacant", update_modified=False)
		frappe.db.commit()

		self.assertEqual(
			frappe.db.get_value("Stay", checked_in["stay"], "stay_status"),
			stay_service.IN_HOUSE,
		)
		self.assertIsNone(frappe.db.get_value("Stay", checked_in["stay"], "checked_out_on"))

		return checked_in

	def _rival_reservation(self, *, arrival, nights: int = 1) -> tuple[str, str]:
		"""Somebody else's confirmed booking, ready to be given a room."""
		reservation = self.world.confirmed(nights=nights, arrival=arrival)
		line = self.world.lines(reservation)[0]["name"]

		return reservation, line

	def _offered(self, arrival, departure, **kwargs) -> set[str]:
		return {
			row["name"]
			for row in get_assignable_rooms(
				self.world.property, self.world.room_type, arrival, departure, **kwargs
			)
		}


class TestAssignableRoomsRespectActiveStays(RoomAuthorityTestCase):
	WORLD_CODE = "RAU"

	def test_a_guest_due_out_today_is_not_offered_to_anybody_else(self):
		"""The reproduction, with nothing tampered with.

		This is the path room 402 actually took. `mark_due_out` moves the room's
		occupancy to `Due Out`, which is not in `OCCUPIED_STATES`, and the
		guest's reservation line departs today, which does not overlap an
		assignment arriving today. Both authorities go blind on the same morning.
		"""
		room = self.world.rooms[0]
		self._guest_due_out_today(room)

		today = self.world.business_date

		self.assertNotIn(
			room,
			self._offered(today, add_days(today, 1)),
			msg=(
				"a room whose guest is still in it - Due Out, checked_out_on NULL - "
				"was offered for assignment today"
			),
		)

	def test_room_402s_exact_persisted_state_is_not_offered(self):
		"""HPMS-UAT-16.7.5-B01 as it sits on the bench.

		Active Stay, `checked_out_on` NULL, reservation line departing today,
		Hotel Room occupancy persisted `Vacant`. Every authority the code has is
		blind to this guest at once, which is why the room was offered.
		"""
		room = self.world.rooms[0]
		self._guest_due_out_today(room, force_room_vacant=True)

		today = self.world.business_date

		self.assertNotIn(
			room,
			self._offered(today, add_days(today, 1)),
			msg="room 402's persisted state was offered for assignment",
		)

	def test_a_stale_vacant_flag_mid_stay_is_still_refused(self):
		"""A guard-rail, not B01 evidence: this case already held.

		Mid-stay the interval authority still sees the guest, so the stale flag
		alone never opened the door. Pinned so a fix cannot remove the layer that
		was working.
		"""
		room = self.world.rooms[0]
		self._guest_in_house_mid_stay(room)

		today = self.world.business_date

		self.assertNotIn(
			room,
			self._offered(today, add_days(today, 1)),
			msg="a room with an In House stay was offered because its flag said Vacant",
		)

	def test_the_other_rooms_are_still_offered(self):
		"""The guard must not collapse the house.

		A fix that answers "nothing is assignable" would pass the two tests
		above and be worse than the defect.
		"""
		room = self.world.rooms[0]
		self._guest_due_out_today(room)

		today = self.world.business_date
		offered = self._offered(today, add_days(today, 1))

		self.assertEqual(offered, set(self.world.rooms[1:]))

	def test_a_checked_out_stay_releases_the_room(self):
		"""Occupancy authority is about *active* stays, not about history."""
		room = self.world.rooms[0]
		checked_in = self._guest_due_out_today(room)

		stay_service.transition(checked_in["stay"], stay_service.CHECKED_OUT)
		frappe.db.set_value(
			"Stay", checked_in["stay"], "checked_out_on", "2026-01-01 12:00:00", update_modified=False
		)
		frappe.db.commit()

		today = self.world.business_date

		self.assertIn(
			room,
			self._offered(today, add_days(today, 1), allow_unready_housekeeping=True),
			msg="a room whose guest has left was still held against the house",
		)

	def test_a_future_stay_after_a_coherent_departure_is_still_offered(self):
		"""Occupied now is not occupied forever.

		The guest in room 0 departs today. A booking arriving tomorrow must
		still be able to have that room, or one overdue guest would sterilise a
		room for the rest of the year.
		"""
		room = self.world.rooms[0]
		self._guest_due_out_today(room)

		tomorrow = add_days(self.world.business_date, 1)

		self.assertIn(
			room,
			self._offered(tomorrow, add_days(tomorrow, 1), allow_unready_housekeeping=True),
			msg="a room was withheld from a future date on the strength of today's occupant",
		)


class TestCommitPathsRespectActiveStays(RoomAuthorityTestCase):
	"""The picker is advisory. These are the mutations, and they must refuse."""

	WORLD_CODE = "RAC"

	def test_assign_room_refuses_a_room_an_active_stay_occupies(self):
		room = self.world.rooms[0]
		self._guest_due_out_today(room)

		today = self.world.business_date
		reservation, line = self._rival_reservation(arrival=today)

		with self.assertRaises((HospitalityPMSError, RoomNotAssignableError)):
			reservation_service.assign_room(reservation, line, room)

	def test_check_in_refuses_a_room_an_active_stay_occupies(self):
		room = self.world.rooms[0]
		self._guest_due_out_today(room)

		today = self.world.business_date
		reservation, line = self._rival_reservation(arrival=today)

		with self.assertRaises((HospitalityPMSError, RoomNotAssignableError)):
			stay_service.check_in(reservation, line, room)

		self.assertFalse(
			frappe.db.exists("Stay", {"reservation": reservation}),
			msg="a refused check-in still created a Stay",
		)

	def test_check_in_refuses_room_402s_exact_persisted_state(self):
		"""The B01 mutation guard, against the state found on the bench."""
		room = self.world.rooms[0]
		self._guest_due_out_today(room, force_room_vacant=True)

		today = self.world.business_date
		reservation, line = self._rival_reservation(arrival=today)

		with self.assertRaises((HospitalityPMSError, RoomNotAssignableError)):
			stay_service.check_in(reservation, line, room)

	def test_walk_in_refuses_a_room_an_active_stay_occupies(self):
		room = self.world.rooms[0]
		self._guest_due_out_today(room)

		with self.assertRaises((HospitalityPMSError, RoomNotAssignableError)):
			walk_in_service.create_walk_in(
				property_name=self.world.property,
				guest=self.world.fixtures.guest("Rival"),
				departure_date=add_days(self.world.business_date, 1),
				room_type=self.world.room_type,
				room=room,
			)

	def test_change_room_refuses_moving_into_an_occupied_room(self):
		"""A room move is a physical placement like any other."""
		occupied = self.world.rooms[0]
		self._guest_due_out_today(occupied)

		# A second guest, in a different room, who will try to move into the first.
		mover_reservation = self.world.confirmed(nights=2, arrival=self.world.business_date)
		mover_line = self.world.lines(mover_reservation)[0]["name"]
		mover = stay_service.check_in(mover_reservation, mover_line, self.world.rooms[1])
		frappe.db.commit()

		with self.assertRaises((HospitalityPMSError, RoomNotAssignableError)):
			stay_service.change_room(mover["stay"], occupied, "guest asked for a quieter room")

		self.assertEqual(
			frappe.db.get_value("Stay", mover["stay"], "room"),
			self.world.rooms[1],
			msg="a refused room move still moved the guest",
		)

	def test_a_stay_moving_out_of_its_own_room_is_not_its_own_rival(self):
		"""The exclusion that keeps the guard from blocking legitimate work.

		A guest moving from room 0 to room 1 must not be refused because room 0
		is occupied - by them.
		"""
		reservation = self.world.confirmed(nights=2)
		line = self.world.lines(reservation)[0]["name"]
		stay = stay_service.check_in(reservation, line, self.world.rooms[0])
		frappe.db.commit()

		result = stay_service.change_room(stay["stay"], self.world.rooms[1], "higher floor")
		frappe.db.commit()

		self.assertEqual(result["to_room"], self.world.rooms[1])
		self.assertEqual(
			frappe.db.get_value("Stay", stay["stay"], "room"),
			self.world.rooms[1],
		)


class TestTheRuleItself(IntegrationTestCase):
	"""The state set, pinned against the Stay state machine.

	B01 exists because a status that means "guest still in the room" was left out
	of a set that decides whether the room is free, and nothing said so. These
	assertions are the thing that would have said so.

	Needs no fixtures: it reads the declarations, not the database.
	"""

	def test_the_active_set_is_exactly_the_occupied_statuses(self):
		self.assertEqual(
			set(stay_service.ACTIVE_OCCUPANCY_STATES),
			{stay_service.IN_HOUSE, stay_service.DUE_OUT},
		)

	def test_every_active_status_is_a_real_stay_status(self):
		"""A typo in the set would silently stop blocking anything."""
		for status in stay_service.ACTIVE_OCCUPANCY_STATES:
			self.assertIn(status, stay_service.TRANSITIONS, msg=f"{status} is not a Stay status")

	def test_a_new_stay_status_must_be_classified_deliberately(self):
		"""Fails when somebody adds a status without deciding this question.

		Whoever adds one has to come here and say whether a guest in it is in
		their room. That is the whole defence against B01 recurring, so the test
		names the statuses it knows about rather than deriving them.
		"""
		self.assertEqual(
			set(stay_service.TRANSITIONS),
			{
				stay_service.EXPECTED,
				stay_service.IN_HOUSE,
				stay_service.DUE_OUT,
				stay_service.CHECKED_OUT,
				stay_service.CLOSED,
			},
			msg=(
				"the Stay state machine changed: decide whether the new status means the "
				"guest is physically in their room, and add it to ACTIVE_OCCUPANCY_STATES "
				"or deliberately leave it out"
			),
		)

	def test_departed_and_unarrived_statuses_are_not_active(self):
		for status in (stay_service.EXPECTED, stay_service.CHECKED_OUT, stay_service.CLOSED):
			self.assertNotIn(status, stay_service.ACTIVE_OCCUPANCY_STATES)

	def test_due_out_is_not_treated_as_an_occupied_room_flag(self):
		"""The asymmetry that caused B01, pinned so it stays deliberate.

		`Due Out` is *not* in `OCCUPIED_STATES` - the room flag - because a Due
		Out room is genuinely re-lettable once its guest has left. It *is* in
		`ACTIVE_OCCUPANCY_STATES` - the Stay rule - because the guest has not
		necessarily left. Both halves are correct, and the bug was having only
		the first.
		"""
		self.assertNotIn("Due Out", room_service.OCCUPIED_STATES)
		self.assertIn(stay_service.DUE_OUT, stay_service.ACTIVE_OCCUPANCY_STATES)


class TestOccupancyAuthorityHelper(RoomAuthorityTestCase):
	"""The centralised rule itself, independent of any caller."""

	WORLD_CODE = "RAH"

	def test_an_in_house_stay_occupies_its_room(self):
		room = self.world.rooms[0]
		checked_in = self._guest_in_house_mid_stay(room)

		self.assertEqual(
			room_service.active_stay_in_room(room),
			checked_in["stay"],
			msg="the authority did not see an In House stay",
		)

	def test_a_due_out_stay_occupies_its_room(self):
		room = self.world.rooms[0]
		checked_in = self._guest_due_out_today(room)

		self.assertEqual(room_service.active_stay_in_room(room), checked_in["stay"])

	def test_an_empty_room_is_not_occupied(self):
		self.assertIsNone(room_service.active_stay_in_room(self.world.rooms[2]))

	def test_the_excluded_stay_is_not_reported(self):
		room = self.world.rooms[0]
		checked_in = self._guest_due_out_today(room)

		self.assertIsNone(
			room_service.active_stay_in_room(room, exclude_stay=checked_in["stay"]),
			msg="a stay was reported as its own rival",
		)

	def test_a_checked_out_stay_does_not_occupy_its_room(self):
		room = self.world.rooms[0]
		checked_in = self._guest_due_out_today(room)

		stay_service.transition(checked_in["stay"], stay_service.CHECKED_OUT)
		frappe.db.set_value(
			"Stay", checked_in["stay"], "checked_out_on", "2026-01-01 12:00:00", update_modified=False
		)
		frappe.db.commit()

		self.assertIsNone(room_service.active_stay_in_room(room))

	def test_a_stay_with_a_checkout_timestamp_does_not_occupy_its_room(self):
		"""`checked_out_on` is half of the rule, and carries its own weight.

		Estate audit F found three stays whose status and timestamp disagree, so
		the two halves genuinely do come apart on real data.
		"""
		room = self.world.rooms[0]
		checked_in = self._guest_due_out_today(room)

		frappe.db.set_value(
			"Stay", checked_in["stay"], "checked_out_on", "2026-01-01 12:00:00", update_modified=False
		)
		frappe.db.commit()

		self.assertIsNone(room_service.active_stay_in_room(room))
