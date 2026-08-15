# Copyright (c) 2026, Globcom Qatar and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class NightAuditReconciledPosting(Document):
	"""Evidence, not state.

	One row per Financial Posting Log entry that a Night Audit reconciliation
	examined and accepted. `NightAuditService` is the only writer; nothing here
	validates, because the service writes the rows and reads them back within
	the same audit and no operator path creates one.
	"""

	pass
