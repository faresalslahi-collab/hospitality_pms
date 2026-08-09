# Copyright (c) 2026, Globcom Qatar and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from hospitality_pms.hospitality_setup.structure_utils import guard_deactivation
from hospitality_pms.utils.naming import CodeNamedDocument


class Building(CodeNamedDocument, Document):
	code_field = "building_code"

	def validate(self):
		self.normalise_code_field()
		self.guard_deactivation()

	def guard_deactivation(self):
		# A building cannot go inactive while an active wing or floor still
		# organises rooms under it.
		guard_deactivation(
			self,
			references=[
				("Wing", "building"),
				("Floor", "building"),
			],
		)
