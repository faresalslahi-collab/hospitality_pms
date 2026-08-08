# Copyright (c) 2026, Globcom Qatar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from hospitality_pms.hospitality_setup.structure_utils import validate_property_matches_parent
from hospitality_pms.services.exceptions import ConfigurationError, RoomNotAssignableError
from hospitality_pms.services.rooms import OCCUPIED_STATES
from hospitality_pms.utils.naming import CodeNamedDocument


class HotelRoom(CodeNamedDocument, Document):
	code_field = "room_code"

	def validate(self):
		self.normalise_code_field()
		self.validate_property_consistency()
		self.validate_location_hierarchy()
		self.validate_connecting_rooms()
		self.validate_housekeeping_credits()
		self.validate_deactivation()

	def validate_property_consistency(self):
		# The four status fields are intentionally untouched here - they belong
		# to RoomStatusService and are read-only on this form.
		validate_property_matches_parent(self, "Room Type", "room_type")
		validate_property_matches_parent(self, "Hospitality Building", "building")
		validate_property_matches_parent(self, "Hospitality Wing", "wing")
		validate_property_matches_parent(self, "Hospitality Floor", "floor")
		validate_property_matches_parent(self, "Hospitality Zone", "zone")

	def validate_location_hierarchy(self):
		# Wing and Floor both need to be checked against the same Building,
		# so the check is factored into one small helper rather than repeated.
		self._validate_belongs_to_building("Hospitality Wing", self.wing, _("wing"))
		self._validate_belongs_to_building("Hospitality Floor", self.floor, _("floor"))

	def _validate_belongs_to_building(self, doctype: str, name: str | None, label: str):
		if not name or not self.building:
			return

		linked_building = frappe.db.get_value(doctype, name, "building")

		if linked_building and linked_building != self.building:
			frappe.throw(
				_("Room {0} is set to building {1}, but its {2} {3} belongs to building {4}.").format(
					self.name or self.room_code, self.building, label, name, linked_building
				),
				exc=ConfigurationError,
			)

	def validate_connecting_rooms(self):
		seen = set()

		for row in self.connecting_rooms or []:
			room = row.connecting_room
			if not room:
				continue

			if room == self.name:
				frappe.throw(
					_("Row {0}: A room cannot be listed as its own connecting room.").format(row.idx),
					exc=ConfigurationError,
				)

			if room in seen:
				frappe.throw(
					_("Row {0}: Room {1} is listed more than once in Connecting Rooms.").format(row.idx, room),
					exc=ConfigurationError,
				)
			seen.add(room)

			other_property = frappe.db.get_value("Hotel Room", room, "property")
			if other_property and self.property and other_property != self.property:
				frappe.throw(
					_("Row {0}: Room {1} belongs to property {2}, but this room belongs to property {3}.").format(
						row.idx, room, other_property, self.property
					),
					exc=ConfigurationError,
				)

		# Symmetry (if A connects to B, B should connect to A) is maintained
		# deliberately by the operator, not auto-mirrored here. The child
		# doctype's own description documents this: connections are "recorded
		# both ways" by the person setting up the property, who is in the best
		# position to judge whether a pairing is truly reciprocal (some
		# configurations, e.g. one room connecting to two neighbours where only
		# one of them connects back, are intentional). Auto-writing the
		# reciprocal row here would also mean mutating a document other than
		# the one being validated from inside validate(), which is fragile.

	def validate_housekeeping_credits(self):
		if self.housekeeping_credits is not None and self.housekeeping_credits < 0:
			frappe.throw(_("Housekeeping Credits cannot be negative."), exc=ConfigurationError)

	def validate_deactivation(self):
		if self.is_active or not self.has_value_changed("is_active"):
			return

		if self.occupancy_status in OCCUPIED_STATES:
			frappe.throw(
				_("Room {0} cannot be deactivated while it is {1}.").format(
					self.room_number or self.name, _(self.occupancy_status)
				),
				exc=RoomNotAssignableError,
			)
