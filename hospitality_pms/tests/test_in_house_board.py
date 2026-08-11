"""The in-house board, once it carries enough to work a shift from (16.7.1).

Until this build `stays.in_house` returned thirteen fields: no balance, no
currency, no room number, no reservation, no alert signal and no checkout
readiness. The screen said so in a comment and refused to guess at any of it,
which was right — a guessed "ready to check out" is the worst kind of guess.

So the board is enriched from the authoritative sources rather than from
arithmetic done here: the balance is the one `Guest Folio` maintains, the
blockers are `checkout.get_departure_blockers`'s own answer, the room number is
the room's, and the alert signal is a count and never an alert.

What this suite holds down:

* the added fields are present and correct, from the right source;
* split folios stay *counted*, never folded into the guest's balance — a
  company-pay split is a different payer's debt;
* the response keeps the shape the 16.7.0 frontend is built on;
* the board is property-scoped, and a permlevel-restricted guest field never
  travels on it;
* every added field comes from a bulk query, so the board does not degrade as
  the house fills.
"""

import json

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt

from hospitality_pms.api import stays as stays_api
from hospitality_pms.services import checkout as checkout_service
from hospitality_pms.services import folio as folio_service
from hospitality_pms.services import front_office as front_office_service
from hospitality_pms.services import reservations as reservation_service
from hospitality_pms.services import stays as stay_service
from hospitality_pms.services.exceptions import PermissionDeniedError
from hospitality_pms.tests.fixtures import Fixtures

#: Both shapes a refusal legitimately takes, as in `test_authorization`.
REFUSALS = (frappe.PermissionError, PermissionDeniedError)

#: The four keys the 16.7.0 screen and its own tests read off the summary.
LEGACY_SUMMARY_KEYS = ("in_house", "due_out", "adults", "children")

#: The thirteen row fields `stays.get_in_house` returned before this build. The
#: frontend table is built on these names, so none of them may be renamed away.
LEGACY_ROW_FIELDS = (
	"name",
	"guest",
	"guest_name",
	"room",
	"room_type",
	"arrival_date",
	"departure_date",
	"nights",
	"adults",
	"children",
	"stay_status",
	"folio",
	"room_rate",
)

MASTER_CHARGE = 400.0
SPLIT_CHARGE = 175.5

#: Alert text that must never leave the guest endpoints. On the board it is a
#: count and nothing else: this is a screen at a counter, with the guest in front
#: of it, and it prints.
ALERT_TEXT = "CONFIDENTIAL: guest disputes minibar charges, escalate to the duty manager"


class TestInHouseBoard(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()

		cls.fixtures = Fixtures("INHS")

		cls.property = cls.fixtures.property("IA", require_id_at_check_in=0)
		cls.other_property = cls.fixtures.property("IB", require_id_at_check_in=0)

		cls.room_type = cls.fixtures.room_type(cls.property)
		cls.rooms = cls.fixtures.rooms(cls.property, cls.room_type, count=4)
		cls.rate_plan = cls.fixtures.rate_plan(cls.property, cls.room_type)

		# One guest with a balance, an alert history and a split folio: the row
		# every assertion about money and alerts is made against.
		cls.guest = cls.fixtures.guest("Charged")
		cls.stay, cls.folio = cls._check_in(cls, cls.property, cls.guest, cls.rooms[0])

		folio_service.post_charge(
			cls.folio, "Room Charge", "Night", MASTER_CHARGE, idempotency_key="inhs:master"
		)

		# A second folio on the same stay, with its own money. `open_folio`
		# returns the existing master for a stay, so the split is opened as one.
		cls.split_folio = folio_service.open_folio(
			cls.property, cls.guest, stay=cls.stay, folio_type="Split", parent_folio=cls.folio
		)
		cls.fixtures.track("Guest Folio", cls.split_folio)
		folio_service.post_charge(
			cls.split_folio, "Minibar", "Water", SPLIT_CHARGE, idempotency_key="inhs:split"
		)

		cls._add_alerts(cls, cls.guest)

		# A guest who owes nothing, so "ready to check out" has a true case as
		# well as a false one.
		cls.settled_guest = cls.fixtures.guest("Settled")
		cls.settled_stay, cls.settled_folio = cls._check_in(
			cls, cls.property, cls.settled_guest, cls.rooms[1]
		)

		# The same world in a property this suite's user may not operate in.
		cls.other_room_type = cls.fixtures.room_type(cls.other_property)
		cls.other_rooms = cls.fixtures.rooms(cls.other_property, cls.other_room_type, count=1)
		cls.other_rate_plan = cls.fixtures.rate_plan(cls.other_property, cls.other_room_type)
		cls.other_guest = cls.fixtures.guest("Elsewhere")
		cls.other_stay, cls.other_folio = cls._check_in(
			cls, cls.other_property, cls.other_guest, cls.other_rooms[0]
		)

		# Cleared for the blacklist flag, and permitted in one property only.
		cls.desk = cls.fixtures.user("fo", ["Front Office Agent"], properties=[cls.property])

		# In Stay readers (OPERATIONAL) and so able to open this board, but not a
		# Guest reader at any level.
		cls.housekeeper = cls.fixtures.user(
			"hk", ["Housekeeping Manager"], properties=[cls.property]
		)

		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		cls.fixtures.teardown()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user(self.desk)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	# -- world ----------------------------------------------------------

	def _check_in(self, property_name: str, guest: str, room: str) -> tuple[str, str]:
		room_type = frappe.db.get_value("Hotel Room", room, "room_type")
		rate_plan = frappe.db.get_value("Rate Plan", {"property": property_name}, "name")

		reservation = self.fixtures.reservation(
			property_name, room_type, guest, rate_plan=rate_plan, nights=3
		)
		reservation_service.confirm(reservation)

		line = frappe.get_all("Reservation Room", filters={"parent": reservation}, pluck="name")[0]
		result = stay_service.check_in(reservation, line, room)

		return result["stay"], result["folio"]

	def _add_alerts(self, guest: str):
		"""Two alerts that apply, and one that has expired.

		The expired one is the point: the count is answered on the property's
		operating day, so an alert that ran out yesterday is not counted today.
		"""
		business_date = frappe.db.get_value("Property", self.property, "business_date")

		doc = frappe.get_doc("Guest", guest)
		doc.append(
			"alerts",
			{"alert_type": "Payment", "severity": "Warning", "alert": ALERT_TEXT, "is_active": 1},
		)
		doc.append(
			"alerts",
			{
				"alert_type": "Behaviour",
				"severity": "Critical",
				"alert": ALERT_TEXT,
				"is_active": 1,
				"valid_upto": business_date,
			},
		)
		doc.append(
			"alerts",
			{
				"alert_type": "Operational",
				"severity": "Info",
				"alert": ALERT_TEXT,
				"is_active": 1,
				"valid_upto": add_days(business_date, -1),
			},
		)
		doc.save(ignore_permissions=True)

	# -- helpers --------------------------------------------------------

	def _row(self, stay: str, board: dict | None = None) -> dict:
		board = board if board is not None else stays_api.in_house(property=self.property)
		rows = [row for row in board["stays"] if row["stay"] == stay]

		self.assertTrue(rows, msg=f"{stay} is not on the in-house board")

		return rows[0]

	# -- money ----------------------------------------------------------

	def test_in_house_returns_folio_balance(self):
		"""The balance the folio service maintains, not one recomputed here."""
		row = self._row(self.stay)

		authoritative = flt(frappe.db.get_value("Guest Folio", self.folio, "balance"), 2)

		self.assertEqual(row["folio"], self.folio)
		self.assertEqual(row["balance"], authoritative)
		self.assertEqual(row["balance"], MASTER_CHARGE)
		self.assertEqual(row["folio_status"], folio_service.OPEN)

		# And a guest who owes nothing reads as zero, not as absent.
		self.assertEqual(self._row(self.settled_stay)["balance"], 0.0)

	def test_in_house_returns_currency(self):
		"""The row carries its own currency; the screen no longer assumes one."""
		row = self._row(self.stay)

		folio_currency = frappe.db.get_value("Guest Folio", self.folio, "currency")
		property_currency = frappe.db.get_value("Property", self.property, "currency")

		self.assertTrue(row["currency"])
		self.assertEqual(row["currency"], folio_currency or property_currency)

		# The board says it too, for a screen that has no row selected yet.
		board = stays_api.in_house(property=self.property)
		self.assertEqual(board["currency"], property_currency)

	def test_in_house_returns_required_identifiers(self):
		row = self._row(self.stay)

		room_number = frappe.db.get_value("Hotel Room", self.rooms[0], "room_number")
		reservation = frappe.db.get_value("Stay", self.stay, "reservation")

		self.assertEqual(row["stay"], self.stay)
		self.assertEqual(row["name"], self.stay)
		self.assertEqual(row["guest"], self.guest)
		self.assertEqual(row["room"], self.rooms[0])
		self.assertEqual(row["room_number"], room_number)
		self.assertEqual(row["reservation"], reservation)
		self.assertEqual(row["folio"], self.folio)
		self.assertEqual(row["property"], self.property)

		# The room column now means what it means on arrivals and departures:
		# the number a human uses, not the record's code.
		self.assertNotEqual(row["room_number"], row["room"])
		self.assertTrue(row["room_type_name"])

	# -- alerts and guest privacy -----------------------------------------

	def test_in_house_alert_metadata_respects_permissions(self):
		"""Count and grade for a Guest reader, a body for nobody.

		The first version of this gave the **count** to every board reader and
		gated only the grade, on the theory that "there is something to ask about"
		is not a disclosure. The security review took that apart. Both numbers come
		out of `Guest Alert`, a child table with no permissions of its own, so its
		reader set *is* Guest's - and the argument for the count named the front
		desk, which holds Guest read and was therefore never the audience in
		question. A room attendant learns that the guest in 412 carries two alerts,
		acts on none of it, and over a season accumulates the very profile the
		permission was drawn around. So both travel together, or neither does.

		The **body**, the type and the raw child rows reach nobody here, whatever
		their clearance: an alert is free text about a guest who may be reading the
		screen over the counter.

		The blacklist flag on the same row follows the same shape, on its own
		narrower clearance: absent rather than false.
		"""
		for user, cleared in ((self.desk, True), (self.housekeeper, False)):
			frappe.set_user(user)

			board = stays_api.in_house(property=self.property)
			row = self._row(self.stay, board)

			# Never, for anyone: the alert itself.
			for field in ("alerts", "alert", "alert_type", "severity"):
				self.assertNotIn(field, row, msg=f"{user} received {field} on a board row")

			self.assertNotIn(
				ALERT_TEXT, json.dumps(board, default=str), msg=f"{user} received an alert body"
			)

			# Both numbers track Guest read, which the desk holds and housekeeping
			# does not.
			may_read_guest = frappe.has_permission("Guest", "read")

			for field in ("alert_count", "alert_severity"):
				self.assertEqual(
					field in row,
					may_read_guest,
					msg=f"{user} {field} disclosure did not match Guest read permission",
				)

			if may_read_guest:
				# Two of the three fixture alerts still apply on the operating day,
				# and the worst of those two is Critical.
				self.assertEqual(row["alert_count"], 2)
				self.assertIsInstance(row["alert_count"], int)
				self.assertEqual(row["alert_severity"], "Critical")

			self.assertEqual("is_blacklisted" in row, cleared)

	def test_in_house_does_not_expose_protected_guest_fields(self):
		"""Nothing above permlevel 0 on the Guest travels on this board."""
		for user in (self.desk, self.housekeeper):
			frappe.set_user(user)

			board = stays_api.in_house(property=self.property)
			serialised = json.dumps(board, default=str)

			for field in (
				"blacklist_reason",
				"blacklisted_by",
				"blacklisted_on",
				"identifications",
				"id_number",
				"date_of_birth",
				"nationality",
			):
				self.assertNotIn(f'"{field}"', serialised, msg=f"{user} received {field}")

		# Whereas the permlevel-0 standing the desk works from is still there.
		frappe.set_user(self.desk)
		self.assertIn("vip_status", self._row(self.stay))

	def test_a_caller_who_cannot_read_guest_gets_no_guest_standing(self):
		"""Permlevel 0 is not "public".

		`vip_status` and `guest_type` are unprivileged *among people entitled to
		the Guest record*. Housekeeping is not one of them - it holds Stay read,
		which is what opens this board, and no Guest permission at all. The board
		assembles those fields with a permission-free `frappe.get_all`, so nothing
		but this gate stands between the two facts.
		"""
		frappe.set_user(self.housekeeper)
		row = self._row(self.stay)

		for field in ("vip_status", "guest_type", "alert_count", "alert_severity"):
			self.assertNotIn(field, row, msg=f"housekeeping received {field}")

		# And the aggregate does not hand back what the rows withheld.
		board = stays_api.in_house(property=self.property)
		for key in ("vip", "with_alerts"):
			self.assertNotIn(key, board["summary"], msg=f"housekeeping received summary.{key}")

		# The desk, which may read Guest, still gets all of it.
		frappe.set_user(self.desk)
		cleared = self._row(self.stay)
		for field in ("vip_status", "alert_count", "alert_severity"):
			self.assertIn(field, cleared)

	def test_a_caller_who_cannot_read_the_folio_gets_no_money(self):
		"""The defect this build was chartered to close, one DocType over.

		The board gates on `Stay.read` and then reads Guest Folio with a
		permission-free `frappe.get_all`. Ten roles on this site hold Stay read and
		no Guest Folio read - housekeeping, maintenance, kitchen, F&B, revenue,
		corporate sales - and the Command Center is their landing page, because its
		navigation entry carries no role filter. Without this gate a room attendant
		opened the dashboard onto a named, sorted list of guest debts.

		The blockers matter as much as the numbers: `get_departure_blockers` words
		them with the amount inside the sentence, so passing the strings through
		would disclose the money even with every numeric field withheld.
		"""
		frappe.set_user(self.housekeeper)
		row = self._row(self.stay)

		for field in (
			"balance",
			"related_balance",
			"related_folios",
			"folio",
			"folio_status",
			"blockers",
			"can_check_out",
		):
			self.assertNotIn(field, row, msg=f"housekeeping received {field}")

		board = stays_api.in_house(property=self.property)
		serialised = json.dumps(board, default=str)

		# The amount appears in no form anywhere in the payload - not as a field,
		# not inside a blocker sentence, not as a total.
		balance = flt(frappe.db.get_value("Guest Folio", self.folio, "balance"), 2)
		self.assertGreater(balance, 0, msg="the fixture folio must carry a balance to prove anything")
		self.assertNotIn(str(balance), serialised, msg="housekeeping received the balance in some form")

		for key in ("outstanding_balance", "balance_pending", "ready_to_check_out", "blocked"):
			self.assertNotIn(key, board["summary"], msg=f"housekeeping received summary.{key}")

		# What housekeeping legitimately holds is untouched: this is a Stay board,
		# and the stay's own fields are theirs to read.
		for field in ("room", "room_number", "stay_status", "arrival_date", "departure_date"):
			self.assertIn(field, row)

		# And the desk still gets the whole folio position.
		frappe.set_user(self.desk)
		cleared = self._row(self.stay)
		for field in ("balance", "folio", "can_check_out", "blockers"):
			self.assertIn(field, cleared)

	# -- property scoping --------------------------------------------------

	def test_in_house_is_property_scoped(self):
		"""Another property's guest is neither listed nor reachable."""
		frappe.set_user(self.desk)

		board = stays_api.in_house(property=self.property)
		serialised = json.dumps(board, default=str)

		self.assertNotIn(self.other_stay, serialised)
		self.assertNotIn(self.other_guest, serialised)
		self.assertNotIn(self.other_property, serialised)

		for row in board["stays"]:
			self.assertEqual(row["property"], self.property)

		# And asking for the other property outright is refused, rather than
		# quietly answered with this user's own property.
		with self.assertRaises(REFUSALS) as caught:
			stays_api.in_house(property=self.other_property)

		self.assertNotIn(self.other_guest, str(caught.exception))

	# -- the response contract ---------------------------------------------

	def test_in_house_preserves_its_existing_response_shape(self):
		board = stays_api.in_house(property=self.property)

		self.assertEqual(board["property"], self.property)
		self.assertIn("stays", board)
		self.assertIn("summary", board)
		self.assertIsInstance(board["stays"], list)

		expected = frappe.get_all(
			"Stay",
			filters={
				"property": self.property,
				"stay_status": ("in", (stay_service.IN_HOUSE, stay_service.DUE_OUT)),
			},
			fields=["name", "stay_status", "adults", "children"],
		)

		self.assertEqual(len(board["stays"]), len(expected))

		summary = board["summary"]

		for key in LEGACY_SUMMARY_KEYS:
			self.assertIn(key, summary)

		self.assertEqual(
			summary["in_house"],
			sum(1 for s in expected if s["stay_status"] == stay_service.IN_HOUSE),
		)
		self.assertEqual(
			summary["due_out"], sum(1 for s in expected if s["stay_status"] == stay_service.DUE_OUT)
		)
		self.assertEqual(summary["adults"], sum(int(s["adults"] or 0) for s in expected))
		self.assertEqual(summary["children"], sum(int(s["children"] or 0) for s in expected))

		for row in board["stays"]:
			for field in LEGACY_ROW_FIELDS:
				self.assertIn(field, row, msg=f"{field} was dropped from the in-house row")

	# -- split folios ------------------------------------------------------

	def test_in_house_split_folios_are_counted_not_summed(self):
		"""A split is a different payer's debt, so it is never merged in.

		Adding it to `balance` would put a company's liability on the guest's
		line and send the desk asking the wrong person for the money. It is
		counted, carried separately, and it still blocks the door.
		"""
		row = self._row(self.stay)

		self.assertEqual(row["balance"], MASTER_CHARGE)
		self.assertEqual(row["related_folios"], 1)
		self.assertEqual(row["related_balance"], flt(SPLIT_CHARGE, 2))
		self.assertNotEqual(row["balance"], MASTER_CHARGE + SPLIT_CHARGE)

		# And a stay with no split reads zero rather than nothing.
		settled = self._row(self.settled_stay)
		self.assertEqual(settled["related_folios"], 0)
		self.assertEqual(settled["related_balance"], 0.0)

	# -- readiness ---------------------------------------------------------

	def test_in_house_checkout_readiness_comes_from_the_service(self):
		"""Character for character the checkout service's own answer.

		The board must not be able to promise a checkout the checkout screen
		would refuse, so the blockers are not re-derived here: they are compared
		against `checkout.get_departure_blockers` called directly on the same
		folio rows.
		"""
		board = stays_api.in_house(property=self.property)

		frappe.set_user("Administrator")

		for row in board["stays"]:
			folios = frappe.get_all(
				"Guest Folio",
				filters={"stay": row["stay"]},
				fields=["name", "folio_type", "folio_status", "balance", "currency"],
			)
			primary = next((f for f in folios if f["name"] == row["folio"]), None)
			related = [f for f in folios if f["name"] != row["folio"]]

			expected = checkout_service.get_departure_blockers(
				row["stay_status"], primary, related
			)

			self.assertEqual(row["blockers"], expected)
			self.assertEqual(row["can_check_out"], not expected)

		# Both outcomes really occur in this world, or the comparison above
		# could be trivially satisfied.
		charged = self._row(self.stay, board)
		settled = self._row(self.settled_stay, board)

		self.assertFalse(charged["can_check_out"])
		self.assertTrue(charged["blockers"])
		self.assertTrue(settled["can_check_out"])
		self.assertEqual(settled["blockers"], [])

	# -- shape at scale ----------------------------------------------------

	def test_in_house_is_a_fixed_number_of_queries(self):
		"""Every added field comes from a bulk query over the whole board.

		The count does not grow with the number of rows: one stays query, one
		folios query, one rooms query, one guest-flags query, one room-types
		query, one alert-counts query and the business date behind them. An
		upper bound is asserted rather than an exact figure, because the point
		is that it is bounded at all.
		"""
		# Warm the caches a first call would pay for (the Property document, the
		# Guest meta behind the clearance question), so what is counted is the
		# board's own work.
		front_office_service.get_in_house_board(self.property)

		with self.assertQueryCount(10):
			board = front_office_service.get_in_house_board(self.property)

		self.assertTrue(board["rows"])
