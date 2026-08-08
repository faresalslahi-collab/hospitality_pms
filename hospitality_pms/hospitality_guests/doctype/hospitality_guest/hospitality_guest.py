# Copyright (c) 2026, Globcom Qatar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from hospitality_pms.services.base import require_role
from hospitality_pms.services.exceptions import throw
from hospitality_pms.services.guests import compose_guest_name, find_duplicates

#: Roles allowed to place or lift a blacklist. Blacklisting is an elevated,
#: audited action (SAS section 7), not an everyday front desk edit.
BLACKLIST_ROLES = (
	"Hotel Manager",
	"General Manager",
	"Guest Relations Officer",
	"Hospitality Administrator",
	"System Manager",
)


class HospitalityGuest(Document):
	def validate(self):
		self.set_guest_name()
		self.normalise_contact_fields()
		self.validate_identifications()
		self.apply_consent_rules()
		self.stamp_new_alerts()
		self.apply_blacklist_rules()

		# Stay statistics (total_stays, total_nights, last_stay_on, lifetime_value)
		# are read-only here by design: they are rolled up from stays/folios by
		# later builds, not computed from anything this controller can see.

	def set_guest_name(self):
		"""Compose the display name via the guest service so every entry point
		(this controller, imports, channel bookings, merges) agrees on it."""
		self.guest_name = compose_guest_name(self.first_name, self.middle_name, self.last_name)

		if not self.guest_name:
			throw(_("A guest must have at least a first or last name."))

	def normalise_contact_fields(self):
		"""Trim stray whitespace and normalise email case.

		Format itself (valid email/phone shape) is already enforced by the
		fields' `options` (Email/Phone), so this only tidies input.
		"""
		if self.email_id:
			self.email_id = self.email_id.strip().lower()

		if self.mobile_no:
			self.mobile_no = self.mobile_no.strip()

	def validate_identifications(self):
		before = self.get_doc_before_save()
		before_rows = {row.name: row for row in (before.identifications if before else [])}

		if len(self.identifications) == 1:
			# A single document is unambiguously the primary one; do not make
			# the user tick a checkbox to say so.
			self.identifications[0].is_primary = 1
		elif sum(1 for row in self.identifications if row.is_primary) > 1:
			throw(_("Only one identification document may be marked as primary."))

		seen_pairs = set()

		for row in self.identifications:
			pair = (row.id_type, (row.id_number or "").strip())

			if pair in seen_pairs:
				throw(_("Identification {0} {1} is listed more than once.").format(_(row.id_type), row.id_number))
			seen_pairs.add(pair)

			if row.issue_date and row.expiry_date and row.issue_date > row.expiry_date:
				throw(
					_("Row {0}: issue date cannot be after the expiry date.").format(row.idx),
				)

			# A row absent from the pre-save doc is new -- on insert there is no
			# pre-save doc at all, so every row is treated as new.
			before_row = before_rows.get(row.name)
			was_verified = bool(before_row.verified) if before_row else False

			if row.verified and not was_verified:
				row.verified_by = frappe.session.user
				row.verified_on = now_datetime()
			elif not row.verified and was_verified:
				row.verified_by = None
				row.verified_on = None

	def apply_consent_rules(self):
		before = self.get_doc_before_save()
		before_rows = {row.name: row for row in (before.consents if before else [])}

		for row in self.consents:
			before_row = before_rows.get(row.name)
			was_granted = bool(before_row.granted) if before_row else False

			if row.granted and not was_granted and not row.granted_on:
				row.granted_on = now_datetime()
			elif not row.granted and was_granted and not row.withdrawn_on:
				row.withdrawn_on = now_datetime()

			# A consent that was never granted and never withdrawn needs no
			# stamp at all -- that is a perfectly ordinary "not asked yet" row.

	def stamp_new_alerts(self):
		"""Record who raised an alert and when, on the row that raised it.

		`alert` is already a mandatory field on Hospitality Guest Alert, so an
		empty Critical alert is refused by standard mandatory-field validation
		already -- no extra severity-specific check is needed here.
		"""
		for row in self.alerts:
			if row.is_new() and not row.raised_by:
				row.raised_by = frappe.session.user
				row.raised_on = now_datetime()

	def apply_blacklist_rules(self):
		"""Placing or lifting a blacklist is an elevated, audited action.

		A brand new, never-blacklisted guest is not a transition worth
		auditing -- `has_value_changed` reports every field as "changed" on
		insert (there is no prior value to compare against), so the plain
		default-case creation of an ordinary guest is excluded explicitly
		before that check is consulted.
		"""
		if self.is_new() and not self.is_blacklisted:
			return

		if not self.has_value_changed("is_blacklisted"):
			return

		require_role(BLACKLIST_ROLES)

		if self.is_blacklisted:
			if not (self.blacklist_reason or "").strip():
				throw(_("A reason is required to blacklist a guest."))

			self.blacklisted_by = frappe.session.user
			self.blacklisted_on = now_datetime()
		else:
			self.blacklisted_by = None
			self.blacklisted_on = None
			self.blacklist_reason = None

	@frappe.whitelist()
	def check_duplicates(self):
		"""Score existing guests against the details typed so far.

		Exposed as a whitelisted method rather than `onload()`: `onload()`
		only runs once, when an *existing* record is opened for display, before
		any data has been entered, so it has nothing useful to match against on
		a new record. A whitelisted document method can be called by the Desk
		client with the in-progress, unsaved form (`frm.call(...)`), which is
		when first/last name, email or mobile actually have values -- so the
		front desk sees likely duplicates while the record is being created.
		This only surfaces candidates; it never blocks the save.
		"""
		if not self.is_new():
			return []

		primary_id_number = next((row.id_number for row in self.identifications if row.is_primary), None)

		return find_duplicates(
			first_name=self.first_name,
			last_name=self.last_name,
			email_id=self.email_id,
			mobile_no=self.mobile_no,
			id_number=primary_id_number,
			date_of_birth=self.date_of_birth,
		)

	# No ERPNext Customer is created or linked here. `ensure_customer` (see
	# services/guests.py) is called by the financial builds only when a folio
	# or invoice is actually about to be raised (HPMS-DEC-012) -- creating one
	# on every guest save would pollute the receivables ledger with customers
	# that never carry a balance.
