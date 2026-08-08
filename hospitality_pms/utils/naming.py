"""Naming helpers for records identified by a short operational code.

Property, building, wing, floor, zone, department and shift are all named after
a code that staff type and read aloud. Codes are normalised before the document
is named, not during validation, because `autoname` runs first: normalising
later would leave `name` and the code field disagreeing on case for records
created with lowercase input.
"""


def normalise_code(code: str | None) -> str:
	"""Strip and uppercase an operational code."""
	return (code or "").strip().upper()


class CodeNamedDocument:
	"""Mixin for documents named `field:<code_field>`.

	Set `code_field` on the subclass. Normalisation runs at `before_naming`
	(which Frappe calls ahead of `autoname`) and again on validate, so edits to
	an existing record stay consistent too.
	"""

	code_field: str = ""

	def before_naming(self):
		self.normalise_code_field()

	def normalise_code_field(self):
		if not self.code_field:
			return

		self.set(self.code_field, normalise_code(self.get(self.code_field)))
