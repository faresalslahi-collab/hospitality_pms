# Copyright (c) 2026, Globcom Qatar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from hospitality_pms.hospitality_setup.structure_utils import validate_property_matches_parent
from hospitality_pms.services.exceptions import ConfigurationError
from hospitality_pms.utils.naming import CodeNamedDocument


class HospitalityShift(CodeNamedDocument, Document):
	code_field = "shift_code"

	def validate(self):
		self.normalise_code_field()
		validate_property_matches_parent(self, "Hospitality Department", "department")
		self.validate_timing()
		self.validate_days()

	def validate_timing(self):
		"""Keep the shift window and the midnight flag consistent.

		A night audit shift legitimately starts at 23:00 and ends at 07:00, but
		that only makes sense with `crosses_midnight` set. Left inconsistent,
		later shift-based reporting would attribute work to the wrong day.
		"""
		if not self.start_time or not self.end_time:
			return

		if self.start_time == self.end_time:
			frappe.throw(_("A shift cannot start and end at the same time."), exc=ConfigurationError)

		ends_next_day = self.end_time < self.start_time

		if ends_next_day and not self.crosses_midnight:
			frappe.throw(
				_("This shift ends before it starts. Tick Crosses Midnight if it runs overnight."),
				exc=ConfigurationError,
			)

		if not ends_next_day and self.crosses_midnight:
			frappe.throw(
				_("Crosses Midnight is ticked, but the shift ends on the same day it starts."),
				exc=ConfigurationError,
			)

	def validate_days(self):
		if not self.shift_days:
			frappe.throw(_("Select at least one day the shift runs on."), exc=ConfigurationError)

		days = [row.day for row in self.shift_days]

		duplicates = {day for day in days if days.count(day) > 1}
		if duplicates:
			frappe.throw(
				_("Day {0} is listed more than once.").format(", ".join(sorted(duplicates))),
				exc=ConfigurationError,
			)
