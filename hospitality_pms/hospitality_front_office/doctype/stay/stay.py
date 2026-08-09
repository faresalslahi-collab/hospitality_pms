# Copyright (c) 2026, Globcom Qatar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, now_datetime

from hospitality_pms.services.availability import nights_between
from hospitality_pms.services.exceptions import HospitalityPMSError, InvalidStateTransitionError
from hospitality_pms.services.stays import EXPECTED, IN_HOUSE

#: Statuses a brand-new stay may be saved as directly. StayService.check_in
#: inserts the stay as Expected and then promotes it to In House with
#: `frappe.db.set_value()` within the same call - that write does not run
#: `validate()`, so both values have to be accepted here, not only the value
#: used at insert.
CREATABLE_STATUSES = (EXPECTED, IN_HOUSE)


class Stay(Document):
	def validate(self):
		# The two guards run first so an edit that is simply not allowed is
		# reported as such, rather than as some other field's derived rule
		# failing downstream.
		self._guard_status_change()
		self._guard_locked_fields()

		self._validate_dates()
		self._validate_room()
		self._validate_guest()
		self._validate_companions()
		self._stamp_notes()

	def on_trash(self):
		# Stay history is retained for ten years (SAS section 8). A stay that
		# never left Expected never became a real physical stay, so it alone
		# may be deleted; the state machine never transitions back to
		# Expected, so "currently Expected" and "never left Expected" are the
		# same test.
		if self.stay_status != EXPECTED:
			frappe.throw(
				_("Stay {0} has left Expected and must be retained; it cannot be deleted.").format(self.name),
				exc=HospitalityPMSError,
			)

	# ------------------------------------------------------------------
	# Dates
	# ------------------------------------------------------------------

	def _validate_dates(self):
		if getdate(self.arrival_date) >= getdate(self.departure_date):
			frappe.throw(
				_("Arrival date {0} must be before departure date {1}.").format(
					self.arrival_date, self.departure_date
				),
				exc=HospitalityPMSError,
			)

		self.nights = len(nights_between(self.arrival_date, self.departure_date))

	# ------------------------------------------------------------------
	# Room
	# ------------------------------------------------------------------

	def _validate_room(self):
		if not self.room:
			return

		room_property, room_type = frappe.db.get_value("Hotel Room", self.room, ["property", "room_type"])

		if room_property != self.property:
			frappe.throw(
				_("Room {0} belongs to another property.").format(self.room),
				exc=HospitalityPMSError,
			)

		if self.room_type and room_type != self.room_type:
			frappe.throw(
				_("Room {0} is a {1}, not the stay's room type {2}.").format(
					self.room, room_type, self.room_type
				),
				exc=HospitalityPMSError,
			)

	# ------------------------------------------------------------------
	# Guest
	# ------------------------------------------------------------------

	def _validate_guest(self):
		if not self.guest:
			frappe.throw(_("A guest is required for a stay."), exc=HospitalityPMSError)

	# ------------------------------------------------------------------
	# Companions
	# ------------------------------------------------------------------

	def _validate_companions(self):
		if len(self.companions) == 1:
			# A single companion is unambiguously the primary guest - there is
			# nothing to choose between, so mark it rather than making the
			# front desk tick a box that has only one possible answer.
			self.companions[0].is_primary = 1
			return

		if len([row for row in self.companions if row.is_primary]) > 1:
			frappe.throw(
				_("Only one companion can be marked as the primary guest."),
				exc=HospitalityPMSError,
			)

	# ------------------------------------------------------------------
	# Notes
	# ------------------------------------------------------------------

	def _stamp_notes(self):
		for row in self.stay_notes:
			# `row.is_new()` is the child-row equivalent of `is_new()`: it is
			# true for a row appended in this save and false for one already
			# persisted, which is what tells a freshly logged note apart from
			# one being re-saved along with an unrelated change elsewhere on
			# the stay.
			if not row.is_new():
				continue

			row.noted_by = row.noted_by or frappe.session.user
			row.noted_on = row.noted_on or now_datetime()

	# ------------------------------------------------------------------
	# Status is service-owned
	# ------------------------------------------------------------------

	def _guard_status_change(self):
		"""Refuse a direct edit of `stay_status`.

		Every real transition goes through StayService, which writes the field
		with `frappe.db.set_value()` - that call does not run `validate()`, so
		this guard never fights the service; it only catches a form save or
		API call that tried to set the field itself.
		"""
		if self.is_new():
			# has_value_changed() has no prior value to compare against on
			# insert and unconditionally reports True, so a new document is
			# checked against the fixed list of legal starting statuses
			# instead.
			if self.stay_status not in CREATABLE_STATUSES:
				frappe.throw(
					_("A new stay can only be created with status {0}.").format(
						" or ".join(CREATABLE_STATUSES)
					),
					exc=InvalidStateTransitionError,
				)
			return

		if self.has_value_changed("stay_status"):
			frappe.throw(
				_("Stay status is changed only through a stay transition, not by editing the document directly."),
				exc=InvalidStateTransitionError,
			)

	# ------------------------------------------------------------------
	# Immutability once the guest has actually arrived
	# ------------------------------------------------------------------

	def _guard_locked_fields(self):
		"""Refuse edits to who and where a stay belongs to once it is real.

		`property`, `guest` and `reservation` identify the stay; once it has
		left Expected the guest is, or has been, physically in the property
		and these can no longer be silently repointed. `room` is deliberately
		excluded: StayService.change_room is the supported way to move a
		guest mid-stay and legitimately rewrites `room`/`room_type` on this
		same document while it is In House or Due Out.
		"""
		if self.is_new() or self.stay_status == EXPECTED:
			return

		for fieldname in ("property", "guest", "reservation"):
			if self.has_value_changed(fieldname):
				frappe.throw(
					_("{0} cannot be changed once a stay is {1}.").format(
						_(self.meta.get_label(fieldname)), _(self.stay_status)
					),
					exc=InvalidStateTransitionError,
				)
