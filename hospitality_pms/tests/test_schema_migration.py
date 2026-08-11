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

These tests drop and recreate the index on purpose, and restore it in a
`finally` whatever happens. That is unavoidable: the guard cannot be observed
while the constraint it exists to protect is already in place.
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import nowdate

from hospitality_pms.services import folio as folio_service
from hospitality_pms.setup import schema
from hospitality_pms.tests.fixtures import Fixtures

CHARGE = "Folio Charge"
INDEX = "unique_parent_idempotency_key"


def _index_present(doctype: str) -> bool:
	return schema._index_exists(f"tab{doctype}", INDEX)


def _drop_index(doctype: str):
	if _index_present(doctype):
		frappe.db.sql_ddl(f"alter table `tab{doctype}` drop index `{INDEX}`")


class TestFinancialIdempotencyConstraint(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()

		cls.fixtures = Fixtures("SCHEMA")
		cls.property = cls.fixtures.property("SC")
		cls.guest = cls.fixtures.guest("Schema")

		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		# Whatever these tests did, the site must end with the constraint on.
		schema.apply_financial_idempotency_constraints()
		frappe.db.commit()

		cls.fixtures.teardown()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")
		self.folio = self.fixtures.folio(self.property, self.guest)
		frappe.db.commit()

	def tearDown(self):
		frappe.db.rollback()
		schema.apply_financial_idempotency_constraints()
		frappe.db.commit()

	def _insert_raw_charge(self, key: str):
		"""A charge row written underneath the ORM, to plant a duplicate."""
		frappe.db.sql(
			f"""
			insert into `tab{CHARGE}`
				(name, parent, parenttype, parentfield, idx, creation, modified, owner,
				 modified_by, charge_date, business_date, charge_type, description,
				 quantity, unit_price, amount, tax_amount, total_amount, idempotency_key)
			values (%(name)s, %(parent)s, 'Guest Folio', 'charges', 1, now(), now(),
				 'Administrator', 'Administrator', %(date)s, %(date)s, 'Room Charge',
				 'planted duplicate', 1, 10, 10, 0, 10, %(key)s)
			""",
			{
				"name": frappe.generate_hash(length=10),
				"parent": self.folio,
				"date": nowdate(),
				"key": key,
			},
		)

	# -- the states a site can be in --------------------------------------

	def test_constraint_is_created_when_absent(self):
		_drop_index(CHARGE)
		self.assertFalse(_index_present(CHARGE))

		schema.apply_financial_idempotency_constraints()

		self.assertTrue(_index_present(CHARGE))

	def test_reapplying_is_a_no_op(self):
		"""`after_migrate` calls this on every migrate; it must be idempotent."""
		schema.apply_financial_idempotency_constraints()
		schema.apply_financial_idempotency_constraints()

		self.assertTrue(_index_present(CHARGE))
		self.assertTrue(_index_present("Folio Payment"))

	# -- the guard ---------------------------------------------------------

	def test_migration_stops_safely_when_duplicates_exist(self):
		"""It refuses, it says which rows, and it deletes nothing."""
		_drop_index(CHARGE)

		try:
			self._insert_raw_charge("dupe:key:1")
			self._insert_raw_charge("dupe:key:1")
			frappe.db.commit()

			duplicates = schema.find_duplicate_keys(CHARGE)

			self.assertTrue(
				any(row["parent"] == self.folio for row in duplicates),
				msg=f"the duplicate was not detected; found {duplicates}",
			)

			with self.assertRaises(frappe.ValidationError) as caught:
				schema.apply_financial_idempotency_constraints()

			message = str(caught.exception)

			self.assertIn("dupe:key:1", message, msg="the report must name the offending key")
			self.assertIn(self.folio, message, msg="the report must name the folio")

			# The whole point: the money is still there.
			self.assertEqual(
				frappe.db.count(CHARGE, {"parent": self.folio, "idempotency_key": "dupe:key:1"}),
				2,
				msg="the migration deleted a financial row to make itself pass",
			)
			self.assertFalse(_index_present(CHARGE))
		finally:
			frappe.db.delete(CHARGE, {"parent": self.folio})
			frappe.db.commit()

	def test_null_keys_do_not_block_the_constraint(self):
		"""Historical rows with no key at all must not stop the upgrade.

		MariaDB treats NULLs as distinct in a unique index, so any number of
		them coexist. Rewriting them to satisfy the constraint would be exactly
		the silent edit of financial history the migration must not make.
		"""
		_drop_index(CHARGE)

		try:
			self._insert_raw_charge(None)
			self._insert_raw_charge(None)
			frappe.db.commit()

			self.assertEqual(schema.find_duplicate_keys(CHARGE), [])

			schema.apply_financial_idempotency_constraints()

			self.assertTrue(_index_present(CHARGE))
			self.assertEqual(frappe.db.count(CHARGE, {"parent": self.folio}), 2)
		finally:
			frappe.db.delete(CHARGE, {"parent": self.folio})
			frappe.db.commit()

	def test_the_constraint_is_what_the_service_relies_on(self):
		"""End to end: with the index in place, a duplicate key cannot be stored."""
		schema.apply_financial_idempotency_constraints()

		folio_service.post_charge(
			self.folio, "Minibar", "Water", 20, idempotency_key="schema:live:1"
		)
		frappe.db.commit()

		with self.assertRaises(Exception) as caught:
			self._insert_raw_charge("schema:live:1")

		self.assertTrue(frappe.db.is_unique_key_violation(caught.exception))

		frappe.db.rollback()
