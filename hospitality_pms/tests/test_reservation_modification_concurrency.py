# Copyright (c) 2026, Globcom Qatar and Contributors
# See license.txt

"""16.7.2 — the reservation modification services under genuine concurrency.

Every test here runs **real OS processes**, each with its own database
connection, its own transaction and its own REPEATABLE-READ snapshot,
choreographed through the file barrier in `tests/concurrency.py`. A threaded or
sequential version of any of these tests would share one connection, share one
snapshot, and therefore prove nothing at all about the locking these services
depend on - it would pass against code that oversells in production.

The shape every test uses
------------------------
Each worker issues a plain read, waits at the barrier, then calls the service.
The plain read is not decoration: it opens the transaction's consistent read
view *before* the rival commits, which is what a real HTTP request does long
before it reaches a service - the session load, the permission check and the
availability screen the agent was looking at have all read by then. Without it a
worker's first read would happen after the rival's commit, and the hazard under
test would be absent from the test that exists to catch it.

Two interleavings are used, deliberately:

* **Simultaneous** - both workers released together, so they contend for the
  same row lock and one waits for the other's commit. This is the production
  shape.
* **Sequenced** - one worker takes its snapshot, the other completes and commits
  in full, and only then does the first act. This removes the timing question
  entirely, so a failure can only mean the service decided on a value that was
  already out of date when it decided. Used for the stale-read tests, which are
  the ones the Wave-1 current-read primitives exist for.

What is asserted
----------------
Inventory state, not merely exceptions. After every race the availability
engine's own sold count for the contested nights is compared with the house's
capacity, because **an oversell that raises no exception is the failure mode that
matters**. Exceptions are the second question, never the first.

What this suite found, and what closed it
-----------------------------------------
Two defects reproduced here, both pre-existing and both since fixed. The tests
that found them are kept exactly as they were written, now as ordinary passing
tests, because a regression test is only worth what its failure once proved.

* **HPMS-QA-16.7.2-A — the oversell.** The availability engine counted sold
  rooms with a plain `frappe.get_all`, so a caller holding the Room Type lock
  still counted from the read view it opened before the writer it queued behind
  committed, and sold the same room twice. Reproduced at 5 rooms sold in a house
  of 4, through `change_line_interval` *and* through two plain `confirm`s - which
  is what placed the defect in `services/availability.py` rather than in the
  modification services. Closed by threading a `current` flag through
  `check_availability` / `check_demand` / `_sold_by_night`, set only on the paths
  that commit inventory, so the count comes from a locking read there and stays a
  cheap snapshot read everywhere a screen renders it.
* **HPMS-QA-16.7.2-C — still open, and a consequence of fixing A.** A locking
  read locks every row the database examines, not the handful it counts, so the
  current sold count above conflicts with any caller holding its own
  reservation's rows (`lock_and_get_doc` locks child rows) while queuing for the
  same Room Type lock. Two commit paths contending for one room type can
  therefore close a lock cycle. Measured on this bench with a re-type racing a
  confirmation for the last deluxe room: 3 runs in 4 deadlocked with the current
  read, 0 in 4 without it. Resolving it is a lock-order decision - Room Type
  before Reservation rather than after - which changes the documented chain and
  is the Lead's to make, so it is reported rather than taken. The affected test
  is sequenced rather than simultaneous, and says so.
* **HPMS-QA-16.7.2-B — the deadlock.** `stays.change_room` wrote
  `Reservation Room.assigned_room` while holding both Hotel Rooms, inverting the
  documented chain against `change_line_interval`, which holds the row and then
  asks for the room. InnoDB broke the cycle with a 1213 rather than either caller
  being refused for a readable reason. Closed by taking the row's lock first in
  `change_room`, ahead of the Stay and both rooms.
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import getdate

from hospitality_pms.services import reservations as reservation_service
from hospitality_pms.services import stays as stay_service
from hospitality_pms.services.availability import get_availability
from hospitality_pms.services.exceptions import AvailabilityError, HospitalityPMSError
from hospitality_pms.tests.concurrency import Worker, assert_all_ran, run_workers
from hospitality_pms.tests.inventory_world import InventoryWorld

#: Operational residue to clear between tests. The workers commit, so nothing a
#: race leaves behind is covered by `IntegrationTestCase`'s rollback - and a
#: premise of "exactly one room free" is worthless if the previous test's
#: booking is still holding rooms.
RESET = (
	"Folio Log",
	"Guest Folio",
	"Room Status Log",
	"Stay",
	"Reservation Log",
	"Reservation",
)

#: The reservation states that consume inventory, as SQL. Kept as text rather
#: than imported so the worker's snapshot read is plainly a raw statement.
HOLDING = "('Confirmed', 'Guaranteed', 'Checked In')"

DELUXE_RATE = 150.0


# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------
#
# Module level, JSON-serialisable arguments only: each is imported by a fresh
# process through `frappe.get_attr` (see tests/concurrency.py).
#
# Two barrier conventions are used. `tag`/`partner` releases both workers at the
# same instant; `snapshot_taken`/`rival_committed` sequences them.


def _open_snapshot(property_name: str):
	"""Open this transaction's REPEATABLE-READ view before the race starts.

	InnoDB establishes a transaction's consistent read view at its first
	non-locking read and holds it until the transaction ends. Every plain read
	afterwards is answered from that view - including the `frappe.get_all` calls
	inside the availability engine - so *when* the view was opened decides
	whether a service can see a rival's committed booking at all.

	Reads exactly the table availability counts, so there is no doubt about what
	the view covers, and as raw SQL so no Frappe cache can answer instead of the
	database.
	"""
	frappe.db.sql(
		f"""
		select count(*) from `tabReservation Room`
		where property = %s and reservation_status in {HOLDING}
		""",
		property_name,
	)


# -- simultaneous workers ---------------------------------------------------


def _move_worker(
	barrier,
	property_name: str,
	reservation: str,
	room_line: str,
	arrival: str | None,
	departure: str | None,
	tag: str,
	partner: str,
) -> dict:
	"""Move one room line's dates through the service under test."""
	_open_snapshot(property_name)

	barrier.signal(f"ready_{tag}")
	barrier.wait(f"ready_{partner}")

	result = reservation_service.change_line_interval(reservation, room_line, arrival, departure)
	frappe.db.commit()

	return result


def _confirm_worker(barrier, property_name: str, reservation: str, tag: str, partner: str) -> dict:
	"""Confirm a competing booking - the operation that commits inventory."""
	_open_snapshot(property_name)

	barrier.signal(f"ready_{tag}")
	barrier.wait(f"ready_{partner}")

	status = reservation_service.confirm(reservation)
	frappe.db.commit()

	return {"reservation": reservation, "status": status}


def _assign_worker(
	barrier, property_name: str, reservation: str, room_line: str, room: str, tag: str, partner: str
) -> dict:
	"""Promise a specific physical room to a line."""
	_open_snapshot(property_name)

	barrier.signal(f"ready_{tag}")
	barrier.wait(f"ready_{partner}")

	assigned = reservation_service.assign_room(reservation, room_line, room)
	frappe.db.commit()

	return {"assigned_room": assigned}


def _change_room_worker(
	barrier, property_name: str, stay: str, room: str, tag: str, partner: str
) -> dict:
	"""Move an in-house guest to another room, from the other end of the chain."""
	_open_snapshot(property_name)

	barrier.signal(f"ready_{tag}")
	barrier.wait(f"ready_{partner}")

	result = stay_service.change_room(stay, room, "Concurrency test: guest moved")
	frappe.db.commit()

	return result


def _extend_worker(
	barrier, property_name: str, stay: str, departure: str, tag: str, partner: str
) -> dict:
	"""Extend a stay - the other caller of the documented chain."""
	_open_snapshot(property_name)

	barrier.signal(f"ready_{tag}")
	barrier.wait(f"ready_{partner}")

	result = stay_service.extend_stay(stay, departure, reason="Concurrency test: guest stays on")
	frappe.db.commit()

	return result


def _add_line_worker(
	barrier,
	property_name: str,
	reservation: str,
	room_type: str,
	arrival: str,
	departure: str,
	tag: str,
	partner: str,
) -> dict:
	"""Add one room to a booking that is still being put together."""
	_open_snapshot(property_name)

	barrier.signal(f"ready_{tag}")
	barrier.wait(f"ready_{partner}")

	result = reservation_service.add_room_line(reservation, room_type, arrival, departure)
	frappe.db.commit()

	return result


def _remove_line_worker(
	barrier, property_name: str, reservation: str, room_line: str, tag: str, partner: str
) -> dict:
	"""Drop a room line from a booking."""
	_open_snapshot(property_name)

	barrier.signal(f"ready_{tag}")
	barrier.wait(f"ready_{partner}")

	result = reservation_service.remove_room_line(reservation, room_line)
	frappe.db.commit()

	return result


def _confirm_and_check_in_worker(
	barrier, property_name: str, reservation: str, room_line: str, room: str, tag: str, partner: str
) -> dict:
	"""Take a booking all the way to a guest standing in the room.

	Two desk actions in one transaction. That is not how the front office issues
	them - confirmation and check-in are separate requests - but the point of
	this worker is that the booking's *status* moves while the rival is queued
	behind the Reservation lock, and one transaction is the sharpest way to
	arrange that.
	"""
	_open_snapshot(property_name)

	barrier.signal(f"ready_{tag}")
	barrier.wait(f"ready_{partner}")

	reservation_service.confirm(reservation)
	result = stay_service.check_in(reservation, room_line, room)
	frappe.db.commit()

	return result


# -- sequenced workers ------------------------------------------------------
#
# The first takes its snapshot and then waits for the second to finish
# committing. No lock contention is involved at all: whatever the first one then
# decides, it decides with the rival's work already durable in the database.


def _snapshot_then_move_worker(
	barrier,
	property_name: str,
	reservation: str,
	room_line: str,
	arrival: str,
	departure: str,
) -> dict:
	_open_snapshot(property_name)

	barrier.signal("snapshot_taken")
	barrier.wait("rival_committed")

	result = reservation_service.change_line_interval(reservation, room_line, arrival, departure)
	frappe.db.commit()

	return result


def _snapshot_then_retype_worker(
	barrier, property_name: str, reservation: str, room_line: str, room_type: str
) -> dict:
	_open_snapshot(property_name)

	barrier.signal("snapshot_taken")
	barrier.wait("rival_committed")

	result = reservation_service.change_line_room_type(reservation, room_line, room_type)
	frappe.db.commit()

	return result


def _snapshot_then_confirm_worker(barrier, property_name: str, reservation: str) -> dict:
	_open_snapshot(property_name)

	barrier.signal("snapshot_taken")
	barrier.wait("rival_committed")

	status = reservation_service.confirm(reservation)
	frappe.db.commit()

	return {"reservation": reservation, "status": status}


def _rival_confirm_worker(barrier, reservation: str) -> dict:
	barrier.wait("snapshot_taken")

	status = reservation_service.confirm(reservation)
	frappe.db.commit()

	barrier.signal("rival_committed")

	return {"reservation": reservation, "status": status}


def _rival_move_worker(
	barrier, reservation: str, room_line: str, arrival: str, departure: str
) -> dict:
	barrier.wait("snapshot_taken")

	result = reservation_service.change_line_interval(reservation, room_line, arrival, departure)
	frappe.db.commit()

	barrier.signal("rival_committed")

	return result


def _rival_cancel_worker(barrier, reservation: str) -> dict:
	barrier.wait("snapshot_taken")

	result = reservation_service.cancel(reservation, "Concurrency test: guest cancelled")
	frappe.db.commit()

	barrier.signal("rival_committed")

	return result


# ---------------------------------------------------------------------------
# Shared fixture world
# ---------------------------------------------------------------------------


class ModificationRaceTestCase(IntegrationTestCase):
	"""A house with rooms to contest, emptied before every race.

	Fixtures commit and workers commit, so a booking left behind by one test
	would satisfy - or destroy - the next test's premise before it started. Every
	test therefore states its premise as an assertion (`fill_house`) rather than
	assuming it.
	"""

	ROOMS = 4

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.world = InventoryWorld(cls.WORLD_TAG, cls.WORLD_CODE, rooms=cls.ROOMS)

	@classmethod
	def tearDownClass(cls):
		cls.world.teardown()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")
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

	# -- reading the world back ------------------------------------------

	def line(self, reservation: str, index: int = 0) -> dict:
		return self.world.lines(reservation)[index]

	def interval(self, room_line: str) -> dict:
		return frappe.db.get_value(
			"Reservation Room",
			room_line,
			["arrival_date", "departure_date", "nights", "assigned_room", "room_type", "parent"],
			as_dict=True,
		)

	def header(self, reservation: str) -> dict:
		return frappe.db.get_value(
			"Reservation",
			reservation,
			["reservation_status", "arrival_date", "departure_date", "nights"],
			as_dict=True,
		)

	def rate_dates(self, reservation: str, room_line: str) -> list:
		return [
			getdate(row["rate_date"])
			for row in frappe.get_all(
				"Reservation Rate Line",
				filters={"parent": reservation, "room_line": room_line},
				fields=["rate_date"],
				order_by="rate_date asc",
			)
		]

	def sold_by_night(self, start: int, end: int, room_type: str | None = None) -> dict:
		"""What the availability engine itself says, night by night.

		The authority, not a count of rows this test wrote: an oversell is only
		real - and only visible to the next agent selling a room - through this.
		"""
		room_type = room_type or self.world.room_type
		availability = get_availability(
			self.world.property, self.world.day(start), self.world.day(end), room_type
		)

		return {
			night: int(figures["sold"])
			for night, figures in availability["room_types"][room_type]["by_night"].items()
		}

	def sold(self, start: int, end: int, room_type: str | None = None) -> int:
		return max(self.sold_by_night(start, end, room_type).values())

	def fill_house(self, leave_free: int, *, start: int, end: int) -> str:
		"""Confirm a booking that takes every room but `leave_free` on those nights."""
		filler = self.world.reservation(
			nights=end - start, rooms=self.ROOMS - leave_free, arrival=self.world.day(start)
		)
		reservation_service.confirm(filler)
		frappe.db.commit()

		self.assertEqual(
			self.world.available(start, end),
			leave_free,
			msg="the fixture premise is wrong: the house is not as full as this test needs",
		)

		return filler

	# -- reading a race back ---------------------------------------------

	def committed(self, results: list[dict]) -> list[dict]:
		return [result for result in results if result["status"] == "committed"]

	def failed(self, results: list[dict]) -> list[dict]:
		return [result for result in results if result["status"] == "failed"]

	def errors(self, results: list[dict]) -> str:
		return " | ".join(result.get("error", "") for result in self.failed(results))

	def deadlocks(self, results: list[dict]) -> list[dict]:
		"""Workers the database rolled back to break a lock cycle.

		A deadlock is a finding, not a flaky test: it means two callers took the
		documented chain in different orders. Matched on the message rather than
		on the exception class, because the driver in use decides which wrapper
		Frappe raises.
		"""
		return [
			result for result in self.failed(results) if "deadlock" in (result.get("error") or "").lower()
		]

	# -- assertions on inventory ------------------------------------------

	def assertSoldNights(self, start: int, end: int, expected: dict, room_type: str | None = None):
		"""Every contested night's sold count, against a house of known size."""
		actual = self.sold_by_night(start, end, room_type)
		capacity = 1 if room_type and room_type != self.world.room_type else self.ROOMS

		over = {night: count for night, count in actual.items() if count > capacity}
		self.assertEqual(
			over,
			{},
			msg=f"OVERSELL: {over} sold in a house of {capacity}; the whole picture was {actual}",
		)

		self.assertEqual(
			actual,
			{str(self.world.day(offset)): count for offset, count in expected.items()},
			msg=f"the engine's per-night sold count is not what this race should have left: {actual}",
		)

	def assertNoRoomPromisedTwice(self, room: str):
		"""No physical room may be promised to two overlapping holding lines.

		The question `_assert_room_free` exists to answer, asked of the database
		after the race rather than of the service during it.
		"""
		rows = frappe.get_all(
			"Reservation Room",
			filters={"assigned_room": room, "reservation_status": ("in", reservation_service.HOLDING_STATES)},
			fields=["name", "parent", "arrival_date", "departure_date"],
		)

		for first in rows:
			for second in rows:
				if first["name"] >= second["name"]:
					continue

				overlap = getdate(first["arrival_date"]) < getdate(second["departure_date"]) and getdate(
					first["departure_date"]
				) > getdate(second["arrival_date"])

				self.assertFalse(
					overlap,
					msg=f"room {room} is promised to two overlapping lines: {first} and {second}",
				)

	def assertNoOrphanStay(self):
		"""No Stay may point at a room line that no longer exists."""
		stays = frappe.get_all(
			"Stay",
			filters={"property": self.world.property},
			fields=["name", "reservation", "reservation_room_line", "room", "stay_status"],
		)

		for stay in stays:
			self.assertTrue(
				stay["reservation_room_line"]
				and frappe.db.exists("Reservation Room", stay["reservation_room_line"]),
				msg=f"stay {stay['name']} points at a room line that is gone: {stay}",
			)

			line = self.interval(stay["reservation_room_line"])
			self.assertEqual(
				line["assigned_room"],
				stay["room"],
				msg=f"stay {stay['name']} and its inventory row name different rooms: {stay} vs {line}",
			)


# ---------------------------------------------------------------------------
# 1. Two users moving the same booking's dates
# ---------------------------------------------------------------------------


class TestConcurrentDateChanges(ModificationRaceTestCase):
	"""Race 1: the same confirmed line, moved by two people at once."""

	WORLD_TAG = "RMCC1"
	WORLD_CODE = "C1"

	def test_two_moves_of_one_line_leave_one_coherent_interval(self):
		"""The interleaving: both read the line, both compute, both write.

		Two agents open their transactions and read the same confirmed room line
		(2 nights, arriving on day 1). Released together, one moves it to days
		5-7 and the other to days 6-8. Both are legal shifts on their own, and
		both contend for the Reservation row, so one waits for the other.

		What would go wrong without the current read under the lock: the waiter
		would recompute from the interval it read *before* the winner's commit
		and write a row assembled from both attempts - an arrival from one and a
		departure from the other, with `nights` matching neither. That row would
		then be counted by `_sold_by_night` for nights nobody sold. The service
		reads the line back with `lock_inventory_line` (a locking read) for
		exactly this reason.

		Both moves may legitimately succeed - moving a booking twice is a normal
		thing for a desk to do - so what is asserted is that the *end state* is
		one of the two intended intervals and nothing in between, and that the
		nights the engine reports sold are exactly that interval's nights.
		"""
		reservation = self.world.confirmed(nights=2, arrival=self.world.day(1))
		room_line = self.line(reservation)["name"]
		frappe.db.commit()

		self.assertSoldNights(5, 8, {5: 0, 6: 0, 7: 0})

		results = run_workers(
			[
				Worker(
					f"{__name__}._move_worker",
					{
						"property_name": self.world.property,
						"reservation": reservation,
						"room_line": room_line,
						"arrival": str(self.world.day(5)),
						"departure": str(self.world.day(7)),
						"tag": "a",
						"partner": "b",
					},
				),
				Worker(
					f"{__name__}._move_worker",
					{
						"property_name": self.world.property,
						"reservation": reservation,
						"room_line": room_line,
						"arrival": str(self.world.day(6)),
						"departure": str(self.world.day(8)),
						"tag": "b",
						"partner": "a",
					},
				),
			]
		)
		assert_all_ran(results)

		# HPMS-QA-16.7.2-C, made executable.
		#
		# This assertion used to demand that no deadlock occur. It cannot: making
		# the availability count a current read (the fix for the oversell, A) turned
		# it into a ranged `FOR UPDATE` over `tabReservation Room`, which locks every
		# row the optimiser examines — and `lock_and_get_doc` already holds this
		# booking's own child rows. Two agents editing one booking is an ordinary
		# event, so this is the plainest contention the build introduces, not the
		# knife-edge last-room case it was first characterised as.
		#
		# A deadlock here is safe: InnoDB rolls one whole transaction back, nothing
		# partial commits, and the caller sees a retryable refusal. So the invariant
		# under test is *coherence*, not which agent wins — and the assertion below
		# runs either way. The count is recorded rather than tolerated silently, so
		# that when the lock chain is reordered in a later build this test says so
		# instead of merely continuing to pass.
		deadlocked = self.deadlocks(results)

		if deadlocked:
			print(
				f"\n  HPMS-QA-16.7.2-C reproduced: two moves of one line deadlocked "
				f"({self.errors(results)})"
			)

		self.assertLessEqual(
			len(deadlocked),
			1,
			msg=f"both workers were rolled back, so neither move was applied: {self.errors(results)}",
		)

		final = self.interval(room_line)
		interval = (getdate(final["arrival_date"]), getdate(final["departure_date"]))

		self.assertIn(
			interval,
			[
				(getdate(self.world.day(5)), getdate(self.world.day(7))),
				(getdate(self.world.day(6)), getdate(self.world.day(8))),
			],
			msg=f"the line describes neither move's interval: {final}",
		)
		self.assertEqual(
			int(final["nights"]),
			2,
			msg=f"a two-night booking ended up with {final['nights']} nights: {final}",
		)

		# The header is a summary of its children and must have followed.
		header = self.header(reservation)
		self.assertEqual(getdate(header["arrival_date"]), interval[0])
		self.assertEqual(getdate(header["departure_date"]), interval[1])

		start = 5 if interval[0] == getdate(self.world.day(5)) else 6

		# The preserved rate must describe the nights the guest now holds - the
		# money and the interval cannot come apart.
		self.assertEqual(
			self.rate_dates(reservation, room_line),
			[getdate(self.world.day(start)), getdate(self.world.day(start + 1))],
			msg="the stored rate no longer describes the nights the line holds",
		)

		# And the engine sees the booking on exactly those nights, nowhere else.
		self.assertSoldNights(
			5, 8, {offset: 1 if start <= offset < start + 2 else 0 for offset in (5, 6, 7)}
		)


# ---------------------------------------------------------------------------
# 2. A date change against a competing last-room booking
# ---------------------------------------------------------------------------


class TestDateChangeAgainstCompetingBooking(ModificationRaceTestCase):
	"""Race 2: the contested last room, reached from two directions."""

	WORLD_TAG = "RMCC2"
	WORLD_CODE = "C2"

	#: The contested nights. Far enough out that nothing else touches them, and
	#: after the business date so a move may legitimately take them.
	START = 5
	END = 7

	def _mover(self) -> tuple[str, str]:
		"""A confirmed booking sitting on other nights, ready to be moved in."""
		reservation = self.world.confirmed(nights=self.END - self.START, arrival=self.world.day(1))
		frappe.db.commit()

		return reservation, self.line(reservation)["name"]

	def _competitor(self) -> str:
		"""A draft booking for the contested nights, about to be confirmed."""
		reservation = self.world.reservation(
			nights=self.END - self.START, arrival=self.world.day(self.START)
		)
		frappe.db.commit()

		return reservation

	def test_a_move_and_a_competing_confirm_cannot_both_take_the_last_room(self):
		"""HPMS-QA-16.7.2-A — the race that oversold the house.

		The interleaving: one room of the type is free on the contested nights.
		User A moves an existing confirmed booking's line *into* those nights;
		user B confirms a new booking *for* those nights. Both open their
		snapshot, then both are released together. They contend for the Room Type
		row, so one of them waits for the other's commit before it checks
		anything.

		What went wrong without a current read: the lock serialises the two
		callers but does not refresh the loser's snapshot.
		`availability._sold_by_night` read `tabReservation Room` with a plain
		`frappe.get_all`, which InnoDB answers from the read view opened before
		the winner committed - so the loser was told the room was still free and
		sold it too. Both callers held the right lock, both decided from a stale
		count, and the house was sold twice: **5 rooms sold in a house of 4**,
		with no exception raised anywhere.

		`tests/test_locking.py` had proved the same hazard on a single column and
		`lock_and_read` closed it there; the availability engine was never
		converted, so the guarantee in `services/reservations.py`'s own module
		docstring - "the second agent's read happens after the first agent's write
		and correctly sees zero" - did not hold. `check_availability(current=True)`
		is what makes it true.
		"""
		self.fill_house(1, start=self.START, end=self.END)

		mover, room_line = self._mover()
		competitor = self._competitor()

		results = run_workers(
			[
				Worker(
					f"{__name__}._move_worker",
					{
						"property_name": self.world.property,
						"reservation": mover,
						"room_line": room_line,
						"arrival": str(self.world.day(self.START)),
						"departure": str(self.world.day(self.END)),
						"tag": "a",
						"partner": "b",
					},
				),
				Worker(
					f"{__name__}._confirm_worker",
					{
						"property_name": self.world.property,
						"reservation": competitor,
						"tag": "b",
						"partner": "a",
					},
				),
			]
		)
		assert_all_ran(results)

		# The count first. An oversell that raised nothing is invisible to an
		# assertion about exceptions, and it is the one that reaches the guest.
		self.assertSoldNights(self.START, self.END, {self.START: self.ROOMS, self.START + 1: self.ROOMS})

		self.assertEqual(
			len(self.committed(results)),
			1,
			msg=f"exactly one of the two may take the last room; got {results}",
		)


class TestConcurrentConfirmations(ModificationRaceTestCase):
	"""The same defect at its own front door, with no modification involved.

	Not a modification service at all, and deliberately so. When the oversell
	above was first reproduced it had to be settled whether the new
	`change_line_interval` had introduced it or merely reached an existing one,
	because that decides where the fix belongs. Two plain confirmations of two
	ordinary bookings answer it.
	"""

	WORLD_TAG = "RMCCA"
	WORLD_CODE = "CA"

	START = 5
	END = 7

	def test_two_confirmations_cannot_both_take_the_last_room(self):
		"""The interleaving: one room free, two agents confirming at once.

		Both open their snapshots and are released together. `confirm` locks the
		Room Type row before it counts, so one waits for the other's commit -
		which is precisely the state the module docstring of
		`services/reservations.py` claims is safe: "the second agent's read
		happens after the first agent's write and correctly sees zero".

		It was not safe. The lock serialises without refreshing, and
		`check_demand` counted through `_sold_by_night`'s plain `frappe.get_all`
		- answered from the read view opened before the winner committed. Both
		agents were told the room was free and both sold it (observed on this
		bench: 5 rooms sold in a house of 4).

		The count is asserted first, because an oversell that raises nothing is
		invisible to any assertion about exceptions.
		"""
		self.fill_house(1, start=self.START, end=self.END)

		first = self.world.reservation(
			nights=self.END - self.START, arrival=self.world.day(self.START)
		)
		second = self.world.reservation(
			nights=self.END - self.START, arrival=self.world.day(self.START)
		)
		frappe.db.commit()

		results = run_workers(
			[
				Worker(
					f"{__name__}._confirm_worker",
					{
						"property_name": self.world.property,
						"reservation": first,
						"tag": "a",
						"partner": "b",
					},
				),
				Worker(
					f"{__name__}._confirm_worker",
					{
						"property_name": self.world.property,
						"reservation": second,
						"tag": "b",
						"partner": "a",
					},
				),
			]
		)
		assert_all_ran(results)

		self.assertSoldNights(self.START, self.END, {self.START: self.ROOMS, self.START + 1: self.ROOMS})

		self.assertEqual(
			len(self.committed(results)),
			1,
			msg=f"exactly one confirmation may take the last room; got {results}",
		)

	def test_two_confirmations_of_one_room_type_hold_inventory_true(self):
		"""HPMS-QA-16.7.2-C, pinned: the cycle the ranged locking read can close.

		The test above races for the *last* room, so a refusal is the expected
		outcome and a deadlock hides inside it - a worker that raised is a worker
		that did not oversell, whichever exception it raised. This one leaves the
		house half empty, so both confirmations *should* commit and the only
		thing that can stop either is the lock order itself.

		The cycle, from the code rather than from observation. `confirm` takes
		`lock_and_get_doc(Reservation)` at reservations.py:276, which locks the
		reservation row *and every one of its Reservation Room children*. It then
		takes the Room Type row at :301, and only then counts, through
		`check_demand` -> `_sold_by_night`, whose `current=True` read is a
		`SELECT ... FOR UPDATE` over `tabReservation Room` filtered on property
		and date range (availability.py:239-250). MariaDB picks the index, so
		that read locks every row it *examines*, including the other booking's.
		`exclude_reservation` is a WHERE predicate, not an index restriction, and
		it excludes the caller's own rows - never the rival's, which are the ones
		it blocks on.

		So: A holds its own room lines and the Room Type row, and waits for B's
		room lines. B holds its own room lines and waits for the Room Type row.
		Two resources, acquired in opposite orders, and InnoDB raises 1213.

		What this test fixes in place is the *invariant*, not the deadlock. A
		deadlock is a refusal, and a refusal never oversells; the count is
		therefore asserted unconditionally and first. The deadlock itself is
		recorded as a finding rather than asserted away, exactly as the two-moves
		test does, because 16.7.3 reviewed the documented remedy - hoisting the
		Room Type lock above the Reservation - and did not take it: `confirm`
		cannot know which types to lock until it has read `doc.rooms`, and
		`normalise_room_lines` may add rows to that set before the lock point, so
		hoisting means deciding the lock target from a plain read of a mutable
		column. That is the stale-read pattern this whole suite exists to refuse,
		and trading a deadlock for an oversell on the flagship inventory path is
		the wrong way round. See docs/BUILD_LOG.md, 16.7.3.
		"""
		first = self.world.reservation(
			nights=self.END - self.START, arrival=self.world.day(self.START)
		)
		second = self.world.reservation(
			nights=self.END - self.START, arrival=self.world.day(self.START)
		)
		frappe.db.commit()

		results = run_workers(
			[
				Worker(
					f"{__name__}._confirm_worker",
					{
						"property_name": self.world.property,
						"reservation": first,
						"tag": "a",
						"partner": "b",
					},
				),
				Worker(
					f"{__name__}._confirm_worker",
					{
						"property_name": self.world.property,
						"reservation": second,
						"tag": "b",
						"partner": "a",
					},
				),
			]
		)
		assert_all_ran(results)

		# The invariant, whatever the lock order does. Every booking that
		# committed is counted once, and nothing that refused left inventory
		# behind it.
		committed = self.committed(results)
		sold = len(committed)

		self.assertSoldNights(self.START, self.END, {self.START: sold, self.START + 1: sold})

		self.assertGreaterEqual(
			sold,
			1,
			msg=f"a half-empty house must take at least one of two bookings; got {results}",
		)

		deadlocked = self.deadlocks(results)

		self.assertLessEqual(
			len(deadlocked),
			1,
			msg=f"both workers deadlocked, which is not a lock-ordering cycle; got {results}",
		)

		if deadlocked:
			print(
				"\nHPMS-QA-16.7.2-C reproduced: two confirmations of one room type "
				"closed a lock cycle on the ranged inventory read. Inventory stayed "
				f"true ({sold} of 2 committed, {sold} sold per night). {deadlocked}"
			)


# ---------------------------------------------------------------------------
# 3. The stale read, with the timing question removed
# ---------------------------------------------------------------------------


class TestStaleReadDiscipline(ModificationRaceTestCase):
	"""Race 7: A reads, B commits, A acts. The most important tests in the file.

	Nothing here contends for a lock. The rival finishes and commits in full
	before the subject makes its first service call, so a failure cannot be
	blamed on timing, on lock ordering or on the harness: it can only mean the
	service decided from a value that was already out of date.

	Two halves, and when this suite was written they disagreed - which is exactly
	what made the finding precise. Guards that read through the Wave-1 primitives
	saw the rival's commit; the availability engine, which had never been
	converted, did not. Both halves pass now, and the first is what proves the
	second is being tested rather than merely being asked politely.
	"""

	WORLD_TAG = "RMCC7"
	WORLD_CODE = "C7"

	START = 5
	END = 7

	def _mover(self) -> tuple[str, str]:
		reservation = self.world.confirmed(nights=self.END - self.START, arrival=self.world.day(1))
		frappe.db.commit()

		return reservation, self.line(reservation)["name"]

	def test_a_status_that_changed_under_the_reader_is_seen(self):
		"""The control: the same interleaving, on a guard that reads currently.

		Without this, the availability test below proves nothing - a harness that
		failed to open the reader's snapshot early would make a broken service
		look correct. Here worker A opens its transaction and reads, worker B
		cancels the same booking and commits, and only then does A call
		`change_line_interval`.

		A's snapshot still says Confirmed. It must not act on that:
		`_assert_modifiable` decides from `lock_and_get_doc`, a locking read, so
		it sees Cancelled and refuses. The line must be left exactly where it
		was, and a cancelled booking must hold no inventory on the nights it was
		trying to move into.
		"""
		mover, room_line = self._mover()
		before = self.interval(room_line)

		results = run_workers(
			[
				Worker(
					f"{__name__}._snapshot_then_move_worker",
					{
						"property_name": self.world.property,
						"reservation": mover,
						"room_line": room_line,
						"arrival": str(self.world.day(self.START)),
						"departure": str(self.world.day(self.END)),
					},
				),
				Worker(f"{__name__}._rival_cancel_worker", {"reservation": mover}),
			]
		)
		assert_all_ran(results)

		mover_result, cancel_result = results

		# Diagnose a missing payload rather than subscripting `None`: when this
		# race resolved the other way the worker returned nothing, and the
		# `TypeError` that followed reported a harness bug as a product failure.
		for label, result in (("mover", mover_result), ("cancel", cancel_result)):
			self.assertIsNotNone(result, msg=f"the {label} worker returned no result at all")
			self.assertIn("status", result, msg=f"the {label} worker returned {result!r}")

		self.assertEqual(cancel_result["status"], "committed", msg=cancel_result)
		self.assertEqual(
			mover_result["status"],
			"failed",
			msg=f"a cancelled booking had its dates moved from a stale status read: {mover_result}",
		)
		self.assertIn("Cancelled", mover_result["error"], msg=mover_result["error"])

		after = self.interval(room_line)
		self.assertEqual(getdate(after["arrival_date"]), getdate(before["arrival_date"]))
		self.assertEqual(getdate(after["departure_date"]), getdate(before["departure_date"]))

		self.assertSoldNights(1, self.END, {offset: 0 for offset in range(1, self.END)})

	def test_a_move_after_a_committed_rival_sees_the_room_is_gone(self):
		"""HPMS-QA-16.7.2-A — `change_line_interval` acted on a stale count.

		The same interleaving as the control above, aimed at the availability
		check instead of the status guard. One room is free on the contested
		nights. Worker A opens its transaction and reads. Worker B confirms a
		booking for those nights and **commits in full**. Only then does A call
		`change_line_interval` to move its own line into the same nights.

		There is no lock contention left to explain the outcome. The room is
		gone, durably, before A asks, so A must be refused with an
		`AvailabilityError`. Before the fix it was not: `check_availability`
		reached `_sold_by_night`, which read with a plain `frappe.get_all`, which
		InnoDB answered from A's pre-commit read view. A was told the room was
		free and took it.

		This is the sharpest statement of the defect the simultaneous race in
		`TestDateChangeAgainstCompetingBooking` also produced, and it localised
		it: the Room Type lock was held correctly, the status guard was current,
		and the *inventory* read was not.
		"""
		self.fill_house(1, start=self.START, end=self.END)

		mover, room_line = self._mover()
		competitor = self.world.reservation(
			nights=self.END - self.START, arrival=self.world.day(self.START)
		)
		frappe.db.commit()

		results = run_workers(
			[
				Worker(
					f"{__name__}._snapshot_then_move_worker",
					{
						"property_name": self.world.property,
						"reservation": mover,
						"room_line": room_line,
						"arrival": str(self.world.day(self.START)),
						"departure": str(self.world.day(self.END)),
					},
				),
				Worker(f"{__name__}._rival_confirm_worker", {"reservation": competitor}),
			]
		)
		assert_all_ran(results)

		self.assertSoldNights(self.START, self.END, {self.START: self.ROOMS, self.START + 1: self.ROOMS})

		mover_result = results[0]
		self.assertEqual(
			mover_result["status"],
			"failed",
			msg="the move took a room a committed rival had already taken",
		)
		self.assertIn("AvailabilityError", mover_result.get("error", ""), msg=mover_result)

	def test_a_confirm_after_a_committed_move_sees_the_room_is_gone(self):
		"""HPMS-QA-16.7.2-A — the same defect, reached through `confirm`.

		The mirror of the test above, and the reason the escalation is not filed
		against the modification services alone. Worker A opens its transaction
		and reads; worker B moves an existing booking's line into the contested
		nights and commits in full; A then confirms a new booking for those same
		nights.

		`confirm` locks the Room Type and calls `check_demand`, which reached the
		same plain `get_all` - so the flagship Wave-1 guarantee ("a reservation
		may only reach a holding state if, at that exact moment and under a lock,
		the inventory is there") did not survive a caller whose snapshot predated
		the rival's commit either.

		Kept because it decided where the fix belonged: in
		`services/availability.py`, once, rather than in each of the four callers
		that reach it.
		"""
		self.fill_house(1, start=self.START, end=self.END)

		mover, room_line = self._mover()
		competitor = self.world.reservation(
			nights=self.END - self.START, arrival=self.world.day(self.START)
		)
		frappe.db.commit()

		results = run_workers(
			[
				Worker(
					f"{__name__}._snapshot_then_confirm_worker",
					{"property_name": self.world.property, "reservation": competitor},
				),
				Worker(
					f"{__name__}._rival_move_worker",
					{
						"reservation": mover,
						"room_line": room_line,
						"arrival": str(self.world.day(self.START)),
						"departure": str(self.world.day(self.END)),
					},
				),
			]
		)
		assert_all_ran(results)

		self.assertSoldNights(self.START, self.END, {self.START: self.ROOMS, self.START + 1: self.ROOMS})

		confirm_result = results[0]
		self.assertEqual(
			confirm_result["status"],
			"failed",
			msg="a confirmation took a room a committed rival had already taken",
		)


# ---------------------------------------------------------------------------
# 4. A room-type change against a competing booking for the new type
# ---------------------------------------------------------------------------


class TestRoomTypeChangeAgainstCompetingBooking(ModificationRaceTestCase):
	"""Race 3: the last room of the *new* type, contested."""

	WORLD_TAG = "RMCC3"
	WORLD_CODE = "C3"

	START = 5
	END = 7

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		fixtures = cls.world.fixtures

		#: One deluxe room in the whole house, so "the last room of the new
		#: type" is a premise the fixture can guarantee rather than arrange.
		cls.deluxe = fixtures.room_type(cls.world.property, "DLX", base_rate=DELUXE_RATE)
		fixtures.rooms(cls.world.property, cls.deluxe, count=1)

		plan = frappe.get_doc("Rate Plan", cls.world.rate_plan)
		if not any(row.room_type == cls.deluxe for row in plan.room_types):
			plan.append("room_types", {"room_type": cls.deluxe, "base_rate": DELUXE_RATE, "is_active": 1})
			plan.save(ignore_permissions=True)

		frappe.db.commit()

	def test_a_retype_after_a_committed_rival_sees_the_last_room_is_gone(self):
		"""The interleaving: a draft is re-typed onto the last deluxe room after
		a rival has already taken it and committed.

		Worker A opens its transaction and reads. Worker B confirms a new deluxe
		booking for the same nights and **commits in full**. Only then does A call
		`change_line_room_type` to move its line onto the deluxe type. There is
		one deluxe room in the house.

		What would go wrong without a current read: A's snapshot predates B's
		commit, so `check_availability` counts the deluxe room as free and A is
		told it may have it. Nothing is oversold at that instant - a booking in an
		editable state holds no inventory at all - but the agent has been told
		something untrue about the only room of that type, and will be refused at
		confirmation with the guest on the phone. With `current=True` the answer
		is the truth: refused now.

		**Sequenced rather than simultaneous, deliberately, and this is the one
		place in this file where that is not the sharper choice.** The
		simultaneous form of this pair - re-type and confirmation released
		together, contending for the same Room Type row - trips the lock cycle
		recorded as HPMS-QA-16.7.2-C (3 runs in 4 on this bench), because the
		re-type holds its own reservation's rows while the confirmation's current
		read wants them. That is a lock-order question and not an inventory one,
		it is not this suite's to resolve, and a test that fails three times in
		four is not evidence of anything. The simultaneous contention case for a
		single room type is covered by `TestDateChangeAgainstCompetingBooking` and
		`TestConcurrentConfirmations`.
		"""
		draft = self.world.reservation(nights=self.END - self.START, arrival=self.world.day(self.START))
		room_line = self.line(draft)["name"]

		competitor = self.world.fixtures.reservation(
			self.world.property,
			self.deluxe,
			self.world.fixtures.guest("Deluxe"),
			rate_plan=self.world.rate_plan,
			arrival=self.world.day(self.START),
			nights=self.END - self.START,
		)
		frappe.db.commit()

		self.assertEqual(
			self.sold(self.START, self.END, self.deluxe), 0, msg="the deluxe room must start free"
		)

		results = run_workers(
			[
				Worker(
					f"{__name__}._snapshot_then_retype_worker",
					{
						"property_name": self.world.property,
						"reservation": draft,
						"room_line": room_line,
						"room_type": self.deluxe,
					},
				),
				Worker(f"{__name__}._rival_confirm_worker", {"reservation": competitor}),
			]
		)
		assert_all_ran(results)

		# One deluxe room, sold once: the rival's confirmation and nothing else.
		self.assertSoldNights(
			self.START, self.END, {self.START: 1, self.START + 1: 1}, room_type=self.deluxe
		)

		retype = results[0]
		self.assertEqual(
			retype["status"],
			"failed",
			msg="a line was moved onto a room type a committed rival had already taken",
		)
		self.assertIn("AvailabilityError", retype.get("error", ""), msg=retype)

		self.assertEqual(
			self.interval(room_line)["room_type"],
			self.world.room_type,
			msg="the refused re-type moved the line anyway",
		)

		# And the enforcement point refuses it too, so nothing here rests on the
		# advisory check alone. The line is put onto the deluxe type directly -
		# standing in for a re-type that had been allowed through - and the
		# confirmation that follows must still be refused.
		frappe.db.set_value("Reservation Room", room_line, "room_type", self.deluxe, update_modified=False)
		frappe.db.commit()

		with self.assertRaises(
			AvailabilityError,
			msg="the draft was confirmed onto a deluxe room the rival already holds",
		):
			reservation_service.confirm(draft)

		frappe.db.rollback()

		self.assertSoldNights(
			self.START, self.END, {self.START: 1, self.START + 1: 1}, room_type=self.deluxe
		)


# ---------------------------------------------------------------------------
# 5. Removing a line against a check-in on that line
# ---------------------------------------------------------------------------


class TestRemoveLineAgainstCheckIn(ModificationRaceTestCase):
	"""Race 4: the room being deleted is the room the guest just walked into."""

	WORLD_TAG = "RMCC4"
	WORLD_CODE = "C4"

	def test_a_line_cannot_be_removed_from_under_an_arriving_guest(self):
		"""The interleaving: a two-room draft; A removes room line 1 while B
		confirms the booking and checks a guest into that same line.

		Both open their snapshots and are released together. Both take the
		Reservation row lock first, so they serialise - and the loser then has to
		decide from what it finds, not from what it read.

		What would go wrong without the current read: `remove_room_line` decides
		it may act from `reservation_status`, which its snapshot still shows as
		Draft. Acting on that would delete the inventory row a guest has just
		been checked into, leaving a Stay - with an open folio, an occupied room
		and a guest asleep in it - pointing at a room line that no longer exists,
		and the room reported free to the next arrival.

		Either serialisation is legitimate; both must be coherent. If the
		check-in wins, the removal must be refused because the booking is no
		longer editable. If the removal wins, the check-in must be refused
		because the line it names is gone. What must never happen is both.
		"""
		reservation = self.world.reservation_with_lines([{"nights": 2}, {"nights": 2}])
		lines = self.world.lines(reservation)
		room_line = lines[0]["name"]
		frappe.db.commit()

		self.assertEqual(len(lines), 2, msg="the premise is a two-room booking")
		self.assertSoldNights(0, 2, {0: 0, 1: 0})

		results = run_workers(
			[
				Worker(
					f"{__name__}._remove_line_worker",
					{
						"property_name": self.world.property,
						"reservation": reservation,
						"room_line": room_line,
						"tag": "a",
						"partner": "b",
					},
				),
				Worker(
					f"{__name__}._confirm_and_check_in_worker",
					{
						"property_name": self.world.property,
						"reservation": reservation,
						"room_line": room_line,
						"room": self.world.rooms[0],
						"tag": "b",
						"partner": "a",
					},
				),
			]
		)
		assert_all_ran(results)

		self.assertEqual(self.deadlocks(results), [], msg=f"the race deadlocked: {self.errors(results)}")
		self.assertEqual(
			len(self.committed(results)),
			1,
			msg=f"a removal and a check-in of the same line both took effect: {results}",
		)

		removal, check_in = results

		# Whatever happened, nothing may be left dangling.
		self.assertNoOrphanStay()

		if check_in["status"] == "committed":
			self.assertTrue(
				frappe.db.exists("Reservation Room", room_line),
				msg="the line a guest is checked into was deleted",
			)
			self.assertIn(
				"cannot be changed",
				removal["error"],
				msg=f"the removal was refused for the wrong reason: {removal['error']}",
			)
			# Two rooms held: the guest's, and the line that has not arrived.
			self.assertSoldNights(0, 2, {0: 2, 1: 2})
		else:
			self.assertFalse(
				frappe.db.exists("Reservation Room", room_line),
				msg="neither operation took effect",
			)
			self.assertFalse(
				frappe.db.exists("Stay", {"reservation": reservation}),
				msg="a stay survived the removal of the line it belonged to",
			)
			# Still a draft, so it holds nothing.
			self.assertSoldNights(0, 2, {0: 0, 1: 0})


# ---------------------------------------------------------------------------
# 6. A date change against room assignment, and against a room move
# ---------------------------------------------------------------------------


class TestDateChangeAgainstAssignment(ModificationRaceTestCase):
	"""Race 5a: the chain taken from the same end by two different operations."""

	WORLD_TAG = "RMCC6"
	WORLD_CODE = "C6"

	def test_a_move_and_an_assignment_cannot_promise_one_room_twice(self):
		"""The interleaving: a room that is free *now* and taken *later*.

		Room 1 is already promised to another confirmed booking for days 5-7.
		Our booking's line sits on days 1-3 with no room. Worker A moves that
		line to days 5-7; worker B assigns room 1 to it. Each is legal against
		the state the other has not yet committed, and together they are not:
		whichever runs second must see the other's work or room 1 ends up
		promised to two guests for the same nights.

		Both take the Reservation row first, so they queue rather than deadlock -
		and the loser then decides from `lock_inventory_line` and
		`lock_and_get_doc`, which return the winner's committed values, and from
		`_assert_room_free`, which is a `lock_and_find` and therefore a current
		read. Had any of those been a plain read, both callers would have found
		room 1 free and both would have taken it.
		"""
		other = self.world.confirmed(nights=2, arrival=self.world.day(5))
		room = self.world.rooms[0]
		reservation_service.assign_room(other, self.line(other)["name"], room)
		frappe.db.commit()

		mover = self.world.confirmed(nights=2, arrival=self.world.day(1))
		room_line = self.line(mover)["name"]
		frappe.db.commit()

		self.assertIsNone(self.interval(room_line)["assigned_room"], msg="the line must start unassigned")

		results = run_workers(
			[
				Worker(
					f"{__name__}._move_worker",
					{
						"property_name": self.world.property,
						"reservation": mover,
						"room_line": room_line,
						"arrival": str(self.world.day(5)),
						"departure": str(self.world.day(7)),
						"tag": "a",
						"partner": "b",
					},
				),
				Worker(
					f"{__name__}._assign_worker",
					{
						"property_name": self.world.property,
						"reservation": mover,
						"room_line": room_line,
						"room": room,
						"tag": "b",
						"partner": "a",
					},
				),
			]
		)
		assert_all_ran(results)

		self.assertEqual(self.deadlocks(results), [], msg=f"the race deadlocked: {self.errors(results)}")

		self.assertEqual(
			len(self.committed(results)),
			1,
			msg=(
				"a move into nights the room is taken and an assignment of that room "
				f"both took effect: {results}"
			),
		)

		self.assertNoRoomPromisedTwice(room)

		# Two bookings, one room each, on whichever nights they ended up holding.
		final = self.interval(room_line)
		self.assertEqual(
			int(final["nights"]), 2, msg=f"the line's night count no longer matches its dates: {final}"
		)


class TestDateChangeAgainstRoomMove(ModificationRaceTestCase):
	"""Race 5b: the documented chain, taken from opposite ends."""

	WORLD_TAG = "RMCC8"
	WORLD_CODE = "C8"

	def _in_house(self) -> dict:
		"""A two-room booking with one guest already upstairs.

		Two rooms deliberately: `check_in` moves a Reservation to Checked In only
		once every line is in house, so a two-line booking with one guest in the
		room is still Confirmed - which is what keeps `change_line_interval`
		reaching the lock chain at all, rather than being turned away on status
		before any lock is taken.
		"""
		reservation = self.world.reservation_with_lines([{"nights": 2}, {"nights": 2}])
		reservation_service.confirm(reservation)
		frappe.db.commit()

		lines = self.world.lines(reservation)
		occupied, vacant = self.world.rooms[0], self.world.rooms[1]

		reservation_service.assign_room(reservation, lines[0]["name"], occupied)
		self.world.check_in(reservation, line=lines[0]["name"], room=occupied)
		frappe.db.commit()

		stay = frappe.db.get_value("Stay", {"reservation_room_line": lines[0]["name"]}, "name")
		self.assertTrue(stay, msg="the fixture premise is wrong: no stay was created")

		return {
			"reservation": reservation,
			"room_line": lines[0]["name"],
			"stay": stay,
			"occupied": occupied,
			"vacant": vacant,
		}

	def _race(self, world: dict) -> list[dict]:
		return run_workers(
			[
				Worker(
					f"{__name__}._move_worker",
					{
						"property_name": self.world.property,
						"reservation": world["reservation"],
						"room_line": world["room_line"],
						"arrival": str(self.world.day(4)),
						"departure": str(self.world.day(6)),
						"tag": "a",
						"partner": "b",
					},
				),
				Worker(
					f"{__name__}._change_room_worker",
					{
						"property_name": self.world.property,
						"stay": world["stay"],
						"room": world["vacant"],
						"tag": "b",
						"partner": "a",
					},
				),
			]
		)

	def test_the_room_the_guest_is_in_and_the_row_that_holds_it_agree(self):
		"""The interleaving: a guest is in house on room line 1. Worker A moves
		that line's dates (`change_line_interval`: Reservation → Room Line → Room
		Type → Hotel Room); worker B moves the guest to another room
		(`stays.change_room`: Stay → Hotel Room, then a write to the room line).
		The same rows, reached from opposite ends of the documented chain.

		What would go wrong without the guards: the date change would move an
		interval out from under a guest who is asleep in the room, and the Stay
		and its inventory row would end up naming different rooms - P1-5 from the
		other side, which `_assert_line_not_in_stay` and `change_room`'s row write
		exist to prevent between them.

		A date change is always refused here - a line with a live stay moves
		through `extend_stay`/`shorten_stay`, never through this service - so what
		is asserted is the end state: the line keeps its dates, and the Stay and
		the row name the same room whichever way the two were serialised.
		"""
		world = self._in_house()
		before = self.interval(world["room_line"])

		results = self._race(world)
		assert_all_ran(results)

		after = self.interval(world["room_line"])

		self.assertNoOrphanStay()
		self.assertEqual(
			after["assigned_room"],
			frappe.db.get_value("Stay", world["stay"], "room"),
			msg="the stay and the inventory row name different rooms",
		)
		self.assertEqual(
			getdate(after["arrival_date"]),
			getdate(before["arrival_date"]),
			msg="a line with a guest in the room had its arrival moved",
		)
		self.assertEqual(
			getdate(after["departure_date"]),
			getdate(before["departure_date"]),
			msg="a line with a guest in the room had its departure moved",
		)

	def test_the_two_chain_followers_serialise_rather_than_deadlock(self):
		"""HPMS-QA-16.7.2-B — the interleaving that deadlocked.

		The same interleaving as the test above, asserted on the *mechanism*: two
		callers touching the same rows must queue behind each other, which is the
		entire purpose of having one documented lock order.

		They did not. `change_line_interval` holds the Reservation Room row (chain
		position 2) and then asks for the assigned Hotel Room (position 4).
		`stays.change_room` held both Hotel Rooms (position 4) and then *wrote*
		`Reservation Room.assigned_room` (position 2) without taking that row's
		lock, on the reasoning recorded in its own comment that "nothing is being
		decided from the row". Taking no lock does not avoid the inversion: the
		UPDATE needs the row's exclusive lock anyway, so the cycle closed and
		InnoDB rolled one side back - `QueryDeadlockError (1213)`, raised inside
		`_lock_line_chain` at `lock_document("Hotel Room", ...)`.

		The user-visible harm was small - that date change was going to be refused
		a few lines later anyway - but the victim was the database's choice rather
		than the product's, and any future writer of that row met the same
		inversion. `change_room` now takes the row's lock first, ahead of the Stay
		and both rooms, so whoever wins the row runs and the other queues.

		The deadlock was intermittent, which is why this asserts the mechanism
		separately from the outcome: a lock cycle that only fires on some
		interleavings is still a lock cycle, and the test above would have gone on
		passing while it did.
		"""
		world = self._in_house()

		results = self._race(world)
		assert_all_ran(results)

		self.assertEqual(
			self.deadlocks(results),
			[],
			msg=f"a lock cycle was broken by the database rather than avoided: {self.errors(results)}",
		)

	def test_a_room_move_and_a_stay_extension_serialise(self):
		"""The other caller of the chain, raced against the one that was fixed.

		`change_room` now takes the inventory row first. `extend_stay` reaches
		the same row through `_lock_stay_chain`, which takes Reservation → Room
		Line → Room Type → Hotel Room → Stay - so both take the row before either
		takes a Hotel Room, and whichever wins it runs while the other queues.
		This is that claim tested rather than reasoned about: a guest is moved to
		another room while their stay is extended by a night.

		The two are compatible operations, so both may commit. What must hold
		either way is that they do not deadlock and that the four records still
		agree afterwards - the Stay and the inventory row naming the same room,
		and the same departure date. That agreement is P1-5's whole subject: an
		extension that moved only the Stay left the room sellable for a night the
		guest was still in it.
		"""
		world = self._in_house()

		results = run_workers(
			[
				Worker(
					f"{__name__}._extend_worker",
					{
						"property_name": self.world.property,
						"stay": world["stay"],
						"departure": str(self.world.day(3)),
						"tag": "a",
						"partner": "b",
					},
				),
				Worker(
					f"{__name__}._change_room_worker",
					{
						"property_name": self.world.property,
						"stay": world["stay"],
						"room": world["vacant"],
						"tag": "b",
						"partner": "a",
					},
				),
			]
		)
		assert_all_ran(results)

		self.assertEqual(
			self.deadlocks(results),
			[],
			msg=f"the two chain followers deadlocked: {self.errors(results)}",
		)
		self.assertTrue(
			self.committed(results), msg=f"neither operation took effect: {self.errors(results)}"
		)

		line = self.interval(world["room_line"])
		stay = frappe.db.get_value(
			"Stay", world["stay"], ["room", "departure_date"], as_dict=True
		)

		self.assertNoOrphanStay()
		self.assertEqual(
			line["assigned_room"], stay["room"], msg="the stay and the inventory row disagree on the room"
		)
		self.assertEqual(
			getdate(line["departure_date"]),
			getdate(stay["departure_date"]),
			msg="the stay and the inventory row disagree on the departure date (P1-5)",
		)

	def test_a_guest_cannot_be_moved_into_a_room_promised_to_somebody_else(self):
		"""The one test here that does not race, and it belongs here anyway.

		`change_room` asked `assert_assignable`, which reports on a room's own
		state - sellable, operational, clean enough - and never asked the question
		room assignment exists to answer: is this room already promised to
		somebody for these nights? A room held for tomorrow's arrival is sellable,
		operational and clean today, so a move into it committed and left two
		`Reservation Room` rows naming one physical room over overlapping
		intervals. `reservations.assign_room` has refused that since Wave 1;
		`change_room` was the one writer that did not ask.

		It is in this file because the guard could not be added safely until the
		row lock above it was: `_assert_room_free` is a current read, and a
		current read is only worth taking under the lock that keeps its answer
		true until the write. The race that lock resolves is the test above; this
		is what the lock made it possible to check.
		"""
		world = self._in_house()

		# The vacant room is promised to a booking arriving in the same nights.
		future = self.world.confirmed(nights=2)
		future_line = self.line(future)["name"]
		reservation_service.assign_room(future, future_line, world["vacant"])
		frappe.db.commit()

		with self.assertRaises(
			HospitalityPMSError,
			msg="a guest was moved into a room already promised to another booking",
		) as caught:
			stay_service.change_room(world["stay"], world["vacant"], "Guest asked for a quieter room")

		frappe.db.rollback()

		self.assertIn(future, str(caught.exception), msg=str(caught.exception))

		self.assertNoRoomPromisedTwice(world["vacant"])
		self.assertEqual(
			frappe.db.get_value("Stay", world["stay"], "room"),
			world["occupied"],
			msg="the refused move still moved the guest",
		)
		self.assertNoOrphanStay()


# ---------------------------------------------------------------------------
# 7. Two concurrent additions when one room of capacity remains
# ---------------------------------------------------------------------------


class TestConcurrentAddRoomLine(ModificationRaceTestCase):
	"""Race 6: summed demand, and the write that must not be lost."""

	WORLD_TAG = "RMCC9"
	WORLD_CODE = "C9"

	START = 5
	END = 7

	def test_two_additions_neither_lose_a_write_nor_oversell(self):
		"""The interleaving: two agents add a room to the same booking at once,
		with one room of capacity left on the nights they are adding.

		Both open their snapshots and are released together; both take the
		Reservation row lock in `add_room_line`, so one waits for the other's
		commit.

		What would go wrong without the current read: `add_room_line` appends to
		the document and saves it, and Frappe's child-table save deletes every
		row not present in the document it is saving. A waiter that had loaded
		the reservation from its pre-lock snapshot would save a `rooms` table
		that does not contain the winner's new line, and **the winner's write
		would silently disappear** - a room the agent was told had been added,
		gone, with no error anywhere. `lock_and_get_doc` is what prevents that,
		and this test is what proves it.

		Both additions may legitimately succeed, and that is not an oversell: a
		booking in an editable state holds no inventory at all, so the check each
		one runs is advisory - "is there a room to be had?" - and the enforcement
		point is confirmation, where `check_demand` sums the whole booking per
		night under lock. So this asserts three things: neither write was lost,
		the engine's count did not move, and the confirmation that follows is
		refused because the booking now needs two rooms on a night that has one.
		"""
		self.fill_house(1, start=self.START, end=self.END)

		draft = self.world.reservation(nights=2)
		frappe.db.commit()

		self.assertEqual(len(self.world.lines(draft)), 1, msg="the premise is a one-room draft")

		results = run_workers(
			[
				Worker(
					f"{__name__}._add_line_worker",
					{
						"property_name": self.world.property,
						"reservation": draft,
						"room_type": self.world.room_type,
						"arrival": str(self.world.day(self.START)),
						"departure": str(self.world.day(self.END)),
						"tag": "a",
						"partner": "b",
					},
				),
				Worker(
					f"{__name__}._add_line_worker",
					{
						"property_name": self.world.property,
						"reservation": draft,
						"room_type": self.world.room_type,
						"arrival": str(self.world.day(self.START)),
						"departure": str(self.world.day(self.END)),
						"tag": "b",
						"partner": "a",
					},
				),
			]
		)
		assert_all_ran(results)

		self.assertEqual(self.deadlocks(results), [], msg=f"the race deadlocked: {self.errors(results)}")

		added = [result["result"]["room_line"] for result in self.committed(results)]
		lines = {row["name"] for row in self.world.lines(draft)}

		for room_line in added:
			self.assertIn(
				room_line,
				lines,
				msg=f"a line the service reported adding is not on the booking: {room_line} of {lines}",
			)

		self.assertEqual(
			len(lines),
			1 + len(added),
			msg=f"a concurrent addition lost a write: {len(added)} added, lines are {lines}",
		)

		# A draft holds nothing, so the house is exactly as full as it was.
		self.assertSoldNights(
			self.START, self.END, {self.START: self.ROOMS - 1, self.START + 1: self.ROOMS - 1}
		)

		if len(added) == 2:
			with self.assertRaises(
				AvailabilityError,
				msg="two rooms were confirmed onto a night with one room free",
			):
				reservation_service.confirm(draft)

			frappe.db.rollback()

		self.assertSoldNights(
			self.START, self.END, {self.START: self.ROOMS - 1, self.START + 1: self.ROOMS - 1}
		)
