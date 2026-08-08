# Copyright (c) 2026, Globcom Qatar and contributors
# For license information, please see license.txt

"""Small helpers shared by more than one Rates controller (HPMS-0.8.0).

Kept outside `doctype/` because it belongs to no single DocType - it is
imported by both `hospitality_rate_plan.py` and `hospitality_daily_rate.py`
and `hospitality_room_inventory_restriction.py`. Resolution logic itself stays
in `services/rates.py`; these controllers only stop contradictory
configuration from being saved in the first place.
"""

import frappe
from frappe import _

from hospitality_pms.services.exceptions import ConfigurationError

ROOM_TYPE_DOCTYPE = "Room Type"


def get_room_type_property(room_type: str) -> str | None:
	"""The property a Room Type belongs to, or None if it does not exist."""
	return frappe.db.get_value(ROOM_TYPE_DOCTYPE, room_type, "property")


def validate_room_type_property(parent_doc, room_type: str | None, *, row=None) -> None:
	"""Raise unless `room_type` belongs to `parent_doc.property`.

	`parent_doc` is the top-level document, not necessarily the document that
	holds `room_type`: a child table row has no `property` of its own, so the
	comparison always runs against the parent. Pass `row` when `room_type`
	comes from a child table row, so the message can point at it.
	"""
	if not room_type:
		return

	room_type_property = get_room_type_property(room_type)

	if not room_type_property or room_type_property == parent_doc.property:
		return

	if row is not None:
		frappe.throw(
			_("Row #{0}: Room Type {1} belongs to property {2}, but {3} {4} belongs to property {5}.").format(
				row.idx, room_type, room_type_property, _(parent_doc.doctype), parent_doc.name, parent_doc.property
			),
			exc=ConfigurationError,
		)

	frappe.throw(
		_("Room Type {0} belongs to property {1}, but {2} {3} belongs to property {4}.").format(
			room_type, room_type_property, _(parent_doc.doctype), parent_doc.name, parent_doc.property
		),
		exc=ConfigurationError,
	)
