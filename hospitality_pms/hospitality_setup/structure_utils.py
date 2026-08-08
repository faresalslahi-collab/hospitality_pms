"""Shared validation for the physical hierarchy: building, wing, floor, zone.

These rules protect property isolation. A wing or floor that drifts to another
property would quietly widen what a property-restricted user can see once rooms
hang off this hierarchy.
"""

import frappe
from frappe import _

from hospitality_pms.services.exceptions import ConfigurationError


def validate_property_matches_parent(doc, parent_doctype: str, parent_fieldname: str) -> None:
	"""Ensure `doc.property` equals the property of the linked parent record."""
	parent_name = doc.get(parent_fieldname)
	if not parent_name:
		return

	parent_property = frappe.db.get_value(parent_doctype, parent_name, "property")

	if parent_property and doc.property != parent_property:
		frappe.throw(
			_("{0} {1} belongs to property {2}, but its {3} {4} belongs to property {5}.").format(
				_(doc.doctype), doc.name, doc.property, _(parent_doctype), parent_name, parent_property
			),
			exc=ConfigurationError,
		)


def guard_deactivation(doc, references: list[tuple[str, str]]) -> None:
	"""Refuse an is_active 1 -> 0 transition while active children still refer to it.

	`references` is a list of (child_doctype, link_fieldname) pairs.
	"""
	if doc.is_active or not doc.has_value_changed("is_active"):
		return

	for child_doctype, fieldname in references:
		blocking = frappe.get_all(
			child_doctype,
			filters={fieldname: doc.name, "is_active": 1},
			pluck="name",
			limit=1,
		)

		if blocking:
			frappe.throw(
				_("{0} {1} cannot be deactivated because active {2} {3} still references it.").format(
					_(doc.doctype), doc.name, _(child_doctype), blocking[0]
				),
				exc=ConfigurationError,
			)
