# Copyright (c) 2026, Globcom Qatar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from hospitality_pms.services import folio as folio_service
from hospitality_pms.services.base import FINANCIAL_POSTING, assert_service_context
from hospitality_pms.services.exceptions import FolioError, InvalidStateTransitionError

#: Statuses a brand-new folio may be saved as directly. Every other status is
#: reached only through FolioService.transition, which writes the field with
#: `frappe.db.set_value()` and so never runs `validate()`.
CREATABLE_STATUSES = (folio_service.OPEN,)

#: Fields that fix what a posted charge *is*. Once a charge row is saved,
#: editing any of these would let money move without a trace, which is
#: exactly what reversal exists to prevent.
CHARGE_FINANCIAL_FIELDS = ("amount", "tax_amount", "total_amount", "charge_type", "quantity", "unit_price")

#: Same rule for a posted payment row.
PAYMENT_FINANCIAL_FIELDS = ("amount", "payment_type", "payment_method")

#: Fields compared as numbers rather than as raw values, so a value stored as
#: "150" and one stored as "150.0" are not reported as a change.
NUMERIC_FIELDS = {"amount", "tax_amount", "total_amount", "quantity", "unit_price"}


class GuestFolio(Document):
	def validate(self):
		# The status guard and the immutability guards run first, so an edit
		# that is simply not allowed is reported as such rather than as a
		# knock-on total that no longer balances.
		self._guard_status_change()
		self._guard_new_financial_rows()
		self._guard_posted_rows_immutable()

		self._validate_credit_limit()
		self._validate_split_folio()

		# Totals are derived, never entered (see folio.py "Totals" section).
		# `_recalculate` is the one place that formula is written; importing
		# it here - rather than re-deriving charges/taxes/payments/balance on
		# the DocType - means there is exactly one definition to get right and
		# exactly one place to fix if it ever changes. It only mutates the
		# in-memory document and does not save, so it is safe to call from
		# inside validate().
		folio_service._recalculate(self)

	def on_trash(self):
		# A folio that has ever taken a charge or a payment is financial
		# history. Charges and payments are themselves append-only (corrected
		# by reversal, never removed), so the rows currently on the folio are
		# exactly the rows it has ever had.
		if self.charges or self.payments:
			frappe.throw(
				_("Folio {0} has posted charges or payments and cannot be deleted.").format(self.name),
				exc=FolioError,
			)

	# ------------------------------------------------------------------
	# Status is service-owned
	# ------------------------------------------------------------------

	def _guard_status_change(self):
		"""Refuse a direct edit of `folio_status`.

		Every real transition goes through FolioService.transition, which
		writes the field with `frappe.db.set_value()` - that call does not run
		`validate()`, so this guard never fights the service; it only catches
		a form save or API call that tried to set the field itself.
		"""
		if self.is_new():
			# has_value_changed() has no prior value to compare against on
			# insert and unconditionally reports True, so a new document is
			# checked against the fixed list of legal starting statuses
			# instead.
			if self.folio_status not in CREATABLE_STATUSES:
				frappe.throw(
					_("A new folio can only be created with status {0}.").format(
						", ".join(CREATABLE_STATUSES)
					),
					exc=InvalidStateTransitionError,
				)
			return

		if self.has_value_changed("folio_status"):
			frappe.throw(
				_("Folio status is changed only through a folio transition, not by editing the document directly."),
				exc=InvalidStateTransitionError,
			)

	# ------------------------------------------------------------------
	# Money is created by the financial services, not by saving a document
	# ------------------------------------------------------------------

	def _guard_new_financial_rows(self):
		"""Refuse a charge or payment row that no financial service posted.

		Write permission on the folio is not authority to invent money. The
		front desk holds it legitimately, and the sweep showed what that meant
		in practice: through a plain `Document.save()` an agent created a
		+500 room charge, a -500 room charge, a -250 adjustment, a +999
		discount that *increased* the balance, a 10 000 payment and a -7 777
		refund - all back-dated into a closed business date, all with
		`posted_by` NULL, all with duplicate idempotency keys, and none of them
		producing a single Folio Log row.

		Every one of those controls lives in `services/folio.py`, and none of
		them can run if the row does not come through it. Rather than restate
		the rules here - a second, drifting copy of the ones that matter most -
		this refuses the row outright unless an approved service is posting it,
		which leaves exactly one way for money to reach a folio.

		Deliberately narrow: only *new* rows in the two monetary tables. Edits
		to `billing_instructions`, `credit_limit` or any other operational
		field are untouched, and a folio with no new money saves normally.
		"""
		if not self._has_new_financial_rows():
			return

		assert_service_context(
			FINANCIAL_POSTING,
			_(
				"Charges and payments are posted through the folio service, which records "
				"the actor, the business date and the audit trail. They cannot be added by "
				"editing the folio directly."
			),
		)

	def _has_new_financial_rows(self) -> bool:
		"""Whether this save introduces a charge or payment row.

		On insert every row is new. On update, `get_doc_before_save()` holds
		the folio as it was, so a row whose name is absent from it is one this
		save is adding.
		"""
		if self.is_new():
			return bool(self.charges or self.payments)

		before = self.get_doc_before_save()

		if not before:
			# No before-image means Frappe could not read the prior state; the
			# safe reading of "cannot tell" is "assume rows may be new".
			return bool(self.charges or self.payments)

		for table, before_rows in (("charges", before.charges), ("payments", before.payments)):
			known = {row.name for row in before_rows}

			if any(row.name not in known for row in self.get(table)):
				return True

		return False

	# ------------------------------------------------------------------
	# Posted charges and payments are immutable
	# ------------------------------------------------------------------

	def _guard_posted_rows_immutable(self):
		"""Refuse editing or deleting a charge or payment row already saved.

		`get_doc_before_save()` is only populated on an update, and only holds
		the document as it stood before this save started, which is exactly
		the "already posted" snapshot to compare against.
		"""
		if self.is_new():
			return

		before = self.get_doc_before_save()
		if not before:
			return

		self._guard_table_immutable(before.charges, self.charges, CHARGE_FINANCIAL_FIELDS, _("charge"))
		self._guard_table_immutable(before.payments, self.payments, PAYMENT_FINANCIAL_FIELDS, _("payment"))

	def _guard_table_immutable(self, before_rows, current_rows, fields, label):
		before_by_name = {row.name: row for row in before_rows}
		current_names = set()

		for row in current_rows:
			current_names.add(row.name)

			original = before_by_name.get(row.name)
			if not original:
				# A row with no match in the before-save snapshot is new in
				# this save, so there is nothing to protect yet.
				continue

			for fieldname in fields:
				before_value = original.get(fieldname)
				after_value = row.get(fieldname)

				changed = (
					flt(before_value) != flt(after_value)
					if fieldname in NUMERIC_FIELDS
					else before_value != after_value
				)

				if changed:
					frappe.throw(
						_(
							"{0} {1} is posted and cannot be edited; correct it with a reversal instead."
						).format(_(label).title(), row.name),
						exc=FolioError,
					)

		missing = set(before_by_name) - current_names
		if missing and not self.flags.hpms_moving_rows:
			frappe.throw(
				_(
					"{0} {1} is posted and cannot be deleted; correct it with a reversal instead."
				).format(_(label).title(), next(iter(missing))),
				exc=FolioError,
			)

	# `flags.hpms_moving_rows` is set only by FolioService's split and merge,
	# which move a row from one folio to another. The row is not destroyed - it
	# exists on the target and the audit log records both sides - so the
	# reversal rule does not apply. Nothing else may set this flag.

	# ------------------------------------------------------------------
	# Other fields
	# ------------------------------------------------------------------

	def _validate_credit_limit(self):
		if self.credit_limit is not None and flt(self.credit_limit) < 0:
			frappe.throw(_("Credit limit cannot be negative."), exc=FolioError)

	def _validate_split_folio(self):
		if self.folio_type == "Split" and not self.parent_folio:
			frappe.throw(_("A split folio must reference its parent folio."), exc=FolioError)
