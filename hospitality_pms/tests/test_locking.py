"""N1 - a lock must protect current state, not the transaction's snapshot.

The defect
----------
`lock_document()` issues `SELECT name ... FOR UPDATE`. That serialises writers
correctly, and InnoDB answers a *locking* read from the latest committed row.
But it selects only `name`, which never changes, so nothing useful is learned
from it - and the `frappe.get_doc()` that follows is a plain, non-locking read.
Under REPEATABLE READ a plain read is answered from the snapshot the
transaction established at its first consistent read, which was taken *before*
the lock was granted. The waiter therefore acquires the lock and then reads
pre-lock values.

That is not a Frappe bug and it is not fixable by re-reading harder: within one
REPEATABLE READ transaction there is no plain read that will ever see the
winner's commit. The value has to come out of a locking read.

These tests prove all three halves of that: that the hazard is real on this
database, that `lock_and_read` closes it for named fields, and that
`lock_and_get_doc` closes it for a whole document including its child tables.
"""

import time

import frappe
from frappe.tests import IntegrationTestCase

from hospitality_pms.services.base import lock_and_get_doc, lock_and_read, lock_document
from hospitality_pms.tests.concurrency import Worker, assert_all_ran, run_workers
from hospitality_pms.tests.fixtures import Fixtures

ACCOUNT = "Corporate Account"

#: How long the writer holds its lock after the reader has asked for it. The
#: reader only has to reach the lock wait; a second is orders of magnitude more
#: than that takes, and the test is not timing-sensitive beyond it.
LOCK_SETTLE_SECONDS = 1.5

#: The value the winning writer commits. Any non-zero number works; a distinctive
#: one makes a failure message readable.
COMMITTED_CREDIT = 200.0


# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------
#
# These run in their own OS processes (see tests/concurrency.py), so they are
# module level and take only JSON-serialisable arguments.


def _writer(barrier, account: str, amount: float) -> dict:
	"""Win the race: take the lock, write, and commit while the reader waits."""
	barrier.wait("reader_snapshot_taken")

	lock_document(ACCOUNT, account)
	frappe.db.set_value(ACCOUNT, account, "credit_used", amount, update_modified=False)

	barrier.signal("writer_holds_lock")
	barrier.wait("reader_requesting_lock")

	# The reader has said it is about to ask for the lock. Give it time to
	# actually block on it, so the commit lands while it is waiting - which is
	# the whole scenario.
	time.sleep(LOCK_SETTLE_SECONDS)

	frappe.db.commit()
	barrier.signal("writer_committed")

	return {"committed": amount}


def _reader(barrier, account: str, mode: str) -> dict:
	"""Lose the race, then read. What it sees is what the test is about."""
	# Establish this transaction's consistent snapshot before the writer has
	# written anything. Raw SQL, so there is no question of a Frappe cache
	# layer answering instead of the database.
	snapshot = frappe.db.sql(
		"select credit_used from `tabCorporate Account` where name = %s", account
	)[0][0]

	barrier.signal("reader_snapshot_taken")
	barrier.wait("writer_holds_lock")
	barrier.signal("reader_requesting_lock")

	# Blocks here until the writer commits.
	if mode == "lock_then_plain_read":
		lock_document(ACCOUNT, account)
		observed = frappe.get_doc(ACCOUNT, account).credit_used
	elif mode == "lock_and_read":
		observed = lock_and_read(ACCOUNT, account, ["credit_used"])["credit_used"]
	elif mode == "lock_and_get_doc":
		observed = lock_and_get_doc(ACCOUNT, account).credit_used
	else:
		raise ValueError(f"unknown read mode {mode!r}")

	frappe.db.commit()

	return {"snapshot": float(snapshot or 0), "observed": float(observed or 0)}


def _folio_charge_writer(barrier, folio: str) -> dict:
	"""Post a charge through the service and commit, holding the lock meanwhile."""
	from hospitality_pms.services import folio as folio_service

	barrier.wait("reader_snapshot_taken")

	folio_service.post_charge(
		folio,
		"Room Charge",
		"race",
		50,
		idempotency_key=f"race:{folio}",
	)

	barrier.signal("writer_holds_lock")
	barrier.wait("reader_requesting_lock")
	time.sleep(LOCK_SETTLE_SECONDS)

	frappe.db.commit()

	return {"posted": True}


def _folio_charge_reader(barrier, folio: str) -> dict:
	"""Read the folio's child rows after losing the race for its lock."""
	from hospitality_pms.services import folio as folio_service

	snapshot = frappe.db.sql(
		"select count(*) from `tabFolio Charge` where parent = %s", folio
	)[0][0]

	barrier.signal("reader_snapshot_taken")
	barrier.wait("writer_holds_lock")
	barrier.signal("reader_requesting_lock")

	doc = lock_and_get_doc(folio_service.FOLIO_DOCTYPE, folio)
	observed = len(doc.charges)

	frappe.db.commit()

	return {"snapshot": int(snapshot), "observed": int(observed)}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLocking(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()

		cls.fixtures = Fixtures("LOCK")
		cls.property = cls.fixtures.property("LK")
		cls.account = cls.fixtures.corporate_account(cls.property)
		cls.guest = cls.fixtures.guest("Locking")
		cls.folio = cls.fixtures.folio(cls.property, cls.guest)

		# The workers are separate processes; they can only see committed rows.
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		cls.fixtures.teardown()
		super().tearDownClass()

	def setUp(self):
		frappe.db.set_value(ACCOUNT, self.account, "credit_used", 0, update_modified=False)
		frappe.db.commit()

	def _race(self, mode: str) -> dict:
		results = run_workers(
			[
				Worker(f"{__name__}._writer", {"account": self.account, "amount": COMMITTED_CREDIT}),
				Worker(f"{__name__}._reader", {"account": self.account, "mode": mode}),
			]
		)
		assert_all_ran(results)

		writer, reader = results

		self.assertEqual(writer["status"], "committed", msg=writer)
		self.assertEqual(reader["status"], "committed", msg=reader)

		return reader["result"]

	def test_harness_reproduces_stale_snapshot_hazard(self):
		"""The control. Without this, a green regression test proves nothing.

		If the harness failed to establish the reader's snapshot early, or the
		two workers did not genuinely overlap, `lock_and_read` would look
		correct while testing nothing at all. This pins the hazard the fix
		exists to close: lock, then plain read, still returns the pre-lock
		value on this database.
		"""
		observed = self._race("lock_then_plain_read")

		self.assertEqual(
			observed["snapshot"],
			0.0,
			msg="the reader's snapshot was not established before the writer wrote",
		)
		self.assertEqual(
			observed["observed"],
			0.0,
			msg=(
				"lock-then-plain-read returned the committed value, so this database no longer "
				"exhibits the N1 hazard and lock_and_read's contract is no longer being tested"
			),
		)

	def test_lock_waiter_reads_committed_state(self):
		"""N1: the primitive must return the winner's committed value."""
		observed = self._race("lock_and_read")

		self.assertEqual(observed["snapshot"], 0.0)
		self.assertEqual(
			observed["observed"],
			COMMITTED_CREDIT,
			msg="lock_and_read returned the pre-lock snapshot instead of current state",
		)

	def test_lock_waiter_document_read_sees_committed_state(self):
		"""N1: the same guarantee when a whole document is needed."""
		observed = self._race("lock_and_get_doc")

		self.assertEqual(observed["snapshot"], 0.0)
		self.assertEqual(
			observed["observed"],
			COMMITTED_CREDIT,
			msg="lock_and_get_doc returned the pre-lock snapshot instead of current state",
		)

	def test_lock_waiter_document_read_sees_committed_child_rows(self):
		"""N1: child tables must be current too.

		A folio's money lives in its child tables, so a document read that
		refreshed only the parent would leave every financial guard - duplicate
		key detection, balance arithmetic, reversal state - deciding on stale
		rows.
		"""
		results = run_workers(
			[
				Worker(f"{__name__}._folio_charge_writer", {"folio": self.folio}),
				Worker(f"{__name__}._folio_charge_reader", {"folio": self.folio}),
			]
		)
		assert_all_ran(results)

		writer, reader = results
		self.assertEqual(writer["status"], "committed", msg=writer)
		self.assertEqual(reader["status"], "committed", msg=reader)

		self.assertEqual(reader["result"]["snapshot"], 0)
		self.assertEqual(
			reader["result"]["observed"],
			1,
			msg="lock_and_get_doc did not see the charge row the winner committed",
		)

	def test_lock_and_read_rejects_a_missing_document(self):
		with self.assertRaises(frappe.DoesNotExistError):
			lock_and_read(ACCOUNT, "WV1-does-not-exist", ["credit_used"])
