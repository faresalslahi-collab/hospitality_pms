# Copyright (c) 2026, Globcom Qatar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from hospitality_pms.hospitality_rates.rate_utils import validate_room_type_property
from hospitality_pms.hospitality_setup.structure_utils import validate_property_matches_parent
from hospitality_pms.services.exceptions import ConfigurationError

RATE_PLAN_ROOM_TYPE_DOCTYPE = "Hospitality Rate Plan Room Type"
RATE_PLAN_DOCTYPE = "Hospitality Rate Plan"


class HospitalityDailyRate(Document):
	def validate(self):
		self.validate_property_consistency()
		self.validate_room_type_sold_by_plan()
		self.validate_rate()
		self.validate_length_of_stay()
		self.validate_rooms_to_sell()
		self.validate_uniqueness()

	def validate_property_consistency(self):
		validate_property_matches_parent(self, RATE_PLAN_DOCTYPE, "rate_plan")
		validate_room_type_property(self, self.room_type)

	def validate_room_type_sold_by_plan(self):
		"""A daily rate for a room type the plan does not cover would never be
		read by `RateService._daily_rate` (it is only looked up once a rate
		plan already claims that room type in `Hospitality Rate Plan Room Type`).
		"""
		if not (self.rate_plan and self.room_type):
			return

		sold = frappe.db.exists(
			RATE_PLAN_ROOM_TYPE_DOCTYPE,
			{"parent": self.rate_plan, "parenttype": RATE_PLAN_DOCTYPE, "room_type": self.room_type},
		)

		if not sold:
			frappe.throw(
				_(
					"Rate Plan {0} does not sell Room Type {1}; a Daily Rate for it would never be read."
				).format(self.rate_plan, self.room_type),
				exc=ConfigurationError,
			)

	def validate_rate(self):
		if self.rate is not None and self.rate < 0:
			frappe.throw(_("Rate cannot be negative."), exc=ConfigurationError)

	def validate_length_of_stay(self):
		if (
			self.min_length_of_stay
			and self.max_length_of_stay
			and self.min_length_of_stay > self.max_length_of_stay
		):
			frappe.throw(
				_("Min Length of Stay ({0}) cannot exceed Max Length of Stay ({1}).").format(
					self.min_length_of_stay, self.max_length_of_stay
				),
				exc=ConfigurationError,
			)

	def validate_rooms_to_sell(self):
		if self.rooms_to_sell is not None and self.rooms_to_sell < 0:
			frappe.throw(_("Rooms to Sell cannot be negative."), exc=ConfigurationError)

	def validate_uniqueness(self):
		"""Frappe's DocType JSON cannot express a multi-column unique key, so
		(property, rate_plan, room_type, rate_date) is enforced here.
		"""
		duplicate = frappe.db.exists(
			self.doctype,
			{
				"property": self.property,
				"rate_plan": self.rate_plan,
				"room_type": self.room_type,
				"rate_date": self.rate_date,
				"name": ("!=", self.name),
			},
		)

		if duplicate:
			frappe.throw(
				_(
					"A Daily Rate for Room Type {0} on Rate Plan {1} and date {2} already exists ({3})."
				).format(self.room_type, self.rate_plan, self.rate_date, duplicate),
				exc=ConfigurationError,
			)
