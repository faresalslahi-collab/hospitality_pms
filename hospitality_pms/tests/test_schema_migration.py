"""The financial uniqueness constraint, and how it behaves on a real site.

`setup/schema.apply_financial_idempotency_constraints` runs from a patch on
upgrade, from `after_install` on a fresh site, and from `after_migrate` on
every migrate after that. All three call the same function, so what has to be
proven is that the function is safe to call in every state a site can be in:

* index absent, data clean      -> creates it
* index already present         -> does nothing
* index absent, data duplicated -> refuses, and destroys nothing

The last is the one that matters. A migration that "fixed" duplicate financial
keys by deleting a row would be deciding, unsupervised, which of two recorded
charges never happened.

Tested against a throwaway table, not against Folio Charge (16.7.5-R1D)
--------------------------------------------------------------------------
Observing the "index absent" states requires the index to be absent, and until
R1D these tests produced that state by dropping the real
`tabFolio Charge.unique_parent_idempotency_key` and restoring it in a `finally`.
The old docstring called that unavoidable. It was not, and it was not safe
either: `sql_ddl` commits in MariaDB, so between the drop and the restore the
site had **no financial idempotency protection at all** - and a crash, a SIGKILL,
a failing assertion in the wrong place or a test-runner timeout in that window
left the host site's constraint off until somebody next ran a migrate. The suite
runs against a real site by design, so that window was real.

`_apply_unique_parent_key` is parameterised by DocType, so the same code path can
be driven against a purpose-built child DocType instead. The index that gets
dropped and recreated is then the probe's, and `tabFolio Charge` is never
touched. Nothing about the code under test is mocked or reimplemented - it is the
same function `after_migrate` calls, on a table whose shape is the shape it cares
about.

What still runs against the real tables is everything that does *not* need the
constraint absent: that it is present, that re-applying is a no-op, and that the
folio service actually relies on it. Those are the assertions worth making about
the live site, and none of them removes anything.
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import nowdate

from hospitality_pms.services import folio as folio_service
from hospitality_pms.setup import schema
from hospitality_pms.tests.fixtures import Fixtures

CHARGE = "Folio Charge"
PAYMENT = "Folio Payment"
INDEX = "unique_parent_idempotency_key"

#: A child DocType with the two columns the constraint is about, and nothing
#: financial in it. Named so it is recognisable in a stray-table sweep.
PROBE = "HPMS R1D Idempotency Probe"


def _index_present(doctype: str) -> bool:
	return schema._index_exists(f"tab{doctype}", INDEX)


class TestTheLiveConstraint(IntegrationTestCase):
	"""What must be true of the site this suite is running against.

	Read-only with respect to the constraint: nothing here drops an index. If any
	of it fails, the site has a real problem rather than the test having a
	premise problem.
	"""

	def test_both_money_tables_carry_the_constraint(self):
		for doctype in schema.IDEMPOTENCY_CONSTRAINTS:
			with self.subTest(doctype=doctype):
				self.assertTrue(
					_index_present(doctype),
					msg=(
						f"tab{doctype} has no {INDEX}. Financial replay protection is "
						f"absent on this site - run `bench --site <site> migrate`."
					),
				)

	def test_the_constraint_is_on_parent_and_idempotency_key_in_that_order(self):
		"""Column order matters: it is what makes the key unique *per folio*."""
		for doctype in schema.IDEMPOTENCY_CONSTRAINTS:
			with self.subTest(doctype=doctype):
				columns = frappe.db.sql(
					"""
					select column_name, seq_in_index
					from information_schema.statistics
					where table_schema = database() and table_name = %s and index_name = %s
					order by seq_in_index
					""",
					(f"tab{doctype}", INDEX),
					as_dict=True,
				)

				self.assertEqual(
					[row["column_name"] for row in columns],
					["parent", "idempotency_key"],
				)

	def test_reapplying_is_a_no_op(self):
		"""`after_migrate` calls this on every migrate; it must be idempotent."""
		schema.apply_financial_idempotency_constraints()
		schema.apply_financial_idempotency_constraints()

		self.assertTrue(_index_present(CHARGE))
		self.assertTrue(_index_present(PAYMENT))

	def test_the_night_audit_constraint_is_present_too(self):
		self.assertTrue(schema._index_exists("tabNight Audit", "unique_property_business_date"))


class TestConstraintMigrationOnAThrowawayTable(IntegrationTestCase):
	"""The three states a site can be in, driven against a probe DocType.

	The probe exists so that "index absent" can be produced without producing it
	on the money tables. Its own index is dropped freely; `tabFolio Charge` is
	never referenced.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")

		if frappe.db.exists("DocType", PROBE):
			frappe.delete_doc("DocType", PROBE, force=True, ignore_permissions=True)

		# A child table, so Frappe gives it `parent`, `parenttype` and
		# `parentfield` exactly as the money tables have them.
		frappe.get_doc(
			{
				"doctype": "DocType",
				"name": PROBE,
				"module": "Hospitality Setup",
				"custom": 1,
				"istable": 1,
				"fields": [
					{"fieldname": "idempotency_key", "fieldtype": "Data", "label": "Idempotency Key"},
					{"fieldname": "amount", "fieldtype": "Currency", "label": "Amount"},
				],
			}
		).insert(ignore_permissions=True)

		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")

		if frappe.db.exists("DocType", PROBE):
			frappe.delete_doc("DocType", PROBE, force=True, ignore_permissions=True)

		# `delete_doc` on a DocType does not always drop its table, so the probe
		# would otherwise leave a `tabHPMS ...` orphan behind on every site the
		# suite ever runs against. Dropped explicitly, and only ever this table -
		# the name is a literal constant in this module, not a parameter.
		frappe.db.sql_ddl(f"drop table if exists `tab{PROBE}`")

		frappe.db.commit()

		# The real constraint was never touched by this class. Asserted rather
		# than assumed, because that is the whole claim of the rewrite.
		assert _index_present(CHARGE), "a probe test disturbed tabFolio Charge"

		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")
		self._reset_probe()

	def tearDown(self):
		frappe.set_user("Administrator")
		self._reset_probe()

	def _reset_probe(self):
		frappe.db.delete(PROBE)

		if _index_present(PROBE):
			frappe.db.sql_ddl(f"alter table `tab{PROBE}` drop index `{INDEX}`")

		frappe.db.commit()

	def _apply(self):
		"""The function under test, pointed at the probe."""
		schema._apply_unique_parent_key(PROBE, INDEX)

	def _insert_raw_row(self, key, parent="probe-folio-1"):
		"""A row written underneath the ORM, to plant a duplicate."""
		frappe.db.sql(
			f"""
			insert into `tab{PROBE}`
				(name, parent, parenttype, parentfield, idx, creation, modified, owner,
				 modified_by, idempotency_key, amount)
			values (%(name)s, %(parent)s, 'Guest Folio', 'charges', 1, now(), now(),
				 'Administrator', 'Administrator', %(key)s, 10)
			""",
			{"name": frappe.generate_hash(length=10), "parent": parent, "key": key},
		)

	# -- the premise -------------------------------------------------------

	def test_the_probe_starts_without_the_constraint(self):
		"""Without this the state tests below could pass by measuring nothing."""
		self.assertFalse(_index_present(PROBE))
		self.assertTrue(frappe.db.table_exists(PROBE))

		# And the real table is unaffected by the probe's absence.
		self.assertTrue(_index_present(CHARGE))

	# -- the states a site can be in --------------------------------------

	def test_constraint_is_created_when_absent(self):
		self._apply()

		self.assertTrue(_index_present(PROBE))

	def test_reapplying_on_the_probe_is_a_no_op(self):
		self._apply()
		self._apply()

		self.assertTrue(_index_present(PROBE))

	def test_a_missing_table_is_not_an_error(self):
		"""`after_migrate` can run before a DocType has been synced."""
		schema._apply_unique_parent_key("HPMS Nonexistent DocType", INDEX)

	# -- the guard ---------------------------------------------------------

	def test_migration_stops_safely_when_duplicates_exist(self):
		"""It refuses, it says which rows, and it deletes nothing."""
		self._insert_raw_row("dupe:key:1")
		self._insert_raw_row("dupe:key:1")
		frappe.db.commit()

		duplicates = schema.find_duplicate_keys(PROBE)

		self.assertTrue(
			any(row["parent"] == "probe-folio-1" for row in duplicates),
			msg=f"the duplicate was not detected; found {duplicates}",
		)

		with self.assertRaises(frappe.ValidationError) as caught:
			self._apply()

		message = str(caught.exception)

		self.assertIn("dupe:key:1", message, msg="the report must name the offending key")
		self.assertIn("probe-folio-1", message, msg="the report must name the parent")

		# The whole point: the rows are still there.
		self.assertEqual(
			frappe.db.count(PROBE, {"idempotency_key": "dupe:key:1"}),
			2,
			msg="the migration deleted a row to make itself pass",
		)
		self.assertFalse(_index_present(PROBE))

	def test_the_same_key_under_two_parents_is_not_a_duplicate(self):
		"""The reason the index is composite: a key is unique *within* a folio."""
		self._insert_raw_row("minibar:water:1", parent="probe-folio-1")
		self._insert_raw_row("minibar:water:1", parent="probe-folio-2")
		frappe.db.commit()

		self.assertEqual(schema.find_duplicate_keys(PROBE), [])

		self._apply()

		self.assertTrue(_index_present(PROBE))
		self.assertEqual(frappe.db.count(PROBE), 2)

	def test_null_keys_do_not_block_the_constraint(self):
		"""Historical rows with no key at all must not stop the upgrade.

		MariaDB treats NULLs as distinct in a unique index, so any number of
		them coexist. Rewriting them to satisfy the constraint would be exactly
		the silent edit of financial history the migration must not make.
		"""
		self._insert_raw_row(None)
		self._insert_raw_row(None)
		frappe.db.commit()

		self.assertEqual(schema.find_duplicate_keys(PROBE), [])

		self._apply()

		self.assertTrue(_index_present(PROBE))
		self.assertEqual(frappe.db.count(PROBE), 2)

	def test_an_empty_string_key_is_treated_as_a_real_value(self):
		"""`''` is not NULL: two of them on one parent would collide."""
		self._insert_raw_row("")
		self._insert_raw_row("")
		frappe.db.commit()

		duplicates = schema.find_duplicate_keys(PROBE)

		self.assertTrue(duplicates, msg="an empty-string key was treated as NULL")

		with self.assertRaises(frappe.ValidationError):
			self._apply()

		self.assertEqual(frappe.db.count(PROBE), 2)

	def test_the_constraint_actually_rejects_a_duplicate_once_created(self):
		"""The index does what the refusal above is protecting."""
		self._apply()
		self._insert_raw_row("probe:live:1")
		frappe.db.commit()

		with self.assertRaises(Exception) as caught:
			self._insert_raw_row("probe:live:1")

		self.assertTrue(frappe.db.is_unique_key_violation(caught.exception))

		frappe.db.rollback()


class TestTheFolioServiceReliesOnTheConstraint(IntegrationTestCase):
	"""End to end on the real table, without removing anything from it."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()

		cls.fixtures = Fixtures("SCHEMA")
		cls.property = cls.fixtures.property("SC")
		cls.guest = cls.fixtures.guest("Schema")

		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		cls.fixtures.teardown()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")
		self.folio = self.fixtures.folio(self.property, self.guest)
		frappe.db.commit()

	def tearDown(self):
		frappe.db.rollback()

	def test_a_replayed_charge_cannot_be_stored_twice(self):
		"""With the index in place, a duplicate key is refused by the database.

		Written through the service for the first charge and underneath it for the
		second: the service's own replay guard would otherwise be what refuses, and
		the point here is that the *database* is the backstop when it does not.
		"""
		self.assertTrue(_index_present(CHARGE), msg="premise: the constraint is present")

		folio_service.post_charge(
			self.folio, "Minibar", "Water", 20, idempotency_key="schema:live:1"
		)
		frappe.db.commit()

		with self.assertRaises(Exception) as caught:
			frappe.db.sql(
				f"""
				insert into `tab{CHARGE}`
					(name, parent, parenttype, parentfield, idx, creation, modified, owner,
					 modified_by, charge_date, business_date, charge_type, description,
					 quantity, unit_price, amount, tax_amount, total_amount, idempotency_key)
				values (%(name)s, %(parent)s, 'Guest Folio', 'charges', 99, now(), now(),
					 'Administrator', 'Administrator', %(date)s, %(date)s, 'Room Charge',
					 'replay', 1, 10, 10, 0, 10, 'schema:live:1')
				""",
				{
					"name": frappe.generate_hash(length=10),
					"parent": self.folio,
					"date": nowdate(),
				},
			)

		self.assertTrue(frappe.db.is_unique_key_violation(caught.exception))

		frappe.db.rollback()

	def test_the_service_refuses_a_replay_before_the_database_has_to(self):
		"""The ordinary path: the guard answers, and no constraint violation occurs."""
		first = folio_service.post_charge(
			self.folio, "Minibar", "Water", 20, idempotency_key="schema:replay:1"
		)
		second = folio_service.post_charge(
			self.folio, "Minibar", "Water", 20, idempotency_key="schema:replay:1"
		)
		frappe.db.commit()

		self.assertEqual(
			frappe.db.count(CHARGE, {"parent": self.folio, "idempotency_key": "schema:replay:1"}),
			1,
			msg="the replay guard let a second row through",
		)
		self.assertEqual(first.get("row"), second.get("row"))
