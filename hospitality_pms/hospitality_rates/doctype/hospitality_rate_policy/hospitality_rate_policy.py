# Copyright (c) 2026, Globcom Qatar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from hospitality_pms.services.exceptions import ConfigurationError
from hospitality_pms.utils.naming import CodeNamedDocument


class HospitalityRatePolicy(CodeNamedDocument, Document):
	code_field = "policy_code"

	def validate(self):
		self.normalise_code_field()
		self.validate_charge()
		self.validate_deposit()
		self.validate_free_cancellation_hours()

	def validate_charge(self):
		charge_value = self.charge_value or 0

		if charge_value < 0:
			frappe.throw(_("Charge Value cannot be negative."), exc=ConfigurationError)

		if self.charge_basis == "Percentage of Stay" and charge_value > 100:
			frappe.throw(
				_("Charge Value cannot exceed 100 when Charge Basis is Percentage of Stay."),
				exc=ConfigurationError,
			)

		if self.charge_basis == "Fixed Amount" and charge_value <= 0:
			frappe.throw(
				_(
					"Charge Value must be greater than zero when Charge Basis is Fixed Amount."
					" A fixed charge of nothing is a No Charge policy, not a Fixed Amount one."
				),
				exc=ConfigurationError,
			)

	def validate_deposit(self):
		if self.deposit_percentage is not None and not (0 <= self.deposit_percentage <= 100):
			frappe.throw(_("Deposit Percentage must be between 0 and 100."), exc=ConfigurationError)

		if self.deposit_fixed_amount is not None and self.deposit_fixed_amount < 0:
			frappe.throw(_("Deposit Fixed Amount cannot be negative."), exc=ConfigurationError)

		if self.policy_type == "Deposit" and not (self.deposit_percentage or self.deposit_fixed_amount):
			frappe.throw(
				_("A Deposit policy must specify a Deposit Percentage or a Deposit Fixed Amount."),
				exc=ConfigurationError,
			)

	def validate_free_cancellation_hours(self):
		if self.free_cancellation_hours is not None and self.free_cancellation_hours < 0:
			frappe.throw(_("Free Cancellation Hours cannot be negative."), exc=ConfigurationError)
