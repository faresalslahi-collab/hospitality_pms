"""The Guest 360 workspace is an aggregate, and aggregates leak.

`api/guest_workspace.py` assembles a guest's profile, papers, standing, stays,
bookings and folios into one payload. Every one of those comes from a different
DocType with a different reader set, and the failure this suite exists to catch is
the one 16.7.1 shipped: gate on the endpoint's own DocType, then join freely.

Real users with real roles and real User Permissions, never a mocked session. A
role matrix is only worth what a session actually receives, and the two defects
this product has already had in this area were both invisible to anything that
asked the permission system politely instead of calling the endpoint.

The rule under test, stated once: **an uncleared caller gets no key.** Not `False`,
not `0`, not `[]`, not `None` - because each of those is a claim about the guest,
and "this guest has no passport on file" is a different sentence from "you may not
see this guest's passport". The two must never be confused, in either direction:
a *cleared* caller still receives the field, including when its value is falsy.
"""

import frappe
from frappe.tests import IntegrationTestCase

from hospitality_pms.api import corporate as corporate_api
from hospitality_pms.api import guest_workspace as workspace
from hospitality_pms.api import guests as guests_api
from hospitality_pms.services import reservations as reservation_service
from hospitality_pms.services.exceptions import PermissionDeniedError
from hospitality_pms.tests.fixtures import Fixtures

#: Kept recognisable so a leak shows up as this sentence in a failure message
#: rather than as a wrong boolean buried in a payload.
BLACKLIST_REASON = "CONFIDENTIAL: barred after an incident, police report QA-2026-903"

#: A passport number that must never reach a caller without permlevel 1.
ID_NUMBER = "QA-PASSPORT-4417789"

#: Either exception is a correct refusal. Which one fires depends on whether the
#: User Permission or the property resolution catches it first, and pinning that
#: would be testing Frappe's internals rather than this module's decision.
REFUSALS = (frappe.PermissionError, PermissionDeniedError)


class GuestWorkspaceMatrix(IntegrationTestCase):
	"""One guest, two properties, and a user per interesting clearance."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()

		cls.fixtures = Fixtures("GW36")

		cls.property = cls.fixtures.property("GA", require_id_at_check_in=0)
		cls.room_type = cls.fixtures.room_type(cls.property)
		cls.rooms = cls.fixtures.rooms(cls.property, cls.room_type, count=4)
		cls.rate_plan = cls.fixtures.rate_plan(cls.property, cls.room_type)

		# A second property, so "scoped to what the caller may see" is a claim
		# with something to exclude rather than a no-op.
		cls.other_property = cls.fixtures.property("GB", require_id_at_check_in=0)
		cls.other_room_type = cls.fixtures.room_type(cls.other_property)
		cls.other_rooms = cls.fixtures.rooms(cls.other_property, cls.other_room_type, count=2)
		cls.other_rate_plan = cls.fixtures.rate_plan(cls.other_property, cls.other_room_type)

		cls.guest = cls.fixtures.guest(
			"Traveller",
			identifications=[
				{
					"id_type": "Passport",
					"id_number": ID_NUMBER,
					"issuing_country": "United Arab Emirates",
					"is_primary": 1,
				}
			],
			preferences=[
				{"preference_category": "Room", "preference": "High floor, away from the lift"}
			],
			alerts=[
				{
					"alert_type": "Allergy",
					"severity": "Critical",
					"alert": "Severe shellfish allergy",
					"is_active": 1,
				}
			],
		)

		# A stay in each property, so cross-property scoping has both sides.
		cls.stay = cls._stay_in(cls.property, cls.room_type, cls.rate_plan, cls.rooms[0])
		cls.other_stay = cls._stay_in(
			cls.other_property, cls.other_room_type, cls.other_rate_plan, cls.other_rooms[0]
		)

		# Blacklisted after the stays: `assert_not_blacklisted` refuses a check-in
		# for a blacklisted guest, so the flag goes on through the audited path.
		cls._blacklist()

		# The clearances that matter, each named for what it may NOT do.
		cls.desk = cls.fixtures.user(
			"gw-fo", ["Front Office Agent"], properties=[cls.property]
		)
		cls.reservationist = cls.fixtures.user(
			"gw-res", ["Reservation Agent"], properties=[cls.property]
		)
		cls.finance = cls.fixtures.user(
			"gw-fin", ["Finance Manager"], properties=[cls.property]
		)
		cls.housekeeper = cls.fixtures.user(
			"gw-hk", ["Housekeeping Manager"], properties=[cls.property]
		)
		cls.auditor = cls.fixtures.user(
			"gw-aud", ["Read-Only Auditor"], properties=[cls.property]
		)
		cls.manager = cls.fixtures.user(
			"gw-mgr", ["Hotel Manager"], properties=[cls.property]
		)

		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		cls.fixtures.teardown()
		super().tearDownClass()

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	@classmethod
	def _stay_in(cls, property_name, room_type, rate_plan, room):
		reservation = cls.fixtures.reservation(
			property_name, room_type, cls.guest, rate_plan=rate_plan, nights=2
		)
		reservation_service.confirm(reservation)

		line = frappe.get_all(
			"Reservation Room", filters={"parent": reservation}, pluck="name"
		)[0]
		reservation_service.assign_room(reservation, line, room)

		from hospitality_pms.services import stays as stay_service

		stay_service.check_in(reservation, line, room)
		frappe.db.commit()

		return frappe.db.get_value("Stay", {"reservation_room_line": line}, "name")

	@classmethod
	def _blacklist(cls):
		doc = frappe.get_doc("Guest", cls.guest)
		doc.is_blacklisted = 1
		doc.blacklist_reason = BLACKLIST_REASON
		doc.save(ignore_permissions=True)
		frappe.db.commit()

	def _workspace(self, user):
		frappe.set_user(user)
		return workspace.get_workspace(self.guest)


class TestWorkspaceFieldGroupPermissions(GuestWorkspaceMatrix):
	def test_the_matrix_premise_holds(self):
		"""The control. Without this, every absence below could be an outage.

		Each role must genuinely hold the permission its other assertions assume,
		or a payload missing a key proves nothing at all.
		"""
		frappe.set_user(self.reservationist)
		self.assertTrue(frappe.has_permission("Guest", "read"))
		self.assertNotIn(1, frappe.get_meta("Guest").get_permlevel_access("read"))

		frappe.set_user(self.finance)
		self.assertTrue(frappe.has_permission("Guest", "read"))
		self.assertNotIn(2, frappe.get_meta("Guest").get_permlevel_access("read"))

		frappe.set_user(self.housekeeper)
		self.assertFalse(frappe.has_permission("Guest", "read"))
		self.assertTrue(frappe.has_permission("Stay", "read"))

	def test_guest_workspace_does_not_leak_identity_fields(self):
		"""Reservation Agent reads Guest and holds no permlevel 1."""
		payload = self._workspace(self.reservationist)

		self.assertNotIn(
			"identifications",
			payload,
			msg="identification rows reached a caller without permlevel 1",
		)
		self.assertFalse(payload["disclosure"]["identity"])
		self.assertNotIn(ID_NUMBER, frappe.as_json(payload))

		# The profile itself still arrived: this is a redaction, not a refusal.
		self.assertEqual(payload["guest"]["name"], self.guest)

	def test_authorised_reader_still_receives_identity_fields(self):
		"""The other half of the rule: clearance means the field arrives."""
		payload = self._workspace(self.desk)

		self.assertIn("identifications", payload)
		self.assertTrue(payload["disclosure"]["identity"])
		self.assertEqual(payload["identifications"][0]["id_number"], ID_NUMBER)

		# And never the image URL, whatever the permlevel: a file is authorised
		# against its attached-to document at permlevel 0, so the URL is a wider
		# grant than the row carrying it (16.7.3, deferred document security).
		self.assertNotIn("id_image", payload["identifications"][0])

	def test_guest_workspace_does_not_leak_blacklist_to_unauthorized_role(self):
		"""Finance Manager reads Guest and holds no permlevel 2."""
		payload = self._workspace(self.finance)

		self.assertNotIn(
			"is_blacklisted",
			payload["standing"],
			msg="the blacklist flag reached a caller without permlevel 2",
		)
		self.assertFalse(payload["disclosure"]["blacklist"])

		# Absence, not falsity. `False` is a claim about the guest, and here it
		# would also be untrue.
		self.assertNotIn("blacklist_reason", payload["standing"])
		self.assertNotIn(BLACKLIST_REASON, frappe.as_json(payload))

	def test_the_blacklist_reason_is_narrower_than_the_flag(self):
		"""Eleven roles may know; six may know why. The desk is not among them."""
		payload = self._workspace(self.desk)

		self.assertTrue(payload["disclosure"]["blacklist"])
		self.assertIs(payload["standing"]["is_blacklisted"], True)

		self.assertFalse(payload["disclosure"]["blacklist_reason"])
		self.assertNotIn("blacklist_reason", payload["standing"])
		self.assertNotIn(BLACKLIST_REASON, frappe.as_json(payload))

	def test_a_reason_reader_receives_the_reason(self):
		"""Read-Only Auditor holds permlevel 3, and the control proves it."""
		payload = self._workspace(self.auditor)

		self.assertTrue(payload["disclosure"]["blacklist_reason"])
		self.assertEqual(payload["standing"]["blacklist_reason"], BLACKLIST_REASON)

	def test_guest_workspace_refuses_a_caller_who_cannot_read_guest(self):
		"""Housekeeping reads Stay and Reservation, and no Guest at all."""
		frappe.set_user(self.housekeeper)

		with self.assertRaises(REFUSALS):
			workspace.get_workspace(self.guest)

	def test_alerts_and_care_travel_with_guest_read(self):
		"""Permlevel 0 means unprivileged among Guest readers, not public."""
		payload = self._workspace(self.desk)

		self.assertEqual(payload["alerts"][0]["alert"], "Severe shellfish allergy")
		self.assertEqual(payload["preferences"][0]["preference_category"], "Room")
		self.assertIn("dietary_requirements", payload["care"])


class TestWorkspaceHistoryAuthorisation(GuestWorkspaceMatrix):
	def test_guest_workspace_does_not_leak_stay_history_without_guest_read(self):
		"""Stay read is not authority for *whose* stays these are."""
		frappe.set_user(self.housekeeper)

		with self.assertRaises(REFUSALS):
			workspace.get_stays(self.guest)

	def test_guest_workspace_does_not_leak_reservation_history_without_guest_read(self):
		frappe.set_user(self.housekeeper)

		with self.assertRaises(REFUSALS):
			workspace.get_reservations(self.guest)

	def test_guest_workspace_does_not_leak_folio_balance_without_folio_read(self):
		"""The 16.7.1 defect, at its new front door.

		Ten roles read Reservation and Stay without Guest Folio. None of them may
		receive a balance, and the tab is refused rather than emptied.
		"""
		frappe.set_user(self.housekeeper)

		with self.assertRaises(REFUSALS):
			workspace.get_folios(self.guest)

	def test_a_folio_reader_receives_the_folio_history(self):
		"""The control, so the refusal above is a decision and not an outage."""
		frappe.set_user(self.desk)
		payload = workspace.get_folios(self.guest)

		self.assertEqual(payload["guest"], self.guest)
		self.assertIn("folios", payload)

		for row in payload["folios"]:
			self.assertIn("balance", row)
			self.assertIn("currency", row)

	def test_no_posting_or_reconciliation_state_reaches_the_folio_tab(self):
		"""16.7.5 owns the financial actions; this is read-only context."""
		frappe.set_user(self.desk)
		payload = workspace.get_folios(self.guest)

		forbidden = ("posting_status", "erp_document", "account_head", "reconciled")

		for row in payload["folios"]:
			for key in forbidden:
				self.assertNotIn(key, row)


class TestWorkspaceCrossProperty(GuestWorkspaceMatrix):
	"""A guest is estate-wide; their bookings are not.

	The guest record itself carries no property and is deliberately readable
	across the estate - the same person checks into Doha this year and Dubai
	next, and hiding them from the desk about to check them in is the one thing
	search must never do. Everything *owned by a property* is scoped.
	"""

	def test_cross_property_stay_history_is_refused(self):
		frappe.set_user(self.desk)
		rows = workspace.get_stays(self.guest)["stays"]

		self.assertTrue(rows, msg="the fixture premise is wrong: no stays are visible")

		for row in rows:
			self.assertEqual(row["property"], self.property)

		self.assertNotIn(
			self.other_property,
			{row["property"] for row in rows},
			msg="another property's stay reached a caller restricted away from it",
		)

	def test_cross_property_reservation_history_is_refused(self):
		frappe.set_user(self.desk)
		rows = workspace.get_reservations(self.guest)["reservations"]

		self.assertTrue(rows, msg="the fixture premise is wrong: no reservations are visible")

		for row in rows:
			self.assertEqual(row["property"], self.property)

	def test_cross_property_folio_history_is_refused(self):
		frappe.set_user(self.desk)

		for row in workspace.get_folios(self.guest)["folios"]:
			self.assertEqual(row["property"], self.property)

	def test_stay_statistics_count_only_permitted_properties(self):
		"""The derived figure must agree with the table printed beneath it."""
		frappe.set_user(self.desk)
		payload = workspace.get_workspace(self.guest)

		visible = workspace.get_stays(self.guest)["stays"]

		self.assertEqual(payload["stay_statistics"]["total_stays"], len(visible))
		self.assertGreaterEqual(payload["stay_statistics"]["total_stays"], 1)

	def test_stay_statistics_are_derived_and_not_the_dead_columns(self):
		"""`Guest.total_stays` is never written and is permanently zero."""
		self.assertEqual(frappe.db.get_value("Guest", self.guest, "total_stays"), 0)

		frappe.set_user(self.desk)
		payload = workspace.get_workspace(self.guest)

		self.assertGreater(
			payload["stay_statistics"]["total_stays"],
			0,
			msg="the workspace published the dead column instead of deriving the figure",
		)
		self.assertNotIn("total_stays", payload["guest"])


class TestWorkspacePagination(GuestWorkspaceMatrix):
	def test_a_page_is_bounded_server_side(self):
		frappe.set_user(self.desk)
		payload = workspace.get_stays(self.guest, limit=5000)

		self.assertLessEqual(len(payload["stays"]), workspace.MAX_PAGE_LENGTH)

	def test_the_page_contract_matches_the_rest_of_the_app(self):
		"""`limit`/`start` and `has_more`, never `page`/`offset`/`total`."""
		frappe.set_user(self.desk)
		payload = workspace.get_stays(self.guest, limit=1, start=0)

		self.assertIn("has_more", payload)
		self.assertNotIn("total", payload)
		self.assertLessEqual(len(payload["stays"]), 1)

	def test_a_negative_start_does_not_walk_backwards(self):
		frappe.set_user(self.desk)
		payload = workspace.get_stays(self.guest, start=-10)

		self.assertIn("stays", payload)

	def test_a_negative_limit_does_not_fault_the_query(self):
		"""`LIMIT -1` is a MariaDB syntax error, not an empty page.

		No row is disclosed by it, but a client-supplied parameter should not be
		able to answer a read-only endpoint with a 500.
		"""
		frappe.set_user(self.desk)

		for endpoint in (workspace.get_stays, workspace.get_reservations, workspace.get_folios):
			with self.subTest(endpoint=endpoint.__name__):
				self.assertIsInstance(endpoint(self.guest, limit=-1), dict)

		self.assertIsInstance(guests_api.search_guests(query="Traveller", limit=-1), list)


class TestGuestSearchIsMinimal(GuestWorkspaceMatrix):
	def test_guest_search_result_is_minimal(self):
		"""Identifiers and standing. Nothing that belongs to another DocType."""
		frappe.set_user(self.desk)
		rows = guests_api.search_guests(query="Traveller")

		self.assertTrue(rows, msg="the fixture premise is wrong: the guest is not findable")

		self.assertEqual(set(rows[0].keys()), set(guests_api.SEARCH_FIELDS))

		for absent in ("total_stays", "last_stay_on", "nationality", "guest_type"):
			self.assertNotIn(
				absent,
				rows[0],
				msg=f"{absent} came back from a search gated only on Guest.read",
			)

	def test_search_never_carries_the_blacklist_in_any_form(self):
		frappe.set_user(self.desk)
		rows = guests_api.search_guests(query="Traveller")

		serialised = frappe.as_json(rows)

		for field in ("is_blacklisted", "blacklist_reason", "blacklisted_by", "blacklisted_on"):
			self.assertNotIn(field, serialised)

		self.assertNotIn(BLACKLIST_REASON, serialised)
		self.assertNotIn(ID_NUMBER, serialised)

	def test_a_blacklisted_guest_is_still_findable(self):
		"""Removing the row is a conclusive one-bit disclosure, not a redaction."""
		frappe.set_user(self.finance)
		rows = guests_api.search_guests(query="Traveller")

		self.assertTrue(
			[row for row in rows if row["name"] == self.guest],
			msg="a blacklisted guest vanished from search, which discloses the flag",
		)

	def test_a_one_character_query_does_not_scan_the_estate(self):
		frappe.set_user(self.desk)

		self.assertEqual(guests_api.search_guests(query="T"), [])

	def test_the_result_count_is_bounded(self):
		frappe.set_user(self.desk)
		rows = guests_api.search_guests(query="a", limit=5000)

		self.assertLessEqual(len(rows), guests_api.MAX_SEARCH_LIMIT)


class TestMergeAuthorisation(GuestWorkspaceMatrix):
	def test_merge_is_refused_to_the_front_desk(self):
		"""A merge repoints reservation, stay and folio history. Manager only."""
		duplicate = self.fixtures.guest("Duplicate")
		frappe.db.commit()

		frappe.set_user(self.desk)

		with self.assertRaises(REFUSALS):
			guests_api.merge(duplicate, self.guest, "Same person, two records")

	def test_the_workspace_tells_the_desk_it_may_not_merge(self):
		payload = self._workspace(self.desk)

		self.assertFalse(payload["disclosure"]["merge"])

	def test_the_workspace_tells_a_manager_it_may_merge(self):
		payload = self._workspace(self.manager)

		self.assertTrue(payload["disclosure"]["merge"])

	def test_a_guest_cannot_be_merged_into_itself(self):
		frappe.set_user(self.manager)

		with self.assertRaises(Exception):
			guests_api.merge(self.guest, self.guest, "Nonsense")

	def test_a_merge_requires_a_reason(self):
		duplicate = self.fixtures.guest("Duplicate2")
		frappe.db.commit()

		frappe.set_user(self.manager)

		with self.assertRaises(Exception):
			guests_api.merge(duplicate, self.guest, "   ")


class TestCorporateCreditAuthorisation(GuestWorkspaceMatrix):
	"""16.7.2 recorded the missing property gate; 16.7.3 closed it.

	Wider than recorded, too: four sibling endpoints took the same client-supplied
	account name behind the same DocType-only check, and one of them is a write.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()

		cls.account = cls.fixtures.corporate_account(cls.property, credit_limit=10000)
		cls.other_account = cls.fixtures.corporate_account(
			cls.other_property, credit_limit=50000
		)
		frappe.db.commit()

	def test_credit_position_requires_property_access(self):
		"""The control: the caller's own property still answers."""
		frappe.set_user(self.desk)
		position = corporate_api.get_credit_position(self.account)

		self.assertEqual(position["account"], self.account)
		self.assertEqual(position["credit_limit"], 10000)

	def test_credit_position_cross_property_refused(self):
		frappe.set_user(self.desk)

		with self.assertRaises(REFUSALS):
			corporate_api.get_credit_position(self.other_account)

	def test_check_credit_cross_property_refused(self):
		frappe.set_user(self.desk)

		with self.assertRaises(REFUSALS):
			corporate_api.check_credit(self.other_account, 100)

	def test_production_report_cross_property_refused(self):
		"""It splats the credit position into its own result."""
		frappe.set_user(self.desk)

		business_date = frappe.db.get_value("Property", self.property, "business_date")

		with self.assertRaises(REFUSALS):
			corporate_api.production_report(
				self.other_account, str(business_date), str(business_date)
			)

	def test_setting_credit_status_cross_property_refused(self):
		"""The worst of the five: a write, reachable estate-wide."""
		frappe.set_user(self.manager)

		with self.assertRaises(REFUSALS):
			corporate_api.set_credit_status(self.other_account, "Suspended", "Not my property")

		self.assertNotEqual(
			frappe.db.get_value("Corporate Account", self.other_account, "credit_status"),
			"Suspended",
		)

	def test_guest_workspace_does_not_leak_corporate_credit(self):
		"""No corporate block on the guest payload at all, for anyone."""
		payload = self._workspace(self.manager)

		serialised = frappe.as_json(payload)

		for field in ("credit_limit", "credit_used", "credit_available", "credit_status"):
			self.assertNotIn(field, serialised)
