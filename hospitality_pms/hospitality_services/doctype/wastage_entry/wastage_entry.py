# Copyright (c) 2026, Globcom Qatar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from hospitality_pms.services.base import require_role
from hospitality_pms.services.exceptions import HospitalityPMSError
from hospitality_pms.services.kitchen import WASTAGE_APPROVAL_ROLES

#: Fields that fix what stock was actually written off, once `record_wastage`
#: (or a later issue) has stamped `stock_entry` onto the entry. `stock_entry`
#: itself is included: clearing it back to empty would silently unlock the
#: other fields on the very next save, since that save would then see no
#: prior write-off to protect.
_LOCKED_FIELDS = ("item", "quantity", "warehouse", "stock_entry")


class WastageEntry(Document):
	def validate(self):
		# Writing off stock is a management decision on every path, not only
		# the one that goes through `kitchen.record_wastage` (Roles Matrix
		# section 3). Importing the same tuple, rather than re-listing the
		# roles here, keeps the two paths from ever disagreeing about who
		# that is.
		require_role(WASTAGE_APPROVAL_ROLES)

		if flt(self.quantity) <= 0:
			frappe.throw(_("Wastage quantity must be greater than zero."), exc=HospitalityPMSError)

		# `notes` is already a mandatory field on this DocType, so there is
		# nothing further to check here.

		self._guard_posted_immutable()

	def _guard_posted_immutable(self):
		if self.is_new():
			return

		before = self.get_doc_before_save()
		if not before or not before.stock_entry:
			return

		for fieldname in _LOCKED_FIELDS:
			before_value = before.get(fieldname)
			after_value = self.get(fieldname)
			changed = (
				flt(before_value) != flt(after_value) if fieldname == "quantity" else before_value != after_value
			)

			if changed:
				frappe.throw(
					_("Wastage {0} has already moved stock and cannot be edited.").format(self.name),
					exc=HospitalityPMSError,
				)
