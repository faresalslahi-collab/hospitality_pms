"""Have Waves 1-5 held, and can later work quietly undo them?

Five waves each established a primitive and then relied on it: current reads
under a lock, deterministic financial identity, durable external calls, one
authoritative inventory interval, the operating day. Every one of them is the
kind of rule that a later, perfectly reasonable-looking change walks straight
past - `frappe.get_doc` after a lock reads fine, `generate_hash()` as an
idempotency key reads fine, `nowdate()` reads fine.

So the audit is written down and run, rather than performed by eye once. Each
check carries an allow-list of the sites that already existed before the wave
that established the rule; those are historical and out of scope. Anything new
fails, which is the only property that matters here.
"""

import ast
import pathlib
import re

import frappe
from frappe.tests import IntegrationTestCase

APP = pathlib.Path(frappe.get_app_path("hospitality_pms"))
SERVICES = APP / "services"
API = APP / "api"


def _python_files(*roots: pathlib.Path) -> list[pathlib.Path]:
	files: list[pathlib.Path] = []

	for root in roots:
		files.extend(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)

	return sorted(files)


def _relative(path: pathlib.Path) -> str:
	return str(path.relative_to(APP))


class TestLockingPrimitive(IntegrationTestCase):
	"""N1: locking a row does not refresh what this transaction can see.

	`lock_document` serialises. It does not give the caller a current read -
	the snapshot was opened before the winner committed, so a plain read of
	the locked row afterwards is answered from stale data and both callers act
	on it. Wave 1 introduced `lock_and_read` / `lock_and_get_doc` /
	`lock_and_find` for exactly this, and Wave 5 found the pattern had crept
	back into room assignment.

	The detector is deliberately narrow: it flags a plain read whose arguments
	name the *same* value that was locked. A read of a different row is a
	different question, and constructing a new document that happens to
	mention the locked name is not a read at all.
	"""

	READS = ("frappe.get_doc", "frappe.get_cached_doc", "frappe.db.get_value", "frappe.get_all")

	#: Sites that predate every hardening wave (all from `a7f89c7`, the
	#: original build) and were never in a wave's scope. Real instances of the
	#: pattern on operational - not financial - state. Recorded with a reason
	#: so the list stays meaningful, and reported for Wave 7 rather than
	#: quietly carried.
	KNOWN = {
		("services/guest_services.py", "assign"): "pre-Wave-1; guest request state",
		("services/guest_services.py", "start"): "pre-Wave-1; guest request state",
		("services/guest_services.py", "complete"): "pre-Wave-1; guest request state",
		("services/guest_services.py", "escalate"): "pre-Wave-1; guest request state",
		("services/guest_services.py", "reopen"): "pre-Wave-1; guest request state",
		("services/guest_services.py", "close"): "pre-Wave-1; guest request state",
		("services/guest_services.py", "apply_service_recovery"): "pre-Wave-1; guest request state",
		("services/housekeeping.py", "assign"): "pre-Wave-1; task state",
		("services/housekeeping.py", "start"): "pre-Wave-1; task state",
		("services/housekeeping.py", "complete"): "pre-Wave-1; task state",
		("services/housekeeping.py", "inspect"): "pre-Wave-1; task state",
		("services/housekeeping.py", "set_do_not_disturb"): "pre-Wave-1; task state",
		("services/maintenance.py", "start_work"): "pre-Wave-1; ticket state",
		("services/maintenance.py", "take_out_of_service"): "pre-Wave-1; ticket state",
		("services/maintenance.py", "complete_work"): "pre-Wave-1; ticket state",
		("services/maintenance.py", "verify_and_release"): "pre-Wave-1; ticket state",
		("services/regulatory.py", "register_guest"): "pre-Wave-1; registration state",
		("services/regulatory.py", "submit_export"): "pre-Wave-1; export state",
		("services/hardware.py", "issue_key"): "pre-Wave-1; key card issue",
		("services/hardware.py", "cancel_key"): "pre-Wave-1; key card state",
		("services/rooms.py", "set_status"): "pre-Wave-1; single-dimension room writer",
		# Reads the room's property and room type - configuration an
		# administrator changes, never contended by concurrent front-desk work.
		("services/reservations.py", "assign_room"): "immutable configuration, not contended state",
		# The balance read behind checkout. Proved harmless by
		# TestCheckoutReadsTheCommittedBalance: FolioService.transition holds
		# the authoritative current-read guard on every route to Settled.
		("services/checkout.py", "check_out"): "defence in depth; the authoritative guard is in FolioService.transition",
	}

	def _sites(self) -> set[tuple[str, str]]:
		found: set[tuple[str, str]] = set()

		for path in _python_files(SERVICES, API):
			tree = ast.parse(path.read_text())

			for function in ast.walk(tree):
				if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
					continue

				locked = {
					ast.unparse(node.args[1])
					for node in ast.walk(function)
					if isinstance(node, ast.Call)
					and isinstance(node.func, ast.Name)
					and node.func.id == "lock_document"
					and len(node.args) >= 2
				}

				if not locked:
					continue

				for node in ast.walk(function):
					if not isinstance(node, ast.Call):
						continue
					if ast.unparse(node.func) not in self.READS:
						continue
					if any(keyword.arg == "for_update" for keyword in node.keywords):
						continue
					# `frappe.get_doc({...})` builds a new document; it reads nothing.
					if node.args and isinstance(node.args[0], ast.Dict):
						continue

					arguments = " ".join(ast.unparse(argument) for argument in node.args)

					if any(re.search(rf"\b{re.escape(name)}\b", arguments) for name in locked):
						found.add((_relative(path), function.name))
						break

		return found

	def test_no_new_lock_then_stale_read_in_hardened_services(self):
		new = self._sites() - set(self.KNOWN)

		self.assertFalse(
			new,
			msg=(
				"lock_document followed by a plain read of the locked row reintroduces "
				"N1: the read is answered from the pre-lock snapshot. Use lock_and_read "
				f"/ lock_and_get_doc / lock_and_find instead. New sites: {sorted(new)}"
			),
		)

	def test_the_known_list_still_describes_reality(self):
		"""An allow-list that outlives what it describes stops meaning anything."""
		stale = set(self.KNOWN) - self._sites()

		self.assertFalse(stale, msg=f"allow-listed but no longer present: {sorted(stale)}")


def _charge_worker(barrier, folio: str, amount: float) -> dict:
	"""A minibar charge landing while the desk is checking the guest out."""
	from hospitality_pms.services import folio as folio_service

	barrier.wait("checkout_snapshot_open")

	folio_service.post_charge(
		folio, "Minibar", "Charged during checkout", amount, idempotency_key=f"race:{folio}"
	)
	frappe.db.commit()

	barrier.signal("charge_committed")

	return {"charged": amount}


def _snapshot_probe_worker(barrier, folio: str) -> dict:
	"""Harness validity: does a plain read here really see the old value?"""
	first = frappe.db.sql("select balance from `tabGuest Folio` where name = %s", folio)[0][0]

	barrier.signal("checkout_snapshot_open")
	barrier.wait("charge_committed")

	after_plain = frappe.db.sql("select balance from `tabGuest Folio` where name = %s", folio)[0][0]
	after_locking = frappe.db.sql(
		"select balance from `tabGuest Folio` where name = %s for update", folio
	)[0][0]

	return {"first": float(first), "plain": float(after_plain), "locking": float(after_locking)}


def _checkout_ready_worker(barrier, stay: str, folio: str) -> dict:
	"""The same race, but with the folio already past its status transitions.

	Isolates *why* the ordinary path is safe: if it is only safe because
	`_settle_folio` happens to write the row before reading the balance, then
	a folio that needs no transition is not safe.
	"""
	from hospitality_pms.services import checkout as checkout_service
	from hospitality_pms.services.exceptions import FolioError

	frappe.db.sql("select balance from `tabGuest Folio` where name = %s", folio)

	barrier.signal("checkout_snapshot_open")
	barrier.wait("charge_committed")

	try:
		checkout_service.check_out(stay, post_to_erp=False)
		frappe.db.commit()
	except FolioError as error:
		return {"refused": True, "message": str(error)[:160]}

	return {"refused": False}


def _checkout_worker(barrier, stay: str, folio: str) -> dict:
	"""A checkout whose transaction opened before that charge existed."""
	from hospitality_pms.services import checkout as checkout_service
	from hospitality_pms.services.exceptions import FolioError

	# Opens this transaction's snapshot, which is the whole premise: everything
	# read plainly from here on is answered from this moment, not from now.
	frappe.db.sql("select balance from `tabGuest Folio` where name = %s", folio)

	barrier.signal("checkout_snapshot_open")
	barrier.wait("charge_committed")

	try:
		checkout_service.check_out(stay, post_to_erp=False)
		frappe.db.commit()
	except FolioError as error:
		return {"refused": True, "message": str(error)[:200]}

	return {"refused": False}


class TestCheckoutReadsTheCommittedBalance(IntegrationTestCase):
	"""A suspected gap that turned out not to be one, kept as the proof.

	The audit flagged `checkout._settle_folio`: it reads the folio balance
	with a plain `frappe.db.get_value` after `check_out` has locked the folio,
	which is the shape of N1 - locking serialises two tills without refreshing
	either one's snapshot. On that reading, a charge committed while a
	checkout was in flight would be invisible and the guest would walk out
	owing money still sitting on the folio.

	It does not happen, and these tests are why the claim is not being made.
	The probe first establishes that this harness *can* observe a stale
	snapshot at all - a plain read returns 0.00 while a locking read in the
	same transaction returns 75.00 - so a passing race here means the system,
	not the setup. Then both checkout paths are raced and both refuse:

	* the ordinary path is refused by `_settle_folio` itself;
	* a folio already at Ready, which makes no status write before reading the
	  balance, is refused by `FolioService.transition`, whose Settled guard
	  reads the balance currently.

	The authoritative guard is the one in the folio service, which is where it
	belongs: every route to Settled passes through it, not only checkout. The
	plain read in `_settle_folio` is defence in depth behind that, and
	rewriting it would change nothing that is observable. Left alone.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()

		from hospitality_pms.tests.inventory_world import InventoryWorld

		cls.world = InventoryWorld("FICO", "FI", rooms=2)

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
		for room in self.world.rooms:
			frappe.db.set_value("Hotel Room", room, "occupancy_status", "Vacant", update_modified=False)
		frappe.db.commit()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_the_harness_can_observe_a_stale_snapshot(self):
		"""Prove the reproduction is capable of showing the hazard at all.

		Without this, a passing race test means nothing: it could be a correct
		system or a harness that never created the condition.
		"""
		from hospitality_pms.tests.concurrency import Worker, assert_all_ran, run_workers

		reservation = self.world.confirmed(nights=1)
		result = self.world.check_in(reservation)
		folio = result["folio"]

		results = run_workers(
			[
				Worker(f"{__name__}._snapshot_probe_worker", {"folio": folio}),
				Worker(f"{__name__}._charge_worker", {"folio": folio, "amount": 75.0}),
			]
		)
		assert_all_ran(results)

		probe = results[0]["result"]

		self.assertEqual(probe["first"], 0.0)
		self.assertEqual(
			probe["plain"],
			0.0,
			msg="a plain read did not go stale, so this harness cannot prove anything",
		)
		self.assertEqual(
			probe["locking"], 75.0, msg="a locking read must see the committed charge"
		)

	def test_a_folio_needing_no_transition_still_sees_the_charge(self):
		"""The prediction that decides whether the ordinary path is safe by luck."""
		from hospitality_pms.services import folio as folio_service
		from hospitality_pms.tests.concurrency import Worker, assert_all_ran, run_workers

		reservation = self.world.confirmed(nights=1)
		result = self.world.check_in(reservation)
		stay, folio = result["stay"], result["folio"]

		# Walk the folio to Ready up front, so checkout has no status write to
		# make before it reads the balance.
		folio_service.transition(folio, folio_service.UNDER_REVIEW, reason="Pre-staged")
		folio_service.transition(folio, folio_service.READY, reason="Pre-staged")
		frappe.db.commit()

		results = run_workers(
			[
				Worker(f"{__name__}._checkout_ready_worker", {"stay": stay, "folio": folio}),
				Worker(f"{__name__}._charge_worker", {"folio": folio, "amount": 75.0}),
			]
		)
		assert_all_ran(results)

		balance = frappe.db.get_value("Guest Folio", folio, "balance")
		status = frappe.db.get_value("Guest Folio", folio, "folio_status")

		self.assertNotIn(
			status,
			("Settled", "Closed"),
			msg=f"a folio carrying {balance} was settled from a stale read: {results}",
		)

	def test_a_charge_committed_mid_checkout_still_blocks_it(self):
		"""The ordinary path: refused by `_settle_folio`."""
		from hospitality_pms.tests.concurrency import Worker, assert_all_ran, run_workers

		reservation = self.world.confirmed(nights=1)
		result = self.world.check_in(reservation)
		stay, folio = result["stay"], result["folio"]

		results = run_workers(
			[
				Worker(f"{__name__}._checkout_worker", {"stay": stay, "folio": folio}),
				Worker(f"{__name__}._charge_worker", {"folio": folio, "amount": 75.0}),
			]
		)
		assert_all_ran(results)

		balance = frappe.db.get_value("Guest Folio", folio, "balance")
		status = frappe.db.get_value("Guest Folio", folio, "folio_status")

		self.assertNotIn(
			status,
			("Settled", "Closed"),
			msg=f"a folio carrying {balance} was settled from a stale read: {results}",
		)


class TestFinancialIdentity(IntegrationTestCase):
	"""Wave 1/2: a financial operation's identity must be derivable, not drawn.

	An idempotency key made from randomness is unique on every attempt, which
	makes a retry a second charge. Every key in this system is built from what
	the operation *is* - the stay, the folio, the business date, the operation.
	"""

	RANDOM = re.compile(
		r"(idempotency_key|operation_key)\s*=\s*[^\n]*\b(generate_hash|uuid|random|token_hex|now_datetime|nowtime)\b"
	)

	def test_no_random_financial_idempotency_fallbacks(self):
		offenders = []

		for path in _python_files(SERVICES, API):
			for number, line in enumerate(path.read_text().splitlines(), start=1):
				if line.strip().startswith("#"):
					continue
				if self.RANDOM.search(line):
					offenders.append(f"{_relative(path)}:{number}")

		self.assertFalse(
			offenders,
			msg=(
				"a financial identity built from randomness makes every retry a new "
				f"operation, so a replay double-charges: {offenders}"
			),
		)

	def test_the_unique_constraint_behind_it_is_still_in_place(self):
		"""Wave 1's database-level guarantee, not just the service-level check."""
		indexes = frappe.db.sql(
			"""
			select index_name from information_schema.statistics
			where table_schema = database()
			  and table_name = 'tabFolio Payment'
			  and non_unique = 0
			""",
			as_dict=True,
		)

		self.assertTrue(
			[row for row in indexes if "idempotency" in row["index_name"].lower()],
			msg="the unique idempotency constraint on Folio Payment is gone",
		)


class TestInventoryAuthority(IntegrationTestCase):
	"""Wave 5: `Reservation Room` is the only thing availability counts."""

	def test_stay_is_not_counted_in_availability(self):
		"""Counting Stay as well would double-count every checked-in guest."""
		source = (SERVICES / "availability.py").read_text()

		self.assertNotIn(
			'"Stay"',
			source,
			msg="availability has started reading Stay; a checked-in guest would be counted twice",
		)
		self.assertIn("HOLDING_RESERVATION_STATES", source)

	def test_the_holding_states_are_unchanged(self):
		from hospitality_pms.services.availability import HOLDING_RESERVATION_STATES

		self.assertEqual(
			set(HOLDING_RESERVATION_STATES), {"Confirmed", "Guaranteed", "Checked In"}
		)

	def test_operational_header_dates_remain_child_derived(self):
		"""Part 9/10 — HPMS-DEC-154 is still how the header gets its dates."""
		source = (
			APP / "hospitality_reservations" / "doctype" / "reservation" / "reservation.py"
		).read_text()

		self.assertIn("_derive_dates_from_room_lines", source)
		self.assertIn("_guard_room_line_immutability", source)


class TestOperationalDateRule(IntegrationTestCase):
	"""Wave 6: one resolver decides what "today" means for a hotel."""

	#: `nowdate()` calls that are correct, each for a stated reason. Anything
	#: else in a service or endpoint is a calendar date standing in for an
	#: operating day, which is the defect this wave closed.
	APPROVED = {
		# Civil timestamps stored *alongside* the operational business_date on
		# the same row: when it happened, as distinct from which hotel day it
		# belongs to.
		("services/folio.py", "charge_date"),
		("services/folio.py", "payment_date"),
		# A 30-day reporting lookback over a Datetime; wall-clock is intended.
		("services/maintenance.py", "completed_on"),
		# When the booking was made - a civil fact about the booking, not the
		# day being priced.
		("services/rates.py", "booked_on"),
		# The last-resort fallback inside the contract rule itself, for an
		# account with no property to take a business date from.
		("services/corporate.py", "return getdate(nowdate())"),
	}

	def test_no_new_calendar_date_operational_defaults(self):
		"""Real `nowdate()` call sites, found in the syntax tree.

		Matching text would flag every docstring that explains the rule, which
		is how a check like this ends up ignored.
		"""
		offenders = []

		for path in _python_files(SERVICES, API):
			relative = _relative(path)
			source = path.read_text()
			tree = ast.parse(source)
			lines = source.splitlines()

			for node in ast.walk(tree):
				if not isinstance(node, ast.Call):
					continue
				if ast.unparse(node.func) not in ("nowdate", "frappe.utils.nowdate", "today", "frappe.utils.today"):
					continue

				statement = lines[node.lineno - 1].strip()

				if any(
					relative == source_file and marker in statement
					for source_file, marker in self.APPROVED
				):
					continue

				offenders.append(f"{relative}:{node.lineno}  {statement}")

		self.assertFalse(
			offenders,
			msg=(
				"a hotel's day is its business date, not the calendar's. Use "
				f"property.resolve_operational_date(): {offenders}"
			),
		)

	def test_there_is_one_resolver_and_the_boards_delegate_to_it(self):
		from hospitality_pms.services.front_office import resolve_business_date
		from hospitality_pms.services.property import resolve_operational_date

		source = (SERVICES / "front_office.py").read_text()

		self.assertIn("return resolve_operational_date(property_name, on_date)", source)
		self.assertTrue(callable(resolve_business_date))
		self.assertTrue(callable(resolve_operational_date))


class TestServiceBoundaries(IntegrationTestCase):
	"""Wave 1/3: authorisation and durability are not optional at the edges."""

	GUARDS = ("require_permission", "require_role", "authorise_document", "require_operation_key")

	#: Mutating endpoints that legitimately carry no PMS authorization, each
	#: for a reason that is not "we forgot".
	EXEMPT = {
		# The gateway has no Frappe session. Authentication is the provider's
		# signature over the raw payload, verified by the adapter before a
		# single field is read; an unsigned callback writes nothing.
		"api/payments.py::webhook": "allow_guest; authenticated by provider signature",
		# Writes one field on the caller's own User record. There is no
		# property or role to scope a user's choice of interface language to.
		"api/session.py::set_language": "self-scoped preference for the authenticated user",
	}

	def test_mutating_endpoints_authorise_beyond_the_doctype(self):
		"""A POST endpoint must do more than trust ORM permissions.

		Wave 1's boundary: `require_permission` / `require_role` /
		`authorise_document` scope an operation to a property and a role. An
		endpoint that mutates while checking neither is the shape of the
		original authorization findings. Read from the decorator list rather
		than by splitting text, so private helpers are not mistaken for
		endpoints.
		"""
		unguarded = []

		for path in _python_files(API):
			tree = ast.parse(path.read_text())

			for node in ast.walk(tree):
				if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
					continue

				whitelisted = [
					decorator
					for decorator in node.decorator_list
					if isinstance(decorator, ast.Call)
					and ast.unparse(decorator.func).endswith("whitelist")
				]

				if not whitelisted:
					continue

				methods = " ".join(ast.unparse(decorator) for decorator in whitelisted)

				if "POST" not in methods:
					continue

				body = ast.unparse(node)

				endpoint = f"{_relative(path)}::{node.name}"

				if endpoint in self.EXEMPT:
					continue

				if not any(guard in body for guard in self.GUARDS):
					unguarded.append(endpoint)

		self.assertFalse(
			unguarded,
			msg=f"mutating endpoints with no explicit authorization: {unguarded}",
		)

	def test_provider_calls_go_through_the_durable_ledger(self):
		"""Wave 3: no external financial call may exist only in memory."""
		source = (SERVICES / "payments.py").read_text()

		self.assertIn("durability.run_durably(", source)
		self.assertIn("durability.get_operation(", source)

	def test_a_conclusive_callback_can_resolve_the_ledger(self):
		"""Wave 6, Part 2 — and it does so through the Wave-3 service."""
		source = (SERVICES / "payments.py").read_text()

		self.assertIn("durability.complete_operation(", source)
		self.assertIn("_resolve_durable_operation", source)
