# Copyright (c) 2026, Globcom Qatar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate

from hospitality_pms.hospitality_rates.rate_utils import validate_room_type_property
from hospitality_pms.hospitality_setup.structure_utils import guard_deactivation
from hospitality_pms.services.exceptions import ConfigurationError
from hospitality_pms.services.rates import WEEKDAYS, ZERO_RATE_TYPES
from hospitality_pms.utils.naming import CodeNamedDocument

#: (fieldname, expected policy_type, field label) for the three policy slots.
POLICY_SLOTS = (
	("cancellation_policy", "Cancellation", "Cancellation Policy"),
	("no_show_policy", "No Show", "No Show Policy"),
	("deposit_policy", "Deposit", "Deposit Policy"),
)


class HospitalityRatePlan(CodeNamedDocument, Document):
	code_field = "rate_plan_code"

	def validate(self):
		self.normalise_code_field()
		self.validate_validity_window()
		self.validate_room_type_rows()
		self.validate_zero_rate_type()
		self.validate_restriction_rows()
		self.validate_policies()
		self.validate_deactivation()

	def validate_validity_window(self):
		if self.valid_upto and getdate(self.valid_upto) < getdate(self.valid_from):
			frappe.throw(
				_("Valid Upto ({0}) cannot be before Valid From ({1}).").format(
					self.valid_upto, self.valid_from
				),
				exc=ConfigurationError,
			)

	def validate_room_type_rows(self):
		seen = set()

		for row in self.get("room_types") or []:
			validate_room_type_property(self, row.room_type, row=row)

			if row.room_type in seen:
				frappe.throw(
					_("Row #{0}: Room Type {1} is already listed on this rate plan.").format(
						row.idx, row.room_type
					),
					exc=ConfigurationError,
				)
			seen.add(row.room_type)

	def validate_zero_rate_type(self):
		"""Complimentary and House Use plans sell at zero (RateService forces
		this at pricing time); a non-zero Base Rate on their rows would be
		contradictory configuration, so it is refused here instead.
		"""
		if self.rate_type not in ZERO_RATE_TYPES:
			return

		for row in self.get("room_types") or []:
			if row.base_rate:
				frappe.throw(
					_(
						"Row #{0}: this plan's Rate Type is {1}, which always sells at zero, so"
						" Room Type {2} cannot have a non-zero Base Rate ({3})."
					).format(row.idx, _(self.rate_type), row.room_type, row.base_rate),
					exc=ConfigurationError,
				)

	def validate_restriction_rows(self):
		own_room_types = {row.room_type for row in self.get("room_types") or [] if row.room_type}

		for row in self.get("restrictions") or []:
			self._validate_restriction_row(row, own_room_types)

	def _validate_restriction_row(self, row, own_room_types):
		if (
			row.min_length_of_stay
			and row.max_length_of_stay
			and row.min_length_of_stay > row.max_length_of_stay
		):
			frappe.throw(
				_("Row #{0}: Min Length of Stay ({1}) cannot exceed Max Length of Stay ({2}).").format(
					row.idx, row.min_length_of_stay, row.max_length_of_stay
				),
				exc=ConfigurationError,
			)

		if row.min_advance_days and row.max_advance_days and row.min_advance_days > row.max_advance_days:
			frappe.throw(
				_("Row #{0}: Min Advance Days ({1}) cannot exceed Max Advance Days ({2}).").format(
					row.idx, row.min_advance_days, row.max_advance_days
				),
				exc=ConfigurationError,
			)

		if row.applies_from and row.applies_upto and getdate(row.applies_from) > getdate(row.applies_upto):
			frappe.throw(
				_("Row #{0}: Applies From ({1}) cannot be after Applies Upto ({2}).").format(
					row.idx, row.applies_from, row.applies_upto
				),
				exc=ConfigurationError,
			)

		if row.room_type:
			validate_room_type_property(self, row.room_type, row=row)

			if row.room_type not in own_room_types:
				frappe.throw(
					_(
						"Row #{0}: Room Type {1} is not one of this rate plan's own room types, so"
						" this restriction would never apply."
					).format(row.idx, row.room_type),
					exc=ConfigurationError,
				)

		row.days_of_week = self._normalise_days_of_week(row.days_of_week, row.idx)

	@staticmethod
	def _normalise_days_of_week(value, idx):
		"""Canonicalise to a comma-separated, deduplicated, weekday-ordered
		string with no stray spaces, so `RateService._plan_restrictions`
		(which splits on comma and strips) matches reliably.
		"""
		if not value:
			return value

		days = {day.strip() for day in value.split(",") if day.strip()}
		invalid = sorted(days - set(WEEKDAYS))

		if invalid:
			frappe.throw(
				_("Row #{0}: {1} is not a valid day of the week.").format(idx, invalid[0]),
				exc=ConfigurationError,
			)

		return ",".join(day for day in WEEKDAYS if day in days)

	def validate_policies(self):
		for fieldname, expected_type, label in POLICY_SLOTS:
			self._validate_policy(fieldname, expected_type, _(label))

	def _validate_policy(self, fieldname, expected_type, label):
		policy = self.get(fieldname)
		if not policy:
			return

		policy_property, policy_type = frappe.db.get_value(
			"Hospitality Rate Policy", policy, ["property", "policy_type"]
		) or (None, None)

		if policy_property and policy_property != self.property:
			frappe.throw(
				_("{0} {1} belongs to property {2}, but this rate plan belongs to property {3}.").format(
					label, policy, policy_property, self.property
				),
				exc=ConfigurationError,
			)

		if policy_type and policy_type != expected_type:
			frappe.throw(
				_("{0}: {1} is a {2} policy and cannot be used here.").format(label, policy, policy_type),
				exc=ConfigurationError,
			)

	def validate_deactivation(self):
		guard_deactivation(self, [("Hospitality Daily Rate", "rate_plan")])
