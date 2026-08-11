"""The blacklist flag is permlevel 2, and a board is not a way around that.

`is_blacklisted` sits at permlevel 2 with a reader set (`BLACKLIST_READERS`) that
is deliberately narrower than Guest itself, and `blacklist_reason` sits at
permlevel 3, narrower again. That design is only enforced on the *document* path.
`front_office.get_guest_flags` read the column with `frappe.get_all`, which
applies neither DocType permission nor permlevel filtering — and the boards that
consume it gate on their own DocType, not on Guest. The arrivals board asks for
`Reservation.read`, whose readers are every operational role in the estate.

So a Room Attendant, a Maintenance Manager, a Kitchen Manager or a Revenue
Manager opened `/arrivals` and was told which guests are blacklisted. Not by a
misconfigured permission — by a permission-free column read. It is the second
time that has defeated this design; `services.guests.assert_not_blacklisted`
records the first, and `test_stay.test_blacklist_refusal_hides_reason` is its
regression.

Two things are asserted throughout, because either alone proves nothing:

* the uncleared role receives no `is_blacklisted` **key** — absence, not `False`.
  `False` is a claim about a guest ("this one is not blacklisted") that the
  caller is not entitled to make and that may be untrue.
* the cleared role still receives it. A guard that also blinds the front desk is
  not a fix, it is an outage: the desk holds the flag precisely so it can refuse
  a check-in.

Real users holding real roles throughout, through the whitelisted endpoints. A
mock cannot tell you what a Room Attendant's session actually receives.
"""

import json

import frappe
from frappe.tests import IntegrationTestCase

from hospitality_pms.api import front_office as front_office_api
from hospitality_pms.api import stays as stays_api
from hospitality_pms.services import front_office as front_office_service
from hospitality_pms.services import guests as guest_identity_service
from hospitality_pms.services import reservations as reservation_service
from hospitality_pms.services import stays as stay_service
from hospitality_pms.tests.fixtures import Fixtures

#: Never allowed on any board, for anyone. Kept recognisable so a leak shows up
#: as this sentence in a failure message rather than as a wrong boolean.
BLACKLIST_REASON = "CONFIDENTIAL: barred after an incident, police report QA-2026-902"

#: Every field name that would disclose the blacklist, or let it be inferred.
#: A board row may carry none of them for an uncleared caller, and none of the
#: reason-bearing ones for anybody.
REASON_FIELDS = ("blacklist_reason", "blacklisted_by", "blacklisted_on")


class TestGuestPrivacyOnBoards(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()

		cls.fixtures = Fixtures("PRIV")

		# Identification capture is a separate control with its own suite; off
		# here so a refusal can only be the one under test.
		cls.property = cls.fixtures.property("PV", require_id_at_check_in=0)
		cls.room_type = cls.fixtures.room_type(cls.property)
		cls.rooms = cls.fixtures.rooms(cls.property, cls.room_type, count=3)
		cls.rate_plan = cls.fixtures.rate_plan(cls.property, cls.room_type)

		# Arriving today and blacklisted: the arrivals row that carries the flag.
		cls.arriving_guest = cls.fixtures.guest(
			"Barred", is_blacklisted=1, blacklist_reason=BLACKLIST_REASON
		)
		cls.reservation = cls.fixtures.reservation(
			cls.property, cls.room_type, cls.arriving_guest, rate_plan=cls.rate_plan, nights=2
		)
		reservation_service.confirm(cls.reservation)

		# In the house and blacklisted during the stay, which is how it usually
		# happens: a guest cannot be checked in while blacklisted at all
		# (`assert_not_blacklisted`), so the flag is placed afterwards, through
		# the document path that audits it.
		cls.resident_guest = cls.fixtures.guest("Resident")
		cls.stay = cls._check_in(cls, cls.resident_guest, cls.rooms[1])
		cls._blacklist(cls, cls.resident_guest)

		# Cleared: Front Office is inside BLACKLIST_READERS, because the desk
		# cannot refuse a check-in it was never told about.
		cls.desk = cls.fixtures.user("fo", ["Front Office Agent"], properties=[cls.property])

		# Not cleared, and the exact shape of the defect: Housekeeping is inside
		# OPERATIONAL, so it reads Reservation and Stay and can open both boards.
		# It is not a Guest reader at any level.
		cls.housekeeper = cls.fixtures.user(
			"hk", ["Housekeeping Manager"], properties=[cls.property]
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

	# -- world ----------------------------------------------------------

	def _check_in(self, guest: str, room: str) -> str:
		reservation = self.fixtures.reservation(
			self.property, self.room_type, guest, rate_plan=self.rate_plan, nights=3
		)
		reservation_service.confirm(reservation)

		line = frappe.get_all("Reservation Room", filters={"parent": reservation}, pluck="name")[0]

		return stay_service.check_in(reservation, line, room)["stay"]

	def _blacklist(self, guest: str):
		doc = frappe.get_doc("Guest", guest)
		doc.is_blacklisted = 1
		doc.blacklist_reason = BLACKLIST_REASON
		doc.save(ignore_permissions=True)

	# -- helpers --------------------------------------------------------

	def _arrivals_row(self, guest: str) -> dict:
		board = front_office_api.arrivals(property=self.property)
		rows = [row for row in board["rows"] if row["guest"] == guest]

		self.assertTrue(rows, msg="the arrivals row under test is not on the board at all")

		return rows[0]

	def _in_house_row(self, guest: str) -> dict:
		board = stays_api.in_house(property=self.property)
		rows = [row for row in board["stays"] if row["guest"] == guest]

		self.assertTrue(rows, msg="the in-house row under test is not on the board at all")

		return rows[0]

	def _assert_no_reason_anywhere(self, payload, label: str):
		"""No reason field, and no reason text, at any depth of the response."""
		serialised = json.dumps(payload, default=str)

		self.assertNotIn(BLACKLIST_REASON, serialised, msg=f"{label} carried the blacklist reason")

		for field in REASON_FIELDS:
			self.assertNotIn(f'"{field}"', serialised, msg=f"{label} carried {field}")

	# -- the permission model itself, as the control ----------------------

	def test_the_clearance_question_answers_by_role(self):
		"""Establishes that this is a bypass, not a gap in the matrix.

		If this failed, every other assertion below would be meaningless: the
		roles would not be the ones the suite thinks it is testing.
		"""
		frappe.set_user(self.desk)
		self.assertTrue(guest_identity_service.may_see_blacklist())

		frappe.set_user(self.housekeeper)
		self.assertFalse(guest_identity_service.may_see_blacklist())

		# And the boards really are open to the uncleared role — otherwise the
		# leak would have been closed by the endpoint guard all along.
		self.assertTrue(frappe.has_permission("Reservation", "read"))
		self.assertTrue(frappe.has_permission("Stay", "read"))

	def test_nobody_is_cleared_for_the_reason_on_a_board(self):
		"""Permlevel 3 is narrower than permlevel 2, and no board reads it."""
		frappe.set_user(self.desk)

		self.assertTrue(guest_identity_service.may_see_blacklist())
		self.assertFalse(guest_identity_service.may_see_blacklist_reason())

	# -- the cleared role keeps the flag ----------------------------------

	def test_authorized_blacklist_reader_receives_allowed_blacklist_state(self):
		frappe.set_user(self.desk)

		row = self._arrivals_row(self.arriving_guest)

		self.assertIn("is_blacklisted", row, msg="the front desk lost the flag it works from")
		self.assertTrue(row["is_blacklisted"])

		# The state, not merely the truthy case: a cleared reader is told "no"
		# for a guest who is not blacklisted.
		clean = self._in_house_row(self.resident_guest)
		self.assertIn("is_blacklisted", clean)

		# permlevel 0 fields are unconditional and unaffected.
		self.assertIn("vip_status", row)
		self.assertIn("guest_name", row)

		self._assert_no_reason_anywhere(row, "the cleared arrivals row")

	def test_authorized_reader_is_told_no_for_a_guest_who_is_not_blacklisted(self):
		"""`False` for a cleared reader is a fact, and it must still arrive."""
		frappe.set_user("Administrator")
		guest = self.fixtures.guest("Ordinary")
		reservation = self.fixtures.reservation(
			self.property, self.room_type, guest, rate_plan=self.rate_plan
		)
		reservation_service.confirm(reservation)
		frappe.db.commit()

		frappe.set_user(self.desk)
		row = self._arrivals_row(guest)

		self.assertIn("is_blacklisted", row)
		self.assertFalse(row["is_blacklisted"])

	# -- the uncleared role loses it entirely -----------------------------

	def test_unauthorized_role_does_not_receive_blacklist_flag(self):
		frappe.set_user(self.housekeeper)

		row = self._arrivals_row(self.arriving_guest)

		# Absence, not falsity. `False` would be a claim about this guest that
		# housekeeping is not entitled to and that is, here, untrue.
		self.assertNotIn("is_blacklisted", row)

		# And the row is otherwise intact: this is a redaction, not an outage. The
		# control is a field housekeeping is actually entitled to — the reservation
		# and room-line data this board is gated on. `vip_status` is no longer a
		# valid control: 16.7.1 gated guest standing on Guest read as well, because
		# permlevel 0 means "unprivileged among Guest readers", not "public".
		self.assertEqual(row["guest"], self.arriving_guest)
		self.assertIn("guest_name", row)
		self.assertIn("room_type", row)
		self.assertIn("arrival_date", row)
		self.assertNotIn("vip_status", row)

	def test_unauthorized_role_does_not_receive_blacklist_reason(self):
		frappe.set_user(self.housekeeper)

		board = front_office_api.arrivals(property=self.property)

		self._assert_no_reason_anywhere(board, "the uncleared arrivals board")
		self._assert_no_reason_anywhere(
			stays_api.in_house(property=self.property), "the uncleared in-house board"
		)

	def test_arrivals_does_not_leak_blacklist_via_guest_flags(self):
		"""The defect, at the endpoint the architecture review found it on."""
		frappe.set_user(self.housekeeper)

		board = front_office_api.arrivals(property=self.property)

		self.assertTrue(board["rows"], msg="an empty board cannot prove anything")

		for row in board["rows"]:
			self.assertNotIn("is_blacklisted", row)

		self.assertNotIn('"is_blacklisted"', json.dumps(board, default=str))

	def test_in_house_board_obeys_the_same_rule(self):
		frappe.set_user(self.housekeeper)

		row = self._in_house_row(self.resident_guest)

		self.assertNotIn("is_blacklisted", row)
		# Guest standing is gated on Guest read from 16.7.1, so it is absent here
		# too; the stay's own fields, which this board is gated on, are not.
		self.assertNotIn("vip_status", row)
		self.assertIn("stay_status", row)
		self.assertIn("room_number", row)

		frappe.set_user(self.desk)

		row = self._in_house_row(self.resident_guest)

		self.assertIn("is_blacklisted", row)
		self.assertTrue(row["is_blacklisted"])

	def test_departures_board_carries_no_blacklist_field_for_either_role(self):
		"""The departures row never carried the flag, and still does not.

		Recorded so a later "make the boards consistent" change adds the field
		deliberately, through `_blacklist_flag`, rather than by copying a line.
		"""
		for user in (self.desk, self.housekeeper):
			frappe.set_user(user)

			board = front_office_api.departures(property=self.property)

			self._assert_no_reason_anywhere(board, f"the departures board for {user}")

			for row in board["rows"]:
				self.assertNotIn("blacklist_reason", row)

	# -- the shared helper, directly ---------------------------------------

	def test_get_guest_flags_omits_the_key_for_an_unauthorized_role(self):
		"""Asserted on the helper too, not only on its callers.

		`get_guest_flags` is the single place the column is read, and a new board
		will reach for it before it reaches for this suite.
		"""
		guests = [self.arriving_guest, self.resident_guest]

		frappe.set_user(self.housekeeper)
		flags = front_office_service.get_guest_flags(guests)

		self.assertEqual(set(flags), set(guests))

		for guest, row in flags.items():
			self.assertNotIn("is_blacklisted", row, msg=f"{guest} leaked the flag")
			self.assertIn("vip_status", row)
			self.assertIn("guest_type", row)

		frappe.set_user(self.desk)
		flags = front_office_service.get_guest_flags(guests)

		for guest in guests:
			self.assertIn("is_blacklisted", flags[guest])
			self.assertTrue(flags[guest]["is_blacklisted"])

	def test_get_guest_flags_stays_a_single_query(self):
		"""The redaction may not cost the board its bulk shape.

		One query for the whole board, whoever asks; only the column list
		changes. A per-guest permission check here would be an N+1 at the desk.
		"""
		guests = [self.arriving_guest, self.resident_guest]

		for user in (self.desk, self.housekeeper):
			frappe.set_user(user)

			# The clearance question reads the Guest meta, which is cached per
			# request; warmed here so the count is the board's own query and not
			# the cache miss of whichever test ran first.
			front_office_service.get_guest_flags(guests)

			with self.assertQueryCount(1):
				front_office_service.get_guest_flags(guests)
