"""Hotel Room: whose property, whose log, and whose room is actually free.

Three defects, all reachable through `api/rooms.py`, all found by independent
security testing of 16.7.5 (R1B).

**Cross-property (HIGH).** `get_room` and `set_room_status` took a room name from
the client and checked `require_permission` plus `doc.check_permission`. That is
the two-step form the app itself declared insufficient in 16.7.5: a User
Permission created without `apply_to_all_doctypes` restricts only the DocTypes it
names, so the document check can legitimately pass for a room in a property the
caller may not operate in. `authorise_document` adds the third check, resolved
from the record rather than from the request. `set_room_status` is the sharper of
the two because it writes, and `require_dimension_role` beside it is a global role
test with no property dimension at all.

**Room Status Log (MEDIUM).** `get_room` returned the log's `changed_by`,
`reason` and `reference_*` on Hotel Room read alone, through `get_status_history`,
which reads with `frappe.get_all` and so applies no permission whatsoever. Hotel
Room is read by twenty-three roles and Room Status Log by nine - it is described
in `setup/permissions.py` as a technical record "hidden from ordinary operational
users". The fourteen in between were being told who took a room out of order and
why, in free text a manager wrote.

**Room Rack presentation (from R1A).** R1A made active Stay occupancy
authoritative for every path that *places* a guest and deliberately left the rack
computing its badge from `occupancy_status` alone. So a room whose flag had gone
stale - room 402, and the five Due Out rooms the estate audit found - was still
advertised as assignable. No guest could be put in it, because the mutations
refuse; the desk was simply being offered a room it could not have.

Real users holding real roles throughout, restricted to a property by a real User
Permission, called through the whitelisted endpoints. Administrator proves
nothing here: it holds no User Permission, so it is unrestricted by design.
"""

import json

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days

from hospitality_pms.api import rooms as rooms_api
from hospitality_pms.services import rooms as room_service
from hospitality_pms.services import stays as stay_service
from hospitality_pms.services.exceptions import PermissionDeniedError, PropertyAccessError
from hospitality_pms.tests.fixtures import Fixtures

#: Either exception is a correct refusal, and which one depends on whether the
#: document check or the property check refuses first. The suite cares that the
#: call was refused, not which guard got there.
REFUSALS = (frappe.PermissionError, PermissionDeniedError, PropertyAccessError)

#: Log fields that describe *who* and *why*, as opposed to what changed. These are
#: the ones a caller without Room Status Log read may never receive.
LOG_ACTOR_FIELDS = ("changed_by", "reason", "reference_doctype", "reference_name")

#: Planted in a status-change reason so a leak shows up as this sentence in a
#: failure message rather than as a missing assertion.
OOO_REASON = "CONFIDENTIAL: flooded by the burst riser, insurer notified, claim QA-2026-77"


class RoomAuthorizationWorld(IntegrationTestCase):
	"""Two properties, and one operator permitted in only one of them."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()

		cls.fixtures = Fixtures("RMAUTH")

		cls.property_a = cls.fixtures.property("RA", require_id_at_check_in=0)
		cls.type_a = cls.fixtures.room_type(cls.property_a)
		cls.rooms_a = cls.fixtures.rooms(cls.property_a, cls.type_a, count=3)
		cls.plan_a = cls.fixtures.rate_plan(cls.property_a, cls.type_a)

		cls.property_b = cls.fixtures.property("RB", require_id_at_check_in=0)
		cls.type_b = cls.fixtures.room_type(cls.property_b)
		cls.rooms_b = cls.fixtures.rooms(cls.property_b, cls.type_b, count=2)

		# Restricted to property A by a real User Permission - the mechanism the
		# product actually relies on (HPMS-DEC-052). Housekeeping Manager because
		# it holds Hotel Room read *and* the housekeeping dimension role, so it can
		# legitimately drive `set_room_status` in its own property.
		cls.operator_a = cls.fixtures.user(
			"hkm-a", ["Housekeeping Manager"], properties=[cls.property_a]
		)

		# Holds Hotel Room read and is NOT a Room Status Log reader - one of the
		# fourteen. Also holds no Guest Folio and no Guest read.
		cls.attendant = cls.fixtures.user(
			"att-a", ["Room Attendant"], properties=[cls.property_a]
		)

		# A Room Status Log reader, for the other side of every log assertion.
		cls.log_reader = cls.fixtures.user(
			"hks-a", ["Housekeeping Supervisor"], properties=[cls.property_a]
		)

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


class TestRoomPropertyAuthorization(RoomAuthorizationWorld):
	"""The premise, then both directions, for both endpoints."""

	def test_the_matrix_premise_holds(self):
		"""Without this, every refusal below could be a permission gap instead.

		The operator must genuinely hold Hotel Room read, and genuinely be
		restricted to property A. If either were false the cross-property tests
		would pass for the wrong reason.
		"""
		frappe.set_user(self.operator_a)

		self.assertTrue(frappe.has_permission("Hotel Room", "read"))

		from hospitality_pms.services.property import get_permitted_properties

		permitted = get_permitted_properties()

		self.assertIn(self.property_a, permitted)
		self.assertNotIn(self.property_b, permitted, msg="the operator is not actually restricted")

	def test_get_room_same_property_allowed(self):
		frappe.set_user(self.operator_a)

		payload = rooms_api.get_room(room=self.rooms_a[0])

		self.assertEqual(payload["room"]["name"], self.rooms_a[0])

	def test_get_room_cross_property_refused(self):
		frappe.set_user(self.operator_a)

		with self.assertRaises(REFUSALS):
			rooms_api.get_room(room=self.rooms_b[0])

	def test_set_room_status_same_property_allowed(self):
		frappe.set_user(self.operator_a)

		rooms_api.set_room_status(
			room=self.rooms_a[0], dimension="Housekeeping", status="Dirty", reason="turned"
		)

		self.assertEqual(
			frappe.db.get_value("Hotel Room", self.rooms_a[0], "housekeeping_status"), "Dirty"
		)

	def test_set_room_status_cross_property_refused(self):
		frappe.set_user(self.operator_a)

		with self.assertRaises(REFUSALS):
			rooms_api.set_room_status(
				room=self.rooms_b[0], dimension="Housekeeping", status="Dirty", reason="turned"
			)

	def test_a_refused_mutation_changes_nothing_and_logs_nothing(self):
		"""The refusal must land before the write and before the audit row.

		`set_status` inserts a Room Status Log with `ignore_permissions=True`, so a
		guard that refused too late would leave the foreign property holding an
		audit entry naming an operator with no business in it.
		"""
		before = frappe.db.get_value("Hotel Room", self.rooms_b[0], "housekeeping_status")
		log_count = frappe.db.count("Room Status Log", {"room": self.rooms_b[0]})

		frappe.set_user(self.operator_a)

		with self.assertRaises(REFUSALS):
			rooms_api.set_room_status(
				room=self.rooms_b[0], dimension="Housekeeping", status="Dirty", reason="turned"
			)

		frappe.set_user("Administrator")

		self.assertEqual(
			frappe.db.get_value("Hotel Room", self.rooms_b[0], "housekeeping_status"), before
		)
		self.assertEqual(
			frappe.db.count("Room Status Log", {"room": self.rooms_b[0]}),
			log_count,
			msg="a refused cross-property mutation still wrote an audit row",
		)

	def test_cross_property_room_id_cannot_bypass_via_document_permission(self):
		"""The narrowed User Permission case, which is the actual hole.

		A Property User Permission created *without* `apply_to_all_doctypes`
		restricts only the DocTypes it names. Frappe's own document check then has
		nothing to say about Hotel Room, so `doc.check_permission("read")` passes
		for a foreign room - and the endpoint's old two-step guard had no third
		question to ask. This is the configuration in which the two tests above
		would both have passed while the defect was live, so it is pinned
		separately.
		"""
		narrowed = self.fixtures.user("narrow", ["Housekeeping Manager"])

		# Deliberately not through `Fixtures.user`, which sets
		# `apply_to_all_doctypes=1`. This is the weaker form.
		permission = frappe.get_doc(
			{
				"doctype": "User Permission",
				"user": narrowed,
				"allow": "Property",
				"for_value": self.property_a,
				"apply_to_all_doctypes": 0,
				"applicable_for": "Housekeeping Task",
			}
		).insert(ignore_permissions=True)
		self.fixtures.track("User Permission", permission.name)
		frappe.db.commit()

		frappe.set_user(narrowed)

		# The premise: Frappe's document check really does pass here, so the
		# refusal below can only come from the property check.
		doc = frappe.get_doc("Hotel Room", self.rooms_b[0])
		doc.check_permission("read")

		with self.assertRaises(REFUSALS):
			rooms_api.get_room(room=self.rooms_b[0])

		with self.assertRaises(REFUSALS):
			rooms_api.set_room_status(
				room=self.rooms_b[0], dimension="Housekeeping", status="Dirty", reason="x"
			)

	def test_the_rack_is_property_scoped_for_this_operator(self):
		"""The rack was already safe; pinned so it stays that way."""
		frappe.set_user(self.operator_a)

		rack = rooms_api.get_room_rack(property=self.property_a)
		offered = {
			room["name"] for bucket in rack["room_types"] for room in bucket["rooms"]
		}

		self.assertTrue(offered)
		self.assertFalse(
			offered.intersection(self.rooms_b), msg="the rack leaked another property's rooms"
		)

		with self.assertRaises(REFUSALS):
			rooms_api.get_room_rack(property=self.property_b)


class TestRoomStatusLogDisclosure(RoomAuthorizationWorld):
	"""Room detail opens for everyone; its history does not."""

	def setUp(self):
		super().setUp()

		# A transition with a confidential reason, written through the service so
		# the log row is the product's own.
		room_service.set_status(
			self.rooms_a[0],
			room_service.MAINTENANCE,
			"Out of Order",
			reason=OOO_REASON,
			reference_doctype="Hotel Room",
			reference_name=self.rooms_a[0],
		)
		frappe.db.commit()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.set_value(
			"Hotel Room", self.rooms_a[0], "maintenance_status", "Operational", update_modified=False
		)
		frappe.db.delete("Room Status Log", {"room": self.rooms_a[0]})
		frappe.db.commit()
		super().tearDown()

	def test_the_matrix_premise_holds(self):
		frappe.set_user(self.attendant)
		self.assertTrue(frappe.has_permission("Hotel Room", "read"))
		self.assertFalse(
			frappe.has_permission("Room Status Log", "read"),
			msg="Room Attendant now reads the log, so this suite tests nothing",
		)

		frappe.set_user(self.log_reader)
		self.assertTrue(frappe.has_permission("Hotel Room", "read"))
		self.assertTrue(frappe.has_permission("Room Status Log", "read"))

	def test_room_reader_without_log_permission_opens_room(self):
		"""Redaction, not outage. The dialog must still work."""
		frappe.set_user(self.attendant)

		payload = rooms_api.get_room(room=self.rooms_a[0])

		self.assertEqual(payload["room"]["name"], self.rooms_a[0])
		self.assertIn("room_number", payload["room"])
		self.assertIn("maintenance_status", payload["room"])
		self.assertIn("assignable", payload)

	def test_room_reader_without_log_permission_gets_no_status_log(self):
		"""Absent, not empty. `[]` would claim the room has no history."""
		frappe.set_user(self.attendant)

		payload = rooms_api.get_room(room=self.rooms_a[0])

		self.assertNotIn(
			"history",
			payload,
			msg="the history block reached a caller who may not read Room Status Log",
		)

	def test_log_reason_and_actor_not_leaked_anywhere_in_the_payload(self):
		"""At any depth, and by text as well as by field name."""
		frappe.set_user(self.attendant)

		payload = rooms_api.get_room(room=self.rooms_a[0])
		serialised = json.dumps(payload, default=str)

		self.assertNotIn(OOO_REASON, serialised, msg="room detail carried the confidential reason")

		for field in LOG_ACTOR_FIELDS:
			self.assertNotIn(f'"{field}"', serialised, msg=f"room detail carried {field}")

	def test_log_reader_gets_status_history(self):
		"""The cleared role keeps what it works from."""
		frappe.set_user(self.log_reader)

		payload = rooms_api.get_room(room=self.rooms_a[0])

		self.assertIn("history", payload)
		self.assertTrue(payload["history"], msg="the cleared reader lost the history")

		entry = next(row for row in payload["history"] if row["reason"] == OOO_REASON)

		self.assertEqual(entry["dimension"], room_service.MAINTENANCE)
		self.assertEqual(entry["to_status"], "Out of Order")
		self.assertTrue(entry["changed_by"])

	def test_the_mutation_response_obeys_the_same_rule(self):
		"""`set_room_status` returns `get_room`, so it is a second way in."""
		frappe.set_user(self.log_reader)
		payload = rooms_api.set_room_status(
			room=self.rooms_a[1], dimension="Housekeeping", status="Dirty", reason="turned"
		)
		self.assertIn("history", payload)

		frappe.set_user(self.operator_a)
		payload = rooms_api.set_room_status(
			room=self.rooms_a[1], dimension="Housekeeping", status="Clean", reason="turned"
		)
		self.assertIn("history", payload, msg="Housekeeping Manager does read the log")

		# And an attendant driving the same endpoint gets the room without the log.
		frappe.set_user(self.attendant)
		payload = rooms_api.set_room_status(
			room=self.rooms_a[1], dimension="Housekeeping", status="Dirty", reason="turned"
		)
		self.assertNotIn("history", payload)


class TestRoomRackRespectsActiveStays(RoomAuthorizationWorld):
	"""The display gap R1A left open on purpose, now closed."""

	def _occupied(self, room: str) -> str:
		"""A guest genuinely checked in, with the room's flag left honest."""
		reservation = self.fixtures.reservation(
			self.property_a,
			self.type_a,
			self.fixtures.guest("Rack"),
			rate_plan=self.plan_a,
			nights=2,
		)

		from hospitality_pms.services import reservations as reservation_service

		reservation_service.confirm(reservation)
		line = frappe.get_all("Reservation Room", filters={"parent": reservation}, pluck="name")[0]
		stay = stay_service.check_in(reservation, line, room)["stay"]
		frappe.db.commit()

		return stay

	def _stale_occupied(self, room: str) -> str:
		"""A guest in the room, with the room's own flag lying about it.

		Room 402's persisted state: an active Stay, `checked_out_on` null, and an
		`occupancy_status` that does not say Occupied because a later guest's
		checkout set it Vacant. Forced with `set_value` because the point is that
		the display holds when the flag is wrong, however it got that way - and
		because no legal transition reaches it, which is itself the tell that this
		state should not exist.
		"""
		stay = self._occupied(room)

		frappe.db.set_value("Hotel Room", room, "occupancy_status", "Vacant", update_modified=False)
		frappe.db.commit()

		return stay

	def tearDown(self):
		frappe.set_user("Administrator")
		self.fixtures.reset_property_records(
			self.property_a,
			("Folio Log", "Guest Folio", "Room Status Log", "Stay", "Reservation Log", "Reservation"),
		)
		for room in self.rooms_a:
			frappe.db.set_value(
				"Hotel Room",
				room,
				{"occupancy_status": "Vacant", "housekeeping_status": "Clean"},
				update_modified=False,
			)
		frappe.db.commit()
		super().tearDown()

	def _rack_row(self, room: str) -> dict:
		rack = rooms_api.get_room_rack(property=self.property_a)

		for bucket in rack["room_types"]:
			for row in bucket["rooms"]:
				if row["name"] == room:
					return row

		self.fail(f"room {room} is not on the rack at all")

	def test_room_state_active_stay_overrides_vacant_flag(self):
		room = self.rooms_a[0]
		self._stale_occupied(room)

		frappe.set_user(self.operator_a)
		row = self._rack_row(room)

		self.assertFalse(
			row["assignable"],
			msg="the rack offered a room with an active Stay because its flag said Vacant",
		)
		self.assertEqual(row["blocking_reason"], "Occupied")

	def test_room_state_due_out_active_stay_not_assignable_now(self):
		"""The systemic case, and the one that needs no corrupted data at all.

		Nothing is forced here. `Occupied -> Due Out` is what `mark_due_out` does
		from the Night Audit for every departing guest, every morning, and `Due Out`
		is deliberately not in `OCCUPIED_STATES` - so before R1B the rack offered
		every one of those rooms while its guest was still in it. The estate audit
		found five of them live on this bench.
		"""
		room = self.rooms_a[0]
		stay = self._occupied(room)

		# Through the services, exactly as the audit does it.
		stay_service.transition(stay, stay_service.DUE_OUT)
		room_service.set_status(room, room_service.OCCUPANCY, "Due Out", reason="departing")
		frappe.db.commit()

		# The premise: the room's own flag does not read as occupied, so only the
		# active-Stay authority can refuse it.
		self.assertNotIn("Due Out", room_service.OCCUPIED_STATES)
		self.assertEqual(
			frappe.db.get_value("Hotel Room", room, "occupancy_status"), "Due Out"
		)

		frappe.set_user(self.operator_a)

		self.assertFalse(self._rack_row(room)["assignable"])

	def test_room_state_checked_out_stay_no_longer_blocks(self):
		"""Release, not merely block."""
		room = self.rooms_a[0]
		stay = self._stale_occupied(room)

		stay_service.transition(stay, stay_service.CHECKED_OUT)
		frappe.db.set_value(
			"Stay", stay, "checked_out_on", "2026-01-01 12:00:00", update_modified=False
		)
		frappe.db.set_value(
			"Hotel Room",
			room,
			{"occupancy_status": "Vacant", "housekeeping_status": "Clean"},
			update_modified=False,
		)
		frappe.db.commit()

		frappe.set_user(self.operator_a)
		row = self._rack_row(room)

		self.assertTrue(row["assignable"], msg="a departed guest still held the room on the rack")
		self.assertIsNone(row["blocking_reason"])

	def test_the_rack_summary_agrees_with_the_rows(self):
		"""A tile that disagreed with the grid under it would be the same defect."""
		room = self.rooms_a[0]
		self._stale_occupied(room)

		frappe.set_user(self.operator_a)
		rack = rooms_api.get_room_rack(property=self.property_a)

		rows = [row for bucket in rack["room_types"] for row in bucket["rooms"]]

		self.assertEqual(
			rack["summary"]["assignable"],
			sum(1 for row in rows if row["assignable"]),
		)
		self.assertNotIn(room, [row["name"] for row in rows if row["assignable"]])

	def test_room_detail_agrees_with_the_rack(self):
		"""One room, two endpoints, one answer."""
		room = self.rooms_a[0]
		self._stale_occupied(room)

		frappe.set_user(self.operator_a)

		self.assertFalse(rooms_api.get_room(room=room)["assignable"])
		self.assertFalse(self._rack_row(room)["assignable"])

	def test_room_state_bulk_query_not_n_plus_one(self):
		"""The occupancy authority is asked once for the property, not once per room.

		Asserted as a bounded query count rather than as a timing, so it fails on a
		regression instead of on a slow machine. The rack is open all shift on every
		terminal, and a per-room Stay query is what this fix must not introduce.
		"""
		for room in self.rooms_a[:2]:
			self._stale_occupied(room)

		frappe.set_user(self.operator_a)

		# Warm the caches a first call would otherwise pay for - DocType meta,
		# permissions, the property - so the count measures the rack's own queries.
		rooms_api.get_room_rack(property=self.property_a)

		with self.assertQueryCount(12):
			rooms_api.get_room_rack(property=self.property_a)

	def test_the_dashboard_room_states_obey_the_same_rule(self):
		"""`front_office.get_room_states` feeds the dashboard's counts."""
		from hospitality_pms.services import front_office as front_office_service

		room = self.rooms_a[0]
		self._stale_occupied(room)

		frappe.set_user(self.operator_a)
		states = front_office_service.get_room_states(self.property_a)

		self.assertFalse(states[room]["assignable"])
		self.assertTrue(states[self.rooms_a[2]]["assignable"])
