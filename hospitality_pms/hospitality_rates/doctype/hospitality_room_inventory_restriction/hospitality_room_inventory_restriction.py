# Copyright (c) 2026, Globcom Qatar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from hospitality_pms.hospitality_rates.rate_utils import validate_room_type_property
from hospitality_pms.services.exceptions import ConfigurationError


class HospitalityRoomInventoryRestriction(Document):
	def validate(self):
		self.validate_room_type_scope()
		self.validate_non_negative_fields()
		self.validate_uniqueness()

	def validate_room_type_scope(self):
		validate_room_type_property(self, self.room_type)

	def validate_non_negative_fields(self):
		if self.min_length_of_stay is not None and self.min_length_of_stay < 0:
			frappe.throw(_("Min Length of Stay cannot be negative."), exc=ConfigurationError)

		if self.rooms_to_sell is not None and self.rooms_to_sell < 0:
			frappe.throw(_("Rooms to Sell cannot be negative."), exc=ConfigurationError)

	def validate_uniqueness(self):
		"""Frappe's DocType JSON cannot express a multi-column unique key, so
		(property, room_type, restriction_date) is enforced here. A blank
		Room Type is a property-wide row and is its own distinct key: it must
		not collide with, nor be shadowed by, a room-type-specific row on the
		same date.
		"""
		duplicate = frappe.db.exists(
			self.doctype,
			{
				"property": self.property,
				"room_type": self.room_type or "",
				"restriction_date": self.restriction_date,
				"name": ("!=", self.name),
			},
		)

		if duplicate:
			scope = _("Room Type {0}").format(self.room_type) if self.room_type else _("the whole property")
			frappe.throw(
				_("An Inventory Restriction for {0} on {1} already exists ({2}).").format(
					scope, self.restriction_date, duplicate
				),
				exc=ConfigurationError,
			)
