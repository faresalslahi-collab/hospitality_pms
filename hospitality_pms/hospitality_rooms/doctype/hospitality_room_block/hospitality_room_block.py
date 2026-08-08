# Copyright (c) 2026, Globcom Qatar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime, today

from hospitality_pms.hospitality_setup.structure_utils import validate_property_matches_parent
from hospitality_pms.services.exceptions import AvailabilityError, ConfigurationError
from hospitality_pms.services.rooms import INVENTORY, set_status


class HospitalityRoomBlock(Document):
	def validate(self):
		self.validate_target()
		self.validate_dates()
		self.validate_rooms_blocked()
		self.validate_property_consistency()

	def before_submit(self):
		# Overlap only matters for a specific room: a type-level block is a
		# quantity held back from the pool, and several of those may legitimately
		# stack on the same date range.
		if self.room and self.status == "Active":
			self.validate_no_overlap()

	def on_submit(self):
		if self.room:
			set_status(
				self.room,
				INVENTORY,
				"Blocked",
				reason=self.reason,
				reference_doctype=self.doctype,
				reference_name=self.name,
			)

	def on_cancel(self):
		self.db_set("status", "Cancelled")

		if self.room and not self._room_covered_by_other_block():
			set_status(
				self.room,
				INVENTORY,
				"Available",
				reason=self.reason,
				reference_doctype=self.doctype,
				reference_name=self.name,
			)

	def release(self):
		"""Manually release an Active block ahead of its To Date.

		Not whitelisted here - an API layer will check permissions and call
		this once it is added.
		"""
		if self.docstatus != 1:
			frappe.throw(_("Only a submitted block can be released."), exc=ConfigurationError)

		if self.status != "Active":
			frappe.throw(_("Only an Active block can be released."), exc=ConfigurationError)

		self.db_set("status", "Released")
		self.db_set("released_on", now_datetime())
		self.db_set("released_by", frappe.session.user)

		if self.room and not self._room_covered_by_other_block():
			set_status(
				self.room,
				INVENTORY,
				"Available",
				reason=self.reason,
				reference_doctype=self.doctype,
				reference_name=self.name,
			)

	def validate_target(self):
		if self.room and self.room_type:
			frappe.throw(
				_("Set either Room or Room Type, not both - a block cannot target both at once."),
				exc=ConfigurationError,
			)

		if not self.room and not self.room_type:
			frappe.throw(
				_("Set either Room or Room Type to define what this block covers."),
				exc=ConfigurationError,
			)

	def validate_dates(self):
		if self.from_date and self.to_date and self.from_date > self.to_date:
			frappe.throw(
				_("From Date {0} cannot be after To Date {1}.").format(self.from_date, self.to_date),
				exc=ConfigurationError,
			)

	def validate_rooms_blocked(self):
		if self.room:
			# A specific room is always exactly one room; the quantity field
			# does not apply, so it is normalised rather than flagged as an error.
			self.rooms_blocked = 1
			return

		if not self.rooms_blocked or self.rooms_blocked < 1:
			frappe.throw(
				_("Rooms Blocked must be at least 1 when blocking by Room Type."),
				exc=ConfigurationError,
			)

	def validate_property_consistency(self):
		validate_property_matches_parent(self, "Hotel Room", "room")
		validate_property_matches_parent(self, "Room Type", "room_type")

	def validate_no_overlap(self):
		overlapping = frappe.get_all(
			"Hospitality Room Block",
			filters={
				"room": self.room,
				"status": "Active",
				"docstatus": 1,
				"name": ("!=", self.name),
				"from_date": ("<=", self.to_date),
				"to_date": (">=", self.from_date),
			},
			pluck="name",
			limit=1,
		)

		if overlapping:
			frappe.throw(
				_("Room {0} already has active block {1} covering {2} to {3}.").format(
					self.room, overlapping[0], self.from_date, self.to_date
				),
				exc=AvailabilityError,
			)

	def _room_covered_by_other_block(self) -> bool:
		"""True if another submitted, Active block still covers this room today.

		Releasing the Inventory dimension to Available is only safe when
		nothing else keeps the room out of sale right now; the room's own
		block might end but a second, unrelated block could still be running.
		"""
		return bool(
			frappe.get_all(
				"Hospitality Room Block",
				filters={
					"room": self.room,
					"status": "Active",
					"docstatus": 1,
					"name": ("!=", self.name),
					"from_date": ("<=", today()),
					"to_date": (">=", today()),
				},
				limit=1,
			)
		)
