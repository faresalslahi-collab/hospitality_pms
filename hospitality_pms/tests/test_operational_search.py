"""The global operational search: what it finds, and what it must never find.

Built on real role and property contexts from `tests.fixtures` rather than
patched permission helpers, because everything this endpoint claims is a claim
about Frappe's own permission machinery: that `get_list` applies DocType
permissions *and* the Property User Permissions the product's scoping is built
on (HPMS-DEC-052), and that a permlevel-2 column cannot be inferred from a
result set. A mocked permission check would prove none of it.

Two properties, one user restricted to the first, and three users holding three
genuinely different reader sets - a front office agent who may read all five
entities, a room attendant who may read three of them, and an accounts user who
may read guests but is not cleared for the blacklist flag.
"""

import frappe
from frappe.tests import IntegrationTestCase

from hospitality_pms.api import search as search_api
from hospitality_pms.services import reservations as reservation_service
from hospitality_pms.services import search as search_service
from hospitality_pms.services import stays as stay_service
from hospitality_pms.services.exceptions import PermissionDeniedError
from hospitality_pms.tests.fixtures import Fixtures

#: Both shapes a refusal legitimately takes, as in `test_authorization`.
REFUSALS = (frappe.PermissionError, PermissionDeniedError)

#: Keys that must never appear on a search result, whatever the entity. Not a
#: guess at what a leak would look like: these are the exact fieldnames the
#: blacklist, identification, alert and accounting data live under, so a future
#: change that widened the field list would name one of them.
FORBIDDEN_KEYS = frozenset(
	{
		"is_blacklisted",
		"blacklist_reason",
		"blacklisted_by",
		"blacklisted_on",
		"identifications",
		"id_number",
		"alerts",
		"charges",
		"payments",
		"balance",
		"total_charges",
		"total_taxes",
		"total_payments",
		"total_adjustments",
		"credit_limit",
		"customer",
		"account_head",
		"erp_document",
		"notes",
		"internal_notes",
		"special_requests",
	}
)

GUEST_A_FIRST_NAME = "Layla"
GUEST_B_FIRST_NAME = "Bravo"
BLACKLISTED_FIRST_NAME = "Barred"
CAPPED_FIRST_NAME = "Capped"

#: More matches than the default per-entity cap, so truncation is real.
CAPPED_COUNT = search_service.DEFAULT_LIMIT + 2

GUEST_A_MOBILE = "+97455512345"

#: The five tables an entity query is allowed to touch, backtick-quoted so
#: `tabGuest` cannot match `tabGuest Folio`.
ENTITY_TABLES = {doctype: f"`tab{doctype}`" for doctype in search_service.SEARCHABLE_TYPES}


class _QuerySpy:
	"""Records the SQL a block of code runs, so N+1 is a test and not a hope."""

	def __init__(self):
		self.queries: list[str] = []
		self._original = None

	def __enter__(self):
		self._original = frappe.db.sql

		def spy(query, *args, **kwargs):
			self.queries.append(str(query))

			return self._original(query, *args, **kwargs)

		frappe.db.sql = spy

		return self

	def __exit__(self, *exc):
		frappe.db.sql = self._original

		return False

	def entity_selects(self) -> dict[str, int]:
		"""How many selects were run against each searchable entity's table."""
		counts = {}

		for doctype, table in ENTITY_TABLES.items():
			counts[doctype] = sum(
				1 for query in self.queries if table in query and query.lower().lstrip().startswith("select")
			)

		return counts


class TestOperationalSearch(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()

		cls.fixtures = Fixtures("SRCH")

		cls.property_a = cls.fixtures.property("PA", require_id_at_check_in=0)
		cls.property_b = cls.fixtures.property("PB", require_id_at_check_in=0)

		cls.guest_a, cls.rooms_a, cls.reservation_a, cls.stay_a, cls.folio_a = cls._world(
			cls, cls.property_a, GUEST_A_FIRST_NAME, mobile_no=GUEST_A_MOBILE
		)
		cls.guest_b, cls.rooms_b, cls.reservation_b, cls.stay_b, cls.folio_b = cls._world(
			cls, cls.property_b, GUEST_B_FIRST_NAME
		)

		# A blacklisted guest, placed through the real controller: it demands one
		# of the elevated roles and a written reason, which is the audited
		# transition this test must not route around.
		cls.blacklisted_guest = cls.fixtures.guest(
			BLACKLISTED_FIRST_NAME, is_blacklisted=1, blacklist_reason="Search suite fixture"
		)

		# More guests matching one fragment than a page can hold.
		cls.capped_guests = [cls.fixtures.guest(CAPPED_FIRST_NAME) for _ in range(CAPPED_COUNT)]

		# Three real reader sets, each expressed as roles plus a Property User
		# Permission - not a test-only convention.
		#
		# Front Office Agent: read on all five entities, and cleared for the
		# blacklist flag (Guest permlevel 2).
		cls.agent = cls.fixtures.user("srchagent", ["Front Office Agent"], properties=[cls.property_a])

		# Room Attendant: read on Reservation, Stay and Hotel Room; none at all
		# on Guest or Guest Folio.
		cls.attendant = cls.fixtures.user("srchhk", ["Room Attendant"], properties=[cls.property_a])

		# Accounts User: read on Guest, Reservation, Stay and Guest Folio, but
		# not cleared for permlevel 2 - so it may read a guest and may not know
		# whether one is blacklisted.
		cls.accounts = cls.fixtures.user("srchfin", ["Accounts User"], properties=[cls.property_a])

		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		cls.fixtures.teardown()
		super().tearDownClass()

	def _world(self, property_name: str, first_name: str, **guest_fields):
		"""A guest checked into a room, with a folio, through the real services."""
		room_type = self.fixtures.room_type(property_name)
		rooms = self.fixtures.rooms(property_name, room_type, count=2)
		rate_plan = self.fixtures.rate_plan(property_name, room_type)
		guest = self.fixtures.guest(first_name, **guest_fields)

		reservation = self.fixtures.reservation(
			property_name, room_type, guest, rate_plan=rate_plan, nights=2
		)
		reservation_service.confirm(reservation)

		line = frappe.get_all("Reservation Room", filters={"parent": reservation}, pluck="name")[0]
		result = stay_service.check_in(reservation, line, rooms[0])

		return guest, rooms, reservation, result["stay"], result["folio"]

	def setUp(self):
		frappe.set_user(self.agent)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	# -- helpers ----------------------------------------------------------

	def _search(self, query, **kwargs) -> dict:
		return search_api.operational_search(query=query, **kwargs)

	def _ids(self, payload: dict, doctype: str) -> list[str]:
		return [row["id"] for row in payload["results"] if row["type"] == doctype]

	def _guest_name(self, first_name: str) -> str:
		"""The composed display name a fixture guest ends up with."""
		return f"{first_name} One{self.fixtures.tag}"

	# -- finding things ---------------------------------------------------

	def test_search_guest_by_name(self):
		payload = self._search(GUEST_A_FIRST_NAME, property=self.property_a)

		self.assertEqual(self._ids(payload, "Guest"), [self.guest_a])
		self.assertEqual(payload["counts"]["Guest"], 1)

		guest = next(row for row in payload["results"] if row["type"] == "Guest")

		self.assertEqual(guest["primary_label"], self._guest_name(GUEST_A_FIRST_NAME))
		# A guest belongs to no property; the field is present and empty rather
		# than absent, so the client never has to branch on the key existing.
		self.assertIsNone(guest["property"])

	def test_search_guest_by_mobile(self):
		payload = self._search("5551234", property=self.property_a)

		self.assertIn(self.guest_a, self._ids(payload, "Guest"))

		guest = next(row for row in payload["results"] if row["id"] == self.guest_a)

		self.assertEqual(guest["secondary_label"], GUEST_A_MOBILE)

	def test_search_reservation(self):
		"""By the docname an agent pastes, and by the guest name they type."""
		by_docname = self._search(self.reservation_a, property=self.property_a)

		self.assertEqual(self._ids(by_docname, "Reservation"), [self.reservation_a])

		by_guest_name = self._search(GUEST_A_FIRST_NAME, property=self.property_a)

		self.assertEqual(self._ids(by_guest_name, "Reservation"), [self.reservation_a])

		reservation = next(row for row in by_guest_name["results"] if row["type"] == "Reservation")

		self.assertEqual(reservation["property"], self.property_a)
		self.assertEqual(
			reservation["status"],
			frappe.db.get_value("Reservation", self.reservation_a, "reservation_status"),
		)

	def test_search_stay(self):
		payload = self._search(self.stay_a, property=self.property_a)

		self.assertEqual(self._ids(payload, "Stay"), [self.stay_a])

		stay = next(row for row in payload["results"] if row["type"] == "Stay")

		self.assertEqual(stay["property"], self.property_a)
		self.assertEqual(stay["secondary_label"], self.rooms_a[0])

	def test_search_folio(self):
		payload = self._search(self.folio_a, property=self.property_a)

		self.assertEqual(self._ids(payload, "Guest Folio"), [self.folio_a])

		folio = next(row for row in payload["results"] if row["type"] == "Guest Folio")

		self.assertEqual(folio["property"], self.property_a)
		self.assertEqual(folio["status"], frappe.db.get_value("Guest Folio", self.folio_a, "folio_status"))
		# Nothing monetary travels on a search result.
		self.assertEqual(folio["safe_summary"], "")

	def test_search_room(self):
		"""Both room identifiers: the number on the door and the room code."""
		room = self.rooms_a[0]
		room_number = frappe.db.get_value("Hotel Room", room, "room_number")

		by_number = self._search(room_number, property=self.property_a)

		self.assertIn(room, self._ids(by_number, "Hotel Room"))

		by_code = self._search(room, property=self.property_a)

		self.assertIn(room, self._ids(by_code, "Hotel Room"))

		result = next(row for row in by_code["results"] if row["id"] == room)

		self.assertEqual(result["primary_label"], room_number)
		self.assertEqual(result["property"], self.property_a)

	# -- property scoping -------------------------------------------------

	def test_search_is_property_scoped(self):
		"""Another property's operational records are absent, and asking is refused."""
		payload = self._search(GUEST_B_FIRST_NAME, property=self.property_a)

		self.assertNotIn(self.reservation_b, self._ids(payload, "Reservation"))
		self.assertNotIn(self.stay_b, self._ids(payload, "Stay"))
		self.assertNotIn(self.folio_b, self._ids(payload, "Guest Folio"))
		self.assertNotIn(self.rooms_b[0], self._ids(payload, "Hotel Room"))

		self.assertEqual(payload["counts"]["Reservation"], 0)
		self.assertEqual(payload["counts"]["Stay"], 0)
		self.assertEqual(payload["counts"]["Guest Folio"], 0)

		# The guest, however, is found: a Guest is a global master record with
		# no property, and hiding a returning guest from the desk about to check
		# them in would break the case the search exists for.
		self.assertEqual(self._ids(payload, "Guest"), [self.guest_b])

		# Naming a property this user may not operate in is a refusal, not an
		# empty result - an empty result reads as "no such booking here".
		with self.assertRaises(REFUSALS) as caught:
			self._search(GUEST_B_FIRST_NAME, property=self.property_b)

		self.assertNotIn(self.reservation_b, str(caught.exception))

	def test_search_without_a_property_stays_within_the_permitted_set(self):
		"""No property named: the search spans what the user may operate in.

		It must not error - a global search box on a multi-property user is the
		normal case - and it must not reach the property they were never given.
		"""
		payload = self._search(GUEST_B_FIRST_NAME)

		self.assertEqual(payload["property"], self.property_a)
		self.assertEqual(payload["counts"]["Reservation"], 0)
		self.assertNotIn(self.stay_b, self._ids(payload, "Stay"))

	# -- permissions ------------------------------------------------------

	def test_search_respects_permissions(self):
		"""A reader set of three entities gets three entities, not a 403."""
		frappe.set_user(self.attendant)

		self.assertFalse(frappe.has_permission("Guest", "read"))
		self.assertFalse(frappe.has_permission("Guest Folio", "read"))
		self.assertTrue(frappe.has_permission("Stay", "read"))

		payload = self._search(GUEST_A_FIRST_NAME, property=self.property_a)

		# The entities this role may not read are absent, and their counts read
		# exactly as "no matches" would - the response cannot be used to probe
		# which DocTypes a user holds.
		self.assertEqual(self._ids(payload, "Guest"), [])
		self.assertEqual(self._ids(payload, "Guest Folio"), [])
		self.assertEqual(payload["counts"]["Guest"], 0)
		self.assertEqual(payload["counts"]["Guest Folio"], 0)

		# And the ones it may read still work, which is the whole point: a
		# per-entity refusal must not become a refusal of the search.
		self.assertEqual(self._ids(payload, "Reservation"), [self.reservation_a])
		self.assertEqual(self._ids(payload, "Stay"), [self.stay_a])

	def test_search_does_not_return_sensitive_blacklist_fields(self):
		"""The flag is neither returned nor inferable from what is returned.

		Not inferable is the harder half, and it is why the guest row is *kept*.
		"""
		frappe.set_user(self.accounts)

		# Establishes the premise: this user may read guests and is not cleared
		# for the flag. Without it the assertion below could pass for the wrong
		# reason.
		self.assertTrue(frappe.has_permission("Guest", "read"))
		self.assertNotIn(2, frappe.get_meta("Guest").get_permlevel_access("read"))

		payload = self._search(BLACKLISTED_FIRST_NAME, property=self.property_a)

		# The row is returned, and carries no flag. This module first *removed* it,
		# and that was worse: hiding the row turns a withheld field into a
		# conclusive one-bit inference, because this same response labels the
		# guest's Reservation, Stay and Folio rows with `guest_name`. Absent from
		# the guest group while present in the others meant "blacklisted", every
		# time. Returning the row discloses nothing — the flag is never selected.
		self.assertEqual(
			self._ids(payload, "Guest"),
			[self.blacklisted_guest],
			msg="the guest row should be returned; only the flag is withheld",
		)

		for row in payload["results"]:
			for key in FORBIDDEN_KEYS:
				self.assertNotIn(key, row, msg=f"{key} leaked on a {row['type']} result")

		# The inference channel itself: what an uncleared caller sees for a
		# blacklisted guest is indistinguishable from what they see for a guest who
		# is not, beyond the guest's own identity.
		clean = self._search(GUEST_A_FIRST_NAME, property=self.property_a)

		self.assertEqual(
			{key for row in payload["results"] if row["type"] == "Guest" for key in row},
			{key for row in clean["results"] if row["type"] == "Guest" for key in row},
			msg="a blacklisted guest's result differs in shape from a clean guest's",
		)

		# And a cleared user sees the same row: clearance changes what is known
		# about the guest, never whether the guest can be found.
		frappe.set_user(self.agent)

		self.assertIn(2, frappe.get_meta("Guest").get_permlevel_access("read"))

		cleared = self._search(BLACKLISTED_FIRST_NAME, property=self.property_a)

		self.assertEqual(self._ids(cleared, "Guest"), [self.blacklisted_guest])

		# Asserted over a result set that reaches every builder, so the guarantee
		# is about all five entities and not only the one the blacklist lives on.
		broad = self._search(GUEST_A_FIRST_NAME, property=self.property_a)

		self.assertTrue({row["type"] for row in broad["results"]} >= {"Guest", "Stay", "Guest Folio"})

		for row in cleared["results"] + broad["results"]:
			for key in FORBIDDEN_KEYS:
				self.assertNotIn(key, row, msg=f"{key} leaked on a {row['type']} result")

	# -- bounds -----------------------------------------------------------

	def test_search_result_count_is_bounded(self):
		payload = self._search(CAPPED_FIRST_NAME, property=self.property_a)

		self.assertEqual(payload["limit"], search_service.DEFAULT_LIMIT)
		self.assertEqual(payload["counts"]["Guest"], search_service.DEFAULT_LIMIT)
		self.assertEqual(len(self._ids(payload, "Guest")), search_service.DEFAULT_LIMIT)
		self.assertTrue(payload["truncated"])

		# A caller asking for more than a typeahead can afford is clamped, not
		# refused, and the cap it actually got is reported back.
		clamped = self._search(CAPPED_FIRST_NAME, property=self.property_a, limit=500)

		self.assertEqual(clamped["limit"], search_service.MAX_LIMIT)
		self.assertLessEqual(len(clamped["results"]), search_service.MAX_LIMIT * len(search_service.SEARCHABLE_TYPES))

		# `truncated` is a fact, not a guess: a search that fits reports False.
		fits = self._search(GUEST_A_FIRST_NAME, property=self.property_a)

		self.assertFalse(fits["truncated"])

	def test_search_runs_one_query_per_entity(self):
		with _QuerySpy() as spy:
			self._search(GUEST_A_FIRST_NAME, property=self.property_a)

		selects = spy.entity_selects()

		self.assertEqual(
			selects,
			{doctype: 1 for doctype in search_service.SEARCHABLE_TYPES},
			msg=f"expected one query per entity and no hydration pass, got {selects}",
		)

	def test_every_caller_pays_the_same_five_queries(self):
		"""Five entity selects, whoever asks — no per-caller extra step.

		This replaces a test that pinned a *sixth* query: an uncleared caller used
		to pay one extra primary-key lookup to remove blacklisted guests from the
		page. That removal is gone (hiding the row was a worse disclosure than
		keeping it, see the note in `services/search.py`), and with it the extra
		query. Cost is now identical for every role, which also means query count
		cannot be used to infer anything about the caller's clearance.
		"""
		frappe.set_user(self.accounts)

		with _QuerySpy() as spy:
			self._search(CAPPED_FIRST_NAME, property=self.property_a)

		selects = spy.entity_selects()

		# One query for every entity this role may read, none for the rest.
		# Expectations are derived from live permissions rather than hard-coded, so
		# the test describes the endpoint and not this site's role configuration.
		for doctype in search_service.SEARCHABLE_TYPES:
			expected = 1 if frappe.has_permission(doctype, "read") else 0

			self.assertEqual(selects[doctype], expected, msg=f"{doctype}: {selects}")

		# And a cleared caller pays exactly the same.
		frappe.set_user(self.agent)

		with _QuerySpy() as cleared_spy:
			self._search(CAPPED_FIRST_NAME, property=self.property_a)

		self.assertEqual(
			cleared_spy.entity_selects()["Guest"],
			selects["Guest"],
			msg="clearance changed the query count, which is an inference channel of its own",
		)

	def test_empty_or_too_short_query_is_safe(self):
		"""Every shape an unusable query arrives in, including the client bug.

		`undefined` is not hypothetical: a GET parameter that was a JavaScript
		`undefined` reaches the server as that literal text, and an endpoint
		that matched on it would search for `%undefined%` on every first load.
		"""
		for query in ("", None, "   ", "a", "undefined", "null", "None"):
			with self.subTest(query=query):
				with _QuerySpy() as spy:
					payload = self._search(query, property=self.property_a)

				self.assertEqual(payload["results"], [])
				self.assertEqual(payload["min_length"], search_service.MIN_QUERY_LENGTH)
				self.assertFalse(payload["truncated"])
				self.assertEqual(
					payload["counts"],
					{doctype: 0 for doctype in search_service.SEARCHABLE_TYPES},
				)
				# `query` is always a string, so the client's own length check
				# never has to handle two types.
				self.assertIsInstance(payload["query"], str)

				# And it cost the database nothing at all.
				self.assertEqual(
					sum(spy.entity_selects().values()),
					0,
					msg="an unusable query reached the database",
				)

	# -- contract ---------------------------------------------------------

	def test_search_result_shape(self):
		"""Every result carries exactly the frozen contract keys."""
		payload = self._search(GUEST_A_FIRST_NAME, property=self.property_a)

		self.assertEqual(
			set(payload),
			{"query", "property", "min_length", "limit", "truncated", "counts", "results"},
		)
		self.assertEqual(payload["query"], GUEST_A_FIRST_NAME)
		self.assertEqual(payload["property"], self.property_a)
		self.assertEqual(set(payload["counts"]), set(search_service.SEARCHABLE_TYPES))

		# All four property-bearing entities plus the guest, so the shape is
		# asserted on every builder and not just the first one.
		self.assertTrue(payload["results"])
		seen = {row["type"] for row in payload["results"]}
		self.assertEqual(seen, {"Guest", "Reservation", "Stay", "Guest Folio"})

		for row in payload["results"]:
			self.assertEqual(set(row), set(search_service.RESULT_KEYS))
			self.assertIn(row["type"], search_service.SEARCHABLE_TYPES)
			self.assertTrue(row["id"])
			self.assertTrue(row["primary_label"])
			# No key is ever None except `property`, which is genuinely absent
			# for a Guest; the string fields are "" instead so the client can
			# render them without a guard.
			for key in ("primary_label", "secondary_label", "status", "safe_summary"):
				self.assertIsInstance(row[key], str)

		# `route_target` is deliberately not in the contract: Vue route names
		# are the frontend's concern and naming them here would couple this
		# layer to the SPA.
		self.assertNotIn("route_target", payload["results"][0])

	def test_no_arbitrary_doctype_can_be_searched(self):
		"""The entity list is closed, not a caller-supplied argument."""
		self.assertEqual(
			search_service.SEARCHABLE_TYPES,
			("Guest", "Reservation", "Stay", "Hotel Room", "Guest Folio"),
		)
		self.assertEqual(tuple(search_service._SEARCHERS), search_service.SEARCHABLE_TYPES)
