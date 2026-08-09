# Copyright (c) 2026, Globcom Qatar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from hospitality_pms.services.exceptions import HospitalityPMSError
from hospitality_pms.services.kitchen import MENU_DOCTYPE

#: Header fields that fix what was actually billed, once `deliver_order` has
#: stamped `folio_charge_row` onto the order. `folio_charge_row` itself is
#: included: clearing it back to empty would silently unlock every other
#: field on the very next save, since that save would then see no prior
#: charge to protect.
_LOCKED_HEADER_FIELDS = ("subtotal", "service_charge", "tax_amount", "total_amount", "folio", "folio_charge_row")

#: Line fields that fix what was actually billed. `item_name` is derived
#: from `menu_item` and so never moves independently of it.
_LOCKED_LINE_FIELDS = ("menu_item", "item_name", "quantity", "rate", "amount", "notes", "is_prepared")

_NUMERIC_FIELDS = {"quantity", "rate", "amount", "subtotal", "service_charge", "tax_amount", "total_amount"}


class RoomServiceOrder(Document):
	def validate(self):
		before = None if self.is_new() else self.get_doc_before_save()

		if before and before.folio_charge_row:
			# The folio has already been charged for exactly these lines and
			# totals. Re-pricing here (as the branch below does) would let the
			# order drift away from what was actually billed if the menu's
			# rate has changed since, so a charged order is only checked for
			# forbidden edits, never recomputed.
			self._guard_charged_immutable(before)
			return

		self._price_lines()

	def _price_lines(self):
		"""Price every line from the menu and derive the totals from that.

		Mirrors `kitchen.create_order`'s pricing rule exactly: the rate always
		comes from `Menu Item.selling_rate`, never from whatever a
		client (Desk or API) typed into the row.
		"""
		if not self.lines:
			frappe.throw(_("An order needs at least one line."), exc=HospitalityPMSError)

		subtotal = 0.0

		for row in self.lines:
			if not row.menu_item:
				frappe.throw(_("Row {0}: a menu item is required.").format(row.idx), exc=HospitalityPMSError)

			if flt(row.quantity) <= 0:
				frappe.throw(
					_("Row {0}: quantity must be greater than zero.").format(row.idx), exc=HospitalityPMSError
				)

			item = frappe.db.get_value(
				MENU_DOCTYPE, row.menu_item, ["menu_item_name", "selling_rate", "is_active"], as_dict=True
			)

			if not item or not item.is_active:
				frappe.throw(
					_("Menu item {0} is not available.").format(row.menu_item), exc=HospitalityPMSError
				)

			# The rate comes from the menu, not from what was typed: a Desk
			# user who could set their own price could give the guest
			# anything away, exactly as a tampered API caller could.
			row.item_name = item.menu_item_name
			row.rate = flt(item.selling_rate)
			row.amount = flt(flt(row.quantity) * row.rate, 2)
			subtotal += row.amount

		# Totals are derived, never entered.
		self.subtotal = flt(subtotal, 2)
		self.total_amount = flt(subtotal + flt(self.service_charge) + flt(self.tax_amount), 2)

	def _guard_charged_immutable(self, before):
		for fieldname in _LOCKED_HEADER_FIELDS:
			if self._changed(before.get(fieldname), self.get(fieldname), fieldname):
				frappe.throw(
					_("Order {0} has already been charged to the folio and cannot be edited.").format(self.name),
					exc=HospitalityPMSError,
				)

		before_lines = {row.name: row for row in before.lines}

		if len(before_lines) != len(self.lines):
			frappe.throw(
				_("Order {0} has already been charged to the folio; its lines cannot change.").format(self.name),
				exc=HospitalityPMSError,
			)

		for row in self.lines:
			original = before_lines.get(row.name)

			if not original:
				frappe.throw(
					_("Order {0} has already been charged to the folio; its lines cannot change.").format(
						self.name
					),
					exc=HospitalityPMSError,
				)

			for fieldname in _LOCKED_LINE_FIELDS:
				if self._changed(original.get(fieldname), row.get(fieldname), fieldname):
					frappe.throw(
						_("Order {0} has already been charged to the folio; its lines cannot change.").format(
							self.name
						),
						exc=HospitalityPMSError,
					)

	@staticmethod
	def _changed(before_value, after_value, fieldname):
		# A value stored as "150" and one stored as "150.0" are not a real
		# change; only currency/float fields need that tolerance.
		if fieldname in _NUMERIC_FIELDS:
			return flt(before_value) != flt(after_value)
		return before_value != after_value
