# Copyright (c) 2026, Globcom Qatar and contributors
# For license information, please see license.txt

from frappe import _
from frappe.model.document import Document


class PostingProfile(Document):
	def validate(self):
		self._assert_tax_templates_resolve()

	def _assert_tax_templates_resolve(self):
		"""Refuse a tax mapping whose template could never post the tax.

		A folio line that carries tax is posted through `_resolve_tax_head`
		(services/posting.py), which needs the mapped tax template to resolve to
		exactly one Sales Taxes and Charges head: the folio holds a single tax
		figure per line and no breakdown, so a template with more than one head
		could not be reproduced from it without inventing an allocation.

		Left unchecked at save, an unresolvable template is only refused at
		invoice-build time - during checkout or Night Audit - where the person
		who hits it is not the person who set it, and a whole day's posting can
		stall on it. This runs the *same* resolution posting does, sharing
		`resolve_single_tax_head`, so setup accepts every mapping posting would
		accept and refuses only what posting would refuse.

		Only templates that are actually configured are checked: a charge type
		mapped without a tax template is left alone, exactly as a folio line that
		carries no tax posts without one. Whether a charge type carries tax is a
		property of the folio line (its `tax_amount`), not of this profile, so
		requiring a template here on a mapping that has none would reject a
		legitimate, postable configuration.
		"""
		from hospitality_pms.services.posting import resolve_single_tax_head

		for row in self.charge_items:
			if row.is_active and row.tax_template:
				resolve_single_tax_head(row.tax_template, row.charge_type)

		if self.default_tax_template:
			resolve_single_tax_head(self.default_tax_template, _("(profile default)"))
