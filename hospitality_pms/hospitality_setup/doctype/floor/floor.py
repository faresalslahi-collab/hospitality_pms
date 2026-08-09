# Copyright (c) 2026, Globcom Qatar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from hospitality_pms.hospitality_setup.structure_utils import validate_property_matches_parent
from hospitality_pms.services.exceptions import ConfigurationError
from hospitality_pms.utils.naming import CodeNamedDocument


class Floor(CodeNamedDocument, Document):
	code_field = "floor_code"

	def validate(self):
		self.normalise_code_field()
		validate_property_matches_parent(self, "Building", "building")
		self.validate_wing_belongs_to_building()
		self.validate_unique_floor_level()

	def validate_wing_belongs_to_building(self):
		# A wing is optional on a floor, but when set it must belong to the same
		# building - otherwise the floor would sit in another building's wing.
		if not self.wing:
			return

		wing_building = frappe.db.get_value("Wing", self.wing, "building")

		if wing_building and wing_building != self.building:
			frappe.throw(
				_("Floor {0} is set to building {1}, but its wing {2} belongs to building {3}.").format(
					self.name, self.building, self.wing, wing_building
				),
				exc=ConfigurationError,
			)

	def validate_unique_floor_level(self):
		duplicate = frappe.get_all(
			"Floor",
			filters={
				"building": self.building,
				"floor_level": self.floor_level,
				"name": ("!=", self.name),
			},
			pluck="name",
			limit=1,
		)

		if duplicate:
			frappe.throw(
				_("Level {0} is already used by floor {1} in building {2}.").format(
					self.floor_level, duplicate[0], self.building
				),
				exc=ConfigurationError,
			)
