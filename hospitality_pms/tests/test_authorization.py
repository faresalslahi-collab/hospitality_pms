"""Cross-property authorization on named-document endpoints (P1-15, N2).

The framework's permission model works. `frappe.has_permission` on a Property-B
Stay correctly answers False for a Property-A user, `get_list` correctly hides
it, and `frappe.client.get` correctly refuses it. What the sweep found is that
several custom endpoints never asked.

They checked that the caller holds *some* permission on the DocType - which
every front office agent does, for every property - and then loaded the named
document and acted on it. So a Property-A agent read a Property-B guest's name,
room and balance, and posted a charge and a payment to their folio.

The fix is not a new permission model. It is calling the one that exists, on
the document actually named, at every endpoint that takes a document name.

Each refusal here is paired with the same operation against the user's own
property, because an authorization test that only proves things are refused
cannot tell a fix from an outage.
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt

from hospitality_pms.api import checkout as checkout_api
from hospitality_pms.api import folio as folio_api
from hospitality_pms.api import payments as payments_api
from hospitality_pms.api import reservations as reservations_api
from hospitality_pms.api import stays as stays_api
from hospitality_pms.services import reservations as reservation_service
from hospitality_pms.services import stays as stay_service
from hospitality_pms.services.exceptions import PermissionDeniedError
from hospitality_pms.tests.fixtures import Fixtures

#: Both shapes a refusal legitimately takes: Frappe's own document permission
#: error, and the app's property-access error. Which one fires depends on
#: whether the User Permission or the property resolution catches it first, and
#: the caller is refused either way.
REFUSALS = (frappe.PermissionError, PermissionDeniedError)

#: Values the Property-B records carry, so a leak is recognisable in a failure
#: message rather than merely a wrong number.
B_GUEST_FIRST_NAME = "Bravo"
B_BALANCE = 1234.56


class TestCrossPropertyAuthorization(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()

		cls.fixtures = Fixtures("AUTH")

		cls.property_a = cls.fixtures.property("PA", require_id_at_check_in=0)
		cls.property_b = cls.fixtures.property("PB", require_id_at_check_in=0)

		cls.stay_a, cls.folio_a = cls._world(cls, cls.property_a, "Alpha")
		cls.stay_b, cls.folio_b = cls._world(cls, cls.property_b, B_GUEST_FIRST_NAME)

		# A real Frappe User Permission on Property, which is the mechanism the
		# product relies on (HPMS-DEC-052) - not a test-only convention.
		cls.agent = cls.fixtures.user(
			"aonly",
			["Front Office Agent", "Finance Manager"],
			properties=[cls.property_a],
		)

		# Give the Property-B folio a balance worth leaking.
		from hospitality_pms.services import folio as folio_service

		folio_service.post_charge(
			cls.folio_b, "Room Charge", "Night", B_BALANCE, idempotency_key="auth:b:seed"
		)

		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		cls.fixtures.teardown()
		super().tearDownClass()

	def _world(self, property_name: str, guest_name: str) -> tuple[str, str]:
		"""A checked-in guest with a folio, built through the real orchestration."""
		room_type = self.fixtures.room_type(property_name)
		rooms = self.fixtures.rooms(property_name, room_type, count=2)
		rate_plan = self.fixtures.rate_plan(property_name, room_type)
		guest = self.fixtures.guest(guest_name)

		reservation = self.fixtures.reservation(
			property_name, room_type, guest, rate_plan=rate_plan, nights=2
		)
		reservation_service.confirm(reservation)

		line = frappe.get_all("Reservation Room", filters={"parent": reservation}, pluck="name")[0]
		result = stay_service.check_in(reservation, line, rooms[0])

		return result["stay"], result["folio"]

	def setUp(self):
		frappe.set_user(self.agent)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def _b_charges(self) -> int:
		return len(frappe.get_all("Folio Charge", filters={"parent": self.folio_b}))

	def _b_payments(self) -> int:
		return len(frappe.get_all("Folio Payment", filters={"parent": self.folio_b}))

	# -- the framework's own behaviour, as the control --------------------

	def test_framework_permission_already_refuses_the_other_property(self):
		"""Establishes that this is a bypass, not a gap in the permission model.

		If this failed, the User Permission fixture would be wrong and every
		other assertion in the suite would be meaningless.
		"""
		self.assertFalse(frappe.has_permission("Stay", "read", doc=self.stay_b))
		self.assertFalse(frappe.has_permission("Guest Folio", "write", doc=self.folio_b))

		self.assertTrue(frappe.has_permission("Stay", "read", doc=self.stay_a))
		self.assertTrue(frappe.has_permission("Guest Folio", "write", doc=self.folio_a))

	# -- P1-15: the read leak ---------------------------------------------

	def test_checkout_summary_refuses_other_property(self):
		"""The confirmed leak: guest name, room, balance and blockers."""
		with self.assertRaises(REFUSALS) as caught:
			checkout_api.summary(stay=self.stay_b)

		# Nothing about the other property's guest may appear even in the refusal.
		self.assertNotIn(B_GUEST_FIRST_NAME, str(caught.exception))
		self.assertNotIn(str(B_BALANCE), str(caught.exception))

	def test_checkout_summary_still_works_for_own_property(self):
		summary = checkout_api.summary(stay=self.stay_a)

		self.assertEqual(summary["stay"], self.stay_a)
		self.assertEqual(summary["folio"], self.folio_a)

	# -- N2: the write leak, which is worse -------------------------------

	def test_folio_charge_refuses_other_property(self):
		with self.assertRaises(REFUSALS):
			folio_api.post_charge(
				folio=self.folio_b,
				charge_type="Minibar",
				description="cross property",
				amount=99,
				idempotency_key="auth:cross:charge",
			)

		frappe.db.rollback()
		self.assertEqual(self._b_charges(), 1, msg="a cross-property charge was posted")

	def test_folio_payment_refuses_other_property(self):
		with self.assertRaises(REFUSALS):
			folio_api.post_payment(
				folio=self.folio_b,
				amount=50,
				payment_method="Cash",
				idempotency_key="auth:cross:payment",
			)

		frappe.db.rollback()
		self.assertEqual(self._b_payments(), 0, msg="a cross-property payment was recorded")

	def test_folio_charge_still_works_for_own_property(self):
		result = folio_api.post_charge(
			folio=self.folio_a,
			charge_type="Minibar",
			description="own property",
			amount=99,
			idempotency_key="auth:own:charge",
		)

		self.assertEqual(flt(result["amount"]), 99.0)

	def test_folio_payment_still_works_for_own_property(self):
		result = folio_api.post_payment(
			folio=self.folio_a,
			amount=50,
			payment_method="Cash",
			idempotency_key="auth:own:payment",
		)

		self.assertEqual(flt(result["amount"]), 50.0)

	# -- the adjacent endpoints found by the sweep -------------------------

	def test_folio_read_refuses_other_property(self):
		with self.assertRaises(REFUSALS):
			folio_api.get_folio(folio=self.folio_b)

	def test_folio_adjustment_refuses_other_property(self):
		"""Refused *before* the money moves, not by the serialiser afterwards.

		These endpoints post first and then return `get_folio(folio)`, which
		does check the document - so the request failed, but only after the row
		had been written and only because the reply could not be rendered. The
		row count is what distinguishes a guard from that accident.
		"""
		before = self._b_charges()

		with self.assertRaises(REFUSALS):
			folio_api.post_adjustment(
				folio=self.folio_b,
				amount=-10,
				description="cross property",
				reason="cross property",
				idempotency_key="auth:cross:adj",
			)

		self.assertEqual(
			self._b_charges(),
			before,
			msg="the adjustment reached the other property's folio before the refusal",
		)

	def test_folio_transition_refuses_other_property(self):
		before = frappe.db.get_value("Guest Folio", self.folio_b, "folio_status")

		with self.assertRaises(REFUSALS):
			folio_api.transition(folio=self.folio_b, target="Under Review")

		self.assertEqual(
			frappe.db.get_value("Guest Folio", self.folio_b, "folio_status"),
			before,
			msg="the other property's folio changed status before the refusal",
		)

	def test_folio_reverse_charge_refuses_other_property(self):
		row = frappe.get_all("Folio Charge", filters={"parent": self.folio_b}, pluck="name")[0]

		with self.assertRaises(REFUSALS):
			folio_api.reverse_charge(folio=self.folio_b, charge_row=row, reason="cross property")

	def test_folio_split_refuses_other_property(self):
		row = frappe.get_all("Folio Charge", filters={"parent": self.folio_b}, pluck="name")[0]

		with self.assertRaises(REFUSALS):
			folio_api.split_folio(folio=self.folio_b, charge_rows=[row])

	def test_payment_initiation_refuses_other_property(self):
		with self.assertRaises(REFUSALS):
			payments_api.initiate(
				folio=self.folio_b, amount=25, idempotency_key="auth:cross:pay"
			)

	def test_checkout_refuses_other_property(self):
		with self.assertRaises(REFUSALS):
			checkout_api.check_out(stay=self.stay_b)

	def test_reverse_checkout_refuses_other_property(self):
		with self.assertRaises(REFUSALS):
			checkout_api.reverse_checkout(stay=self.stay_b, reason="cross property")

	def test_post_folio_refuses_other_property(self):
		with self.assertRaises(REFUSALS):
			checkout_api.post_folio(folio=self.folio_b)

	def test_reconcile_folio_refuses_other_property(self):
		with self.assertRaises(REFUSALS):
			checkout_api.reconcile_folio(folio=self.folio_b)

	def test_stay_operations_refuse_other_property(self):
		business_date = frappe.db.get_value("Property", self.property_b, "business_date")

		with self.assertRaises(REFUSALS):
			stays_api.add_note(stay=self.stay_b, note="cross property")

		with self.assertRaises(REFUSALS):
			stays_api.extend_stay(stay=self.stay_b, new_departure=str(add_days(business_date, 9)))

		with self.assertRaises(REFUSALS):
			stays_api.shorten_stay(
				stay=self.stay_b, new_departure=str(add_days(business_date, 1)), reason="cross"
			)

	def test_reservation_operations_refuse_other_property(self):
		reservation_b = frappe.db.get_value("Stay", self.stay_b, "reservation")

		with self.assertRaises(REFUSALS):
			reservations_api.get_reservation(reservation=reservation_b)

		with self.assertRaises(REFUSALS):
			reservations_api.cancel(reservation=reservation_b, reason="cross property")

		with self.assertRaises(REFUSALS):
			reservations_api.mark_no_show(reservation=reservation_b, reason="cross property")

	def test_own_property_stay_note_still_works(self):
		stays_api.add_note(stay=self.stay_a, note="own property")

		notes = frappe.get_all("Stay Note", filters={"parent": self.stay_a}, pluck="note")

		self.assertIn("own property", notes)
