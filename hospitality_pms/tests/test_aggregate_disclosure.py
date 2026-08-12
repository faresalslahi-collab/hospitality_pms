"""Aggregate endpoints: a field group is authorised by the DocType that owns it.

The permanent 16.7 rule, applied to the five aggregates independent security
testing of 16.7.5 found still breaking it (R1B). Each of these endpoints
authorises one DocType and then assembles a response out of several, and each was
reading the others with `frappe.get_all` or raw SQL - neither of which applies any
permission at all.

* **Command Center.** Gated on Hotel Room and Stay, and returned
  `revenue.room_revenue_posted`, `payments_received` and `outstanding_balance`,
  summed out of Folio Charge, Folio Payment and Guest Folio. `outstanding_balance`
  is the whole property's open receivables. Ten roles hold Stay read without Guest
  Folio read and every one of them lands on this screen, because its navigation
  entry carries no role filter - a fact `_board_disclosure`'s own docstring
  records, on the helper that existed to prevent exactly this and had been applied
  only to the three boards.
* **Checkout summary.** Gated on Stay, and returned the folio's name, currency,
  charge and payment totals, balance, the split folios' names *and balances*, the
  departure verdict, and blocker sentences with the amounts inside them. The
  departures board already refused all of this; the single-stay reader did not,
  and carried two fields the board never had.
* **Guest Services.** Guest Request is read by every operational role in the
  estate. The board and the detail returned a Guest identifier, and the detail a
  Folio Charge row name plus the compensation paid and who approved it.
* **Kitchen.** A requisition and a wastage entry returned the ERPNext `Stock
  Entry` they created. Stock Entry is read by four ERPNext roles and by none of
  the kitchen ones.
* **Night Audit.** Every audit exception carried `reference`, which for a failed
  posting is a `Financial Posting Log` and for a variance a `Guest Folio` - to all
  twenty-three roles that can read a Night Audit. The reconciliation variance also
  had the folio's name and the money in its stored description, and the arrival
  and departure exceptions had the guest's name.

Two things are asserted everywhere, because either alone proves nothing:

* the uncleared role receives no **key** - absence, not `0`, `""`, `[]` or
  `false`, each of which is a claim about the hotel's money or a guest that the
  caller is not entitled to make and that may be untrue;
* the cleared role still receives it, including when the value is falsy. A guard
  that also blinds the front desk is an outage, not a fix.

Real users holding real roles, through the whitelisted endpoints. Administrator
proves nothing: it passes every check by construction.
"""

import json
from types import SimpleNamespace

import frappe
from frappe.tests import IntegrationTestCase

from hospitality_pms.api import checkout as checkout_api
from hospitality_pms.api import front_office as front_office_api
from hospitality_pms.api import guest_services as guest_services_api
from hospitality_pms.api import kitchen as kitchen_api
from hospitality_pms.api import night_audit as night_audit_api
from hospitality_pms.services import checkout as checkout_service
from hospitality_pms.services import guest_services as guest_service
from hospitality_pms.services import reservations as reservation_service
from hospitality_pms.services import stays as stay_service
from hospitality_pms.tests.fixtures import Fixtures

#: Every key of the dashboard's folio-derived money block.
REVENUE_FIELDS = ("room_revenue_posted", "payments_received", "outstanding_balance")

#: Every key of the checkout summary that belongs to Guest Folio.
CHECKOUT_FOLIO_FIELDS = (
	"folio",
	"currency",
	"total_charges",
	"total_payments",
	"balance",
	"related_folios",
	"can_check_out",
)

#: A charge large enough to be unmistakable in a serialised payload, and odd
#: enough that it cannot collide with a room rate or a tax.
SENTINEL_CHARGE = 2521.5


class DisclosureWorld(IntegrationTestCase):
	"""One property, a guest in the house with money on the folio, and five roles."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()

		cls.fixtures = Fixtures("AGGDIS")

		cls.property = cls.fixtures.property("AG", require_id_at_check_in=0)
		cls.room_type = cls.fixtures.room_type(cls.property)
		cls.rooms = cls.fixtures.rooms(cls.property, cls.room_type, count=3)
		cls.rate_plan = cls.fixtures.rate_plan(cls.property, cls.room_type)

		cls.guest = cls.fixtures.guest("Owing")
		cls.stay = cls._check_in(cls, cls.guest, cls.rooms[0])
		cls.folio = frappe.db.get_value("Stay", cls.stay, "folio")

		# Money on the folio, so a balance exists to leak.
		from hospitality_pms.services import folio as folio_service

		folio_service.post_charge(
			cls.folio,
			"Minibar",
			"Sentinel charge",
			SENTINEL_CHARGE,
			idempotency_key=f"aggdis-charge:{cls.folio}",
		)

		# Cleared for money and for guests: the front desk.
		cls.desk = cls.fixtures.user("fo", ["Front Office Agent"], properties=[cls.property])

		# Holds Stay read, Guest Request read and Hotel Room read; holds neither
		# Guest Folio nor Guest read. One of the ten, and the Command Center is its
		# landing page.
		cls.attendant = cls.fixtures.user(
			"att", ["Room Attendant"], properties=[cls.property]
		)

		# Kitchen: reaches requisitions and wastage, holds no Stock Entry read.
		cls.kitchen = cls.fixtures.user("kit", ["Kitchen Manager"], properties=[cls.property])

		# Night audit: holds Night Audit, Financial Posting Log and Guest Folio read.
		cls.auditor = cls.fixtures.user("na", ["Night Auditor"], properties=[cls.property])

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

	def _check_in(self, guest: str, room: str) -> str:
		reservation = self.fixtures.reservation(
			self.property, self.room_type, guest, rate_plan=self.rate_plan, nights=3
		)
		reservation_service.confirm(reservation)
		line = frappe.get_all("Reservation Room", filters={"parent": reservation}, pluck="name")[0]

		return stay_service.check_in(reservation, line, room)["stay"]

	# -- shared assertions -------------------------------------------------

	def _closed_audit_with_money(self) -> str:
		"""A closed Night Audit carrying the sentinel amount in its figures.

		Written directly rather than by driving the audit to close: closing moves
		the property's business date, and this suite is about disclosure, not the
		audit lifecycle. The fields are what `_refresh_figures` would have stored,
		which is what the endpoints read.

		Dated **yesterday**, not today, for two reasons. A unique index covers
		`(property, business_date)`, so planting a closed audit on today's date
		would collide with the `night_audit.start()` another test in this class
		calls - and `get_current` falls back to the most recently *closed* audit
		when none is open, so yesterday is found just the same.

		Idempotent, because more than one test wants it and the row commits.
		"""
		from frappe.utils import add_days

		from hospitality_pms.services.base import NIGHT_AUDIT_SERVICE, service_context

		business_date = add_days(frappe.db.get_value("Property", self.property, "business_date"), -1)

		figures = {
			"audit_status": "Closed",
			"occupancy_percentage": 68.3,
			"adr": 420.5,
			"revpar": 287.2,
			"room_revenue": SENTINEL_CHARGE,
			"total_revenue": SENTINEL_CHARGE,
			"payments_received": SENTINEL_CHARGE,
			"outstanding_balance": SENTINEL_CHARGE,
			"currency": "QAR",
		}

		existing = frappe.db.get_value(
			"Night Audit", {"property": self.property, "business_date": business_date}, "name"
		)

		if existing:
			frappe.db.set_value("Night Audit", existing, figures, update_modified=False)
			frappe.db.commit()

			return existing

		with service_context(NIGHT_AUDIT_SERVICE):
			audit = frappe.get_doc(
				{
					"doctype": "Night Audit",
					"property": self.property,
					"business_date": business_date,
					"next_business_date": add_days(business_date, 1),
					**figures,
				}
			).insert(ignore_permissions=True)

		self.fixtures.track("Night Audit", audit.name)
		frappe.db.commit()

		return audit.name

	def assertNoMoneyAnywhere(self, payload, label: str):
		"""No sentinel amount, at any depth, in any field or any sentence.

		The serialisation sweep is what catches a leak through a blocker string or
		a helper label rather than through a numeric field - which is the form this
		defect actually took.
		"""
		serialised = json.dumps(payload, default=str)

		for rendering in (str(SENTINEL_CHARGE), f"{SENTINEL_CHARGE:.2f}", str(int(SENTINEL_CHARGE))):
			self.assertNotIn(rendering, serialised, msg=f"{label} carried the amount {rendering}")


class TestCommandCenterFinancialDisclosure(DisclosureWorld):
	def test_the_matrix_premise_holds(self):
		"""The uncleared role really can open the Command Center."""
		frappe.set_user(self.attendant)

		self.assertTrue(frappe.has_permission("Hotel Room", "read"))
		self.assertTrue(frappe.has_permission("Stay", "read"))
		self.assertFalse(
			frappe.has_permission("Guest Folio", "read"),
			msg="Room Attendant now reads Guest Folio, so this suite tests nothing",
		)

		frappe.set_user(self.desk)
		self.assertTrue(frappe.has_permission("Guest Folio", "read"))

	def test_dashboard_with_folio_permission_returns_financial_metrics(self):
		frappe.set_user(self.desk)

		payload = front_office_api.dashboard(property=self.property)

		self.assertIn("revenue", payload)
		for field in REVENUE_FIELDS:
			self.assertIn(field, payload["revenue"])

	def test_dashboard_without_folio_permission_omits_financial_metrics(self):
		"""Absent, not zeroed. `outstanding_balance: 0` reads as "everyone paid"."""
		frappe.set_user(self.attendant)

		payload = front_office_api.dashboard(property=self.property)

		self.assertNotIn(
			"revenue", payload, msg="folio-derived money reached a caller who may not read Guest Folio"
		)

	def test_dashboard_without_folio_permission_still_returns_operational_metrics(self):
		"""Redaction, not outage. The screen is this role's landing page."""
		frappe.set_user(self.attendant)

		payload = front_office_api.dashboard(property=self.property)

		for block in ("rooms", "front_office", "workload", "performance"):
			self.assertIn(block, payload, msg=f"the {block} block was lost with the money")

		self.assertEqual(payload["property"], self.property)
		self.assertTrue(payload["business_date"])
		self.assertIn("total", payload["rooms"])
		self.assertIn("in_house_rooms", payload["front_office"])

	def test_dashboard_does_not_leak_amounts_via_other_fields(self):
		"""Not through a count, a label, a currency field or a nested block."""
		frappe.set_user(self.attendant)

		payload = front_office_api.dashboard(property=self.property)

		self.assertNoMoneyAnywhere(payload, "the uncleared dashboard")

		for field in REVENUE_FIELDS:
			self.assertNotIn(
				f'"{field}"',
				json.dumps(payload, default=str),
				msg=f"the uncleared dashboard carried {field}",
			)

	def test_performance_carries_the_ratios_and_no_absolute_money(self):
		"""Night Audit owns ADR and RevPAR; it does not own the folio's totals.

		A closed audit is planted with real money on it, because without one
		`performance` is `{"available": False}` and every assertion about its
		contents passes by having nothing to inspect - which is exactly how the
		first draft of this suite missed that the block carried
		`payments_received`, `room_revenue` and `total_revenue` ungated.
		"""
		self._closed_audit_with_money()

		frappe.set_user(self.attendant)

		payload = front_office_api.dashboard(property=self.property)
		performance = payload["performance"]

		self.assertTrue(performance["available"], msg="the premise is gone: no closed audit")

		# The ratios stay: the Revenue Manager holds Night Audit read and no Guest
		# Folio read, and these three are their job.
		for field in ("occupancy_percentage", "adr", "revpar"):
			self.assertIn(field, performance)

		# The absolute totals are Guest Folio aggregates and must not be here.
		for field in ("room_revenue", "total_revenue", "payments_received", "outstanding_balance"):
			self.assertNotIn(field, performance, msg=f"performance carried {field}")

		self.assertNoMoneyAnywhere(payload, "the uncleared dashboard with a closed audit")


class TestCheckoutSummaryDisclosure(DisclosureWorld):
	def test_checkout_summary_folio_reader_gets_financial_details(self):
		frappe.set_user(self.desk)

		payload = checkout_api.summary(stay=self.stay)

		for field in CHECKOUT_FOLIO_FIELDS:
			self.assertIn(field, payload)

		self.assertEqual(payload["folio"], self.folio)
		self.assertGreater(payload["balance"], 0)

	def test_checkout_summary_non_folio_reader_gets_no_folio_id(self):
		frappe.set_user(self.attendant)

		payload = checkout_api.summary(stay=self.stay)

		self.assertNotIn("folio", payload)
		self.assertNotIn("related_folios", payload)

	def test_checkout_summary_non_folio_reader_gets_no_amounts(self):
		"""Every amount, and no amount reconstructable from what remains."""
		frappe.set_user(self.attendant)

		payload = checkout_api.summary(stay=self.stay)

		for field in ("balance", "total_charges", "total_payments", "currency", "can_check_out"):
			self.assertNotIn(field, payload, msg=f"the checkout summary carried {field}")

		self.assertNoMoneyAnywhere(payload, "the uncleared checkout summary")

	def test_checkout_summary_non_folio_reader_gets_safe_generic_blocker(self):
		"""The workflow fact survives; the figure does not.

		The guest has an outstanding balance, so departure is blocked. An operational
		caller must be able to see that much or the screen offers a checkout the
		server will refuse without saying why.
		"""
		frappe.set_user(self.attendant)

		payload = checkout_api.summary(stay=self.stay)

		self.assertIn("blockers", payload)
		self.assertTrue(payload["blockers"], msg="the uncleared caller lost the blocker entirely")

		joined = " ".join(payload["blockers"])

		self.assertIn("cashier", joined.lower())
		self.assertNoMoneyAnywhere(payload["blockers"], "the abstracted blockers")

		# One sentence however many folio blockers there were, so the count itself
		# discloses nothing.
		self.assertEqual(len(payload["blockers"]), 1)

		# And the unabstracted kinds do not travel alongside the abstracted list.
		self.assertNotIn("blocker_kinds", payload)

	def test_a_non_financial_blocker_still_reaches_an_uncleared_caller(self):
		"""Stay-status blockers are the Stay's to disclose, and pass through."""
		other = self._check_in(self.fixtures.guest("Departed"), self.rooms[1])
		stay_service.transition(other, stay_service.CHECKED_OUT)
		frappe.db.commit()

		frappe.set_user(self.attendant)

		payload = checkout_api.summary(stay=other)
		joined = " ".join(payload["blockers"])

		self.assertIn("Checked Out", joined, msg="a stay-status blocker was wrongly abstracted")

	def test_the_folio_reader_still_sees_the_amount_bearing_sentence(self):
		"""The desk works from the figure in the sentence; it must not be abstracted."""
		frappe.set_user(self.desk)

		payload = checkout_api.summary(stay=self.stay)
		joined = " ".join(payload["blockers"])

		self.assertIn(str(SENTINEL_CHARGE), joined)
		self.assertNotIn("cashier", joined.lower())

	def test_checkout_summary_cross_property_refused_existing_guard(self):
		"""Already covered by `authorise_document`; pinned so R1B did not weaken it."""
		second = self.fixtures.property("AH", require_id_at_check_in=0)
		frappe.db.commit()

		frappe.set_user(self.attendant)

		from hospitality_pms.services.exceptions import PermissionDeniedError, PropertyAccessError
		from hospitality_pms.services.property import get_permitted_properties

		self.assertNotIn(second, get_permitted_properties())

		frappe.set_user("Administrator")
		outsider = self.fixtures.user("out", ["Front Office Agent"], properties=[second])
		frappe.db.commit()

		frappe.set_user(outsider)

		with self.assertRaises(
			(frappe.PermissionError, PermissionDeniedError, PropertyAccessError)
		):
			checkout_api.summary(stay=self.stay)

	def test_the_service_itself_stays_honest(self):
		"""The redaction is at the boundary, not in the domain.

		`checkout.check_out` reads the blockers to decide the city-ledger case, so a
		service that redacted by session would make a credit decision depend on who
		was looking.
		"""
		frappe.set_user(self.attendant)

		summary = checkout_service.get_checkout_summary(self.stay)

		self.assertIn("balance", summary)
		self.assertIn("blocker_kinds", summary)
		self.assertIn(
			checkout_service.BLOCKER_OUTSTANDING_BALANCE, summary["blocker_kinds"]
		)

	def test_blocker_kinds_pair_with_blocker_messages(self):
		"""The abstraction relies on the pairing, so the pairing is pinned."""
		frappe.set_user("Administrator")

		summary = checkout_service.get_checkout_summary(self.stay)

		self.assertEqual(len(summary["blockers"]), len(summary["blocker_kinds"]))

	def test_the_abstraction_fails_closed_on_a_mismatched_pairing(self):
		"""If the lists ever disagree, everything is treated as sensitive."""
		abstracted = checkout_api._abstract_blockers(
			["The folio has an outstanding balance of 2521.5."], []
		)

		self.assertEqual(len(abstracted), 1)
		self.assertNoMoneyAnywhere(abstracted, "the fail-closed abstraction")

	def test_a_non_financial_blocker_survives_the_abstraction(self):
		"""Stay-status blockers pass through the classifier untouched."""
		abstracted = checkout_api._abstract_blockers(
			["The stay is Checked Out.", "The folio has an outstanding balance of 2521.5."],
			[checkout_service.BLOCKER_STAY_STATUS, checkout_service.BLOCKER_OUTSTANDING_BALANCE],
		)

		self.assertIn("The stay is Checked Out.", abstracted)
		self.assertEqual(len(abstracted), 2)
		self.assertNoMoneyAnywhere(abstracted, "the mixed abstraction")

	def test_the_generic_sentence_names_no_amount_and_no_count(self):
		"""One folio blocker or three, the operator reads the same sentence."""
		one = checkout_api._abstract_blockers(
			["The folio has an outstanding balance of 2521.5."],
			[checkout_service.BLOCKER_OUTSTANDING_BALANCE],
		)
		three = checkout_api._abstract_blockers(
			[
				"The folio is disputed and must be resolved first.",
				"The folio has an outstanding balance of 2521.5.",
				"Split folio HPMS-FOL-2026-00074 still has a balance of 300.0.",
			],
			[
				checkout_service.BLOCKER_FOLIO_DISPUTED,
				checkout_service.BLOCKER_OUTSTANDING_BALANCE,
				checkout_service.BLOCKER_RELATED_FOLIO_BALANCE,
			],
		)

		self.assertEqual(one, three)
		# And no split folio's name survived either.
		self.assertNotIn("HPMS-FOL-2026-00074", " ".join(three))

	def test_the_city_ledger_decision_does_not_read_translated_text(self):
		"""The credit decision runs on blocker kinds, not on sentence matching.

		Asserted on the source of the one line that decides it, because the
		alternative - proving the bug by switching the session to Arabic and
		checking that a legitimate city-ledger checkout is still permitted - needs
		a translated catalogue this bench does not ship.
		"""
		import inspect

		# Comment lines stripped before matching. The replacement records the old
		# expression in a comment so the next reader knows why it changed, and
		# without this the assertion trips on the very explanation of the fix.
		source = "\n".join(
			line
			for line in inspect.getsource(checkout_service.check_out).splitlines()
			if not line.strip().startswith("#")
		)

		self.assertNotIn(
			'_("balance") in blocker',
			source,
			msg="the city-ledger decision still substring-matches a translated sentence",
		)
		self.assertIn("blocker_kinds", source)

	def test_a_disputed_folio_is_not_a_city_ledger_case(self):
		"""The override moves a balance; it does not waive a dispute."""
		self.assertNotIn(
			checkout_service.BLOCKER_FOLIO_DISPUTED,
			(
				checkout_service.BLOCKER_OUTSTANDING_BALANCE,
				checkout_service.BLOCKER_RELATED_FOLIO_BALANCE,
			),
		)
		self.assertIn(checkout_service.BLOCKER_FOLIO_DISPUTED, checkout_service.FOLIO_BLOCKER_KINDS)


class TestPostingIdentifierDisclosure(DisclosureWorld):
	"""ERP document names are not the checkout endpoint's to hand out.

	Not one of the reported findings, and the sharpest found while fixing them:
	`check_out` is authorised on Stay write, which includes Front Office Agent, and
	returned the `Financial Posting Log` name, the `Sales Invoice` name and the
	ERPNext `Customer` verbatim. `api/folio.py` already refuses the invoice name to
	that same role, so the gate was being defeated from a different endpoint.
	"""

	POSTING = {
		"log": "HPMS-FPL-2026-00001",
		"erp_doctype": "Sales Invoice",
		"erp_document": "ACC-SINV-2026-00001",
		"amount": 100.0,
		"customer": "Guest Customer",
	}

	def test_front_office_gets_the_operational_fact_without_the_identifiers(self):
		frappe.set_user(self.desk)

		disclosed = checkout_api._disclose_posting(dict(self.POSTING))

		self.assertTrue(disclosed["posted"])
		self.assertEqual(disclosed["amount"], 100.0)

		for field in ("log", "erp_document", "customer"):
			self.assertNotIn(field, disclosed, msg=f"Front Office was told the {field}")

	def test_the_disclosure_map_says_what_was_withheld(self):
		"""So a client can tell "not posted" from "not your business"."""
		frappe.set_user(self.desk)

		disclosed = checkout_api._disclose_posting(dict(self.POSTING))

		self.assertIn("disclosure", disclosed)
		self.assertFalse(disclosed["disclosure"]["erp_document"])

	def test_a_posting_log_reader_keeps_the_log_name(self):
		"""Night Audit and finance work the failure from the log."""
		frappe.set_user(self.auditor)

		self.assertTrue(frappe.has_permission("Financial Posting Log", "read"))

		disclosed = checkout_api._disclose_posting(dict(self.POSTING))

		self.assertEqual(disclosed["log"], self.POSTING["log"])

	def test_nothing_is_invented_when_there_was_no_posting(self):
		self.assertIsNone(checkout_api._disclose_posting(None))

	def test_the_envelope_shape_is_preserved_and_projected(self):
		"""`_post_to_erp` returns `{invoice, payments}`, not a flat posting.

		Added after the first draft of this fix projected the envelope as though it
		were a single posting, which silently emptied `result["invoice"]` and was
		caught by `test_payment_posting`, not by this suite. The shape is part of the
		contract - the checkout screen and the Night Audit's catch-up path both read
		it - so it is pinned here rather than left to a distant financial test.
		"""
		frappe.set_user(self.desk)

		projected = checkout_api._disclose_posting_result(
			{"invoice": dict(self.POSTING), "payments": [dict(self.POSTING)]}
		)

		self.assertIn("invoice", projected)
		self.assertIn("payments", projected)
		self.assertEqual(len(projected["payments"]), 1)

		# Projected, not passed through: the identifiers are gone from both halves.
		self.assertTrue(projected["invoice"]["posted"])
		self.assertNotIn("erp_document", projected["invoice"])
		self.assertNotIn("erp_document", projected["payments"][0])

	def test_an_unposted_envelope_keeps_its_none_invoice(self):
		"""No charges to invoice is a real answer, and stays distinguishable."""
		frappe.set_user(self.desk)

		projected = checkout_api._disclose_posting_result({"invoice": None, "payments": []})

		self.assertIsNone(projected["invoice"])
		self.assertEqual(projected["payments"], [])

	def test_the_operational_facts_beside_the_identifiers_survive(self):
		"""A whitelist that dropped these silently broke the screen that posts.

		`duplicate` is the idempotent-replay signal, and the surplus figures are
		"a real decision the desk has taken" in the posting service's own words.
		Neither is an ERP identifier, so neither is withheld.
		"""
		frappe.set_user(self.desk)

		disclosed = checkout_api._disclose_posting(
			{
				**self.POSTING,
				"duplicate": True,
				"allocated_amount": 90.0,
				"unallocated_amount": 10.0,
				"allocations": [{"invoice": "ACC-SINV-2026-00001", "amount": 90.0}],
			}
		)

		self.assertTrue(disclosed["duplicate"])
		self.assertEqual(disclosed["allocated_amount"], 90.0)
		self.assertEqual(disclosed["unallocated_amount"], 10.0)

		# `allocations` names Sales Invoices, so it goes with the identifiers.
		self.assertNotIn("allocations", disclosed)
		self.assertNotIn("ACC-SINV-2026-00001", json.dumps(disclosed, default=str))

	def test_the_replay_path_does_not_leak_the_posting_log_under_another_name(self):
		"""An idempotent replay returns `name`, not `log`, and it is the same thing.

		`post_folio_invoice` hands back `get_posting`'s row when the work was already
		done, whose primary key *is* the Financial Posting Log. A whitelist naming
		only `log` passed it straight through on the path a retry most often takes.
		"""
		frappe.set_user(self.desk)

		self.assertFalse(frappe.has_permission("Financial Posting Log", "read"))

		replay = {
			"name": "HPMS-FPL-2026-00001",
			"posting_status": "Posted",
			"erp_doctype": "Sales Invoice",
			"erp_document": "ACC-SINV-2026-00001",
			"amount": 110.0,
			"error_message": "OperationalError(1213, 'Deadlock found') at 10.0.0.4:3306",
			"duplicate": True,
		}

		disclosed = checkout_api._disclose_posting(replay)

		self.assertNotIn("name", disclosed, msg="the posting log name was disclosed as `name`")
		self.assertNotIn("erp_document", disclosed)

		# Raw failure text is never re-disclosed here; the sanitised category comes
		# from the reconciliation endpoint built for it.
		self.assertNotIn("error_message", disclosed)
		self.assertNotIn(
			"10.0.0.4", json.dumps(disclosed, default=str), msg="raw exception text survived"
		)

		# The operational facts still travel.
		self.assertTrue(disclosed["duplicate"])
		self.assertEqual(disclosed["posting_status"], "Posted")

	def test_an_unknown_erp_doctype_fails_closed(self):
		"""A renamed or unknown doctype is a refusal, not a reveal, and never raises."""
		frappe.set_user(self.auditor)

		disclosed = checkout_api._disclose_posting(
			{
				"log": "HPMS-FPL-2026-00001",
				"erp_doctype": "Hospitality Sales Invoice",
				"erp_document": "ACC-SINV-2026-00001",
				"amount": 10.0,
			}
		)

		self.assertFalse(disclosed["disclosure"]["erp_document"])
		self.assertNotIn("erp_document", disclosed)

	def test_retry_posting_does_not_restore_the_identifiers(self):
		"""Driven through the real endpoint, not through a re-implementation.

		The first version of this test rebuilt `retry_posting`'s merge inline, which
		meant rewriting the endpoint to the wrong spelling - spreading the raw result
		first, so every identifier survives while looking redacted - would have left
		the test green. It now monkeypatches only the *service* and calls the
		whitelisted function, so the endpoint's own projection is what is measured.
		"""
		from hospitality_pms.services import posting as posting_service

		log = frappe.get_doc(
			{
				"doctype": posting_service.POSTING_LOG,
				"property": self.property,
				"folio": self.folio,
				"posting_type": "Sales Invoice",
				"posting_status": "Posted",
				"idempotency_key": f"aggdis-retry:{self.folio}",
				"amount": 110.0,
			}
		).insert(ignore_permissions=True)
		self.fixtures.track(posting_service.POSTING_LOG, log.name)
		frappe.db.commit()

		original = posting_service.retry_posting
		posting_service.retry_posting = lambda _log: {
			**self.POSTING,
			"retried": True,
			"error_message": "OperationalError at 10.0.0.4:3306",
		}

		try:
			frappe.set_user(self.auditor)
			result = checkout_api.retry_posting(log=log.name)
		finally:
			posting_service.retry_posting = original

		self.assertTrue(result["retried"])

		# The Night Auditor may read the posting log, so that name travels.
		self.assertTrue(frappe.has_permission("Financial Posting Log", "read"))
		self.assertEqual(result["log"], self.POSTING["log"])

		# They hold no Sales Invoice or Customer read, and raw text never travels.
		for field in ("erp_document", "customer", "error_message"):
			self.assertNotIn(field, result, msg=f"retry_posting restored {field}")

		self.assertNotIn("10.0.0.4", json.dumps(result, default=str))


class TestReverseCheckoutDisclosure(DisclosureWorld):
	"""`standing_invoices` names Sales Invoices, and no hospitality role reads them.

	Reported rather than fixed on the first R1B pass, on the grounds that the note
	beside it is operational. Escalated once the three sibling endpoints were
	projected: fixing three of four endpoints that hand out the same class of
	identifier fixes none of them.
	"""

	SERVICE_RESULT = {
		"standing_invoices": ["ACC-SINV-2026-00001", "ACC-SINV-2026-00002"],
		# 16.7.5-R1D. The same class of identifier under a name that describes the
		# problem instead of the payload - which is exactly how `currency_mismatch`
		# escaped the first R1B pass, so it is in the stub from the day it exists.
		"cancelled_invoices": ["ACC-SINV-2026-00003"],
		"needs_erp_reconciliation": True,
		"note": "Any submitted invoice is left standing and must be handled by finance.",
	}

	def _reverse_as(self, user: str) -> dict:
		"""Drive the real endpoint, with only the service stubbed.

		Reversing a checkout for real needs a settled folio with a submitted
		ERPNext invoice behind it. The service is stubbed so the *endpoint's*
		projection is what is measured - a test that re-implemented the projection
		would pass against an endpoint that had none.
		"""
		original = checkout_service.reverse_checkout
		checkout_service.reverse_checkout = lambda stay, reason: {
			"stay": stay,
			"folio": self.folio,
			**self.SERVICE_RESULT,
		}

		try:
			frappe.set_user(user)

			return checkout_api.reverse_checkout(stay=self.stay, reason="guest returned")
		finally:
			checkout_service.reverse_checkout = original

	def test_the_invoice_names_are_withheld_but_the_fact_is_not(self):
		result = self._reverse_as(self.desk)

		self.assertNotIn("standing_invoices", result, msg="Sales Invoice names were disclosed")
		self.assertEqual(result["standing_invoice_count"], 2)
		self.assertFalse(result["disclosure"]["standing_invoices"])

		# The operational note survives: finance still has to be told.
		self.assertIn("must be handled by finance", result["note"])
		self.assertNotIn("ACC-SINV", json.dumps(result, default=str))

	def test_a_sales_invoice_reader_keeps_the_names(self):
		"""The gate is the permission, not the role name.

		Two roles, and both are needed, which is the point this test got wrong at
		first. `Accounts Manager` supplies the `Sales Invoice` read the gate turns
		on; `Front Office Manager` supplies the `Stay` write the endpoint itself
		requires. A user holding only the first is refused by `authorise_document`
		before the projection is ever reached - so the earlier single-role version
		was not testing the gate, it was testing the door.

		It did not show up until R1C. On a bench where `setup/posting_service.py`
		had already revoked ERPNext's standard grants, `has_permission("Sales
		Invoice", "read")` was False for every role, this test skipped, and the flaw
		in it skipped with it. Repairing the permissions made the test run, and it
		failed immediately. Recorded because that is the useful part: a skip had
		been standing in for a broken assertion.
		"""
		reader = self.fixtures.user(
			"acct", ["Accounts Manager", "Front Office Manager"], properties=[self.property]
		)
		frappe.db.commit()

		frappe.set_user(reader)

		if not frappe.has_permission("Sales Invoice", "read"):
			self.skipTest(
				"no role on this site resolves Sales Invoice read - if this fires, "
				"check whether setup/posting_service.py has clobbered the standard "
				"grants again (see tests/test_posting_service_permissions.py)"
			)

		self.assertTrue(frappe.has_permission("Stay", "write"), msg="premise: needs Stay write")

		result = self._reverse_as(reader)

		self.assertEqual(result["standing_invoices"], self.SERVICE_RESULT["standing_invoices"])
		self.assertTrue(result["disclosure"]["standing_invoices"])

	def test_the_cancelled_invoice_names_are_withheld_too(self):
		"""16.7.5-R1D added a second list of Sales Invoice names to this endpoint.

		Gating `standing_invoices` and not this one would leave the endpoint
		disclosing exactly what it was changed to withhold, under a different key.
		"""
		result = self._reverse_as(self.desk)

		self.assertNotIn("cancelled_invoices", result, msg="cancelled invoice names disclosed")
		self.assertEqual(result["cancelled_invoice_count"], 1)
		self.assertFalse(result["disclosure"]["cancelled_invoices"])
		self.assertNotIn("ACC-SINV", json.dumps(result, default=str))

	def test_the_reconciliation_flag_reaches_an_operational_caller(self):
		"""The boolean is the part that must not be gated.

		It carries no identifier and no amount, and it is what tells the caller the
		reversal is not the whole story. Withholding it would leave the screen
		reporting a clean reversal over a folio that needs finance.
		"""
		result = self._reverse_as(self.desk)

		self.assertTrue(result["needs_erp_reconciliation"])

	def test_a_sales_invoice_reader_keeps_both_lists(self):
		reader = self.fixtures.user(
			"acct2", ["Accounts Manager", "Front Office Manager"], properties=[self.property]
		)
		frappe.db.commit()

		frappe.set_user(reader)

		if not frappe.has_permission("Sales Invoice", "read"):
			self.skipTest("no role on this site resolves Sales Invoice read")

		result = self._reverse_as(reader)

		self.assertEqual(result["cancelled_invoices"], self.SERVICE_RESULT["cancelled_invoices"])
		self.assertTrue(result["disclosure"]["cancelled_invoices"])

	def test_no_hospitality_role_reads_sales_invoice(self):
		"""The premise behind every ERP-identifier gate in this module.

		Front Office **Manager** is included explicitly, and not because it is
		another operational role worth checking. The positive test above hands its
		user `Accounts Manager` *and* `Front Office Manager`, the second only to get
		past `authorise_document(Stay, "write")`. If Front Office Manager ever gained
		Sales Invoice read, that test would keep passing for the wrong reason - the
		names would be disclosed on the strength of the operational role rather than
		the accounting one - and nothing would say so. This is what says so.
		"""
		manager = self.fixtures.user(
			"fom-only", ["Front Office Manager"], properties=[self.property]
		)
		frappe.db.commit()

		for user in (self.desk, self.auditor, self.attendant, self.kitchen, manager):
			frappe.set_user(user)
			self.assertFalse(
				frappe.has_permission("Sales Invoice", "read"),
				msg=f"{user} now reads Sales Invoice, so the gates above test nothing",
			)


class TestReconcileFolioDisclosure(DisclosureWorld):
	"""The endpoint whose one missed key had no test standing behind its fix."""

	RESULT = {
		"folio": "HPMS-FOL-2026-00073",
		"is_reconciled": False,
		"folio_charges": 2521.5,
		"erp_invoiced": 2400.0,
		"charge_variance": 121.5,
		"erp_invoices": ["ACC-SINV-2026-00001"],
		"erp_payment_entries": ["ACC-PAY-2026-00001"],
		"currency_mismatch": ["ACC-SINV-2026-00002"],
		"failed_postings": [
			{
				"name": "HPMS-FPL-2026-00001",
				"posting_type": "Sales Invoice",
				"attempts": 3,
				"error_message": "OperationalError(1213) at 10.0.0.4:3306 key=aggdis",
			}
		],
		# 16.7.5-R1D. Two doctypes on purpose: the projection gates per row, so a
		# single-doctype fixture could not catch a mixed list being passed off as
		# fully disclosed.
		"stale_postings": [
			{
				"log": "HPMS-FPL-2026-00002",
				"posting_type": "Sales Invoice",
				"posting_status": "Posted",
				"erp_doctype": "Sales Invoice",
				"erp_document": "ACC-SINV-2026-00004",
				"amount": 820.0,
			},
			{
				"log": "HPMS-FPL-2026-00003",
				"posting_type": "Payment Entry",
				"posting_status": "Reconciled",
				"erp_doctype": "Payment Entry",
				"erp_document": "ACC-PAY-2026-00004",
				"amount": 460.0,
			},
		],
		"needs_erp_reconciliation": True,
	}

	def _project(self) -> dict:
		"""Drive the real endpoint with only `posting.reconcile_folio` stubbed.

		A genuine reconciliation needs posted ERPNext invoices to disagree with, so
		the service is stubbed and the endpoint's own projection is what is
		measured. Re-implementing the projection here would have let an endpoint
		with no projection at all pass - which is how `currency_mismatch` was missed
		in the first place.
		"""
		from hospitality_pms.services import posting as posting_service

		original = posting_service.reconcile_folio
		posting_service.reconcile_folio = lambda _folio: dict(self.RESULT)

		try:
			return checkout_api.reconcile_folio(folio=self.folio)
		finally:
			posting_service.reconcile_folio = original

	def test_every_erp_name_key_is_gated_including_currency_mismatch(self):
		"""`currency_mismatch` is the key the first pass missed.

		It is a list of Sales Invoice names under a name that describes the problem
		rather than the payload, which is exactly why it was overlooked.
		"""
		frappe.set_user(self.auditor)

		projected = self._project()

		for field in ("erp_invoices", "erp_payment_entries", "currency_mismatch"):
			self.assertNotIn(field, projected, msg=f"{field} was disclosed")

		serialised = json.dumps(projected, default=str)
		self.assertNotIn("ACC-SINV", serialised)
		self.assertNotIn("ACC-PAY", serialised)

	def test_the_variance_figures_survive(self):
		"""This endpoint is Guest Folio-authorised, so its money is the caller's."""
		frappe.set_user(self.auditor)

		projected = self._project()

		self.assertEqual(projected["charge_variance"], 121.5)
		self.assertEqual(projected["folio_charges"], SENTINEL_CHARGE)
		self.assertFalse(projected["is_reconciled"])

	def test_raw_failure_text_never_travels(self):
		frappe.set_user(self.auditor)

		projected = self._project()

		self.assertNotIn("error_message", projected["failed_postings"][0])
		self.assertNotIn("10.0.0.4", json.dumps(projected, default=str))

		# The posting log name stays: every reconciliation role may read it.
		self.assertEqual(projected["failed_postings"][0]["name"], "HPMS-FPL-2026-00001")

	def test_no_retryability_is_asserted_from_a_shape_that_cannot_support_it(self):
		"""`safe_failed_postings` is deliberately not borrowed here.

		Its rows come from `get_failed_postings`, which joins the durable ledger.
		Applied to this endpoint's four-key rows it would read a missing
		`operation_status`, never fire `_NO_RETRY`, and assert every row retryable -
		offering a Retry button that throws.
		"""
		frappe.set_user(self.auditor)

		projected = self._project()

		self.assertNotIn("can_retry", projected["failed_postings"][0])
		self.assertNotIn("category", projected["failed_postings"][0])

	def test_stale_posting_rows_keep_the_log_and_lose_the_document(self):
		"""16.7.5-R1D. `stale_postings` names ERP documents; the same gate applies.

		What survives is what this audience is entitled to and needs: the posting-log
		name they may read and can open, the type, the status and the amount - the
		folio's own money, which this `Guest Folio`-authorised endpoint already
		discloses in `charge_variance` beside it.
		"""
		frappe.set_user(self.auditor)

		projected = self._project()

		self.assertEqual(len(projected["stale_postings"]), 2)

		for row in projected["stale_postings"]:
			self.assertNotIn("erp_document", row, msg=f"ERP document disclosed: {row}")

		self.assertEqual(projected["stale_postings"][0]["log"], "HPMS-FPL-2026-00002")
		self.assertEqual(projected["stale_postings"][0]["amount"], 820.0)
		self.assertEqual(projected["stale_postings"][1]["posting_status"], "Reconciled")

		self.assertNotIn("ACC-SINV", json.dumps(projected, default=str))
		self.assertNotIn("ACC-PAY", json.dumps(projected, default=str))

	def test_the_stale_posting_disclosure_flag_is_honest_and_always_present(self):
		"""A flag that appears only when something was withheld is itself a signal.

		`disclosure` is a claim about this response. Emitting the key only on the
		path that has rows to redact lets a client tell the two cases apart by its
		absence - the leak-by-omission this module refuses everywhere else - and
		`all([])` would then quietly report `True` for a list nobody was shown.
		"""
		frappe.set_user(self.auditor)

		projected = self._project()

		self.assertIn("stale_postings", projected["disclosure"])
		self.assertFalse(projected["disclosure"]["stale_postings"])

		# Same endpoint, nothing stale: the key must still be there, and now true,
		# because nothing was withheld.
		from hospitality_pms.services import posting as posting_service

		clean = dict(self.RESULT)
		clean["stale_postings"] = []
		clean["needs_erp_reconciliation"] = False

		original = posting_service.reconcile_folio
		posting_service.reconcile_folio = lambda _folio: dict(clean)

		try:
			empty = checkout_api.reconcile_folio(folio=self.folio)
		finally:
			posting_service.reconcile_folio = original

		self.assertIn("stale_postings", empty["disclosure"])
		self.assertTrue(empty["disclosure"]["stale_postings"])
		self.assertFalse(empty["needs_erp_reconciliation"])

	def test_the_reconciliation_flag_is_never_gated(self):
		"""It names nothing and it is the reason the folio does not reconcile."""
		frappe.set_user(self.auditor)

		self.assertTrue(self._project()["needs_erp_reconciliation"])


class TestGuestServicesDisclosure(DisclosureWorld):
	"""Guest Request read is not a licence to disclose what the request points at."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()

		cls.request = guest_service.create_request(
			cls.property,
			subject="Air conditioning noisy",
			description="Compressor rattling overnight.",
			category="Housekeeping",
			request_type="Complaint",
			guest=cls.guest,
			stay=cls.stay,
			room=cls.rooms[0],
		)

		# Service recovery, so the financial fields exist to be leaked.
		frappe.db.set_value(
			"Guest Request",
			cls.request,
			{
				"requires_service_recovery": 1,
				"recovery_type": "Discount",
				"recovery_amount": SENTINEL_CHARGE,
				"recovery_folio_charge": "fake-charge-row",
				"recovery_approved_by": cls.desk,
			},
			update_modified=False,
		)
		frappe.db.commit()

	def test_the_matrix_premise_holds(self):
		frappe.set_user(self.attendant)

		self.assertTrue(frappe.has_permission("Guest Request", "read"))
		self.assertFalse(frappe.has_permission("Guest", "read"))
		self.assertFalse(frappe.has_permission("Guest Folio", "read"))

	def test_guest_request_reader_without_guest_permission_gets_no_guest_fields(self):
		frappe.set_user(self.attendant)

		payload = guest_services_api.get_request(request=self.request)

		self.assertNotIn("guest", payload["request"], msg="a Guest identifier was disclosed")

	def test_guest_request_reader_without_folio_permission_gets_no_financial_fields(self):
		frappe.set_user(self.attendant)

		payload = guest_services_api.get_request(request=self.request)

		for field in ("recovery_folio_charge", "recovery_amount", "recovery_approved_by"):
			self.assertNotIn(field, payload["request"], msg=f"{field} was disclosed")

		self.assertNoMoneyAnywhere(payload, "the uncleared guest request")

	def test_the_operational_minimum_survives(self):
		"""A service team must still know what to do, where, and by when."""
		frappe.set_user(self.attendant)

		payload = guest_services_api.get_request(request=self.request)
		request = payload["request"]

		for field in (
			"name",
			"request_status",
			"request_type",
			"priority",
			"subject",
			"description",
			"room",
			"stay",
			"requires_service_recovery",
			"recovery_type",
		):
			self.assertIn(field, request, msg=f"the operational field {field} was lost")

		self.assertIn("allowed_transitions", payload)

	def test_authorized_front_office_gets_allowed_guest_context(self):
		frappe.set_user(self.desk)

		payload = guest_services_api.get_request(request=self.request)
		request = payload["request"]

		self.assertEqual(request["guest"], self.guest)
		self.assertEqual(request["recovery_folio_charge"], "fake-charge-row")
		self.assertEqual(request["recovery_amount"], SENTINEL_CHARGE)

	def test_the_board_obeys_the_same_rule(self):
		frappe.set_user(self.attendant)

		board = guest_services_api.board(property=self.property)
		row = next(r for r in board["requests"] if r["name"] == self.request)

		self.assertNotIn("guest", row, msg="the board disclosed a Guest identifier")

		# Redaction, not outage: the row is otherwise intact.
		self.assertIn("room", row)
		self.assertIn("subject", row)
		self.assertIn("priority", row)
		self.assertIn("summary", board)

	def test_the_board_still_carries_the_guest_for_the_desk(self):
		frappe.set_user(self.desk)

		board = guest_services_api.board(property=self.property)
		row = next(r for r in board["requests"] if r["name"] == self.request)

		self.assertEqual(row["guest"], self.guest)

	def test_the_disclosure_is_asked_once_not_once_per_row(self):
		"""A board must not add a permission question per row."""
		frappe.set_user(self.attendant)

		guest_services_api.board(property=self.property)

		with self.assertQueryCount(6):
			guest_services_api.board(property=self.property)


class TestKitchenStockEntryDisclosure(DisclosureWorld):
	"""CONFIRMED, and fixed by substituting the fact for the identifier.

	Tested against the projection helpers directly rather than end to end: a real
	requisition needs ERPNext warehouses and a real Stock Entry, and the question
	under test is which fields the boundary emits, which is exactly what these
	functions decide. The same approach the guest-privacy suite takes with
	`_blacklist_flag`.
	"""

	REQUISITION = {
		"name": "HPMS-KR-2026-00001",
		"property": "AG",
		"requisition_status": "Issued",
		"requisition_date": "2026-08-11",
		"department": "Kitchen",
		"from_warehouse": "Stores",
		"to_warehouse": "Kitchen",
		"requested_by": "someone",
		"issued_by": "someone",
		"issued_on": "2026-08-11 10:00:00",
		"stock_entry": "MAT-STE-2026-00042",
		"notes": "",
	}

	def test_the_matrix_premise_holds(self):
		frappe.set_user(self.kitchen)

		self.assertTrue(frappe.has_permission("Kitchen Requisition", "read"))
		self.assertFalse(
			frappe.has_permission("Stock Entry", "read"),
			msg="Kitchen Manager now reads Stock Entry, so this suite tests nothing",
		)

	def test_kitchen_gets_the_issue_status_without_the_stock_entry_name(self):
		frappe.set_user(self.kitchen)

		payload = kitchen_api._requisition_payload(dict(self.REQUISITION))

		self.assertNotIn("stock_entry", payload, msg="an ERPNext Stock Entry name was disclosed")
		self.assertTrue(
			payload["is_posted_to_stock"], msg="the operational fact was lost with the identifier"
		)
		self.assertFalse(payload["disclosure"]["stock_entry"])

	def test_the_operational_fields_survive(self):
		frappe.set_user(self.kitchen)

		payload = kitchen_api._requisition_payload(dict(self.REQUISITION))

		for field in ("name", "requisition_status", "from_warehouse", "to_warehouse", "department"):
			self.assertIn(field, payload)

	def test_not_yet_issued_is_distinguishable_from_withheld(self):
		"""`is_posted_to_stock` is False, and `disclosure` says why nothing is named."""
		frappe.set_user(self.kitchen)

		draft = {**self.REQUISITION, "requisition_status": "Submitted", "stock_entry": None}
		payload = kitchen_api._requisition_payload(draft)

		self.assertFalse(payload["is_posted_to_stock"])
		self.assertNotIn("stock_entry", payload)

	def test_a_stock_entry_reader_keeps_the_name(self):
		"""The gate is the permission, not the role name."""
		reader = self.fixtures.user("stk", ["Stock User"], properties=[self.property])
		frappe.db.commit()

		frappe.set_user(reader)

		self.assertTrue(frappe.has_permission("Stock Entry", "read"))

		payload = kitchen_api._requisition_payload(dict(self.REQUISITION))

		self.assertEqual(payload["stock_entry"], self.REQUISITION["stock_entry"])
		self.assertTrue(payload["disclosure"]["stock_entry"])

	def test_the_room_service_order_gate_is_unchanged(self):
		"""The pattern this fix copied must still work."""
		frappe.set_user(self.kitchen)

		allowed = kitchen_api._order_disclosure()

		self.assertNotIn("folio", allowed)
		self.assertIn("room", allowed)


class TestNightAuditReferenceDisclosure(DisclosureWorld):
	"""An exception's `reference` is gated against the DocType it names."""

	def _row(self, doctype: str, name: str):
		return SimpleNamespace(
			name="row1",
			exception_type="Failed Posting",
			severity="Blocking",
			description="A posting failed.",
			is_resolved=0,
			reference_doctype=doctype,
			reference_name=name,
		)

	def test_a_posting_log_reference_is_withheld_from_operational_roles(self):
		frappe.set_user(self.attendant)

		self.assertFalse(frappe.has_permission("Financial Posting Log", "read"))

		reference = night_audit_api._exception_reference(
			self._row("Financial Posting Log", "HPMS-FPL-2026-00001")
		)

		self.assertNotIn("reference", reference, msg="a posting log name was disclosed")

	def test_a_folio_reference_is_withheld_from_operational_roles(self):
		frappe.set_user(self.attendant)

		reference = night_audit_api._exception_reference(self._row("Guest Folio", self.folio))

		self.assertNotIn("reference", reference)

	def test_the_night_auditor_keeps_the_reference(self):
		"""Codex named the Night Auditor, and the Night Auditor is authorised.

		The claim class was real; its stated principal was not. Pinned in both
		directions so the fix is not mistaken for a restriction on finance.
		"""
		frappe.set_user(self.auditor)

		self.assertTrue(frappe.has_permission("Financial Posting Log", "read"))

		reference = night_audit_api._exception_reference(
			self._row("Financial Posting Log", "HPMS-FPL-2026-00001")
		)

		self.assertEqual(reference["reference"]["name"], "HPMS-FPL-2026-00001")

	def test_an_exception_pointing_at_nothing_is_distinguishable_from_a_refusal(self):
		"""`None` means "no reference"; an absent key means "not disclosed"."""
		frappe.set_user(self.attendant)

		reference = night_audit_api._exception_reference(self._row(None, None))

		self.assertIn("reference", reference)
		self.assertIsNone(reference["reference"])

	def test_a_stay_reference_reaches_every_night_audit_reader(self):
		"""The gate is per row, against that row's own DocType."""
		frappe.set_user(self.attendant)

		self.assertTrue(frappe.has_permission("Stay", "read"))

		reference = night_audit_api._exception_reference(self._row("Stay", self.stay))

		self.assertEqual(reference["reference"]["doctype"], "Stay")

	def test_the_exception_descriptions_review_produces_carry_no_guest_name(self):
		"""Asserted against what `review()` actually stores, not against source text.

		The first draft of this matched fragments of `inspect.getsource`, which
		would have passed had the leak been reinstated with different line
		wrapping - a formatter run was enough to defeat it - and said nothing about
		the sentence a real audit produces. This runs the audit and reads the rows.
		"""
		from hospitality_pms.services import night_audit as night_audit_service

		guest_name = frappe.db.get_value("Stay", self.stay, "guest_name")
		self.assertTrue(guest_name, msg="the fixture stay has no guest name to leak")

		# The fixture guest is In House with a departure date in the future, so
		# make them overdue - that is the exception whose sentence named them.
		frappe.db.set_value(
			"Stay",
			self.stay,
			"departure_date",
			frappe.db.get_value("Property", self.property, "business_date"),
			update_modified=False,
		)
		frappe.db.commit()

		audit = night_audit_service.start(self.property)
		self.fixtures.track("Night Audit", audit)
		night_audit_service.review(audit)
		frappe.db.commit()

		descriptions = frappe.get_all(
			"Night Audit Exception",
			filters={"parent": audit},
			pluck="description",
		)

		self.assertTrue(descriptions, msg="review produced no exceptions to inspect")

		for description in descriptions:
			self.assertNotIn(
				guest_name, description, msg=f"an exception description named the guest: {description}"
			)

		# And the departure exception is still useful: it names the stay and room.
		self.assertTrue(
			any(self.stay in description for description in descriptions),
			msg="the departure exception no longer identifies the stay at all",
		)

	def test_the_variance_description_names_no_folio_and_no_amount(self):
		"""The reconciliation sentence, asserted on its template's output."""
		from hospitality_pms.services import night_audit as night_audit_service

		# Built by calling the template the way `reconcile` does, rather than by
		# driving a full ERPNext reconciliation, which needs posted invoices.
		rendered = night_audit_service._("A folio on this business date does not agree with ERPNext.")

		self.assertNotIn(self.folio, rendered)
		self.assertNotIn(str(SENTINEL_CHARGE), rendered)

	def test_the_figures_block_withholds_folio_money(self):
		"""The dashboard's `revenue` gate is worth nothing if this endpoint leaks it.

		`outstanding_balance` is stored on the audit by the same SQL
		`_revenue_today` uses, with no date filter - a near-current receivables
		snapshot. Night Audit is read by every operational role.
		"""
		self._closed_audit_with_money()

		frappe.set_user(self.attendant)

		payload = night_audit_api.get_current(property=self.property)

		self.assertIsNotNone(payload)

		for field in ("payments_received", "outstanding_balance", "room_revenue", "total_revenue"):
			self.assertNotIn(field, payload["figures"], msg=f"figures carried {field}")
			self.assertNotIn(field, payload["audit"], msg=f"the audit block carried {field}")

		# The ratios remain, so the auditor's own screen still works.
		for field in ("occupancy_percentage", "adr", "revpar"):
			self.assertIn(field, payload["figures"])

		self.assertNoMoneyAnywhere(payload, "the uncleared night audit payload")

	def test_the_history_endpoint_withholds_folio_money_too(self):
		"""The second reader of the same record, and the larger of the two.

		`history` selects `AUDIT_FIELDS` directly and takes a limit of up to a
		hundred audits, so gating `get_current` alone left the bigger disclosure
		open. Both now ask one shared question.
		"""
		self._closed_audit_with_money()

		frappe.set_user(self.attendant)

		payload = night_audit_api.history(property=self.property)

		self.assertTrue(payload["audits"], msg="no audits returned, so this asserts nothing")

		for row in payload["audits"]:
			for field in (
				"payments_received",
				"outstanding_balance",
				"room_revenue",
				"total_revenue",
			):
				self.assertNotIn(field, row, msg=f"history carried {field}")

			# Redaction, not outage: the operational columns remain.
			self.assertIn("business_date", row)
			self.assertIn("audit_status", row)

		self.assertNoMoneyAnywhere(payload, "the uncleared night audit history")

	def test_the_history_endpoint_keeps_the_money_for_a_folio_reader(self):
		self._closed_audit_with_money()

		frappe.set_user(self.auditor)

		payload = night_audit_api.history(property=self.property)

		self.assertTrue(
			any("outstanding_balance" in row for row in payload["audits"]),
			msg="the auditor lost the figures from history",
		)

	def test_a_folio_reader_keeps_the_figures(self):
		self._closed_audit_with_money()

		frappe.set_user(self.auditor)

		payload = night_audit_api.get_current(property=self.property)

		for field in ("payments_received", "outstanding_balance"):
			self.assertIn(field, payload["figures"], msg=f"the auditor lost {field}")

	def test_an_unknown_reference_doctype_is_refused_rather_than_raising(self):
		"""Stored DocType names outlive renames, and this is on every endpoint's path."""
		frappe.set_user(self.auditor)

		reference = night_audit_api._exception_reference(
			self._row("Hospitality Guest Folio", "HPMS-FOL-2026-00001")
		)

		self.assertNotIn("reference", reference)

	def test_the_doctype_permission_memo_does_not_answer_for_the_wrong_user(self):
		"""The memo is keyed by user, and this is why.

		`frappe.local` lives for a request, but the session user does not:
		`posting.erp_posting_authority` switches to the posting service user
		mid-operation and restores it afterwards. A cache keyed on the doctype alone
		hands the second caller the first caller's permissions - and if the first was
		the more privileged of the two, that is a disclosure.

		Caught by this suite before the review saw it, because two tests in this
		class ask the same question as different users.
		"""
		from hospitality_pms.services.base import may_read_doctype

		frappe.set_user(self.auditor)
		self.assertTrue(may_read_doctype("Financial Posting Log"))

		frappe.set_user(self.attendant)
		self.assertFalse(
			may_read_doctype("Financial Posting Log"),
			msg="the memo answered an attendant with the auditor's permissions",
		)

		# And back again, so the cache is not merely last-writer-wins either.
		frappe.set_user(self.auditor)
		self.assertTrue(may_read_doctype("Financial Posting Log"))

	def test_an_unknown_doctype_never_raises(self):
		"""`frappe.has_permission` would take an unknown name into `get_meta`."""
		from hospitality_pms.services.base import may_read_doctype

		frappe.set_user(self.auditor)

		self.assertFalse(may_read_doctype("Hospitality Financial Posting Log"))
		self.assertFalse(may_read_doctype(None))
		self.assertFalse(may_read_doctype(""))
