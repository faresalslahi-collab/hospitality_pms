"""Operational endpoints must authorise the *document*, not just the DocType.

`require_permission(doctype, "write")` answers "may this user ever complete a
housekeeping task", which every supervisor may, for every property in the estate.
It does not answer "may this user complete *this* task". Four operational modules
asked only the first question and then acted on whatever name arrived - the exact
defect class `services.base.authorise_document` was written to close, and which
`api/reservations.py`, `api/folio.py` and seven other modules already use.

Twenty-one endpoints across housekeeping, guest services, maintenance and kitchen
took a caller-supplied document name behind a DocType-level check alone. The worst
of them reached money: `kitchen.create_order` resolved the caller's property, then
looked up a *caller-supplied stay* with a permission-free read and charged that
stay's folio, so a room service order raised in one property could post onto a
guest's folio in another.

Every test here pairs a refusal with the same call against the caller's own
property. A test that only proves a refusal cannot tell a fix from an outage, and
that is the rule `test_authorization.py` already sets for the financial endpoints.
"""

import frappe
from frappe.tests import IntegrationTestCase

from hospitality_pms.api import guest_services as guest_services_api
from hospitality_pms.api import housekeeping as housekeeping_api
from hospitality_pms.api import kitchen as kitchen_api
from hospitality_pms.api import maintenance as maintenance_api
from hospitality_pms.services import guest_services as guest_services_service
from hospitality_pms.services import guests as guest_service
from hospitality_pms.services import housekeeping as housekeeping_service
from hospitality_pms.services import maintenance as maintenance_service
from hospitality_pms.services.exceptions import PermissionDeniedError
from hospitality_pms.tests.fixtures import Fixtures

#: Either exception is a correct refusal; which fires depends on whether the
#: User Permission or the property resolution catches it first.
REFUSALS = (frappe.PermissionError, PermissionDeniedError)


class TwoPropertyWorld(IntegrationTestCase):
	"""One user, permitted in A, and a full set of records in B to reach for."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()

		cls.fixtures = Fixtures("OPAUTH")

		cls.property_a = cls.fixtures.property("OA", require_id_at_check_in=0)
		cls.type_a = cls.fixtures.room_type(cls.property_a)
		cls.rooms_a = cls.fixtures.rooms(cls.property_a, cls.type_a, count=3)

		cls.property_b = cls.fixtures.property("OB", require_id_at_check_in=0)
		cls.type_b = cls.fixtures.room_type(cls.property_b)
		cls.rooms_b = cls.fixtures.rooms(cls.property_b, cls.type_b, count=3)

		# Wide operational roles, restricted to property A by a real User
		# Permission - the mechanism the product actually relies on.
		cls.operator = cls.fixtures.user(
			"op-a",
			[
				"Housekeeping Manager",
				"Maintenance Manager",
				"Front Office Manager",
				"Kitchen Manager",
			],
			properties=[cls.property_a],
		)

		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		cls.fixtures.teardown()
		super().tearDownClass()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		super().tearDown()

	@classmethod
	def _menu_item(cls, property_name, code):
		"""A priced, active menu item so an order can be built at all."""
		name = f"{property_name}-{code}"

		if not frappe.db.exists("Menu Item", name):
			frappe.get_doc(
				{
					"doctype": "Menu Item",
					"menu_item_code": name,
					"menu_item_name": "Club Sandwich",
					"property": property_name,
					"category": "Snack",
					"selling_rate": 45,
					"is_active": 1,
					"is_available_for_room_service": 1,
				}
			).insert(ignore_permissions=True)

		return cls.fixtures.track("Menu Item", name)

	@classmethod
	def _stay_in(cls, property_name, room_type, rate_plan, room):
		"""A guest actually checked in, so the stay has a folio to charge."""
		from hospitality_pms.services import reservations as reservation_service
		from hospitality_pms.services import stays as stay_service

		reservation = cls.fixtures.reservation(
			property_name, room_type, cls.fixtures.guest("Order"), rate_plan=rate_plan, nights=2
		)
		reservation_service.confirm(reservation)

		line = frappe.get_all("Reservation Room", filters={"parent": reservation}, pluck="name")[0]
		reservation_service.assign_room(reservation, line, room)
		stay_service.check_in(reservation, line, room)

		return frappe.db.get_value("Stay", {"reservation_room_line": line}, "name")

	@classmethod
	def _order(cls, property_name, room, menu_item, guest=None):
		"""An order with one priced line, as the controller insists on."""
		return frappe.get_doc(
			{
				"doctype": "Room Service Order",
				"property": property_name,
				"order_status": "Placed",
				"order_type": "Room Service",
				"room": room,
				"guest": guest,
				"lines": [{"menu_item": menu_item, "quantity": 1}],
			}
		).insert(ignore_permissions=True)



class TestHousekeepingAuthorisation(TwoPropertyWorld):
	def _task(self, property_name, room):
		return housekeeping_service.create_task(property_name, room, task_type="Departure Clean")

	def test_the_premise_holds(self):
		"""Control: the operator really does hold the DocType write."""
		frappe.set_user(self.operator)

		self.assertTrue(frappe.has_permission("Housekeeping Task", "write"))

	def test_create_task_authorized(self):
		frappe.set_user(self.operator)

		result = housekeeping_api.create_task(property=self.property_a, room=self.rooms_a[0])

		self.assertEqual(result["task"]["property"], self.property_a)
		self.assertEqual(result["task"]["room"], self.rooms_a[0])

	def test_create_task_cross_property_refused(self):
		"""The property is authorised; the room was not, and is another estate's."""
		frappe.set_user(self.operator)

		with self.assertRaises(REFUSALS) as caught:
			housekeeping_api.create_task(property=self.property_a, room=self.rooms_b[0])

		self.assertIn("another property", str(caught.exception))

	def test_a_task_in_another_property_cannot_be_started(self):
		task = self._task(self.property_b, self.rooms_b[1])
		frappe.db.commit()

		frappe.set_user(self.operator)

		with self.assertRaises(REFUSALS):
			housekeeping_api.start(task)

	def test_a_task_in_the_callers_own_property_still_starts(self):
		"""Paired control, so the refusal above is a decision and not an outage."""
		task = self._task(self.property_a, self.rooms_a[1])
		frappe.db.commit()

		frappe.set_user(self.operator)
		result = housekeeping_api.start(task)

		self.assertEqual(result["task"]["task_status"], "In Progress")

	def test_a_task_in_another_property_cannot_be_assigned_or_flagged(self):
		task = self._task(self.property_b, self.rooms_b[2])
		frappe.db.commit()

		frappe.set_user(self.operator)

		with self.assertRaises(REFUSALS):
			housekeeping_api.assign(task, self.operator)

		with self.assertRaises(REFUSALS):
			housekeeping_api.set_do_not_disturb(task, refused=0)

	def test_room_state_moves_only_through_the_service(self):
		"""The room's dimension follows the task, and nothing else writes it."""
		task = self._task(self.property_a, self.rooms_a[2])
		frappe.db.commit()

		frappe.set_user(self.operator)
		housekeeping_api.start(task)

		self.assertEqual(
			frappe.db.get_value("Hotel Room", self.rooms_a[2], "housekeeping_status"),
			"In Progress",
		)


class TestGuestServicesAuthorisation(TwoPropertyWorld):
	def _request(self, property_name):
		return guest_services_service.create_request(
			property_name,
			subject="Towels",
			description="Two extra towels",
			category="Housekeeping",
		)

	def test_create_request_authorized(self):
		frappe.set_user(self.operator)

		result = guest_services_api.create_request(
			property=self.property_a,
			subject="Towels",
			description="Two extra towels",
			category="Housekeeping",
		)

		self.assertEqual(result["request"]["property"], self.property_a)

	def test_create_request_cross_property_room_refused(self):
		"""16.7.1 recorded this and it stayed open until 16.7.4.

		The property is authorised, the insert runs `ignore_permissions=True`, so
		nothing checked that the room named alongside it was the same estate's.
		"""
		frappe.set_user(self.operator)

		with self.assertRaises(REFUSALS) as caught:
			guest_services_api.create_request(
				property=self.property_a,
				subject="Towels",
				description="Two extra towels",
				category="Housekeeping",
				room=self.rooms_b[0],
			)

		self.assertIn("another property", str(caught.exception))

	def test_a_request_in_another_property_cannot_be_completed(self):
		request = self._request(self.property_b)
		frappe.db.commit()

		frappe.set_user(self.operator)

		with self.assertRaises(REFUSALS):
			guest_services_api.start(request)

		with self.assertRaises(REFUSALS):
			guest_services_api.complete(request, "Done")

	def test_a_request_in_the_callers_own_property_still_completes(self):
		request = self._request(self.property_a)
		frappe.db.commit()

		frappe.set_user(self.operator)
		guest_services_api.start(request)
		result = guest_services_api.complete(request, "Delivered two towels")

		self.assertEqual(result["request"]["request_status"], "Completed")

	def test_service_recovery_cannot_reach_another_property(self):
		"""The one lifecycle endpoint that can post money to a folio."""
		request = self._request(self.property_b)
		frappe.db.commit()

		frappe.set_user(self.operator)

		with self.assertRaises(REFUSALS):
			guest_services_api.apply_service_recovery(
				request, recovery_type="Apology", reason="Sorry"
			)


class TestMaintenanceAuthorisation(TwoPropertyWorld):
	def _ticket(self, property_name, room):
		return maintenance_service.create_ticket(
			property_name,
			title="Tap dripping",
			description="Bathroom tap drips overnight",
			room=room,
		)

	def test_create_ticket_authorized(self):
		frappe.set_user(self.operator)

		result = maintenance_api.create_ticket(
			property=self.property_a,
			title="Tap dripping",
			description="Bathroom tap drips overnight",
			room=self.rooms_a[0],
		)

		self.assertEqual(result["ticket"]["property"], self.property_a)

	def test_a_ticket_in_another_property_cannot_take_a_room_out_of_service(self):
		"""The most damaging maintenance write: it removes a room from sale."""
		ticket = self._ticket(self.property_b, self.rooms_b[0])
		frappe.db.commit()

		frappe.set_user(self.operator)

		with self.assertRaises(REFUSALS):
			maintenance_api.take_out_of_service(
				ticket, status="Out of Order", reason="Not my property"
			)

		self.assertEqual(
			frappe.db.get_value("Hotel Room", self.rooms_b[0], "maintenance_status"),
			"Operational",
		)

	def test_a_ticket_in_the_callers_own_property_still_blocks_its_room(self):
		ticket = self._ticket(self.property_a, self.rooms_a[0])
		frappe.db.commit()

		frappe.set_user(self.operator)
		maintenance_api.take_out_of_service(
			ticket, status="Out of Order", reason="Flooding in the bathroom"
		)

		self.assertEqual(
			frappe.db.get_value("Hotel Room", self.rooms_a[0], "maintenance_status"),
			"Out of Order",
		)

	def test_a_ticket_in_another_property_cannot_be_started_or_completed(self):
		ticket = self._ticket(self.property_b, self.rooms_b[1])
		frappe.db.commit()

		frappe.set_user(self.operator)

		with self.assertRaises(REFUSALS):
			maintenance_api.start_work(ticket)

		with self.assertRaises(REFUSALS):
			maintenance_api.complete_work(ticket)

	def test_starting_work_still_takes_a_healthy_room_out_of_sale(self):
		"""The 16.6.6 rule (UAT-005), re-pinned from the API layer.

		Workflow status never decides sellability; the room's own maintenance
		dimension does. `start_work` must land on a blocking value, never on
		`Required`, which is deliberately sellable.
		"""
		from hospitality_pms.services import rooms as room_service

		ticket = self._ticket(self.property_a, self.rooms_a[1])
		frappe.db.commit()

		frappe.set_user(self.operator)
		maintenance_api.start_work(ticket)

		self.assertIn(
			frappe.db.get_value("Hotel Room", self.rooms_a[1], "maintenance_status"),
			room_service.BLOCKING_MAINTENANCE,
			msg="a room under active repair was left in a sellable maintenance state",
		)

	def test_starting_work_does_not_downgrade_an_already_blocked_room(self):
		"""The other half of UAT-005: the operator's severity judgement stands."""
		ticket = self._ticket(self.property_a, self.rooms_a[2])
		frappe.db.commit()

		frappe.set_user(self.operator)
		maintenance_api.take_out_of_service(
			ticket, status="Out of Order", reason="Ceiling damage"
		)
		maintenance_api.start_work(ticket)

		self.assertEqual(
			frappe.db.get_value("Hotel Room", self.rooms_a[2], "maintenance_status"),
			"Out of Order",
		)


class TestKitchenAuthorisation(TwoPropertyWorld):
	def test_an_order_cannot_be_raised_against_another_propertys_stay(self):
		"""The build's headline financial fix, exercised for real.

		`create_order` resolved the caller's property and then looked up a
		*caller-supplied* stay with a permission-free read, so `deliver_order`
		would post a Room Service charge onto that stay's folio - a
		cross-property financial write reached through an operational endpoint.

		The line list must be non-empty: the API refuses an empty order before
		the service is entered, so a test that passes `lines=[]` never reaches
		the check it claims to be testing and passes against the unfixed code.
		"""
		rate_plan_b = self.fixtures.rate_plan(self.property_b, self.type_b)
		stay_b = self._stay_in(self.property_b, self.type_b, rate_plan_b, self.rooms_b[1])
		menu_a = self._menu_item(self.property_a, "SNK")
		frappe.db.commit()

		before = frappe.db.count("Room Service Order")

		frappe.set_user(self.operator)

		with self.assertRaises(REFUSALS) as caught:
			kitchen_api.create_order(
				property=self.property_a,
				lines=[{"menu_item": menu_a, "quantity": 1}],
				stay=stay_b,
			)

		self.assertIn("another property", str(caught.exception))

		frappe.set_user("Administrator")
		self.assertEqual(
			frappe.db.count("Room Service Order"),
			before,
			msg="an order was written against another property's stay",
		)

	def test_an_order_in_the_callers_own_property_is_still_accepted(self):
		"""The paired control: the refusal above is a decision, not an outage."""
		rate_plan_a = self.fixtures.rate_plan(self.property_a, self.type_a)
		stay_a = self._stay_in(self.property_a, self.type_a, rate_plan_a, self.rooms_a[1])
		menu_a = self._menu_item(self.property_a, "SNK")
		frappe.db.commit()

		frappe.set_user(self.operator)
		result = kitchen_api.create_order(
			property=self.property_a,
			lines=[{"menu_item": menu_a, "quantity": 1}],
			stay=stay_a,
		)

		self.assertEqual(result["order"]["property"], self.property_a)

	def test_an_order_cannot_be_raised_against_another_propertys_room(self):
		menu_a = self._menu_item(self.property_a, "SNK")
		frappe.db.commit()

		before = frappe.db.count("Room Service Order")

		frappe.set_user(self.operator)

		with self.assertRaises(REFUSALS) as caught:
			kitchen_api.create_order(
				property=self.property_a,
				lines=[{"menu_item": menu_a, "quantity": 1}],
				room=self.rooms_b[0],
			)

		self.assertIn("another property", str(caught.exception))

		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.count("Room Service Order"), before)

	def test_an_order_in_another_property_cannot_be_advanced_or_delivered(self):
		menu = self._menu_item(self.property_b, "SNK")
		order = self._order(self.property_b, self.rooms_b[0], menu)
		frappe.db.commit()

		frappe.set_user(self.operator)

		with self.assertRaises(REFUSALS):
			kitchen_api.set_order_status(order.name, "Preparing")

		with self.assertRaises(REFUSALS):
			kitchen_api.deliver_order(order.name)


class TestKitchenBoardDisclosure(TwoPropertyWorld):
	"""A kitchen fulfils from a room and a line. It is owed nothing else.

	The board gates on `Room Service Order.read`, which every kitchen role holds,
	and none of them holds Guest or Guest Folio read at any permlevel. Until
	16.7.4 the guest's name was read with a permission-free query and the folio
	came straight off the order, so a Kitchen User opened the board onto a named
	list of guests and the folios their money sits on.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()

		cls.cook = cls.fixtures.user("op-cook", ["Kitchen User"], properties=[cls.property_a])
		cls.guest = cls.fixtures.guest("Kitchen")

		cls.menu = cls._menu_item(cls.property_a, "SNK")
		cls.order = cls._order(cls.property_a, cls.rooms_a[0], cls.menu, guest=cls.guest)

		frappe.db.commit()

	def test_the_premise_holds(self):
		"""The cook may read orders and may read neither guests nor folios."""
		frappe.set_user(self.cook)

		self.assertTrue(frappe.has_permission("Room Service Order", "read"))
		self.assertFalse(frappe.has_permission("Guest", "read"))
		self.assertFalse(frappe.has_permission("Guest Folio", "read"))

	def test_the_board_gives_a_cook_no_guest_identity(self):
		frappe.set_user(self.cook)
		board = kitchen_api.board(property=self.property_a)

		self.assertTrue(board["orders"], msg="the fixture premise is wrong: no orders")

		for row in board["orders"]:
			self.assertNotIn("guest_name", row)
			self.assertNotIn("guest", row)

		self.assertNotIn(self.guest, frappe.as_json(board))

	def test_the_board_gives_a_cook_no_folio(self):
		frappe.set_user(self.cook)
		board = kitchen_api.board(property=self.property_a)

		for row in board["orders"]:
			self.assertNotIn("folio", row)
			self.assertNotIn("folio_charge_row", row)

	def test_the_stay_follows_stay_read_and_not_the_order(self):
		"""`stay` is gated on Stay, which the kitchen roles happen to hold.

		Recorded deliberately rather than left implicit. A 16.7.4 review read the
		field as a leak; it is not, because `Kitchen User` is inside the Stay
		reader set. The gate is still applied — a caller *without* Stay read gets
		no stay identifier — but on this role matrix it is defence in depth, not
		a redaction. If the matrix ever narrows, this test says which way round
		the rule runs.
		"""
		frappe.set_user(self.cook)

		self.assertTrue(frappe.has_permission("Stay", "read"))

		board = kitchen_api.board(property=self.property_a)

		for row in board["orders"]:
			self.assertIn("stay", row)

	def test_the_board_still_carries_what_a_kitchen_needs(self):
		"""Redaction, not an outage: the order is still fulfillable."""
		frappe.set_user(self.cook)
		board = kitchen_api.board(property=self.property_a)
		row = board["orders"][0]

		self.assertEqual(row["room"], self.rooms_a[0])
		self.assertIn("order_status", row)
		self.assertIn("order_type", row)

	def test_a_front_office_manager_still_sees_the_guest(self):
		"""The paired control. The field is withheld by role, not deleted."""
		frappe.set_user(self.operator)
		board = kitchen_api.board(property=self.property_a)
		row = next(r for r in board["orders"] if r["name"] == self.order.name)

		self.assertIn("guest_name", row)

	def test_one_order_obeys_the_same_rule_as_the_board(self):
		"""The second door: `get_order` published the same fields."""
		frappe.set_user(self.cook)
		payload = kitchen_api.get_order(self.order.name)["order"]

		self.assertNotIn("guest", payload)
		self.assertNotIn("folio", payload)
		self.assertIn("room", payload)


class TestMergeResponsePrivacy(TwoPropertyWorld):
	"""16.7.3 returned per-DocType counts of everything a merge repointed.

	Built from a permission-free, property-unscoped read, and 16.7.3 made merge
	reachable from a browser - so a manager restricted to one property learned
	how many reservations, stays and folios the guest had estate-wide, including
	from DocTypes their role cannot read at all.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()

		cls.manager = cls.fixtures.user(
			"op-mgr", ["Hotel Manager"], properties=[cls.property_a]
		)
		cls.source = cls.fixtures.guest("MergeSource")
		cls.target = cls.fixtures.guest("MergeTarget")

		# References in BOTH properties, so a scoped-count "fix" would be
		# visible and an orphaning "fix" would be caught.
		cls.request_a = guest_services_service.create_request(
			cls.property_a,
			subject="A",
			description="In the caller's own property",
			category="Housekeeping",
			guest=cls.source,
		)
		cls.request_b = guest_services_service.create_request(
			cls.property_b,
			subject="B",
			description="In a property the caller cannot see",
			category="Housekeeping",
			guest=cls.source,
		)

		frappe.db.commit()

	def test_the_merge_response_carries_no_counts(self):
		"""Fails against 16.7.3, which returned `references_moved`."""
		frappe.set_user(self.manager)
		result = guest_service.merge_guests(self.source, self.target, "Same person")

		self.assertEqual(set(result), {"source", "target"})
		self.assertNotIn("references_moved", result)

	def test_no_value_in_the_response_is_a_row_count(self):
		"""Pins the absence, not the key name: no renamed tally may return."""
		frappe.set_user(self.manager)
		result = guest_service.merge_guests(self.source, self.target, "Same person")

		for value in result.values():
			self.assertIsInstance(
				value, str, msg=f"a non-string value leaked into the merge response: {result}"
			)

	def test_the_merge_still_repoints_every_property(self):
		"""The load-bearing test: the leak must not be closed by narrowing the write.

		Scoping the read that built the counts would leave rows in property B
		pointing at a guest the merge has just retired - an orphan, which is
		worse than the disclosure it would have fixed.
		"""
		frappe.set_user(self.manager)
		guest_service.merge_guests(self.source, self.target, "Same person")

		frappe.set_user("Administrator")

		for request in (self.request_a, self.request_b):
			self.assertEqual(
				frappe.db.get_value("Guest Request", request, "guest"),
				self.target,
				msg=f"{request} was left pointing at the merged-away guest",
			)

		self.assertFalse(
			frappe.get_all("Guest Request", filters={"guest": self.source}, pluck="name"),
			msg="rows still reference the source guest after the merge",
		)

	def test_the_merge_is_still_audited(self):
		"""Narrowing the response must not have disturbed the audit trail."""
		frappe.set_user(self.manager)
		guest_service.merge_guests(self.source, self.target, "Duplicate on arrival")

		frappe.set_user("Administrator")
		logs = frappe.get_all(
			"Guest Merge Log",
			filters={"merged_from": self.source, "merged_into": self.target},
			fields=["reason"],
		)

		self.assertEqual(len(logs), 1)
		self.assertEqual(logs[0]["reason"], "Duplicate on arrival")
