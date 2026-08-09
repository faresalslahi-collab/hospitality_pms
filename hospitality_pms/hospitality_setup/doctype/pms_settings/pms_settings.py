# Copyright (c) 2026, Globcom Qatar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from hospitality_pms.services.exceptions import ConfigurationError


class PMSSettings(Document):
	def validate(self):
		self.validate_default_property()
		self.validate_retention()

	def validate_default_property(self):
		if not self.default_property:
			return

		if not frappe.db.get_value("Property", self.default_property, "is_active"):
			frappe.throw(
				_("Property {0} is not active and cannot be the default property.").format(self.default_property),
				exc=ConfigurationError,
			)

	def validate_retention(self):
		"""Retention periods are operational limits, not a way around the policy.

		The approved minimums for reservation, stay, folio and audit data are
		enforced in code; only the short-lived categories are configurable, and
		they still have to be positive (SAS section 8).
		"""
		fields = (
			("guest_id_image_retention_days", "Guest ID Image Retention (Days)"),
			("integration_log_retention_days", "Integration Log Retention (Days)"),
			("temporary_payload_retention_days", "Temporary Payload Retention (Days)"),
		)

		for fieldname, label in fields:
			value = self.get(fieldname)

			if value is not None and value < 1:
				frappe.throw(_("{0} must be at least one day.").format(_(label)), exc=ConfigurationError)

	def on_update(self):
		frappe.clear_document_cache(self.doctype, self.name)
