"""The closed business date, and who is allowed to move it.

Three things this covers, all of them boundaries around a date the hotel has
already reported on:

* `PMS Settings.block_posting_after_close` was proven dead - the flag existed
  and was read nowhere, so a front-desk charge could be back-dated into a day
  whose Night Audit had closed and whose revenue had already been reported.
* Night Audit endpoints checked `Night Audit` write permission and nothing
  else, so neither the property boundary Wave 1 established nor the auditor
  role applied at the endpoint.
* Every field the close gate reads is `read_only` on the DocType, which hides
  it in a form and stops nothing else. The people holding Night Audit write are
  precisely the people the gate constrains, so those fields cannot also be
  theirs to fill in.
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days

from hospitality_pms.services import folio as folio_service
from hospitality_pms.services import night_audit as audit_service
from hospitality_pms.services.exceptions import (
	FolioError,
	NightAuditError,
	PermissionDeniedError,
)
from hospitality_pms.tests.night_audit_world import NightAuditWorld

AUDIT = "Night Audit"


class BusinessDateTestCase(IntegrationTestCase):
	WORLD_CODE = "BD"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.world = NightAuditWorld(cls.__name__[:6].upper(), cls.WORLD_CODE)
		cls.start_date = cls.world.business_date

	@classmethod
	def tearDownClass(cls):
		cls.world.teardown()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.delete("Night Audit Exception", {"parenttype": AUDIT})
		frappe.db.delete(AUDIT, {"property": self.world.property})
		self.world.set_business_date(self.start_date)
		self.world.fixtures.set_setting("block_posting_after_close", 0)
		frappe.db.commit()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def _close_a_day(self):
		"""Close the current business date and return the date that was closed."""
		closed = self.world.business_date
		audit = audit_service.start(self.world.property)

		audit_service.review(audit)
		audit_service.post_room_charges(audit)
		audit_service.reconcile(audit)
		audit_service.close(audit)

		frappe.db.commit()

		return closed


class TestBlockPostingAfterClose(BusinessDateTestCase):
	WORLD_CODE = "BC"

	def test_normal_charge_refused_on_closed_business_date(self):
		"""The setting the sweep found dead."""
		self.world.fixtures.set_setting("block_posting_after_close", 1)
		closed = self._close_a_day()

		guest = self.world.fixtures.guest("Backdater")
		folio = self.world.fixtures.folio(self.world.property, guest)

		with self.assertRaises(FolioError) as caught:
			folio_service.post_charge(
				folio,
				"Minibar",
				"Back-dated into a closed day",
				40,
				idempotency_key=f"{self.world.tag}:bd:1",
				business_date=closed,
			)

		self.assertIn("closed", str(caught.exception).lower())

	def test_normal_payment_refused_on_closed_business_date(self):
		self.world.fixtures.set_setting("block_posting_after_close", 1)
		closed = self._close_a_day()

		guest = self.world.fixtures.guest("Backpayer")
		folio = self.world.fixtures.folio(self.world.property, guest)

		with self.assertRaises(FolioError):
			folio_service.post_payment(
				folio,
				40,
				"Cash",
				idempotency_key=f"{self.world.tag}:bd:2",
				business_date=closed,
			)

	def test_charge_on_the_open_business_date_is_unaffected(self):
		"""Only the closed day is fenced off; today carries on as normal."""
		self.world.fixtures.set_setting("block_posting_after_close", 1)
		self._close_a_day()

		guest = self.world.fixtures.guest("Today")
		folio = self.world.fixtures.folio(self.world.property, guest)

		result = folio_service.post_charge(
			folio,
			"Minibar",
			"Today's water",
			40,
			idempotency_key=f"{self.world.tag}:bd:3",
		)

		self.assertFalse(result["duplicate"])

	def test_setting_disabled_preserves_allowed_behavior(self):
		"""With the switch off, nothing changes - existing role controls still apply."""
		self.world.fixtures.set_setting("block_posting_after_close", 0)
		closed = self._close_a_day()

		guest = self.world.fixtures.guest("Permitted")
		folio = self.world.fixtures.folio(self.world.property, guest)

		result = folio_service.post_charge(
			folio,
			"Minibar",
			"Back-dated, but permitted",
			40,
			idempotency_key=f"{self.world.tag}:bd:4",
			business_date=closed,
		)

		self.assertFalse(result["duplicate"])

	def test_privileged_adjustment_may_still_correct_a_closed_day(self):
		"""Corrections must stay possible, or a mistake becomes permanent.

		An adjustment already demands an elevated role and a written reason,
		which is the difference between correcting a closed day and quietly
		back-dating into one.
		"""
		self.world.fixtures.set_setting("block_posting_after_close", 1)
		closed = self._close_a_day()

		guest = self.world.fixtures.guest("Corrected")
		folio = self.world.fixtures.folio(self.world.property, guest)

		result = folio_service.post_charge(
			folio,
			"Adjustment",
			"Correcting a closed day",
			-25,
			idempotency_key=f"{self.world.tag}:bd:5",
			business_date=closed,
		)

		self.assertFalse(result["duplicate"])

	def test_another_propertys_closed_date_does_not_block(self):
		"""The fence is per property; one hotel's close is not another's."""
		self.world.fixtures.set_setting("block_posting_after_close", 1)
		closed = self._close_a_day()

		other = self.world.fixtures.property("BX")
		guest = self.world.fixtures.guest("Elsewhere")
		other_folio = self.world.fixtures.folio(other, guest)
		frappe.db.commit()

		result = folio_service.post_charge(
			other_folio,
			"Minibar",
			"A different hotel entirely",
			40,
			idempotency_key=f"{self.world.tag}:bd:6",
			business_date=closed,
		)

		self.assertFalse(result["duplicate"])


class TestNightAuditAuthorization(BusinessDateTestCase):
	WORLD_CODE = "BA"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()

		cls.auditor = cls.world.fixtures.user(
			"auditor", ["Night Auditor"], properties=[cls.world.property]
		)
		# Holds Night Audit write by the approved matrix, and is not an auditor.
		cls.finance = cls.world.fixtures.user(
			"finance", ["Finance Manager"], properties=[cls.world.property]
		)
		cls.front_desk = cls.world.fixtures.user(
			"desk", ["Front Office Agent"], properties=[cls.world.property]
		)

		frappe.db.commit()

	def test_unauthorized_role_cannot_close_or_reopen(self):
		"""Night Audit write is not the same authority as closing the day."""
		from hospitality_pms.api import night_audit as audit_api

		audit = audit_service.start(self.world.property)
		audit_service.review(audit)
		audit_service.post_room_charges(audit)
		audit_service.reconcile(audit)
		frappe.db.commit()

		frappe.set_user(self.finance)

		with self.assertRaises(PermissionDeniedError):
			audit_api.close(audit=audit)

	def test_front_desk_cannot_run_the_audit(self):
		from hospitality_pms.api import night_audit as audit_api

		audit = audit_service.start(self.world.property)
		frappe.db.commit()

		frappe.set_user(self.front_desk)

		with self.assertRaises(PermissionDeniedError):
			audit_api.review(audit=audit)

	def test_auditor_from_another_property_is_refused(self):
		"""Wave 1's property boundary applies to the audit endpoints too."""
		from hospitality_pms.api import night_audit as audit_api

		other = self.world.fixtures.property("BY")
		outsider = self.world.fixtures.user(
			"otheraud", ["Night Auditor"], properties=[other]
		)

		audit = audit_service.start(self.world.property)
		frappe.db.commit()

		frappe.set_user(outsider)

		with self.assertRaises((PermissionDeniedError, frappe.PermissionError)):
			audit_api.review(audit=audit)

	def test_the_auditor_can_run_the_audit(self):
		from hospitality_pms.api import night_audit as audit_api

		audit = audit_service.start(self.world.property)
		frappe.db.commit()

		frappe.set_user(self.auditor)

		result = audit_api.review(audit=audit)

		self.assertTrue(result["result"]["audit"])


class TestAuditDocumentIntegrity(BusinessDateTestCase):
	"""Part 14 — the close gate reads fields nobody may hand-write."""

	WORLD_CODE = "BI"

	def test_generic_save_cannot_fake_completion_markers(self):
		audit = audit_service.start(self.world.property)
		frappe.db.commit()

		doc = frappe.get_doc(AUDIT, audit)
		doc.posting_completed_on = frappe.utils.now_datetime()
		doc.reconciliation_completed_on = frappe.utils.now_datetime()

		with self.assertRaises(NightAuditError):
			doc.save(ignore_permissions=True)

		frappe.db.rollback()

		self.assertIsNone(frappe.db.get_value(AUDIT, audit, "posting_completed_on"))

	def test_generic_save_cannot_force_the_status(self):
		audit = audit_service.start(self.world.property)
		frappe.db.commit()

		doc = frappe.get_doc(AUDIT, audit)
		doc.audit_status = audit_service.READY_TO_CLOSE

		with self.assertRaises(NightAuditError):
			doc.save(ignore_permissions=True)

		frappe.db.rollback()

		self.assertEqual(frappe.db.get_value(AUDIT, audit, "audit_status"), audit_service.OPEN)

	def test_generic_save_cannot_rewrite_revenue(self):
		audit = audit_service.start(self.world.property)
		frappe.db.commit()

		doc = frappe.get_doc(AUDIT, audit)
		doc.room_revenue = 99999

		with self.assertRaises(NightAuditError):
			doc.save(ignore_permissions=True)

		frappe.db.rollback()

	def test_generic_save_cannot_move_the_audits_business_date(self):
		audit = audit_service.start(self.world.property)
		frappe.db.commit()

		doc = frappe.get_doc(AUDIT, audit)
		doc.business_date = add_days(self.world.business_date, -5)

		with self.assertRaises(NightAuditError):
			doc.save(ignore_permissions=True)

		frappe.db.rollback()

	def test_notes_remain_editable(self):
		"""The guard is narrow: annotating the day is not declaring it done."""
		audit = audit_service.start(self.world.property)
		frappe.db.commit()

		doc = frappe.get_doc(AUDIT, audit)
		doc.notes = "Handover: two late arrivals expected."
		doc.save(ignore_permissions=True)

		self.assertIn("Handover", frappe.db.get_value(AUDIT, audit, "notes"))

	def test_the_property_business_date_is_service_owned(self):
		"""Only the Night Audit may move it - the pre-existing Property guard."""
		from hospitality_pms.services.exceptions import ConfigurationError

		doc = frappe.get_doc("Property", self.world.property)
		doc.business_date = add_days(self.world.business_date, 3)

		with self.assertRaises(ConfigurationError):
			doc.save(ignore_permissions=True)

		frappe.db.rollback()


# ---------------------------------------------------------------------------
# Wave 6 — the operational day, everywhere a default is chosen
# ---------------------------------------------------------------------------


class OperationalDateTestCase(IntegrationTestCase):
	"""A property working a day the calendar has already left behind.

	The whole class of defect in one sentence: a hotel that has not yet run
	its night audit is still operating on the 8th, and every screen and
	endpoint that reaches for `nowdate()` tells it the 10th.
	"""

	WORLD_CODE = "W6"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()

		from hospitality_pms.tests.inventory_world import InventoryWorld

		cls.world = InventoryWorld(cls.__name__[:6].upper(), cls.WORLD_CODE, rooms=2)

	@classmethod
	def tearDownClass(cls):
		cls.world.teardown()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")
		self.world.fixtures.reset_property_records(
			self.world.property,
			("Folio Log", "Guest Folio", "Room Status Log", "Stay", "Reservation Log", "Reservation"),
		)

		# The premise: the operating day is two days behind the calendar.
		self.today = frappe.utils.getdate()
		self.operating_day = add_days(self.today, -2)
		self.world.set_business_date(self.operating_day)

		frappe.db.commit()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()


class TestReservationApiDates(OperationalDateTestCase):
	"""Part 4 — the legacy endpoint family defaulted to the calendar.

	`api.front_office.arrivals` already resolved the property's business date;
	`api.reservations.arrivals` reached for `nowdate()`. Both are whitelisted,
	both answer the same operational question, and they disagreed. The live
	frontend happens to call the correct one, which makes this a trap rather
	than an outage: the next caller picks whichever it finds.
	"""

	WORLD_CODE = "W7"

	def _arriving_today(self) -> str:
		"""A booking due to arrive on the *operating* day."""
		return self.world.confirmed(nights=2, arrival=self.operating_day)

	def test_reservation_api_arrivals_defaults_to_business_date(self):
		from hospitality_pms.api import reservations as reservation_api

		reservation = self._arriving_today()

		rows = reservation_api.arrivals(property=self.world.property)

		self.assertIn(
			reservation,
			[row["name"] for row in rows],
			msg="the arrivals list was taken from the calendar date, not the operating day",
		)

	def test_reservation_api_departures_defaults_to_business_date(self):
		from hospitality_pms.api import reservations as reservation_api

		reservation = self.world.confirmed(nights=2, arrival=add_days(self.operating_day, -2))
		self.world.check_in(reservation)

		rows = reservation_api.departures(property=self.world.property)

		self.assertIn(reservation, [row["name"] for row in rows])

	def test_reservation_api_calendar_defaults_to_business_date(self):
		from hospitality_pms.api import reservations as reservation_api

		self._arriving_today()

		result = reservation_api.calendar(property=self.world.property)

		self.assertEqual(
			frappe.utils.getdate(result["from_date"]),
			self.operating_day,
			msg="the calendar opened on the calendar date rather than the operating day",
		)

	def test_an_explicit_date_is_still_respected(self):
		"""Only the default changes; a caller asking for a day gets that day."""
		from hospitality_pms.api import reservations as reservation_api

		future = add_days(self.operating_day, 12)
		reservation = self.world.confirmed(nights=2, arrival=future)

		rows = reservation_api.arrivals(property=self.world.property, on_date=str(future))

		self.assertIn(reservation, [row["name"] for row in rows])

	def test_an_explicit_calendar_start_is_still_respected(self):
		from hospitality_pms.api import reservations as reservation_api

		future = add_days(self.operating_day, 12)

		result = reservation_api.calendar(property=self.world.property, from_date=str(future))

		self.assertEqual(frappe.utils.getdate(result["from_date"]), future)

	def test_both_endpoint_families_agree_on_the_default_day(self):
		"""Part 8 — one business rule, whichever public door is used."""
		from hospitality_pms.api import front_office as front_office_api
		from hospitality_pms.api import reservations as reservation_api

		reservation = self._arriving_today()

		legacy = [row["name"] for row in reservation_api.arrivals(property=self.world.property)]
		board = front_office_api.arrivals(property=self.world.property)

		self.assertIn(reservation, legacy)
		self.assertEqual(
			frappe.utils.getdate(board["business_date"]),
			self.operating_day,
			msg="the two families resolved different operational days",
		)


class TestContractDatePolicy(OperationalDateTestCase):
	"""Part 5, Decision A — validity is asked about a date, and which one matters."""

	WORLD_CODE = "W8"

	def _account(self, *, start=None, end=None) -> str:
		doc = frappe.get_doc(
			{
				"doctype": "Corporate Account",
				"account_code": f"W6C{frappe.generate_hash(length=6).upper()}",
				"account_name": f"W6 Contract {frappe.generate_hash(length=6)}",
				"credit_status": "Active",
				"property": self.world.property,
				"account_type": "Corporate",
				"contract_start": start,
				"contract_end": end,
				"credit_limit": 10000,
			}
		).insert(ignore_permissions=True)

		self.world.fixtures.track("Corporate Account", doc.name)
		frappe.db.commit()

		return doc.name

	def test_contract_fallback_uses_business_date(self):
		"""A contract that runs out today is valid for today's business."""
		from hospitality_pms.services import corporate

		account = self._account(
			start=add_days(self.operating_day, -30), end=self.operating_day
		)

		corporate.assert_contract_valid(account)

	def test_a_contract_that_expired_before_the_business_date_is_refused(self):
		from hospitality_pms.services import corporate
		from hospitality_pms.services.exceptions import HospitalityPMSError

		account = self._account(
			start=add_days(self.operating_day, -30), end=add_days(self.operating_day, -1)
		)

		with self.assertRaises(HospitalityPMSError):
			corporate.assert_contract_valid(account)

	def test_future_stay_dates_are_evaluated_on_their_own_date(self):
		"""Pricing a March stay asks whether the contract covers March."""
		from hospitality_pms.services import corporate
		from hospitality_pms.services.exceptions import HospitalityPMSError

		account = self._account(
			start=add_days(self.operating_day, -30), end=add_days(self.operating_day, 5)
		)

		# Inside the contract on the business date, outside it for the stay.
		corporate.assert_contract_valid(account)

		with self.assertRaises(HospitalityPMSError):
			corporate.assert_contract_valid(account, on_date=add_days(self.operating_day, 20))

	def test_future_rate_lookup_uses_explicit_service_date(self):
		from hospitality_pms.services import corporate

		account = self._account(start=add_days(self.operating_day, -30))
		doc = frappe.get_doc("Corporate Account", account)
		doc.append(
			"negotiated_rates",
			{
				"room_type": self.world.room_type,
				"negotiated_rate": 77,
				"valid_from": add_days(self.operating_day, 10),
				"valid_upto": add_days(self.operating_day, 40),
			},
		)
		doc.save(ignore_permissions=True)
		frappe.db.commit()

		self.assertIsNone(
			corporate.get_negotiated_rate(account, self.world.room_type),
			msg="a rate that starts in ten days is not today's rate",
		)
		self.assertEqual(
			corporate.get_negotiated_rate(
				account, self.world.room_type, on_date=add_days(self.operating_day, 20)
			)["rate"],
			77,
		)


class TestGuestAlertDatePolicy(OperationalDateTestCase):
	"""Part 5, Decision B — `valid_upto` is a Date, so it is a business day."""

	WORLD_CODE = "W9"

	def _guest_with_alert(self, valid_upto) -> str:
		guest = self.world.fixtures.guest("Alerted")
		doc = frappe.get_doc("Guest", guest)
		doc.append(
			"alerts",
			{
				"alert_type": "Behaviour",
				"severity": "Critical",
				"alert": "Do not upgrade without a manager.",
				"is_active": 1,
				"valid_upto": valid_upto,
			},
		)
		doc.save(ignore_permissions=True)
		frappe.db.commit()

		return guest

	def test_an_alert_expiring_on_the_business_date_is_still_shown(self):
		"""The calendar has moved on; the hotel's day has not."""
		from hospitality_pms.services.guests import get_active_alerts

		guest = self._guest_with_alert(self.operating_day)

		alerts = get_active_alerts(guest, property_name=self.world.property)

		self.assertTrue(
			alerts, msg="an alert valid for the operating day was hidden by the calendar date"
		)

	def test_an_alert_that_expired_before_the_business_date_is_hidden(self):
		from hospitality_pms.services.guests import get_active_alerts

		guest = self._guest_with_alert(add_days(self.operating_day, -1))

		self.assertFalse(get_active_alerts(guest, property_name=self.world.property))

	def test_without_property_context_the_calendar_date_is_used(self):
		"""A guest is not owned by one property; there is no business day to use."""
		from hospitality_pms.services.guests import get_active_alerts

		guest = self._guest_with_alert(self.today)

		self.assertTrue(get_active_alerts(guest))


class TestFrontendDateContract(OperationalDateTestCase):
	"""Part 3 — what the screens default from, verified where it is produced.

	`Availability.vue` and `ReservationNew.vue` opened on `new Date()`. They now
	take their default from `property.businessDate`, which comes from
	`properties.get_property_context` — the same source WalkIn.vue already used.
	The rule itself is a pure function with its own checks
	(`frontend/src/utils/operationalDate.test.mjs`, `yarn test`); what has to
	hold on this side is that the context actually carries the operating day.
	"""

	WORLD_CODE = "WA"

	def test_property_context_carries_the_operating_day(self):
		from hospitality_pms.api import properties as property_api

		context = property_api.get_property_context()

		record = next(
			row for row in context["properties"] if row["name"] == self.world.property
		)

		self.assertEqual(
			frappe.utils.getdate(record["business_date"]),
			self.operating_day,
			msg="the screens cannot default to a day the context does not carry",
		)
		self.assertNotEqual(
			frappe.utils.getdate(record["business_date"]),
			self.today,
			msg="the fixture should put the operating day behind the calendar",
		)

	def test_the_walk_in_context_agrees(self):
		"""The screen that was already right must stay right."""
		from hospitality_pms.api import walk_in as walk_in_api

		context = walk_in_api.get_walk_in_context(property=self.world.property)

		self.assertEqual(
			frappe.utils.getdate(context["business_date"]), self.operating_day
		)


class TestBusinessDateMatrix(OperationalDateTestCase):
	"""Part 15 — every operational default, in one scenario, at once.

	The property is working the 8th; the calendar says the 10th. Each
	assertion below was its own defect class at some point in Phase 1, and
	checking them one suite at a time is how the last one gets missed. The
	inverse assertions matter as much: an explicit future date must survive,
	and a provider or audit timestamp must stay on the wall clock.
	"""

	WORLD_CODE = "WM"

	def _reserve_today(self) -> str:
		return self.world.confirmed(nights=2, arrival=self.operating_day)

	def test_every_operational_default_is_the_business_date(self):
		from hospitality_pms.api import front_office as front_office_api
		from hospitality_pms.api import properties as property_api
		from hospitality_pms.api import reservations as reservation_api
		from hospitality_pms.api import walk_in as walk_in_api
		from hospitality_pms.services import folio as folio_service
		from hospitality_pms.services.property import get_business_date

		# One booking checked in, so there is a folio to charge and a departure
		# on the board; a second left waiting, because arrivals lists what has
		# not arrived yet.
		staying = self._reserve_today()
		result = self.world.check_in(staying)
		awaiting = self.world.confirmed(nights=2, arrival=self.operating_day)

		expected = self.operating_day
		day = frappe.utils.getdate

		# What the screens default from.
		context = property_api.get_property_context()
		record = next(r for r in context["properties"] if r["name"] == self.world.property)
		walk_in = walk_in_api.get_walk_in_context(property=self.world.property)

		# What the boards answer.
		board_arrivals = front_office_api.arrivals(property=self.world.property)
		board_departures = front_office_api.departures(property=self.world.property)
		board_calendar = front_office_api.calendar(property=self.world.property)

		# What the legacy endpoint family answers.
		legacy_calendar = reservation_api.calendar(property=self.world.property)

		# What a charge is dated against.
		charge = folio_service.post_charge(
			result["folio"],
			"Minibar",
			"Matrix",
			10,
			idempotency_key=f"{self.world.tag}:matrix:1",
		)
		charge_business_date = frappe.db.get_value("Folio Charge", charge["row"], "business_date")

		checks = {
			"Availability / New Reservation default (property context)": day(record["business_date"]),
			"Walk-In context": day(walk_in["business_date"]),
			"Front Office arrivals": day(board_arrivals["business_date"]),
			"Front Office departures": day(board_departures["business_date"]),
			"Front Office calendar": day(board_calendar["from_date"]),
			"Reservation API calendar": day(legacy_calendar["from_date"]),
			"Folio charge business date": day(charge_business_date),
			"Property business date": day(get_business_date(self.world.property)),
		}

		wrong = {name: value for name, value in checks.items() if value != expected}

		self.assertFalse(
			wrong,
			msg=f"these defaulted to something other than the operating day {expected}: {wrong}",
		)

		# The two list endpoints answer with rows rather than a date, so they
		# are checked by what they return.
		self.assertIn(
			awaiting,
			[row["name"] for row in reservation_api.arrivals(property=self.world.property)],
			msg="Reservation API arrivals did not use the operating day",
		)

	def test_the_night_audit_opens_on_the_business_date(self):
		from hospitality_pms.services import night_audit as audit_service

		audit = audit_service.start(self.world.property)

		self.assertEqual(
			frappe.utils.getdate(frappe.db.get_value("Night Audit", audit, "business_date")),
			self.operating_day,
		)

	def test_an_explicit_future_date_is_never_pulled_back(self):
		"""The other half of the rule: only the default changes."""
		from hospitality_pms.api import front_office as front_office_api
		from hospitality_pms.api import reservations as reservation_api

		future = add_days(self.operating_day, 14)
		reservation = self.world.confirmed(nights=2, arrival=future)

		self.assertIn(
			reservation,
			[
				row["name"]
				for row in reservation_api.arrivals(property=self.world.property, on_date=str(future))
			],
		)
		self.assertEqual(
			frappe.utils.getdate(
				front_office_api.calendar(property=self.world.property, from_date=str(future))["from_date"]
			),
			future,
		)
		self.assertEqual(
			frappe.utils.getdate(
				reservation_api.calendar(property=self.world.property, from_date=str(future))["from_date"]
			),
			future,
		)

	def test_a_future_stay_is_priced_on_its_own_dates(self):
		"""Pricing next month asks about next month, not about today."""
		from hospitality_pms.services.rates import get_rate_breakdown

		future = add_days(self.operating_day, 30)

		breakdown = get_rate_breakdown(
			self.world.property,
			self.world.room_type,
			future,
			add_days(future, 2),
			rate_plan=self.world.rate_plan,
		)

		self.assertEqual(
			frappe.utils.getdate(breakdown["lines"][0]["rate_date"]),
			future,
			msg="a future stay was priced against a date that is not its own",
		)
		self.assertEqual(breakdown["nights"], 2)

	def test_audit_and_provider_timestamps_stay_on_the_wall_clock(self):
		"""A business date is not a timestamp, and must not become one.

		`started_on` records when a person did something. Dating it to the
		operating day would make the audit trail lie about real time.
		"""
		from hospitality_pms.services import night_audit as audit_service

		audit = audit_service.start(self.world.property)
		started_on = frappe.db.get_value("Night Audit", audit, "started_on")

		self.assertEqual(
			frappe.utils.getdate(started_on),
			self.today,
			msg="an audit-trail timestamp was moved onto the business date",
		)
