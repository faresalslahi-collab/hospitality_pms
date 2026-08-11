"""N7 — the failure queue was an accumulator, not a retry mechanism.

Two faults compounded. `_queue_failure` inserted a row every time a push
failed, with no check for one already describing the same work; and
`retry_failed` incremented counters without ever calling the channel back. Two
days of a broken channel produced 2,232 rows, and by the time this wave started
the same site held 3,169 rows describing 96 distinct pieces of work — none of
which had been reattempted once.

Both are addressed by the same durable ledger the payment and posting fixes
use. A scheduled push has one stable identity per channel, so a repeated
failure updates that row instead of adding another; and the scheduler dispatches
a real handler that actually pushes again.

The adapter here is a stub. Nothing in this suite touches a network.
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, nowdate

from hospitality_pms.services import channel as channel_service
from hospitality_pms.services import durability
from hospitality_pms.services import retry as retry_service
from hospitality_pms.tests.fixtures import Fixtures

LEDGER = "PMS Integration Failure Queue"


class FlakyChannelAdapter:
	"""A channel that fails until told otherwise, and counts its calls."""

	#: Class state rather than instance, because the service builds a fresh
	#: adapter per call and the test needs to see across all of them.
	fail = True
	calls: list = []

	def __init__(self, *args, **kwargs):
		pass

	def _push(self, kind, from_date, to_date, rows):
		type(self).calls.append({"kind": kind, "rows": len(rows)})

		if type(self).fail:
			raise RuntimeError("channel unavailable")

		from hospitality_pms.integrations.channel.base import ChannelResult

		return ChannelResult(success=True, status="Success", raw={"ok": True})

	def push_availability(self, from_date, to_date, rows):
		return self._push("availability", from_date, to_date, rows)

	def push_rates(self, from_date, to_date, rows):
		return self._push("rates", from_date, to_date, rows)


class ChannelRetryTestCase(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()

		cls.fixtures = Fixtures("CHRT")
		cls.property = cls.fixtures.property("CH")
		cls.room_type = cls.fixtures.room_type(cls.property)
		cls.fixtures.rooms(cls.property, cls.room_type, count=2)
		cls.rate_plan = cls.fixtures.rate_plan(cls.property, cls.room_type)
		cls.channel = cls.fixtures.booking_channel(cls.property, cls.room_type, cls.rate_plan)

		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		cls.fixtures.teardown()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")
		durability.purge_operations(property_name=self.property)

		FlakyChannelAdapter.fail = True
		FlakyChannelAdapter.calls = []

		self._original_adapter = channel_service.get_adapter
		channel_service.get_adapter = lambda name: FlakyChannelAdapter()

	def tearDown(self):
		channel_service.get_adapter = self._original_adapter
		frappe.set_user("Administrator")
		frappe.db.rollback()
		durability.purge_operations(property_name=self.property)

	def _ledger_rows(self, operation: str | None = None) -> list[dict]:
		return durability.find_operations(property_name=self.property, operation=operation)

	def _sync(self):
		"""One scheduler pass."""
		try:
			channel_service.sync_all(self.property)
		except Exception:
			frappe.db.rollback()

		frappe.db.commit()


class TestChannelQueueGrowth(ChannelRetryTestCase):
	def test_channel_failure_reuses_logical_operation(self):
		"""Ten scheduler passes against a dead channel, not ten rows per push.

		This is N7 stated as an assertion. Before, each pass inserted a fresh
		row; the site reached 3,169 rows for 96 pieces of work.
		"""
		for _pass in range(10):
			self._sync()

		availability = self._ledger_rows("push_availability")
		rates = self._ledger_rows("push_rates")

		self.assertEqual(
			len(availability), 1, msg=f"availability pushes accumulated: {len(availability)} rows"
		)
		self.assertEqual(len(rates), 1, msg=f"rate pushes accumulated: {len(rates)} rows")

	def test_repeated_passes_do_not_burn_every_attempt_at_once(self):
		"""The backoff has to mean something.

		A scheduler that re-attempted on every pass regardless of
		`next_attempt_on` would exhaust the attempt budget in an hour and
		abandon a channel that was merely briefly unreachable.
		"""
		for _pass in range(6):
			self._sync()

		record = self._ledger_rows("push_availability")[0]

		self.assertLess(
			record["attempts"],
			6,
			msg=f"every pass counted as an attempt despite the backoff: {record}",
		)
		self.assertNotEqual(record["queue_status"], durability.ABANDONED)

	def test_an_explicitly_ranged_push_is_its_own_operation(self):
		"""A deliberate one-off push is different work from the rolling sync."""
		self._sync()

		try:
			channel_service.push_availability(
				self.property, self.channel, add_days(nowdate(), 200), add_days(nowdate(), 230)
			)
		except Exception:
			frappe.db.rollback()

		self.assertEqual(
			len(self._ledger_rows("push_availability")),
			2,
			msg="a different date range should be a different operation",
		)


class TestChannelRetryDispatch(ChannelRetryTestCase):
	def test_channel_retry_calls_handler(self):
		"""The retry must actually push, not merely count."""
		self._sync()

		key = self._ledger_rows("push_availability")[0]["operation_key"]
		durability.reschedule_now(key)

		FlakyChannelAdapter.calls = []
		retry_service.retry_due_operations(self.property, limit=10)

		self.assertTrue(
			FlakyChannelAdapter.calls,
			msg="the retry incremented counters without calling the channel",
		)

	def test_channel_retry_marks_success(self):
		self._sync()

		key = self._ledger_rows("push_availability")[0]["operation_key"]
		durability.reschedule_now(key)

		FlakyChannelAdapter.fail = False
		results = retry_service.retry_due_operations(self.property, limit=10)

		self.assertIn(durability.RESOLVED, [r["status"] for r in results])
		self.assertEqual(durability.get_operation(key)["queue_status"], durability.RESOLVED)

	def test_channel_retry_abandons_after_limit(self):
		"""A channel that never comes back stops, and says so."""
		self._sync()

		key = self._ledger_rows("push_availability")[0]["operation_key"]

		for _attempt in range(durability.DEFAULT_MAX_ATTEMPTS + 3):
			durability.reschedule_now(key)
			retry_service.retry_due_operations(self.property, limit=10)

		record = durability.get_operation(key)

		self.assertEqual(
			record["queue_status"],
			durability.ABANDONED,
			msg=f"the channel push retried without limit: {record}",
		)
		self.assertIsNone(record["next_attempt_on"])

	def test_abandoned_channel_work_is_not_recreated_by_the_scheduler(self):
		"""Once stopped, the scheduler must not quietly start it again."""
		self._sync()

		key = self._ledger_rows("push_availability")[0]["operation_key"]
		durability.abandon_operation(key, reason="operator stopped it")

		for _pass in range(3):
			self._sync()

		self.assertEqual(len(self._ledger_rows("push_availability")), 1)
		self.assertEqual(durability.get_operation(key)["queue_status"], durability.ABANDONED)

	def test_abandoned_channel_work_is_visible_for_review(self):
		self._sync()

		key = self._ledger_rows("push_availability")[0]["operation_key"]
		durability.abandon_operation(key, reason="channel credentials rejected")

		attention = durability.operations_needing_attention(self.property)

		self.assertIn(key, [row["operation_key"] for row in attention])
