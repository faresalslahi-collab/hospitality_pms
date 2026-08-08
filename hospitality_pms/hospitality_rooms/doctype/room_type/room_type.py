# Copyright (c) 2026, Globcom Qatar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from hospitality_pms.hospitality_setup.structure_utils import guard_deactivation
from hospitality_pms.services.exceptions import ConfigurationError
from hospitality_pms.utils.naming import CodeNamedDocument


class RoomType(CodeNamedDocument, Document):
	code_field = "room_type_code"

	def validate(self):
		self.normalise_code_field()
		self.validate_occupancy()
		self.validate_rates()
		self.validate_deactivation()

	def validate_occupancy(self):
		if self.base_occupancy < 1:
			frappe.throw(_("Base Occupancy must be at least 1."), exc=ConfigurationError)

		if self.max_occupancy < self.base_occupancy:
			frappe.throw(
				_("Max Occupancy ({0}) cannot be less than Base Occupancy ({1}).").format(
					self.max_occupancy, self.base_occupancy
				),
				exc=ConfigurationError,
			)

		if self.max_adults < 1:
			frappe.throw(_("Max Adults must be at least 1."), exc=ConfigurationError)

		# Max Adults may never exceed Max Occupancy - that would let a booking
		# sell more adults than the room can hold at all. But Max Adults +
		# Max Children is deliberately NOT required to equal, or stay under,
		# Max Occupancy: a family room commonly sells 2 adults + 2 children
		# against a Max Occupancy of 4. Which combinations are actually
		# authorised is a rate-plan concern (HPMS-0.8.0), not a room type
		# validity concern, so we do not police it here.
		if self.max_adults > self.max_occupancy:
			frappe.throw(
				_("Max Adults ({0}) cannot exceed Max Occupancy ({1}).").format(
					self.max_adults, self.max_occupancy
				),
				exc=ConfigurationError,
			)

	def validate_rates(self):
		rate_fields = (
			("base_rate", _("Base Rate")),
			("extra_adult_charge", _("Extra Adult Charge")),
			("extra_child_charge", _("Extra Child Charge")),
			("extra_bed_charge", _("Extra Bed Charge")),
		)

		for fieldname, label in rate_fields:
			value = self.get(fieldname)
			if value is not None and value < 0:
				frappe.throw(_("{0} cannot be negative.").format(label), exc=ConfigurationError)

	def validate_deactivation(self):
		guard_deactivation(self, [("Hotel Room", "room_type")])
