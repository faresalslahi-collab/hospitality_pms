"""P1-8 and the concurrency half of P2-1 — the business-date chain.

**P1-8.** `reopen()` checked only that the audit was closed, then set the
property's date to that audit's date. With the 8th, 9th and 10th closed and the
property on the 11th, reopening the 8th rewound the property three days and
deadlocked the chain: the 9th could not close, because the property was no
longer on the 9th, and nothing could put it back.

**P2-1, second half.** `start()` read "no audit for this date" and then created
one. Two callers doing that at the same instant both created one, and a
property with two audits for a date has two sets of figures and two ways to
close it.

The concurrency tests use two OS processes. A property's business date is a
single mutable value that several schedulers reach for at once, which is
exactly the shape a threaded test cannot reproduce.
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, getdate

from hospitality_pms.services import night_audit as audit_service
from hospitality_pms.services.exceptions import NightAuditError
from hospitality_pms.tests.concurrency import Worker, assert_all_ran, run_workers
from hospitality_pms.tests.night_audit_world import NightAuditWorld

AUDIT = "Night Audit"


# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------


def _start_worker(barrier, property_name: str, tag: str, partner: str) -> dict:
	"""Two schedulers opening the night's audit at the same moment."""
	frappe.db.sql("select name from `tabNight Audit` where property = %s", property_name)

	barrier.signal(f"ready_{tag}")
	barrier.wait(f"ready_{partner}")

	audit = audit_service.start(property_name)
	frappe.db.commit()

	return {"audit": audit}


def _close_worker(barrier, audit: str, tag: str, partner: str) -> dict:
	"""Two closes of the same audit, released together."""
	frappe.db.sql("select audit_status from `tabNight Audit` where name = %s", audit)

	barrier.signal(f"ready_{tag}")
	barrier.wait(f"ready_{partner}")

	result = audit_service.close(audit)
	frappe.db.commit()

	return result


class NightAuditChainTestCase(IntegrationTestCase):
	WORLD_CODE = "AC"

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
		self._reset_chain()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def _reset_chain(self):
		frappe.db.delete("Night Audit Exception", {"parenttype": AUDIT})
		frappe.db.delete(AUDIT, {"property": self.world.property})
		self.world.set_business_date(self.start_date)
		frappe.db.commit()

	def _close_one_day(self) -> str:
		"""Run a whole audit through to close, and return its name."""
		audit = audit_service.start(self.world.property)

		audit_service.review(audit)
		audit_service.post_room_charges(audit)
		audit_service.reconcile(audit)
		audit_service.close(audit)

		frappe.db.commit()

		return audit

	def _status(self, audit: str) -> str:
		return frappe.db.get_value(AUDIT, audit, "audit_status")


class TestOneAuditPerDate(NightAuditChainTestCase):
	WORLD_CODE = "A1"

	def test_one_audit_per_property_business_date(self):
		"""The database refuses a second audit for a date, not just the code."""
		audit_service.start(self.world.property)
		frappe.db.commit()

		with self.assertRaises(Exception) as caught:
			frappe.db.sql(
				"""
				insert into `tabNight Audit`
					(name, creation, modified, owner, modified_by, property, business_date,
					 audit_status, docstatus, idx)
				values (%(name)s, now(), now(), 'Administrator', 'Administrator',
					 %(property)s, %(date)s, 'Open', 0, 0)
				""",
				{
					"name": frappe.generate_hash(length=10),
					"property": self.world.property,
					"date": self.world.business_date,
				},
			)

		self.assertTrue(
			frappe.db.is_unique_key_violation(caught.exception),
			msg=f"expected the unique index to refuse a second audit, got {caught.exception!r}",
		)

		frappe.db.rollback()

	def test_concurrent_start_creates_one_audit(self):
		"""Two schedulers, one audit, and neither caller sees a raw SQL error."""
		results = run_workers(
			[
				Worker(
					f"{__name__}._start_worker",
					{"property_name": self.world.property, "tag": "a", "partner": "b"},
				),
				Worker(
					f"{__name__}._start_worker",
					{"property_name": self.world.property, "tag": "b", "partner": "a"},
				),
			]
		)
		assert_all_ran(results)

		self.assertEqual(
			[r["status"] for r in results],
			["committed", "committed"],
			msg=f"a caller got an error rather than the audit that already existed: {results}",
		)

		audits = frappe.get_all(AUDIT, filters={"property": self.world.property}, pluck="name")

		self.assertEqual(len(audits), 1, msg=f"two audits were created for one date: {audits}")
		self.assertEqual(
			{r["result"]["audit"] for r in results},
			set(audits),
			msg="the two callers were handed different audits",
		)

	def test_concurrent_close_advances_the_date_once(self):
		"""Two closes of one audit must move the day forward once, not twice."""
		audit = audit_service.start(self.world.property)
		audit_service.review(audit)
		audit_service.post_room_charges(audit)
		audit_service.reconcile(audit)
		frappe.db.commit()

		before = self.world.business_date

		results = run_workers(
			[
				Worker(f"{__name__}._close_worker", {"audit": audit, "tag": "a", "partner": "b"}),
				Worker(f"{__name__}._close_worker", {"audit": audit, "tag": "b", "partner": "a"}),
			]
		)
		assert_all_ran(results)

		committed = [r for r in results if r["status"] == "committed"]

		self.assertEqual(len(committed), 1, msg=f"both closes took effect: {results}")
		self.assertEqual(
			self.world.business_date,
			add_days(before, 1),
			msg="the business date moved more than one day",
		)


class TestReopenChain(NightAuditChainTestCase):
	"""P1-8 — a reopen is the undo of the last close, and nothing else."""

	WORLD_CODE = "A2"

	def test_reopen_latest_audit_only(self):
		first = self._close_one_day()
		after_first = self.world.business_date

		audit_service.reopen(first, "corrected a late charge")

		self.assertEqual(
			self.world.business_date,
			add_days(after_first, -1),
			msg="reopen did not rewind exactly one day",
		)
		self.assertEqual(self._status(first), audit_service.REVIEWING)

	def test_reopen_refuses_older_audit(self):
		"""The reproduction: three closed days, reopen the first."""
		first = self._close_one_day()
		self._close_one_day()
		self._close_one_day()

		property_date = self.world.business_date

		with self.assertRaises(NightAuditError) as caught:
			audit_service.reopen(first, "trying to rewind three days")

		self.assertEqual(
			self.world.business_date,
			property_date,
			msg="an old audit rewound the property's business date",
		)
		self.assertIn("most recent", str(caught.exception).lower())

	def test_reopen_refuses_middle_audit(self):
		self._close_one_day()
		middle = self._close_one_day()
		self._close_one_day()

		with self.assertRaises(NightAuditError):
			audit_service.reopen(middle, "skipping the newest")

	def test_reopen_reclose_advances_exactly_once(self):
		"""Reopen, put it back, and the chain is where it started.

		The room charge must not be posted a second time by the re-close: the
		charge is already on the folio and its key has not changed.
		"""
		self.world.check_in_guest(0)
		frappe.db.commit()

		audit = self._close_one_day()
		closed_date = getdate(frappe.db.get_value(AUDIT, audit, "business_date"))
		after_close = self.world.business_date

		charges_before = self._room_charge_count(closed_date)

		audit_service.reopen(audit, "late charge")
		self.assertEqual(self.world.business_date, closed_date)

		# Reopening invalidates the reconciliation; it has to be earned again.
		with self.assertRaises(NightAuditError):
			audit_service.close(audit)

		audit_service.post_room_charges(audit)
		audit_service.reconcile(audit)
		audit_service.close(audit)

		self.assertEqual(
			self.world.business_date, after_close, msg="the re-close did not return the same day"
		)
		self.assertEqual(
			self._room_charge_count(closed_date),
			charges_before,
			msg="the re-close posted the night's room charge a second time",
		)

	def test_reopen_refuses_when_property_has_moved_on(self):
		"""Only ever the undo of the last close, never a jump backwards."""
		audit = self._close_one_day()

		# Somebody else closes the next day too.
		self._close_one_day()

		with self.assertRaises(NightAuditError):
			audit_service.reopen(audit, "the property has moved past this")

	def test_reopen_clears_the_close_and_reconciliation_proof(self):
		audit = self._close_one_day()

		audit_service.reopen(audit, "correction")

		record = frappe.db.get_value(
			AUDIT,
			audit,
			["closed_on", "reconciliation_completed_on", "posting_completed_on", "reopen_reason"],
			as_dict=True,
		)

		self.assertIsNone(record["closed_on"])
		self.assertIsNone(record["reconciliation_completed_on"])
		self.assertIsNotNone(
			record["posting_completed_on"],
			msg="posting stays marked; the charges are already on the folios and are idempotent",
		)
		self.assertEqual(record["reopen_reason"], "correction")

	def _room_charge_count(self, business_date) -> int:
		return frappe.db.sql(
			"""
			select count(*) from `tabFolio Charge` c
			inner join `tabGuest Folio` f on f.name = c.parent
			where f.property = %s and c.charge_type = 'Room Charge' and c.business_date = %s
			""",
			(self.world.property, business_date),
		)[0][0]
