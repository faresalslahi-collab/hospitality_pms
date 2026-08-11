"""P1-5, P2-5 and N3 — a Stay's dates and the hotel's inventory disagreed.

`Reservation Room` is what availability counts. `Stay` is what the front desk
looks at. Extending or shortening a stay changed only the second, so the two
told different stories about the same room:

* **P1-5.** A guest extended from the 12th to the 15th. The Stay said the 15th,
  the Reservation Room still said the 12th, and availability reported the only
  room in the property as free for the 12th-15th. A second reservation confirmed
  against it, and the extended guest's room was sold out from under them.
* **P2-5.** The reverse. A stay shortened from the 16th to the 12th released
  nothing: the Reservation Room still held the 16th and four nights stayed
  unsellable.
* **N3.** Both operations appended a Stay Note *after* `doc.save()` and never
  saved again, so neither change left any trace at all.

The fix is not to teach availability about Stays - that would count a
checked-in guest twice. It is to keep the one authoritative interval correct.
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, getdate

from hospitality_pms.services import folio as folio_service
from hospitality_pms.services import reservations as reservation_service
from hospitality_pms.services import stays as stay_service
from hospitality_pms.services.exceptions import AvailabilityError, HospitalityPMSError
from hospitality_pms.tests.inventory_world import InventoryWorld


class StayDateTestCase(IntegrationTestCase):
	ROOMS = 1

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
		self._clear_bookings()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def _clear_bookings(self):
		self.world.fixtures.reset_property_records(
			self.world.property,
			("Folio Log", "Guest Folio", "Room Status Log", "Stay", "Reservation Log", "Reservation"),
		)
		for room in self.world.rooms:
			frappe.db.set_value("Hotel Room", room, "occupancy_status", "Vacant", update_modified=False)
		frappe.db.commit()

	def _line(self, reservation: str) -> dict:
		return self.world.lines(reservation)[0]

	def _stay_and_line(self, *, nights: int = 2):
		"""A checked-in guest, and the inventory line behind them."""
		reservation = self.world.confirmed(nights=nights)
		result = self.world.check_in(reservation)

		return result["stay"], reservation


class TestStayExtension(StayDateTestCase):
	"""P1-5 — the added nights must actually be held."""

	WORLD_CODE = "SE"

	def test_extension_updates_reservation_inventory_interval(self):
		"""The reproduction, as an assertion about the inventory line."""
		stay, reservation = self._stay_and_line(nights=2)

		stay_service.extend_stay(stay, self.world.day(5))

		self.assertEqual(
			getdate(frappe.db.get_value("Stay", stay, "departure_date")), self.world.day(5)
		)
		self.assertEqual(
			getdate(self._line(reservation)["departure_date"]),
			self.world.day(5),
			msg="the Stay moved but the inventory line it is counted from did not",
		)

	def test_extension_holds_the_added_nights(self):
		stay, _reservation = self._stay_and_line(nights=2)

		self.assertEqual(
			self.world.available(2, 5), 1, msg="the added nights should be free before extending"
		)

		stay_service.extend_stay(stay, self.world.day(5))

		self.assertEqual(
			self.world.sold(2, 5), 1, msg="availability did not see the extension"
		)
		self.assertEqual(self.world.available(2, 5), 0)

	def test_extension_blocks_a_second_booking_for_the_added_nights(self):
		"""The consequence the sweep found: the last room sold twice."""
		stay, _reservation = self._stay_and_line(nights=2)

		stay_service.extend_stay(stay, self.world.day(5))
		frappe.db.commit()

		competitor = self.world.reservation(nights=2, arrival=self.world.day(2))

		with self.assertRaises(AvailabilityError):
			reservation_service.confirm(competitor)

	def test_extension_is_denied_when_the_added_nights_are_sold(self):
		stay, _reservation = self._stay_and_line(nights=2)

		self.world.confirmed(nights=2, arrival=self.world.day(2))

		with self.assertRaises(AvailabilityError):
			stay_service.extend_stay(stay, self.world.day(4))

	def test_failed_extension_leaves_both_dates_unchanged(self):
		stay, reservation = self._stay_and_line(nights=2)
		self.world.confirmed(nights=2, arrival=self.world.day(2))

		with self.assertRaises(AvailabilityError):
			stay_service.extend_stay(stay, self.world.day(4))

		frappe.db.rollback()

		self.assertEqual(
			getdate(frappe.db.get_value("Stay", stay, "departure_date")), self.world.day(2)
		)
		self.assertEqual(getdate(self._line(reservation)["departure_date"]), self.world.day(2))

	def test_extension_note_is_persisted(self):
		"""N3 — the note was appended after the save and never written."""
		stay, _reservation = self._stay_and_line(nights=2)

		stay_service.extend_stay(stay, self.world.day(5))

		notes = frappe.get_all(
			"Stay Note", filters={"parent": stay}, fields=["note", "noted_by"], order_by="idx asc"
		)

		self.assertTrue(notes, msg="the extension left no trace on the stay")
		self.assertIn(str(self.world.day(5)), notes[-1]["note"])
		self.assertIn(str(self.world.day(2)), notes[-1]["note"], msg="the note should say what it moved from")
		self.assertTrue(notes[-1]["noted_by"])


class TestStayShortening(StayDateTestCase):
	"""P2-5 — the released nights must become sellable."""

	WORLD_CODE = "SS"

	def test_shortening_releases_inventory(self):
		stay, reservation = self._stay_and_line(nights=6)

		self.assertEqual(self.world.available(2, 6), 0)

		stay_service.shorten_stay(stay, self.world.day(2), "guest leaving early")

		self.assertEqual(
			getdate(self._line(reservation)["departure_date"]),
			self.world.day(2),
			msg="the inventory line still holds nights the guest is not staying",
		)
		self.assertEqual(
			self.world.available(2, 6), 1, msg="the released nights are still unsellable"
		)

	def test_released_nights_can_be_sold(self):
		stay, _reservation = self._stay_and_line(nights=6)

		stay_service.shorten_stay(stay, self.world.day(2), "guest leaving early")
		frappe.db.commit()

		later = self.world.reservation(nights=2, arrival=self.world.day(2))

		self.assertEqual(reservation_service.confirm(later), reservation_service.CONFIRMED)

	def test_shortening_note_is_persisted(self):
		stay, _reservation = self._stay_and_line(nights=6)

		stay_service.shorten_stay(stay, self.world.day(2), "guest leaving early")

		notes = frappe.get_all("Stay Note", filters={"parent": stay}, fields=["note"], order_by="idx asc")

		self.assertTrue(notes, msg="the shortening left no trace on the stay")
		self.assertIn("guest leaving early", notes[-1]["note"])

	def test_shortening_preserves_historical_charges(self):
		"""Nights already charged are history, not something to undo."""
		stay, _reservation = self._stay_and_line(nights=6)
		folio = frappe.db.get_value("Stay", stay, "folio")

		folio_service.post_charge(
			folio,
			"Room Charge",
			"Night already stayed",
			100,
			idempotency_key=f"{self.world.tag}:hist:1",
		)
		before = flt(frappe.db.get_value("Guest Folio", folio, "total_charges"))

		stay_service.shorten_stay(stay, self.world.day(2), "guest leaving early")

		self.assertEqual(
			flt(frappe.db.get_value("Guest Folio", folio, "total_charges")),
			before,
			msg="shortening reversed revenue that had already been posted",
		)

	def test_failed_shortening_leaves_both_dates_unchanged(self):
		stay, reservation = self._stay_and_line(nights=6)

		with self.assertRaises(HospitalityPMSError):
			stay_service.shorten_stay(stay, self.world.day(6), "not actually shorter")

		frappe.db.rollback()

		self.assertEqual(
			getdate(frappe.db.get_value("Stay", stay, "departure_date")), self.world.day(6)
		)
		self.assertEqual(getdate(self._line(reservation)["departure_date"]), self.world.day(6))


class TestReservationHeaderDates(StayDateTestCase):
	"""Part 10 — the header summarises its children, it does not mirror one."""

	WORLD_CODE = "SH"
	ROOMS = 3

	def test_header_departure_follows_the_latest_child(self):
		reservation = self.world.confirmed(nights=2, rooms=2)
		lines = self.world.lines(reservation)

		first = self.world.check_in(reservation, line=lines[0]["name"])
		stay_service.extend_stay(first["stay"], self.world.day(5))

		self.assertEqual(
			getdate(frappe.db.get_value("Reservation", reservation, "departure_date")),
			self.world.day(5),
			msg="the header did not follow the room that now departs latest",
		)

	def test_header_does_not_shrink_to_one_shortened_child(self):
		"""One guest leaving early must not rewrite the whole booking's dates."""
		reservation = self.world.confirmed(nights=6, rooms=2)
		lines = self.world.lines(reservation)

		first = self.world.check_in(reservation, line=lines[0]["name"])
		stay_service.shorten_stay(first["stay"], self.world.day(2), "one guest leaving early")

		self.assertEqual(
			getdate(frappe.db.get_value("Reservation", reservation, "departure_date")),
			self.world.day(6),
			msg="the header took one room's early departure as the whole booking's",
		)


class TestDirectInventoryMutation(StayDateTestCase):
	"""Part 16 — the interval is service-owned, not a form field.

	Every fix in this wave lives in a service: `extend_stay` re-checks
	availability, `shorten_stay` releases nights, `assign_room` locks the room.
	All of it is bypassed by `frappe.get_doc(...).save()`, and a guard that a
	document save can walk around is not a guard.
	"""

	WORLD_CODE = "SM"
	ROOMS = 2

	def test_a_stays_departure_cannot_be_moved_by_a_save(self):
		stay, _reservation = self._stay_and_line(nights=2)

		doc = frappe.get_doc("Stay", stay)
		doc.departure_date = self.world.day(5)

		with self.assertRaises(HospitalityPMSError):
			doc.save(ignore_permissions=True)

		frappe.db.rollback()

		self.assertEqual(
			getdate(frappe.db.get_value("Stay", stay, "departure_date")), self.world.day(2)
		)

	def test_a_stays_arrival_cannot_be_moved_by_a_save(self):
		stay, _reservation = self._stay_and_line(nights=2)

		doc = frappe.get_doc("Stay", stay)
		doc.arrival_date = self.world.day(-1)

		with self.assertRaises(HospitalityPMSError):
			doc.save(ignore_permissions=True)

		frappe.db.rollback()

	def test_the_service_may_still_move_it(self):
		"""The guard is about the route, not the change."""
		stay, reservation = self._stay_and_line(nights=2)

		stay_service.extend_stay(stay, self.world.day(4))

		self.assertEqual(
			getdate(frappe.db.get_value("Stay", stay, "departure_date")), self.world.day(4)
		)
		self.assertEqual(getdate(self._line(reservation)["departure_date"]), self.world.day(4))

	def test_notes_remain_editable_on_a_stay(self):
		"""Narrow: annotating a stay is not moving a guest's dates."""
		stay, _reservation = self._stay_and_line(nights=2)

		doc = frappe.get_doc("Stay", stay)
		doc.append("stay_notes", {"note": "Late arrival expected."})
		doc.save(ignore_permissions=True)

		self.assertTrue(frappe.db.count("Stay Note", {"parent": stay}))

	def test_a_confirmed_lines_interval_cannot_be_moved_by_a_save(self):
		reservation = self.world.confirmed(nights=2)

		doc = frappe.get_doc("Reservation", reservation)
		doc.rooms[0].departure_date = self.world.day(6)

		with self.assertRaises(HospitalityPMSError):
			doc.save(ignore_permissions=True)

		frappe.db.rollback()

		self.assertEqual(getdate(self._line(reservation)["departure_date"]), self.world.day(2))

	def test_a_confirmed_lines_room_cannot_be_repointed_by_a_save(self):
		reservation = self.world.confirmed(nights=2)
		line = self._line(reservation)["name"]
		reservation_service.assign_room(reservation, line, self.world.rooms[0])
		frappe.db.commit()

		doc = frappe.get_doc("Reservation", reservation)
		doc.rooms[0].assigned_room = self.world.rooms[1]

		with self.assertRaises(HospitalityPMSError):
			doc.save(ignore_permissions=True)

		frappe.db.rollback()

		self.assertEqual(
			frappe.db.get_value("Reservation Room", line, "assigned_room"), self.world.rooms[0]
		)

	def test_a_confirmed_line_cannot_grow_a_quantity_again(self):
		"""Normalisation is not something a save may undo."""
		reservation = self.world.confirmed(nights=2)

		doc = frappe.get_doc("Reservation", reservation)
		doc.rooms[0].rooms = 3

		with self.assertRaises(HospitalityPMSError):
			doc.save(ignore_permissions=True)

		frappe.db.rollback()

	def test_a_confirmed_booking_cannot_grow_a_room_line(self):
		"""Adding a row is selling a room without asking availability."""
		reservation = self.world.confirmed(nights=2)

		doc = frappe.get_doc("Reservation", reservation)
		doc.append(
			"rooms",
			{
				"room_type": self.world.room_type,
				"rooms": 1,
				"adults": 1,
				"arrival_date": self.world.business_date,
				"departure_date": self.world.day(2),
			},
		)

		with self.assertRaises(HospitalityPMSError):
			doc.save(ignore_permissions=True)

		frappe.db.rollback()

	def test_a_draft_booking_is_still_freely_editable(self):
		"""Nothing is taken away from making a booking."""
		draft = self.world.reservation(nights=2)

		doc = frappe.get_doc("Reservation", draft)
		doc.rooms[0].departure_date = self.world.day(4)
		doc.rooms[0].rooms = 2
		doc.save(ignore_permissions=True)

		line = self._line(draft)
		self.assertEqual(getdate(line["departure_date"]), self.world.day(4))
		self.assertEqual(line["rooms"], 2)

	def test_an_unrelated_field_is_still_editable_when_confirmed(self):
		reservation = self.world.confirmed(nights=2)

		doc = frappe.get_doc("Reservation", reservation)
		doc.rooms[0].special_requests = "High floor, away from the lift."
		doc.save(ignore_permissions=True)

		self.assertIn(
			"High floor",
			frappe.db.get_value("Reservation Room", self._line(reservation)["name"], "special_requests"),
		)
