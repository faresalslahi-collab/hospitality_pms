# Copyright (c) 2026, Globcom Qatar and contributors
# For license information, please see license.txt

from frappe import _
from frappe.model.document import Document

from hospitality_pms.services.exceptions import throw


class HospitalityGuestMergeLog(Document):
	"""Append-only audit of guest deduplication (SAS section 7).

	Written only by `hospitality_pms.services.guests.merge_guests`. Nothing
	else may create, edit or remove a row: doing so would let a merge's
	history be rewritten after the fact.
	"""

	def on_update(self):
		# `on_update` fires once during insert too, which is the only write
		# this DocType is meant to receive. `is_new()` is already False by that
		# point -- `__islocal` is cleared before the post-save hooks run -- so
		# the insert is identified by `flags.in_insert`, which Frappe sets for
		# exactly that window.
		if self.flags.in_insert:
			return

		throw(_("{0} is an append-only audit record and cannot be edited.").format(_(self.doctype)))

	def on_trash(self):
		throw(_("{0} is an append-only audit record and cannot be deleted.").format(_(self.doctype)))
