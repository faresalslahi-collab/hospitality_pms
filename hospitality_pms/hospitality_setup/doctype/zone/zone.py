# Copyright (c) 2026, Globcom Qatar and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from hospitality_pms.utils.naming import CodeNamedDocument


class Zone(CodeNamedDocument, Document):
	code_field = "zone_code"

	def validate(self):
		self.normalise_code_field()
