# Copyright (c) 2026, Globcom Qatar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, now_datetime

from hospitality_pms.services.availability import nights_between
from hospitality_pms.services.exceptions import (
	ConfigurationError,
	HospitalityPMSError,
	InvalidStateTransitionError,
)
from hospitality_pms.services.guests import assert_not_blacklisted
from hospitality_pms.services.reservations import (
	CANCELLED,
	DRAFT,
	HOLDING_STATES,
	TENTATIVE,
	find_by_external_reference,
	price_reservation,
	sync_room_lines,
)

ROOM_TYPE_DOCTYPE = "Room Type"
GUEST_DOCTYPE = "Hospitality Guest"

#: Once a reservation has left inventory-holding behind it is done: nothing
#: further changes it except a new transition service call. Kept alongside
#: HOLDING_STATES (imported above) rather than merged into it, because the
#: two lists mean different things - one still consumes inventory, the other
#: never will again.
TERMINAL_STATES = ("Checked Out", "Closed", CANCELLED, "No Show")

#: Statuses a brand-new reservation may be saved as directly from the form.
#:
#: Confirmed is deliberately NOT here. Confirming is the moment inventory is
#: committed, and `ReservationService.confirm` is the only path that locks the
#: room types and re-checks availability first. Allowing an insert straight
#: into Confirmed would let a Desk user oversell the house by typing a status.
CREATABLE_STATUSES = (DRAFT, TENTATIVE)


class HotelReservation(Document):
	def before_insert(self):
		self.booked_on = now_datetime()

	def validate(self):
		# The two guards run first so an edit that is simply not allowed is
		# reported as such. Left until last, a forbidden change to the arrival
		# date would instead trip the room-line date check and tell the user
		# their room lines are wrong, which sends them to fix the wrong thing.
		self._guard_status_change()
		self._guard_holding_immutability()

		self._validate_dates()
		self._validate_room_lines()
		self._validate_guest()
		self._validate_blacklist()
		self._validate_duplicate_external_reference()

		# Re-pricing is only safe while the reservation is still editable (see
		# _is_editable). Sync must run after pricing so the denormalised room
		# line fields reflect whatever price_reservation just wrote.
		if self._is_editable():
			price_reservation(self, check_restrictions=self._check_restrictions_on_price())

		sync_room_lines(self)

	def on_trash(self):
		# Reservation history is retained for ten years (SAS section 8). A
		# reservation that never left Draft never became real booking history,
		# so it alone may be deleted; the state machine never transitions back
		# to Draft, so "currently Draft" and "never left Draft" are the same
		# test.
		if self.reservation_status != DRAFT:
			frappe.throw(
				_(
					"Reservation {0} has left Draft and must be retained; it cannot be deleted."
				).format(self.name),
				exc=HospitalityPMSError,
			)

	# ------------------------------------------------------------------
	# Dates
	# ------------------------------------------------------------------

	def _validate_dates(self):
		"""SAS 3.4 mandatory control: arrival < departure, at both levels."""
		if getdate(self.arrival_date) >= getdate(self.departure_date):
			frappe.throw(
				_("Arrival date {0} must be before departure date {1}.").format(
					self.arrival_date, self.departure_date
				),
				exc=HospitalityPMSError,
			)

		self.nights = len(nights_between(self.arrival_date, self.departure_date))

		for line in self.rooms:
			line.arrival_date = line.arrival_date or self.arrival_date
			line.departure_date = line.departure_date or self.departure_date

			if getdate(line.arrival_date) < getdate(self.arrival_date) or getdate(
				line.departure_date
			) > getdate(self.departure_date):
				frappe.throw(
					_(
						"Room line {0} ({1} to {2}) must fall within the reservation's stay ({3} to {4})."
					).format(
						line.idx, line.arrival_date, line.departure_date, self.arrival_date, self.departure_date
					),
					exc=HospitalityPMSError,
				)

	# ------------------------------------------------------------------
	# Room lines
	# ------------------------------------------------------------------

	def _validate_room_lines(self):
		if self.reservation_status != DRAFT and not self.rooms:
			frappe.throw(
				_("At least one room line is required once a reservation leaves Draft."),
				exc=HospitalityPMSError,
			)

		for line in self.rooms:
			if int(line.rooms or 0) < 1:
				frappe.throw(
					_("Room line {0} must book at least one room.").format(line.idx),
					exc=HospitalityPMSError,
				)

			if not line.room_type:
				continue

			room_type_property = frappe.db.get_value(ROOM_TYPE_DOCTYPE, line.room_type, "property")

			if room_type_property != self.property:
				frappe.throw(
					_("Room type {0} on line {1} does not belong to property {2}.").format(
						line.room_type, line.idx, self.property
					),
					exc=ConfigurationError,
				)

	# ------------------------------------------------------------------
	# Guest
	# ------------------------------------------------------------------

	def _validate_guest(self):
		if self.reservation_status != DRAFT and not self.guest:
			frappe.throw(
				_("A guest is required once a reservation leaves Draft."),
				exc=HospitalityPMSError,
			)

		if not self.guest or (self.guest_email and self.guest_mobile):
			return

		# Channel imports and quick walk-ins often only supply the guest link;
		# fill the contact fields from the guest record rather than leaving
		# them blank, but never overwrite a value already entered on this
		# reservation (it may be a stay-specific contact, not the guest's own).
		email, mobile = frappe.db.get_value(GUEST_DOCTYPE, self.guest, ["email_id", "mobile_no"]) or (
			None,
			None,
		)
		self.guest_email = self.guest_email or email
		self.guest_mobile = self.guest_mobile or mobile

	def _validate_blacklist(self):
		"""A blacklisted guest must not get a live booking (Draft/Cancelled are not live)."""
		if self.guest and self.reservation_status not in (DRAFT, CANCELLED):
			assert_not_blacklisted(self.guest)

	# ------------------------------------------------------------------
	# Duplicate channel booking protection
	# ------------------------------------------------------------------

	def _validate_duplicate_external_reference(self):
		"""SAS 3.4 duplicate external booking protection for channel imports."""
		if not self.external_reference or self.reservation_status == CANCELLED:
			return

		existing = find_by_external_reference(self.property, self.external_reference)

		if existing and existing != self.name:
			frappe.throw(
				_("External reference {0} is already used by reservation {1}.").format(
					self.external_reference, existing
				),
				exc=HospitalityPMSError,
			)

	# ------------------------------------------------------------------
	# Pricing
	# ------------------------------------------------------------------

	def _is_editable(self) -> bool:
		"""Whether the rate snapshot may still be recomputed.

		Re-pricing is safe exactly while the reservation has not yet committed
		to inventory or an outcome: once it reaches a HOLDING_STATES status
		(Confirmed, Guaranteed, Checked In) the guest has been quoted these
		amounts and re-running today's rate grid would silently change what
		they owe; once it reaches a terminal status (Checked Out, Closed,
		Cancelled, No Show) the stay is over or never happened and there is
		nothing left to price. Draft, Tentative and Waitlisted are the only
		statuses where the snapshot is still a working draft.
		"""
		return self.reservation_status not in HOLDING_STATES and self.reservation_status not in TERMINAL_STATES

	def _check_restrictions_on_price(self) -> bool:
		"""Whether restriction checks (stop-sell, min-LOS, CTA...) run while pricing.

		Draft and Tentative reservations - including a brand-new one, whose
		status defaults to Draft - are still being put together, so a
		restriction violation should be surfaced immediately. Waitlisted is
		different: a reservation lands there precisely because a restriction
		or availability check failed elsewhere, so re-validating restrictions
		on every subsequent save of a Waitlisted row would make it impossible
		to save the very state that records that failure. Its snapshot is
		still refreshed for informational totals, just without re-throwing on
		the restriction that put it there.
		"""
		return self.is_new() or self.reservation_status in (DRAFT, TENTATIVE)

	# ------------------------------------------------------------------
	# Status is service-owned
	# ------------------------------------------------------------------

	def _guard_status_change(self):
		"""Refuse a direct edit of `reservation_status`.

		Every real transition goes through `ReservationService._transition`,
		which writes the field with `frappe.db.set_value()` - that call does
		not run `validate()`, so this guard never fights the service; it only
		catches a form save or API call that tried to set the field itself.
		"""
		if self.is_new():
			# has_value_changed() has no prior value to compare against on
			# insert and unconditionally reports True, so a new document is
			# checked against the fixed list of legal starting statuses
			# instead.
			if self.reservation_status not in CREATABLE_STATUSES:
				frappe.throw(
					_("A new reservation can only be created with status {0}.").format(
						", ".join(CREATABLE_STATUSES)
					),
					exc=InvalidStateTransitionError,
				)
			return

		if self.has_value_changed("reservation_status"):
			frappe.throw(
				_(
					"Reservation status is changed only through a reservation transition, "
					"not by editing the document directly."
				),
				exc=InvalidStateTransitionError,
			)

	# ------------------------------------------------------------------
	# Immutability once holding
	# ------------------------------------------------------------------

	def _guard_holding_immutability(self):
		"""Refuse edits to the fields a new availability check would depend on.

		Changing dates, property or guest once a reservation is holding
		inventory (or has moved beyond that into a terminal state) can only be
		done safely by re-running availability under lock, which is a service
		operation ("move/rebook") that does not exist yet. Until it does, the
		only correct path is cancel and rebook.
		"""
		if self.is_new() or self._is_editable():
			return

		for fieldname in ("arrival_date", "departure_date", "property", "guest"):
			if self.has_value_changed(fieldname):
				frappe.throw(
					_(
						"{0} cannot be changed once a reservation is {1}; cancel and rebook instead."
					).format(_(self.meta.get_label(fieldname)), _(self.reservation_status)),
					exc=InvalidStateTransitionError,
				)
