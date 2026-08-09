# Copyright (c) 2026, Globcom Qatar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from hospitality_pms.services.exceptions import ConfigurationError
from hospitality_pms.services.property import assert_business_date_change_allowed
from hospitality_pms.utils.naming import CodeNamedDocument

#: Accounts that must belong to the property's company, and the label used when
#: reporting a mismatch.
COMPANY_SCOPED_ACCOUNTS = (
	("receivable_account", "Default Receivable Account"),
	("room_revenue_account", "Room Revenue Account"),
	("deposit_liability_account", "Deposit Liability Account"),
)

PERCENTAGE_BASES = (
	"Percentage of Room Charge",
	"Percentage of All Charges",
)


class Property(CodeNamedDocument, Document):
	code_field = "property_code"

	def validate(self):
		self.normalise_code_field()
		self.apply_company_defaults()
		assert_business_date_change_allowed(self)
		self.validate_single_active_property()
		self.validate_company_scoped_records()
		self.validate_languages()
		self.validate_warehouses()
		self.validate_fees()

	def apply_company_defaults(self):
		"""Fill blanks from the company rather than making the user repeat them."""
		if not self.company:
			return

		if not self.currency:
			self.currency = frappe.db.get_value("Company", self.company, "default_currency")

	def validate_single_active_property(self):
		"""First release operates one active property (HPMS-DEC-009).

		The schema is multi-property-ready, so this is a switch in Hospitality
		Settings rather than a structural limit.
		"""
		if not self.is_active:
			return

		if frappe.db.get_single_value("PMS Settings", "enable_multi_property"):
			return

		existing = frappe.db.get_value(
			"Property",
			{"is_active": 1, "name": ("!=", self.name)},
			"name",
		)

		if existing:
			frappe.throw(
				_(
					"Property {0} is already active. The first release operates one active property; "
					"enable multi property operation in PMS Settings to run more."
				).format(existing),
				exc=ConfigurationError,
			)

	def validate_company_scoped_records(self):
		"""Accounts and cost centers must belong to the property's company.

		Posting a folio to another company's ledger would corrupt the accounts
		this app is not the system of record for, so this is refused outright.
		"""
		if not self.company:
			return

		for fieldname, label in COMPANY_SCOPED_ACCOUNTS:
			self._assert_belongs_to_company("Account", self.get(fieldname), label)

		self._assert_belongs_to_company("Cost Center", self.cost_center, "Cost Center")

		for row in self.fees:
			self._assert_belongs_to_company(
				"Account",
				row.income_account,
				_("Income Account for {0}").format(_(row.fee_type)),
			)

	def _assert_belongs_to_company(self, doctype: str, name: str | None, label: str):
		if not name:
			return

		company = frappe.db.get_value(doctype, name, "company")

		if company and company != self.company:
			frappe.throw(
				_("{0} {1} belongs to company {2}, not {3}.").format(_(label), name, company, self.company),
				exc=ConfigurationError,
			)

	def validate_languages(self):
		"""Keep the language table and the default language in agreement."""
		if not self.default_language:
			frappe.throw(_("A default language is required."), exc=ConfigurationError)

		listed = [row.language for row in self.languages]

		if self.default_language not in listed:
			self.append("languages", {"language": self.default_language, "is_default": 1})

		if len(listed) != len(set(listed)):
			frappe.throw(_("A language may be listed only once."), exc=ConfigurationError)

		# Exactly one row carries the default, and it is the default language.
		for row in self.languages:
			row.is_default = 1 if row.language == self.default_language else 0

	def validate_warehouses(self):
		"""One default warehouse per purpose, and no purpose mapped twice to the same warehouse."""
		seen = set()
		defaults = {}

		for row in self.warehouses:
			key = (row.purpose, row.warehouse)

			if key in seen:
				frappe.throw(
					_("Warehouse {0} is mapped to {1} more than once.").format(row.warehouse, _(row.purpose)),
					exc=ConfigurationError,
				)

			seen.add(key)

			if row.is_default:
				if row.purpose in defaults:
					frappe.throw(
						_("{0} has more than one default warehouse.").format(_(row.purpose)),
						exc=ConfigurationError,
					)
				defaults[row.purpose] = row.warehouse

		# A purpose with exactly one mapping is unambiguous; mark it default so
		# lookups never depend on row order.
		by_purpose = {}
		for row in self.warehouses:
			by_purpose.setdefault(row.purpose, []).append(row)

		for purpose, rows in by_purpose.items():
			if len(rows) == 1 and purpose not in defaults:
				rows[0].is_default = 1

	def validate_fees(self):
		"""Fee rates must be usable by the charge calculation."""
		for row in self.fees:
			if row.rate is None or row.rate < 0:
				frappe.throw(
					_("Rate for {0} must be zero or greater.").format(_(row.fee_type)),
					exc=ConfigurationError,
				)

			if row.charge_basis in PERCENTAGE_BASES and row.rate > 100:
				frappe.throw(
					_("{0} is a percentage and cannot exceed 100.").format(_(row.fee_type)),
					exc=ConfigurationError,
				)

			if row.valid_from and row.valid_upto and row.valid_from > row.valid_upto:
				frappe.throw(
					_("{0} is valid from {1} to {2}, which is not a valid period.").format(
						_(row.fee_type), row.valid_from, row.valid_upto
					),
					exc=ConfigurationError,
				)

	def on_update(self):
		# Property configuration is read through frappe.get_cached_doc on every
		# operational request, so the cache must not outlive an edit.
		frappe.clear_document_cache(self.doctype, self.name)
