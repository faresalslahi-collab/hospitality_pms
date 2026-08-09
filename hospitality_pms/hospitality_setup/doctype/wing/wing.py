# Copyright (c) 2026, Globcom Qatar and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from hospitality_pms.hospitality_setup.structure_utils import (
	guard_deactivation,
	validate_property_matches_parent,
)
from hospitality_pms.utils.naming import CodeNamedDocument


class Wing(CodeNamedDocument, Document):
	code_field = "wing_code"

	def validate(self):
		self.normalise_code_field()
		validate_property_matches_parent(self, "Building", "building")
		# A wing cannot go inactive while an active floor still references it.
		guard_deactivation(self, references=[("Floor", "wing")])
