# Copyright (c) 2026, Globcom Qatar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from hospitality_pms.services.exceptions import HospitalityPMSError


class HospitalityFolioLog(Document):
	def on_update(self):
		# `flags.in_insert` is only true while the very insert that created this
		# row is running, so the initial write goes through untouched and every
		# later save - however it is triggered - is refused.
		if not self.flags.in_insert:
			frappe.throw(
				_("{0} is an append-only audit record and cannot be modified.").format(_(self.doctype)),
				exc=HospitalityPMSError,
			)

	def on_trash(self):
		frappe.throw(
			_("{0} is an append-only audit record and cannot be deleted.").format(_(self.doctype)),
			exc=HospitalityPMSError,
		)
