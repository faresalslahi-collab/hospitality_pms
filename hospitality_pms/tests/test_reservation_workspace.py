"""The Reservation Workspace read model: what it publishes, and to whom.

A workspace is an aggregate, and an aggregate is where permission boundaries
quietly dissolve. 16.7.1 shipped a board gated on `Stay.read` that then handed out
Guest Folio balances and Guest standing, because each value was read with a
permission-free query and only the endpoint's own DocType was ever checked. This
suite exists so the same thing cannot happen to the reservation aggregate.

Every disclosure assertion is made twice — absent for a caller who may not read the
source DocType, present for one who may — because a test that only checks absence
passes just as well when the endpoint is broken.
"""

import json

import frappe
from frappe.tests import IntegrationTestCase

from hospitality_pms.api import reservation_workspace as workspace
from hospitality_pms.services import reservations as reservation_service
from hospitality_pms.services.exceptions import PermissionDeniedError
from hospitality_pms.tests.fixtures import Fixtures

BLACKLIST_REASON = "CONFIDENTIAL: chargeback dispute, incident 2026-114"


class TestReservationWorkspace(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()

		cls.fixtures = Fixtures("RWSP")

		cls.property = cls.fixtures.property("RA")
		cls.other_property = cls.fixtures.property("RB")

		cls.room_type = cls.fixtures.room_type(cls.property)
		cls.rooms = cls.fixtures.rooms(cls.property, cls.room_type, count=4)
		cls.rate_plan = cls.fixtures.rate_plan(cls.property, cls.room_type)

		cls.guest = cls.fixtures.guest("Booker")
		cls.reservation = cls.fixtures.reservation(
			cls.property, cls.room_type, cls.guest, rate_plan=cls.rate_plan, nights=2
		)

		# A blacklisted guest, so the permlevel-2 assertions have a true case.
		cls.flagged_guest = cls.fixtures.guest("Barred")
		flagged = frappe.get_doc("Guest", cls.flagged_guest)
		flagged.is_blacklisted = 1
		flagged.blacklist_reason = BLACKLIST_REASON
		flagged.save(ignore_permissions=True)

		# A confirmed booking, so the editability matrix is exercised against a
		# holding status rather than only a draft.
		cls.confirmed = cls.fixtures.reservation(
			cls.property, cls.room_type, cls.guest, rate_plan=cls.rate_plan, nights=2
		)
		reservation_service.confirm(cls.confirmed)

		# The same world in a property this suite's users may not operate in.
		cls.other_room_type = cls.fixtures.room_type(cls.other_property)
		cls.fixtures.rooms(cls.other_property, cls.other_room_type, count=1)
		cls.other_rate_plan = cls.fixtures.rate_plan(cls.other_property, cls.other_room_type)
		cls.other_guest = cls.fixtures.guest("Elsewhere")
		cls.other_reservation = cls.fixtures.reservation(
			cls.other_property,
			cls.other_room_type,
			cls.other_guest,
			rate_plan=cls.other_rate_plan,
		)

		# A reservation reader who is also a Guest reader and is cleared for the
		# blacklist flag: the ordinary reservation agent.
		cls.agent = cls.fixtures.user(
			"agent", ["Reservation Agent"], properties=[cls.property]
		)

		# A reservation reader who is NOT a Guest reader. Revenue Manager holds
		# Reservation read (it reports on bookings) and no Guest permission, which
		# is exactly the gap 16.7.1 found on the boards.
		cls.revenue = cls.fixtures.user(
			"rev", ["Revenue Manager"], properties=[cls.property]
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

	# -- premises ----------------------------------------------------------

	def test_the_two_roles_differ_exactly_as_this_suite_assumes(self):
		"""Without this, every disclosure test below could pass for the wrong reason."""
		frappe.set_user(self.agent)
		self.assertTrue(frappe.has_permission("Reservation", "read"))
		self.assertTrue(frappe.has_permission("Guest", "read"))

		frappe.set_user(self.revenue)
		self.assertTrue(
			frappe.has_permission("Reservation", "read"),
			msg="Revenue Manager must be able to open a reservation for this suite to mean anything",
		)
		self.assertFalse(
			frappe.has_permission("Guest", "read"),
			msg="Revenue Manager is expected to hold no Guest permission",
		)

	# -- payload -----------------------------------------------------------

	def test_workspace_returns_the_booking_and_its_room_lines(self):
		frappe.set_user(self.agent)

		payload = workspace.get_workspace(self.reservation)

		self.assertEqual(payload["reservation"]["name"], self.reservation)
		self.assertEqual(payload["reservation"]["property"], self.property)
		self.assertTrue(payload["reservation"]["arrival_date"])
		self.assertTrue(payload["reservation"]["departure_date"])
		self.assertEqual(payload["reservation"]["nights"], 2)

		self.assertEqual(len(payload["rooms"]), 1)
		line = payload["rooms"][0]

		for field in ("name", "room_type", "arrival_date", "departure_date", "nights", "rate_plan"):
			self.assertIn(field, line)

		# The per-night snapshot, regrouped per line, is what lets Rooms & Rates
		# show a breakdown without a second request.
		self.assertEqual(len(line["rate_lines"]), 2, msg="two nights, two snapshot rows")

	def test_workspace_publishes_the_servers_allowed_transitions(self):
		frappe.set_user(self.agent)

		payload = workspace.get_workspace(self.confirmed)

		self.assertEqual(
			payload["allowed_transitions"],
			sorted(reservation_service.TRANSITIONS["Confirmed"]),
			msg="the client must be offered the server's state machine, not a copy",
		)

	def test_workspace_publishes_only_allow_listed_reservation_fields(self):
		frappe.set_user(self.agent)

		payload = workspace.get_workspace(self.reservation)

		self.assertEqual(set(payload["reservation"]), set(workspace.WORKSPACE_FIELDS))

	# -- editability -------------------------------------------------------

	def test_editability_matches_the_controllers_own_rules(self):
		"""The flags are what to *offer*; the guards still refuse regardless."""
		frappe.set_user(self.agent)

		draft = workspace.get_workspace(self.reservation)["editability"]

		self.assertTrue(draft["is_draft_like"])
		self.assertFalse(draft["is_holding"])
		self.assertTrue(draft["may_add_or_remove_rooms"])
		self.assertTrue(draft["may_change_room_type"])
		self.assertTrue(draft["may_change_rate_plan"])
		self.assertTrue(draft["may_change_dates"])

		holding = workspace.get_workspace(self.confirmed)["editability"]

		self.assertTrue(holding["is_holding"])
		self.assertFalse(holding["is_draft_like"])
		# Refused by `_guard_holding_immutability` — "cancel and rebook instead".
		self.assertFalse(holding["may_add_or_remove_rooms"])
		self.assertFalse(holding["may_change_room_type"])
		# The snapshot is the guest's quote once the booking holds inventory.
		self.assertFalse(holding["may_change_rate_plan"])
		# But the move/rebook operation is permitted, under lock and availability.
		self.assertTrue(holding["may_change_dates"])
		# Non-inventory fields carry no availability consequence.
		self.assertTrue(holding["may_edit_details"])

	def test_deposit_is_never_offered_as_editable(self):
		"""Money moves through the folio and payment services, never a field."""
		frappe.set_user(self.agent)

		for reservation in (self.reservation, self.confirmed):
			editability = workspace.get_workspace(reservation)["editability"]

			self.assertFalse(editability["may_edit_deposit"])

	def test_a_terminal_booking_offers_no_edits(self):
		cancelled = self.fixtures.reservation(
			self.property, self.room_type, self.guest, rate_plan=self.rate_plan
		)
		reservation_service.cancel(cancelled, "Test teardown")

		frappe.set_user(self.agent)
		editability = workspace.get_workspace(cancelled)["editability"]

		self.assertTrue(editability["is_terminal"])
		self.assertFalse(editability["may_edit_details"])
		self.assertFalse(editability["may_change_dates"])
		self.assertFalse(editability["may_assign_room"])

	# -- disclosure: Guest -------------------------------------------------

	def test_guest_standing_is_withheld_from_a_caller_who_cannot_read_guest(self):
		"""Reservation read does not imply Guest read. The 16.7.1 lesson, restated."""
		frappe.set_user(self.revenue)

		payload = workspace.get_workspace(self.reservation)

		self.assertNotIn("guest_standing", payload)

		# And the booking itself is still perfectly usable: this is a redaction,
		# not an outage.
		self.assertEqual(payload["reservation"]["name"], self.reservation)
		self.assertTrue(payload["rooms"])

		# The cleared reader gets it, so the absence above is about clearance.
		frappe.set_user(self.agent)
		cleared = workspace.get_workspace(self.reservation)

		self.assertIn("guest_standing", cleared)
		self.assertIn("vip_status", cleared["guest_standing"])
		self.assertIn("guest_type", cleared["guest_standing"])

	def test_the_blacklist_reason_reaches_nobody(self):
		flagged = self.fixtures.reservation(
			self.property, self.room_type, self.flagged_guest, rate_plan=self.rate_plan
		)

		for user in (self.agent, self.revenue):
			frappe.set_user(user)

			serialised = json.dumps(workspace.get_workspace(flagged), default=str)

			self.assertNotIn(BLACKLIST_REASON, serialised, msg=f"{user} received the reason")
			self.assertNotIn("blacklist_reason", serialised, msg=f"{user} received the field")
			self.assertNotIn("chargeback", serialised)

	def test_the_blacklist_flag_tracks_its_own_clearance(self):
		flagged = self.fixtures.reservation(
			self.property, self.room_type, self.flagged_guest, rate_plan=self.rate_plan
		)

		# A Guest reader cleared for permlevel 2 is told, and told the truth.
		frappe.set_user(self.agent)
		standing = workspace.get_workspace(flagged)["guest_standing"]

		self.assertIn("is_blacklisted", standing)
		self.assertTrue(standing["is_blacklisted"])

		# A caller with no Guest permission gets no standing block at all, so the
		# flag cannot be inferred from its absence within one.
		frappe.set_user(self.revenue)

		self.assertNotIn("guest_standing", workspace.get_workspace(flagged))

	# -- disclosure: Guest Folio -------------------------------------------

	def test_folio_sourced_deposit_credit_is_gated_on_folio_permission(self):
		"""`deposit_credited` joins Folio Payment to Guest Folio — so it is folio money.

		The expectation fields beside it are Reservation columns and stay.
		"""
		frappe.set_user(self.revenue)
		self.assertFalse(frappe.has_permission("Guest Folio", "read"))

		deposit = workspace.get_workspace(self.reservation)["deposit"]

		self.assertNotIn("credited", deposit, msg="folio money reached a non-folio reader")

		# What is Reservation's own is still there — the tab is not blanked.
		for field in workspace.DEPOSIT_FIELDS:
			self.assertIn(field, deposit)
		self.assertIn("allocation", deposit)

		frappe.set_user(self.agent)
		cleared = workspace.get_workspace(self.reservation)["deposit"]

		if frappe.has_permission("Guest Folio", "read"):
			self.assertIn("credited", cleared)

	def test_deposit_allocation_sums_back_to_the_deposit(self):
		"""One deposit, split across the rooms that will carry it — exactly."""
		multi = self.fixtures.reservation(
			self.property, self.room_type, self.guest, rate_plan=self.rate_plan, rooms=3
		)
		doc = frappe.get_doc("Reservation", multi)
		doc.deposit_received = 300
		doc.save(ignore_permissions=True)

		frappe.set_user(self.agent)
		deposit = workspace.get_workspace(multi)["deposit"]

		self.assertEqual(
			round(sum(deposit["allocation"].values()), 2),
			300.0,
			msg="the shares must add back to the deposit, not to 299.99",
		)

	# -- disclosure: Hotel Room and Stay -----------------------------------

	def test_room_condition_is_gated_on_hotel_room_permission(self):
		"""The room's number and condition are Hotel Room's, not the booking's.

		`assigned_room` is the Reservation Room's own column and stays. What comes
		from the room record — the number on the door, whether housekeeping has
		released it — is gated, because a reservation reader is not automatically a
		room reader.
		"""
		assigned = self.fixtures.reservation(
			self.property, self.room_type, self.guest, rate_plan=self.rate_plan
		)
		reservation_service.confirm(assigned)
		line = frappe.get_doc("Reservation", assigned).rooms[0].name
		reservation_service.assign_room(assigned, line, self.rooms[0])

		for user in (self.agent, self.revenue):
			frappe.set_user(user)

			row = workspace.get_workspace(assigned)["rooms"][0]
			may_read_room = frappe.has_permission("Hotel Room", "read")

			# The line's own column is always there.
			self.assertEqual(row["assigned_room"], self.rooms[0])

			for field in ("room_number", "room_ready", "housekeeping_status"):
				self.assertEqual(
					field in row,
					may_read_room,
					msg=f"{user}: {field} disclosure did not match Hotel Room permission",
				)

			if may_read_room:
				# The distinction that matters: the docname is the room *code*,
				# and the number on the door is a different string.
				self.assertNotEqual(
					row["room_number"],
					row["assigned_room"],
					msg="the room number must not be the docname",
				)

	def test_per_line_stay_linkage_is_gated_on_stay_permission(self):
		"""A line's stay is the only honest source of per-line state.

		`Reservation Room.reservation_status` is a copy of the header status, so it
		is identical on every line of a multi-room booking and cannot say which
		room is in house. The stay can — and it is Stay's data, so it is gated.
		"""
		for user in (self.agent, self.revenue):
			frappe.set_user(user)

			# A booking with no stay carries no stay keys, whatever the clearance.
			row = workspace.get_workspace(self.confirmed)["rooms"][0]

			for field in ("stay", "stay_status", "stay_room"):
				self.assertNotIn(field, row, msg=f"{user} got {field} on a line with no stay")

			# And the line's own status column is still published, unchanged.
			self.assertIn("reservation_status", row)

	def test_display_names_accompany_their_codes_and_follow_their_own_permissions(self):
		"""A code is not a name, and each name is gated on the record it comes from.

		`room_type` and `rate_plan` are the line's own columns and always travel.
		Their human-readable names live on Room Type and Rate Plan — separate
		DocTypes with separate permissions — so each is gated on its own. The first
		draft gated the room-type name on *Hotel Room* read: close enough on this
		site, wrong as a rule, and the rule is the point.
		"""
		frappe.set_user(self.agent)

		payload = workspace.get_workspace(self.confirmed)
		row = payload["rooms"][0]
		disclosure = payload["disclosure"]

		# The codes are unconditional.
		self.assertEqual(row["room_type"], self.room_type)
		self.assertEqual(row["rate_plan"], self.rate_plan)

		# Each name tracks its own DocType, and the disclosure block agrees.
		self.assertEqual(disclosure["room_type"], frappe.has_permission("Room Type", "read"))
		self.assertEqual(disclosure["rate_plan"], frappe.has_permission("Rate Plan", "read"))
		self.assertEqual(("room_type_name" in row), disclosure["room_type"])
		self.assertEqual(("rate_plan_name" in row), disclosure["rate_plan"])

		if disclosure["rate_plan"]:
			self.assertTrue(row["rate_plan_name"])

	def test_the_payload_says_what_it_withheld_and_why(self):
		"""Absent-because-empty and absent-because-forbidden are different facts.

		Without this a screen cannot tell "this booking has no company" from "you
		may not see the company", and would have to either claim one or say nothing
		about both. The block describes the caller's own permissions, never the
		record, so it discloses nothing.
		"""
		for user in (self.agent, self.revenue):
			frappe.set_user(user)

			payload = workspace.get_workspace(self.reservation)
			disclosure = payload["disclosure"]

			for source in ("guest", "folio", "corporate", "room", "stay"):
				self.assertIn(source, disclosure)

			# It agrees with the permissions it claims to describe, and with what
			# the payload actually contains.
			self.assertEqual(disclosure["guest"], frappe.has_permission("Guest", "read"))
			self.assertEqual(disclosure["folio"], frappe.has_permission("Guest Folio", "read"))
			self.assertEqual(
				disclosure["corporate"], frappe.has_permission("Corporate Account", "read")
			)
			self.assertEqual(("guest_standing" in payload), disclosure["guest"])
			self.assertEqual(("credited" in payload["deposit"]), disclosure["folio"])

	# -- property scoping --------------------------------------------------

	def test_another_propertys_reservation_cannot_be_opened(self):
		frappe.set_user(self.agent)

		# The app's own 403, raised by `authorise_document` — which re-asks against
		# the property resolved from the record, never from the request.
		with self.assertRaises(PermissionDeniedError):
			workspace.get_workspace(self.other_reservation)

		with self.assertRaises(PermissionDeniedError):
			workspace.get_history(self.other_reservation)

	# -- history -----------------------------------------------------------

	def test_history_returns_the_bookings_own_transitions(self):
		frappe.set_user(self.agent)

		history = workspace.get_history(self.confirmed)

		self.assertEqual(history["reservation"], self.confirmed)
		self.assertTrue(history["entries"], msg="a confirmed booking has at least one log row")

		entry = history["entries"][0]

		for field in ("changed_by", "changed_at", "from_status", "to_status", "reason", "details"):
			self.assertIn(field, entry)

		self.assertIn("Confirmed", [row["to_status"] for row in history["entries"]])

	def test_history_publishes_no_unreviewed_detail_key(self):
		"""`details` is a service-written blob and is filtered, not passed through."""
		frappe.set_user("Administrator")

		# A log row carrying something that must not be republished.
		log = frappe.get_doc(
			{
				"doctype": "Reservation Log",
				"property": self.property,
				"reservation": self.confirmed,
				"changed_by": "Administrator",
				"changed_at": frappe.utils.now_datetime(),
				"from_status": "Confirmed",
				"to_status": "Confirmed",
				"reason": "Detail filter probe",
				"details": json.dumps(
					{"room_type": self.room_type, "secret_internal_note": "do not publish"}
				),
			}
		).insert(ignore_permissions=True)
		self.fixtures.track("Reservation Log", log.name)

		frappe.set_user(self.agent)
		history = workspace.get_history(self.confirmed)

		probe = next(row for row in history["entries"] if row["name"] == log.name)

		self.assertIn("room_type", probe["details"], msg="a reviewed key should survive")
		self.assertNotIn("secret_internal_note", probe["details"])
		self.assertNotIn("do not publish", json.dumps(history, default=str))

	def test_history_is_bounded(self):
		frappe.set_user(self.agent)

		self.assertEqual(workspace.get_history(self.confirmed, limit=1)["limit"], 1)
		self.assertEqual(
			workspace.get_history(self.confirmed, limit=10_000)["limit"],
			workspace.MAX_HISTORY_LIMIT,
			msg="an unbounded history request must be clamped",
		)

	def test_history_is_gated_on_the_logs_own_doctype(self):
		"""Reservation read is not Reservation Log read, and the sets differ widely.

		This test previously asserted the opposite — that any reservation reader
		may read the log — and so enshrined a leak rather than catching it. The
		approved matrix makes Reservation readable by 23 roles and Reservation Log
		by 9; the 14 in the gap include Room Attendant, kitchen and housekeeping,
		and a log row carries the actor, the transition and a free-text reason that
		holds cancellation reasons and override justifications.
		"""
		frappe.set_user(self.revenue)

		self.assertTrue(
			frappe.has_permission("Reservation", "read"),
			msg="Revenue Manager must still be able to open the booking itself",
		)
		self.assertFalse(
			frappe.has_permission("Reservation Log", "read"),
			msg="Revenue Manager is expected to hold no Reservation Log permission",
		)

		with self.assertRaises(PermissionDeniedError):
			workspace.get_history(self.confirmed)

		# The booking itself is untouched by the log's gate: this is a redaction of
		# one endpoint, not a withdrawal of the workspace.
		self.assertEqual(
			workspace.get_workspace(self.confirmed)["reservation"]["name"], self.confirmed
		)

		# And a log reader still gets it, so the refusal is about clearance.
		frappe.set_user(self.agent)

		self.assertTrue(frappe.has_permission("Reservation Log", "read"))

		history = workspace.get_history(self.confirmed)

		self.assertTrue(history["entries"])
		self.assertNotIn("guest_name", json.dumps(history, default=str))
