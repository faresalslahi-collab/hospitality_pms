# Copyright (c) 2026, Globcom Qatar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from hospitality_pms.hospitality_setup.structure_utils import (
	guard_deactivation,
	validate_property_matches_parent,
)
from hospitality_pms.services.exceptions import ConfigurationError
from hospitality_pms.utils.naming import CodeNamedDocument

#: A department tree deeper than this is almost certainly a data entry mistake,
#: and the guard also bounds the walk when detecting cycles.
MAX_DEPARTMENT_DEPTH = 10


class PropertyDepartment(CodeNamedDocument, Document):
	code_field = "department_code"

	def validate(self):
		self.normalise_code_field()
		validate_property_matches_parent(self, "Property Department", "parent_department")
		self.validate_no_cycle()
		guard_deactivation(self, references=[("Property Department", "parent_department")])

	def validate_no_cycle(self):
		"""A department cannot end up as its own ancestor.

		Permissions and escalation paths walk this tree, so a cycle would hang
		those walks rather than fail visibly.
		"""
		if not self.parent_department:
			return

		if self.parent_department == self.name:
			frappe.throw(_("A department cannot be its own parent."), exc=ConfigurationError)

		seen = {self.name}
		current = self.parent_department

		for _depth in range(MAX_DEPARTMENT_DEPTH):
			if not current:
				return

			if current in seen:
				frappe.throw(
					_("Department {0} would create a loop in the department hierarchy.").format(current),
					exc=ConfigurationError,
				)

			seen.add(current)
			current = frappe.db.get_value("Property Department", current, "parent_department")

		frappe.throw(
			_("The department hierarchy is deeper than {0} levels.").format(MAX_DEPARTMENT_DEPTH),
			exc=ConfigurationError,
		)
