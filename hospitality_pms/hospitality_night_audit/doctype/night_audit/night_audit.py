# Copyright (c) 2026, Globcom Qatar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from hospitality_pms.services.base import NIGHT_AUDIT_SERVICE, in_service_context
from hospitality_pms.services.exceptions import NightAuditError

#: Fields that say what the audit has done and what it is worth. Every one of
#: them is written by `services/night_audit.py` and by nothing else.
#:
#: The whole of Wave 4 rests on these meaning what they say. If an operator can
#: type `Ready to Close` into the status, or set `reconciliation_completed_on`
#: from a form, then the close gate is checking a field the person being gated
#: can fill in themselves - which is no gate at all.
SERVICE_OWNED_FIELDS = (
	"audit_status",
	"business_date",
	"next_business_date",
	"review_completed_on",
	"review_completed_by",
	"posting_completed_on",
	"posting_completed_by",
	"reconciliation_completed_on",
	"reconciliation_completed_by",
	"reconciliation_population",
	"reconciliation_variances",
	"reconciled_row_count",
	"reconciled_row_total",
	"rooms_charged",
	"charges_posted",
	"postings_failed",
	"room_revenue",
	"total_revenue",
	"payments_received",
	"outstanding_balance",
	"occupancy_percentage",
	"adr",
	"revpar",
	"closed_on",
	"closed_by",
	"reopened_on",
	"reopened_by",
)


class NightAudit(Document):
	def validate(self):
		self._guard_service_owned_fields()

	def _guard_service_owned_fields(self):
		"""Refuse a direct edit of anything the audit workflow owns.

		`read_only` on the DocType hides these in the form; it does not stop a
		script, the REST API or `frappe.client.set_value` from writing them.
		The people who hold Night Audit write are exactly the people the close
		gate exists to constrain, so the fields the gate reads cannot also be
		theirs to set.

		Deliberately narrow. `notes` and exception resolutions stay editable -
		an auditor annotating the day is not the same as an auditor declaring
		it reconciled.
		"""
		if in_service_context(NIGHT_AUDIT_SERVICE):
			return

		if self.is_new():
			# A new audit may only be created by the service, which is also
			# what serialises it against a second audit for the same date.
			frappe.throw(
				_("A Night Audit is started through the Night Audit service, not by creating the document."),
				exc=NightAuditError,
			)

		changed = [field for field in SERVICE_OWNED_FIELDS if self.has_value_changed(field)]

		if not changed:
			return

		frappe.throw(
			_(
				"{0} are set by the Night Audit workflow and cannot be edited directly. Run the "
				"corresponding audit step instead."
			).format(", ".join(_(self.meta.get_label(field)) for field in changed)),
			exc=NightAuditError,
		)
