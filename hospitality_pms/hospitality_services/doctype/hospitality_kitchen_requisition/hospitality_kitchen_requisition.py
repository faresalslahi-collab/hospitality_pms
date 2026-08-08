# Copyright (c) 2026, Globcom Qatar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from hospitality_pms.services.exceptions import ConfigurationError, HospitalityPMSError

#: Header fields that fix which warehouses the stock actually moved between,
#: once `issue_requisition` has stamped `stock_entry` onto the requisition.
#: `stock_entry` itself is included: clearing it back to empty would silently
#: unlock every other field on the very next save, since that save would
#: then see no prior movement to protect.
_LOCKED_HEADER_FIELDS = ("from_warehouse", "to_warehouse", "stock_entry")

#: Line fields that fix what actually moved.
_LOCKED_LINE_FIELDS = ("item", "item_name", "quantity", "uom", "issued_quantity", "notes")

_NUMERIC_FIELDS = {"quantity", "issued_quantity"}


class HospitalityKitchenRequisition(Document):
	def validate(self):
		before = None if self.is_new() else self.get_doc_before_save()

		if before and before.stock_entry:
			# The stock has already moved for exactly these lines and
			# warehouses; nothing about the movement itself may change now.
			self._guard_issued_immutable(before)
			return

		self._validate_warehouses()
		self._validate_lines()

	def _validate_warehouses(self):
		if self.from_warehouse and self.to_warehouse and self.from_warehouse == self.to_warehouse:
			frappe.throw(
				_("The source and destination warehouses must differ."), exc=ConfigurationError
			)

	def _validate_lines(self):
		for row in self.lines:
			if flt(row.quantity) <= 0:
				frappe.throw(
					_("Row {0}: quantity must be greater than zero.").format(row.idx), exc=HospitalityPMSError
				)

	def _guard_issued_immutable(self, before):
		for fieldname in _LOCKED_HEADER_FIELDS:
			if self._changed(before.get(fieldname), self.get(fieldname), fieldname):
				frappe.throw(
					_("Requisition {0} has already moved stock and cannot be edited.").format(self.name),
					exc=HospitalityPMSError,
				)

		before_lines = {row.name: row for row in before.lines}

		if len(before_lines) != len(self.lines):
			frappe.throw(
				_("Requisition {0} has already moved stock; its lines cannot change.").format(self.name),
				exc=HospitalityPMSError,
			)

		for row in self.lines:
			original = before_lines.get(row.name)

			if not original:
				frappe.throw(
					_("Requisition {0} has already moved stock; its lines cannot change.").format(self.name),
					exc=HospitalityPMSError,
				)

			for fieldname in _LOCKED_LINE_FIELDS:
				if self._changed(original.get(fieldname), row.get(fieldname), fieldname):
					frappe.throw(
						_("Requisition {0} has already moved stock; its lines cannot change.").format(self.name),
						exc=HospitalityPMSError,
					)

	@staticmethod
	def _changed(before_value, after_value, fieldname):
		if fieldname in _NUMERIC_FIELDS:
			return flt(before_value) != flt(after_value)
		return before_value != after_value
