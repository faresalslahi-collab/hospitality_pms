"""Stay regression suite - occupancy may only be created by orchestration.

Covers:

* **P1-2(a)** a Stay cannot be inserted through generic document CRUD, at any
  status, by any operational role.
* **P1-2(b)** permission to edit a Reservation is not permission to physically
  check a guest in.
* **P2-6** a blacklist refusal does not disclose the confidential reason.

The authorised paths - reservation check-in and walk-in - must keep working
unchanged, so each is exercised end to end alongside the refusals. A guard that
also blocks the front desk is not a fix.
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days

from hospitality_pms.services import reservations as reservation_service
from hospitality_pms.services import stays as stay_service
from hospitality_pms.services import walk_in as walk_in_service
from hospitality_pms.services.exceptions import (
	HospitalityPMSError,
	PermissionDeniedError,
)
from hospitality_pms.tests.fixtures import Fixtures

STAY = "Stay"

#: The confidential text that must never reach a front desk screen.
BLACKLIST_REASON = "CONFIDENTIAL: assaulted a member of staff, police report QA-2026-118"


class TestStayCreationBoundary(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()

		cls.fixtures = Fixtures("STAY")
		# Identification capture is a separate control with its own test; it is
		# switched off here so a refusal can only be the one under test.
		cls.property = cls.fixtures.property("ST", require_id_at_check_in=0)
		cls.room_type = cls.fixtures.room_type(cls.property)
		cls.rooms = cls.fixtures.rooms(cls.property, cls.room_type, count=6)
		cls.rate_plan = cls.fixtures.rate_plan(cls.property, cls.room_type)
		cls.guest = cls.fixtures.guest("Stayer")

		cls.blacklisted = cls.fixtures.guest(
			"Blacklisted", is_blacklisted=1, blacklist_reason=BLACKLIST_REASON
		)

		cls.front_office = cls.fixtures.user(
			"fo", ["Front Office Agent"], properties=[cls.property]
		)
		cls.reservations = cls.fixtures.user(
			"res", ["Reservation Agent"], properties=[cls.property]
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

	# -- helpers --------------------------------------------------------

	def _business_date(self):
		return frappe.db.get_value("Property", self.property, "business_date")

	def _stay_payload(self, **overrides) -> dict:
		arrival = self._business_date()

		return {
			"doctype": STAY,
			"property": self.property,
			"stay_status": stay_service.EXPECTED,
			"guest": self.guest,
			"room": self.rooms[0],
			"room_type": self.room_type,
			"arrival_date": arrival,
			"departure_date": add_days(arrival, 2),
			"adults": 1,
			**overrides,
		}

	def _confirmed_reservation(self) -> tuple[str, str]:
		"""A confirmed reservation and its room line, ready to check in."""
		frappe.set_user("Administrator")

		name = self.fixtures.reservation(
			self.property, self.room_type, self.guest, rate_plan=self.rate_plan, nights=2
		)
		reservation_service.confirm(name)

		line = frappe.get_all("Reservation Room", filters={"parent": name}, pluck="name")[0]
		frappe.db.commit()

		return name, line

	def _stays_for(self, guest: str) -> list[str]:
		return frappe.get_all(STAY, filters={"guest": guest}, pluck="name")

	# -- P1-2(a): no Stay outside orchestration -------------------------

	def test_direct_stay_insert_requires_service(self):
		"""Expected is not a safe status to let through: it skips everything.

		A Stay inserted directly has no reservation behind it, no folio to
		charge, no room marked occupied, and never passed the blacklist,
		identity or deposit checks.
		"""
		frappe.set_user(self.front_office)

		with self.assertRaises(PermissionDeniedError):
			frappe.get_doc(self._stay_payload()).insert()

		frappe.db.rollback()
		self.assertEqual(self._stays_for(self.guest), [])

	def test_direct_in_house_stay_insert_is_refused(self):
		"""The sweep's worst case: a guest in a room, invisible to the system."""
		frappe.set_user(self.front_office)

		with self.assertRaises(PermissionDeniedError):
			frappe.get_doc(self._stay_payload(stay_status=stay_service.IN_HOUSE)).insert()

		frappe.db.rollback()
		self.assertEqual(self._stays_for(self.guest), [])

	def test_direct_stay_insert_for_a_blacklisted_guest_is_refused(self):
		frappe.set_user(self.front_office)

		with self.assertRaises(PermissionDeniedError):
			frappe.get_doc(
				self._stay_payload(guest=self.blacklisted, stay_status=stay_service.IN_HOUSE)
			).insert()

		frappe.db.rollback()
		self.assertEqual(self._stays_for(self.blacklisted), [])

	def test_reservation_agent_direct_stay_insert_is_refused(self):
		frappe.set_user(self.reservations)

		with self.assertRaises(Exception):
			frappe.get_doc(self._stay_payload()).insert()

		frappe.db.rollback()
		self.assertEqual(self._stays_for(self.guest), [])

	def test_administrator_direct_stay_insert_is_refused(self):
		"""Again, the boundary is the path and not the rank."""
		with self.assertRaises(PermissionDeniedError):
			frappe.get_doc(self._stay_payload()).insert(ignore_permissions=True)

		frappe.db.rollback()
		self.assertEqual(self._stays_for(self.guest), [])

	# -- P1-2(b): check-in authority ------------------------------------

	def test_check_in_requires_checkin_authority(self):
		"""A Reservation Agent may edit the booking and not check the guest in.

		The role holds `Reservation.write` and no `Stay.create`, which is
		exactly what the approved matrix says. The endpoint used to consult
		only the first of those, so a reservations-only role could put a body
		in a room and open a financial record.
		"""
		from hospitality_pms.api import stays as stays_api

		reservation, line = self._confirmed_reservation()

		frappe.set_user(self.reservations)

		self.assertTrue(frappe.has_permission("Reservation", "write"))
		self.assertFalse(
			frappe.has_permission(STAY, "create"),
			msg="fixture is wrong: this role is supposed to lack Stay.create",
		)

		with self.assertRaises(PermissionDeniedError):
			stays_api.check_in(reservation=reservation, room_line=line, room=self.rooms[1])

		frappe.db.rollback()

		self.assertEqual(frappe.get_all(STAY, filters={"reservation": reservation}), [])
		self.assertEqual(frappe.get_all("Guest Folio", filters={"reservation": reservation}), [])

	def test_front_office_agent_check_in_still_works(self):
		"""The authorised path, end to end: Stay, Folio and an occupied room."""
		from hospitality_pms.api import stays as stays_api

		reservation, line = self._confirmed_reservation()
		room = self.rooms[2]

		frappe.set_user(self.front_office)

		result = stays_api.check_in(reservation=reservation, room_line=line, room=room)

		self.assertTrue(result["stay"])
		self.assertTrue(result["folio"])

		stay = frappe.get_doc(STAY, result["stay"])

		self.assertEqual(stay.stay_status, stay_service.IN_HOUSE)
		self.assertEqual(stay.folio, result["folio"])
		self.assertEqual(stay.checked_in_by, self.front_office)

		self.assertEqual(
			frappe.db.get_value("Hotel Room", room, "occupancy_status"),
			"Occupied",
			msg="check-in must still mark the room occupied",
		)
		self.assertEqual(
			frappe.db.get_value("Reservation", reservation, "reservation_status"),
			reservation_service.CHECKED_IN,
		)

	def test_walk_in_still_works(self):
		"""Reservation -> confirm -> check-in -> Stay + Folio, in one call."""
		from hospitality_pms.api import walk_in as walk_in_api

		frappe.set_user(self.front_office)

		result = walk_in_api.create_walk_in(
			guest=self.guest,
			departure_date=str(add_days(self._business_date(), 2)),
			room_type=self.room_type,
			room=self.rooms[3],
			property=self.property,
		)

		self.assertTrue(result["stay"])
		self.assertTrue(result["folio"])
		self.assertEqual(
			frappe.db.get_value(STAY, result["stay"], "stay_status"), stay_service.IN_HOUSE
		)

	# -- P2-6: the blacklist reason is confidential ---------------------

	def test_blacklist_refusal_hides_reason(self):
		"""The front desk is told no, and not told why.

		`blacklist_reason` is permlevel 3 and the front office does not hold
		it. The check-in refusal read the field with `frappe.db.get_value`,
		which bypasses permlevels entirely, and interpolated it straight into
		the message on the agent's screen - incident detail that may be police
		or HR material.
		"""
		frappe.set_user("Administrator")

		reservation = self.fixtures.reservation(
			self.property, self.room_type, self.blacklisted, rate_plan=self.rate_plan, nights=2
		)
		reservation_service.confirm(reservation)
		line = frappe.get_all("Reservation Room", filters={"parent": reservation}, pluck="name")[0]
		frappe.db.commit()

		frappe.set_user(self.front_office)

		with self.assertRaises(HospitalityPMSError) as caught:
			stay_service.check_in(reservation, line, self.rooms[4])

		message = str(caught.exception)

		self.assertNotIn(
			BLACKLIST_REASON,
			message,
			msg=f"the confidential reason was disclosed to the front desk: {message}",
		)
		self.assertNotIn("police report", message.lower())
		self.assertIn("manager", message.lower())

		frappe.db.rollback()

	def test_walk_in_blacklist_refusal_hides_reason(self):
		"""Same refusal, same silence, on the other check-in path."""
		frappe.set_user(self.front_office)

		with self.assertRaises(HospitalityPMSError) as caught:
			walk_in_service.create_walk_in(
				property_name=self.property,
				guest=self.blacklisted,
				departure_date=add_days(self._business_date(), 2),
				room_type=self.room_type,
				room=self.rooms[5],
			)

		self.assertNotIn(BLACKLIST_REASON, str(caught.exception))

		frappe.db.rollback()

	def test_elevated_role_can_still_retrieve_the_reason(self):
		"""Hiding it from the desk must not hide it from the people who own it.

		`BLACKLIST_REASON_READERS` in the approved matrix is the blacklist
		writers plus the auditor; a Hotel Manager holds permlevel 3 and reads
		the field through the ordinary document path.
		"""
		manager = self.fixtures.user("hotelmgr", ["Hotel Manager"], properties=[self.property])
		frappe.db.commit()

		frappe.set_user(manager)

		doc = frappe.get_doc("Guest", self.blacklisted)
		doc.check_permission("read")

		self.assertEqual(doc.blacklist_reason, BLACKLIST_REASON)
