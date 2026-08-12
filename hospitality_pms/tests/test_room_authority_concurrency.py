"""Physical-room races: at most one active Stay may own one room.

HPMS-UAT-16.7.5-B01 was found as persisted state, not as a race - room 402 was
re-let to a second guest hours after the first was marked Due Out, with no
concurrency involved at all. The sequential guards are pinned in
`test_room_authority.py`. This suite asks the separate question: now that the
guards exist, do they hold when two front-desk agents act at the same instant?

The invariant asserted is the **persisted** one:

    for any physical room, at most one Stay is active
    (stay_status in ACTIVE_OCCUPANCY_STATES and checked_out_on is null)

and never merely "one worker raised an exception". A guard that refuses both
agents, or that refuses one and lets the other write a Stay it should not have,
would satisfy the weaker assertion and still put two guests behind one door.

Each worker is a real process with its own connection, transaction and
REPEATABLE-READ snapshot; see `tests/concurrency.py` for why threads cannot
test this.

Lock chain
----------
The documented order (`services/reservations.py`) is

    Reservation -> Reservation Room -> Room Type -> Hotel Room -> Stay

and the new guard reads `Stay` under a locking read at position 5, after the
Hotel Room it is asking about. That is the chain's own order, so
`assign_room` and `check_in` acquire nothing out of sequence.

`change_room` is the exception, and `test_two_moves_swapping_rooms` exists to
measure it. It locks its own Stay *before* both Hotel Rooms - it has to know
which rooms to lock, and the Stay is what says so - which is a pre-existing
deviation from the chain, recorded in that function since 16.7.2. Adding a
second Stay acquisition after the Hotel Rooms looks like it should close a
cycle. Measured, it does not: a swap is refused by the two earlier authorities
before either worker reaches the Stay read, six runs out of six, zero
deadlocks. The lock chain is therefore left alone rather than reordered on the
strength of a cycle the evidence says is unreachable; that test carries the full
reasoning and prints its outcome on every run so the decision stays falsifiable.
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days

from hospitality_pms.services import reservations as reservation_service
from hospitality_pms.services import rooms as room_service
from hospitality_pms.services import stays as stay_service
from hospitality_pms.services import walk_in as walk_in_service
from hospitality_pms.tests.concurrency import Worker, assert_all_ran, run_workers
from hospitality_pms.tests.inventory_world import InventoryWorld

RESET = (
	"Folio Log",
	"Guest Folio",
	"Room Status Log",
	"Stay",
	"Reservation Log",
	"Reservation",
)

#: The statuses this suite counts as "a guest is in the room", spelled out here
#: rather than imported from `stays.ACTIVE_OCCUPANCY_STATES`.
#:
#: Deliberate. This is the suite that decides whether the invariant *holds*, and
#: it must be able to measure a build in which the rule does not exist or is
#: wrong - which is exactly the build this defect was found in. Importing the
#: constant would make the measurement agree with the code under test by
#: construction, and would make the whole suite un-runnable against the
#: unfixed services rather than failing against them.
#:
#: `test_room_authority.TestTheRuleItself` pins the service constant to these
#: same two statuses, so the duplication cannot drift silently.
ACTIVE_STAY_STATUSES = ("In House", "Due Out")


# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------
#
# Module level and JSON-serialisable arguments only: each is imported by a fresh
# process through `frappe.get_attr`.
#
# Every worker opens its transaction with a plain read *before* the barrier
# releases it. That is not decoration - it fixes the REPEATABLE-READ snapshot
# early, which is the condition under which a lock-without-refresh bug (N1)
# actually bites. A worker that took its first read after the rival committed
# would see the rival's write through no merit of the code under test.


def _seed_snapshot(room: str):
	"""Open this transaction's read view, and see the room as it stands now."""
	frappe.db.sql("select occupancy_status from `tabHotel Room` where name = %s", room)
	frappe.db.sql(
		"select name from `tabStay` where room = %s and stay_status in ('In House', 'Due Out')", room
	)


def _check_in_worker(barrier, reservation: str, line: str, room: str, tag: str, partner: str) -> dict:
	"""One agent checking a booking into a specific room."""
	_seed_snapshot(room)

	barrier.signal(f"ready_{tag}")
	barrier.wait(f"ready_{partner}")

	result = stay_service.check_in(reservation, line, room)
	frappe.db.commit()

	return {"stay": result["stay"], "room": result["room"]}


def _assign_worker(barrier, reservation: str, line: str, room: str, tag: str, partner: str) -> dict:
	"""One agent pre-assigning a room to a booking that has not arrived."""
	_seed_snapshot(room)

	barrier.signal(f"ready_{tag}")
	barrier.wait(f"ready_{partner}")

	reservation_service.assign_room(reservation, line, room)
	frappe.db.commit()

	return {"assigned": room}


def _move_worker(barrier, stay: str, new_room: str, tag: str, partner: str) -> dict:
	"""One agent moving an in-house guest into a specific room."""
	_seed_snapshot(new_room)

	barrier.signal(f"ready_{tag}")
	barrier.wait(f"ready_{partner}")

	result = stay_service.change_room(stay, new_room, "concurrency probe")
	frappe.db.commit()

	return {"stay": stay, "to_room": result["to_room"]}


def _walk_in_worker(
	barrier, property_name: str, guest: str, departure, room_type: str, room: str, tag: str, partner: str
) -> dict:
	"""One agent booking and checking in a guest at the desk."""
	_seed_snapshot(room)

	barrier.signal(f"ready_{tag}")
	barrier.wait(f"ready_{partner}")

	result = walk_in_service.create_walk_in(
		property_name=property_name,
		guest=guest,
		departure_date=departure,
		room_type=room_type,
		room=room,
	)
	frappe.db.commit()

	return {"stay": result.get("stay"), "room": room}


# ---------------------------------------------------------------------------
# The suite
# ---------------------------------------------------------------------------


class RoomAuthorityRaceTestCase(IntegrationTestCase):
	"""A house with rooms to contest, emptied before every race.

	Fixtures commit and workers commit, so nothing a race leaves behind is
	covered by `IntegrationTestCase`'s rollback. Every test states its premise as
	an assertion rather than assuming it.
	"""

	ROOMS = 4
	WORLD_CODE = "RAR"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.world = InventoryWorld("RAR", cls.WORLD_CODE, rooms=cls.ROOMS)
		cls.opening_date = cls.world.business_date

	@classmethod
	def tearDownClass(cls):
		cls.world.teardown()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")
		self.world.set_business_date(self.opening_date)
		self.world.fixtures.reset_property_records(self.world.property, RESET)

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

	def booking(self, *, nights: int = 2, arrival=None) -> tuple[str, str]:
		reservation = self.world.confirmed(nights=nights, arrival=arrival)
		line = self.world.lines(reservation)[0]["name"]
		frappe.db.commit()

		return reservation, line

	def guest_in(self, room: str, *, nights: int = 2) -> str:
		reservation, line = self.booking(nights=nights)
		stay = stay_service.check_in(reservation, line, room)
		frappe.db.commit()

		return stay["stay"]

	def stale_vacant(self, room: str):
		"""Force the room's flag to lie, the way room 402's did."""
		frappe.db.set_value("Hotel Room", room, "occupancy_status", "Vacant", update_modified=False)
		frappe.db.commit()

	# -- reading the world back -------------------------------------------

	def active_stays_in(self, room: str) -> list[str]:
		"""The persisted invariant's subject, read fresh."""
		return frappe.get_all(
			"Stay",
			filters={
				"room": room,
				"stay_status": ("in", ACTIVE_STAY_STATUSES),
				"checked_out_on": ("is", "not set"),
			},
			pluck="name",
			order_by="creation asc",
		)

	def failed(self, results: list[dict]) -> list[dict]:
		return [result for result in results if result["status"] == "failed"]

	def committed(self, results: list[dict]) -> list[dict]:
		return [result for result in results if result["status"] == "committed"]

	def errors(self, results: list[dict]) -> str:
		return " | ".join(result.get("error", "") for result in self.failed(results))

	def deadlocks(self, results: list[dict]) -> list[dict]:
		return [
			result for result in self.failed(results) if "deadlock" in (result.get("error") or "").lower()
		]

	# -- the invariant ----------------------------------------------------

	def assertSingleOccupant(self, room: str, results: list[dict] | None = None):
		"""At most one active Stay owns this physical room. The whole point.

		Asserted against the database rather than against what the workers
		returned, because a worker that raised may still have committed, and a
		worker that returned may have been rolled back underneath it.
		"""
		occupants = self.active_stays_in(room)
		detail = f" (workers: {self.errors(results)})" if results else ""

		self.assertLessEqual(
			len(occupants),
			1,
			msg=f"room {room} has {len(occupants)} active stays: {occupants}{detail}",
		)

		return occupants


class TestTwoPlacementsRacingForOneRoom(RoomAuthorityRaceTestCase):
	def test_two_check_ins_for_the_same_physical_room(self):
		"""The plainest race: two agents, one empty room, same instant."""
		room = self.world.rooms[0]
		first, first_line = self.booking()
		second, second_line = self.booking()

		results = run_workers(
			[
				Worker(
					"hospitality_pms.tests.test_room_authority_concurrency._check_in_worker",
					{
						"reservation": first,
						"line": first_line,
						"room": room,
						"tag": "a",
						"partner": "b",
					},
				),
				Worker(
					"hospitality_pms.tests.test_room_authority_concurrency._check_in_worker",
					{
						"reservation": second,
						"line": second_line,
						"room": room,
						"tag": "b",
						"partner": "a",
					},
				),
			]
		)
		assert_all_ran(results)

		occupants = self.assertSingleOccupant(room, results)

		self.assertEqual(
			len(occupants), 1, msg=f"both check-ins were refused, so nobody got the room: {self.errors(results)}"
		)
		self.assertEqual(
			len(self.committed(results)), 1, msg=f"more than one check-in committed: {results}"
		)

		# The loser's refusal doubles as an N1 detector for the new guard - when the
		# loser gets as far as the guard at all.
		#
		# Both workers opened their read view on an empty room before the barrier
		# released them, so the loser *cannot* see the winner's Stay through any
		# plain read: its snapshot predates the commit, and the room's own flag
		# still says Vacant in it. A refusal naming the winner's stay is therefore
		# only reachable through the locking read.
		#
		# But there are two ways to lose this race, and only one of them reaches
		# the guard. Both workers take the Hotel Room lock in `check_in` before any
		# of this, and InnoDB may break that contention with a 1213 rather than
		# queueing - measured on the R1C regression site, where the loser deadlocked
		# at `lock_document("Hotel Room", room)` and never got to the Stay read.
		# That is the documented trade this codebase already accepts ("a retryable
		# deadlock is preferable to silent double occupancy"), and it is the *safe*
		# way to lose: the whole transaction rolls back.
		#
		# So the invariant is asserted unconditionally above, and the N1 property is
		# asserted only on the path that can carry it. The property is not left
		# untested by that concession: `TestRacesAgainstASittingGuest` asserts the
		# guard's exact message strictly, with no deadlock exemption, and cannot
		# deadlock for a structural reason.
		#
		# That reason is lock *ordering*, and it is worth stating precisely because
		# two earlier versions of this comment got it wrong. It is not that the room
		# lock is uncontended there - both workers contend for it exactly as they do
		# here. Nor is it that no second lock is taken: `assert_room_unoccupied`
		# reads Stay with `for_update`, so a second lock certainly is requested, and
		# the refusal is derived *from* that locking read. What makes a cycle
		# impossible is that the Stay lock is only ever requested while already
		# holding the Hotel Room lock - always that order, never the reverse - and
		# the sitting guest's Stay row is held by nobody, its transaction having
		# committed long before the race. So the worker that waits holds nothing the
		# holder wants, and there is no cycle to break.
		print(f"\n  R1A empty-room race refusal: {self.errors(results)}")

		winner = self.committed(results)[0]["result"]["stay"]
		deadlocked = self.deadlocks(results)

		if deadlocked:
			print(
				"  R1A note: the loser lost to a lock cycle rather than to the guard "
				f"({len(deadlocked)} of {len(results)}); invariant still asserted"
			)

		for result in self.failed(results):
			if result in deadlocked:
				continue

			self.assertIn(
				winner,
				result.get("error") or "",
				msg=(
					"the loser was not refused by the active-Stay guard naming the winner, "
					f"so the current read may have been answered from the snapshot: {result.get('error')}"
				),
			)

	def test_a_check_in_races_a_pre_assignment_of_the_same_room(self):
		"""Assignment and check-in are different writers of one physical fact."""
		room = self.world.rooms[0]
		arriving, arriving_line = self.booking()
		# A booking that has not arrived yet, which assignment is for.
		future, future_line = self.booking(arrival=self.world.business_date)

		results = run_workers(
			[
				Worker(
					"hospitality_pms.tests.test_room_authority_concurrency._check_in_worker",
					{
						"reservation": arriving,
						"line": arriving_line,
						"room": room,
						"tag": "a",
						"partner": "b",
					},
				),
				Worker(
					"hospitality_pms.tests.test_room_authority_concurrency._assign_worker",
					{
						"reservation": future,
						"line": future_line,
						"room": room,
						"tag": "b",
						"partner": "a",
					},
				),
			]
		)
		assert_all_ran(results)

		self.assertSingleOccupant(room, results)

		# Whoever won, the room must not end up both slept in and promised to
		# somebody else for the same nights.
		occupants = self.active_stays_in(room)
		promised = frappe.get_all(
			"Reservation Room",
			filters={"assigned_room": room, "reservation_status": ("in", ("Confirmed", "Guaranteed"))},
			pluck="parent",
		)

		if occupants and promised:
			self.fail(
				f"room {room} is occupied by {occupants} and also promised to {promised}: "
				f"{self.errors(results)}"
			)

	def test_a_walk_in_races_a_check_in_for_the_same_room(self):
		"""The fast path must be no more permissive than the slow one."""
		room = self.world.rooms[0]
		booked, booked_line = self.booking()
		guest = self.world.fixtures.guest("WalkRace")
		frappe.db.commit()

		results = run_workers(
			[
				Worker(
					"hospitality_pms.tests.test_room_authority_concurrency._check_in_worker",
					{
						"reservation": booked,
						"line": booked_line,
						"room": room,
						"tag": "a",
						"partner": "b",
					},
				),
				Worker(
					"hospitality_pms.tests.test_room_authority_concurrency._walk_in_worker",
					{
						"property_name": self.world.property,
						"guest": guest,
						"departure": str(add_days(self.world.business_date, 2)),
						"room_type": self.world.room_type,
						"room": room,
						"tag": "b",
						"partner": "a",
					},
				),
			]
		)
		assert_all_ran(results)

		occupants = self.assertSingleOccupant(room, results)
		self.assertEqual(
			len(occupants), 1, msg=f"nobody got the room: {self.errors(results)}"
		)


class TestRacesAgainstASittingGuest(RoomAuthorityRaceTestCase):
	"""The B01 shape: somebody is already in the room, and the flag is wrong."""

	WORLD_CODE = "RAS"

	def _due_out_guest_with_a_lying_flag(self, room: str) -> str:
		"""Room 402's persisted state, built through the services then forced.

		A guest checked in for one night, the business date advanced onto their
		departure date the way the Night Audit advances it, `mark_due_out` run,
		and finally the room flag forced to `Vacant` - which is what the *second*
		guest's checkout did on the bench.
		"""
		stay = self.guest_in(room, nights=1)

		self.world.set_business_date(add_days(self.opening_date, 1))
		due = stay_service.mark_due_out(self.world.property)
		frappe.db.commit()

		self.assertIn(stay, due)
		self.stale_vacant(room)

		self.assertEqual(self.active_stays_in(room), [stay], msg="premise lost before the race")

		return stay

	def test_two_check_ins_race_into_a_room_whose_guest_is_still_in_it(self):
		"""Both must lose. There is nowhere for either guest to sleep."""
		room = self.world.rooms[0]
		sitting = self._due_out_guest_with_a_lying_flag(room)

		first, first_line = self.booking(arrival=self.world.business_date)
		second, second_line = self.booking(arrival=self.world.business_date)

		results = run_workers(
			[
				Worker(
					"hospitality_pms.tests.test_room_authority_concurrency._check_in_worker",
					{
						"reservation": first,
						"line": first_line,
						"room": room,
						"tag": "a",
						"partner": "b",
					},
				),
				Worker(
					"hospitality_pms.tests.test_room_authority_concurrency._check_in_worker",
					{
						"reservation": second,
						"line": second_line,
						"room": room,
						"tag": "b",
						"partner": "a",
					},
				),
			]
		)
		assert_all_ran(results)

		# Printed because *which* guard refused is the whole question here.
		#
		# In this premise the other two authorities are both blind by
		# construction, and deliberately so: the room's flag has been forced to
		# `Vacant`, and the sitting guest's line departs today so its
		# departure-exclusive overlap does not catch a rival arriving today. So
		# the refusal below can only have come from the active-Stay guard, and if
		# it ever starts coming from somewhere else this premise has drifted and
		# the test has stopped testing what it claims to.
		print(f"\n  R1A B01 race refusals: {self.errors(results)}")

		for result in self.failed(results):
			self.assertIn(
				"has not been checked out",
				result.get("error") or "",
				msg=(
					"the refusal did not come from the active-Stay guard, so this race "
					f"no longer exercises it: {result.get('error')}"
				),
			)

		occupants = self.assertSingleOccupant(room, results)

		self.assertEqual(
			occupants,
			[sitting],
			msg=(
				"the sitting guest is no longer the room's only occupant - a stale "
				f"Vacant flag admitted somebody: {results}"
			),
		)
		self.assertEqual(
			len(self.committed(results)),
			0,
			msg=f"a check-in committed into an occupied room: {results}",
		)

	def test_a_move_and_a_check_in_race_into_a_room_whose_guest_is_still_in_it(self):
		room = self.world.rooms[0]
		sitting = self._due_out_guest_with_a_lying_flag(room)

		mover = self.guest_in(self.world.rooms[1], nights=2)
		arriving, arriving_line = self.booking(arrival=self.world.business_date)

		results = run_workers(
			[
				Worker(
					"hospitality_pms.tests.test_room_authority_concurrency._move_worker",
					{"stay": mover, "new_room": room, "tag": "a", "partner": "b"},
				),
				Worker(
					"hospitality_pms.tests.test_room_authority_concurrency._check_in_worker",
					{
						"reservation": arriving,
						"line": arriving_line,
						"room": room,
						"tag": "b",
						"partner": "a",
					},
				),
			]
		)
		assert_all_ran(results)

		self.assertEqual(
			self.assertSingleOccupant(room, results),
			[sitting],
			msg=f"somebody was placed in an occupied room: {results}",
		)
		self.assertEqual(
			frappe.db.get_value("Stay", mover, "room"),
			self.world.rooms[1],
			msg="the mover was moved into an occupied room",
		)


class TestRacesBetweenMovesAndPlacements(RoomAuthorityRaceTestCase):
	WORLD_CODE = "RAM"

	def test_a_move_races_a_check_in_for_one_empty_room(self):
		"""Two writers, one destination, neither already in it."""
		target = self.world.rooms[2]
		mover = self.guest_in(self.world.rooms[0], nights=2)
		arriving, arriving_line = self.booking()

		results = run_workers(
			[
				Worker(
					"hospitality_pms.tests.test_room_authority_concurrency._move_worker",
					{"stay": mover, "new_room": target, "tag": "a", "partner": "b"},
				),
				Worker(
					"hospitality_pms.tests.test_room_authority_concurrency._check_in_worker",
					{
						"reservation": arriving,
						"line": arriving_line,
						"room": target,
						"tag": "b",
						"partner": "a",
					},
				),
			]
		)
		assert_all_ran(results)

		self.assertSingleOccupant(target, results)

	def test_a_move_races_an_assignment_for_one_empty_room(self):
		target = self.world.rooms[2]
		mover = self.guest_in(self.world.rooms[0], nights=2)
		future, future_line = self.booking()

		results = run_workers(
			[
				Worker(
					"hospitality_pms.tests.test_room_authority_concurrency._move_worker",
					{"stay": mover, "new_room": target, "tag": "a", "partner": "b"},
				),
				Worker(
					"hospitality_pms.tests.test_room_authority_concurrency._assign_worker",
					{
						"reservation": future,
						"line": future_line,
						"room": target,
						"tag": "b",
						"partner": "a",
					},
				),
			]
		)
		assert_all_ran(results)

		self.assertSingleOccupant(target, results)

		occupants = self.active_stays_in(target)
		promised = frappe.get_all(
			"Reservation Room",
			filters={"assigned_room": target, "reservation_status": ("in", ("Confirmed", "Guaranteed"))},
			pluck="parent",
		)

		if occupants and promised:
			self.fail(
				f"room {target} is occupied by {occupants} and promised to {promised}: "
				f"{self.errors(results)}"
			)

	def test_two_moves_swapping_rooms(self):
		"""The lock-order question this build raises, and the measured answer.

		`change_room` locks its own Stay *before* both Hotel Rooms - it has to,
		because the Stay is what says which rooms to lock - which is a
		pre-existing deviation from the documented chain, recorded in that
		function since 16.7.2. The new occupancy guard adds a second Stay
		acquisition *after* the Hotel Rooms. On paper that closes a cycle: two
		guests swapping rooms would each hold their own Stay and want the other's
		while both queue on the same sorted Hotel Room locks.

		**Measured on this bench, it does not happen, and the reason is
		structural rather than lucky.** A swap means both destination rooms are
		genuinely `Occupied`, so `assert_assignable` refuses both moves from the
		room's own flag - and `_assert_room_free` refuses them again from the
		inventory row - before either worker reaches the Stay read. Six
		consecutive runs: both workers refused with "Room NN is already
		Occupied", zero deadlocks.

		Reaching the new guard in a two-move race would need *both* rooms
		corrupted in *both* of the earlier authorities at once - a stale flag and
		a stale reservation line on each. Room 402 was corrupted in one. So the
		cycle is reachable only from a doubly-corrupted estate, and there a
		retryable deadlock is the right trade against double occupancy: InnoDB
		rolls one whole transaction back, nothing partial commits, and the caller
		sees a refusal it can retry.

		The chain is therefore left as it stands and the reorder is *not* taken -
		it would be a speculative change to a documented lock order on the
		strength of a cycle the evidence says is unreachable. This test is what
		makes that decision falsifiable: it asserts the persisted invariant and
		coherence either way, and prints the outcome on every run, so if the
		behaviour ever changes it says so instead of quietly continuing to pass.
		"""
		first_room, second_room = self.world.rooms[0], self.world.rooms[1]
		first = self.guest_in(first_room, nights=2)
		second = self.guest_in(second_room, nights=2)

		results = run_workers(
			[
				Worker(
					"hospitality_pms.tests.test_room_authority_concurrency._move_worker",
					{"stay": first, "new_room": second_room, "tag": "a", "partner": "b"},
				),
				Worker(
					"hospitality_pms.tests.test_room_authority_concurrency._move_worker",
					{"stay": second, "new_room": first_room, "tag": "b", "partner": "a"},
				),
			]
		)
		assert_all_ran(results)

		deadlocked = self.deadlocks(results)

		# Printed on every run, not only on a deadlock. The outcome of this race
		# is the finding - which worker won, whether the loser was refused for a
		# readable reason or rolled back by InnoDB - and a test that prints
		# nothing when it passes leaves the next reader guessing whether the
		# cycle is closed or merely unobserved.
		print(
			f"\n  R1A swap-move outcome: "
			f"{[r['status'] for r in results]} deadlocks={len(deadlocked)}"
			+ (f" errors={self.errors(results)}" if self.failed(results) else "")
		)

		# Neither room may end up with two active stays, whoever won.
		self.assertSingleOccupant(first_room, results)
		self.assertSingleOccupant(second_room, results)

		# And no guest may be left in no room at all, or in a room somebody else
		# also holds. Every active stay sits in a distinct room.
		rooms = [
			frappe.db.get_value("Stay", stay, "room")
			for stay in (first, second)
			if frappe.db.get_value("Stay", stay, "stay_status") in ACTIVE_STAY_STATUSES
		]

		self.assertTrue(all(rooms), msg=f"a guest was left with no room: {rooms}")
		self.assertEqual(
			len(rooms),
			len(set(rooms)),
			msg=f"two guests ended up in one room: {rooms} - {self.errors(results)}",
		)

		self.assertLessEqual(
			len(deadlocked),
			1,
			msg=f"both moves were rolled back, so neither was applied: {self.errors(results)}",
		)


class TestDepartureReleasesTheRoom(RoomAuthorityRaceTestCase):
	WORLD_CODE = "RAD"

	def test_a_checked_out_stay_lets_the_next_guest_in(self):
		"""The guard must release, not merely block.

		A room whose guest has checked out has to be immediately re-lettable, or
		the fix would close the house instead of protecting it.
		"""
		room = self.world.rooms[0]
		reservation, line = self.booking(nights=1)
		sitting = stay_service.check_in(reservation, line, room)["stay"]
		frappe.db.commit()

		# Departed the way `services/checkout.py` departs a guest, and through the
		# same services it uses: the stay transitions and is stamped, the
		# reservation follows it out of the holding states, and the room is
		# released by `rooms.mark_checked_out` (Vacant, Dirty). Housekeeping then
		# turns it, because a dirty room is not offered to the next guest and this
		# test is about occupancy, not cleaning.
		#
		# All four, not just the Stay: each of the three authorities holds this
		# room for its own reason, and the point of the test is that a departure
		# releases all of them. Releasing only the Stay would prove nothing about
		# the guard and would be refused by the other two - correctly.
		stay_service.transition(sitting, stay_service.CHECKED_OUT)
		frappe.db.set_value(
			"Stay", sitting, "checked_out_on", "2026-01-01 12:00:00", update_modified=False
		)
		reservation_service._transition(
			frappe.get_doc(reservation_service.RESERVATION_DOCTYPE, reservation),
			reservation_service.CHECKED_OUT,
			reason="concurrency fixture: guest departed",
		)
		room_service.mark_checked_out(room, reference_doctype="Stay", reference_name=sitting)
		room_service.set_status(room, room_service.HOUSEKEEPING, "Clean", reason="turned")
		frappe.db.commit()

		self.assertEqual(self.active_stays_in(room), [])

		arriving, arriving_line = self.booking()
		result = stay_service.check_in(arriving, arriving_line, room)
		frappe.db.commit()

		self.assertEqual(self.active_stays_in(room), [result["stay"]])
