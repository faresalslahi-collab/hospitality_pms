"""The ERP world the Wave-2 posting suites share.

Posting cannot be tested against a stub. The defects are about what ERPNext
ends up holding — an invoice's `grand_total`, a Payment Entry's allocation, a
GL Entry against a tax account — so the tests raise real Sales Invoices and
real Payment Entries against a real chart of accounts, and read the answers
back out of ERPNext.

That needs a company, tax accounts, tax templates, items and a Posting Profile
mapping charge types onto them. Building that in three suites separately would
be three chances to build it differently, so it is built once here.

The company is the site's own, taken from the seed property, because its
currency has to match the property's or every invoice would need an exchange
rate that has nothing to do with what is under test.
"""

import frappe
from frappe.utils import flt

from hospitality_pms.services import folio as folio_service
from hospitality_pms.tests.fixtures import Fixtures

#: Tax rates the charge types are configured at. Deliberately different, so a
#: single invoice-level rate cannot accidentally satisfy a mixed-tax test.
ROOM_TAX_RATE = 10.0
MINIBAR_TAX_RATE = 5.0


class PostingWorld:
	"""A property configured to post to ERPNext, and the means to remove it."""

	def __init__(self, tag: str, code: str):
		self.fixtures = Fixtures(tag)
		self.tag = tag

		self.property = self.fixtures.property(code, require_id_at_check_in=0)
		self.company = frappe.db.get_value("Property", self.property, "company")
		self.currency = frappe.db.get_value("Property", self.property, "currency")

		self.room_tax_account = self.fixtures.tax_account(
			self.company, "VAT10", rate=ROOM_TAX_RATE
		)
		self.minibar_tax_account = self.fixtures.tax_account(
			self.company, "VAT5", rate=MINIBAR_TAX_RATE
		)

		self.room_tax_template = self.fixtures.tax_template(
			self.company, "Room VAT", self.room_tax_account, ROOM_TAX_RATE
		)
		self.minibar_tax_template = self.fixtures.tax_template(
			self.company, "Minibar VAT", self.minibar_tax_account, MINIBAR_TAX_RATE
		)

		self.room_item = self.fixtures.erp_item("ROOM")
		self.minibar_item = self.fixtures.erp_item("MINIBAR")
		self.laundry_item = self.fixtures.erp_item("LAUNDRY")

		self.profile = self.fixtures.posting_profile(
			self.property,
			self.company,
			default_item=self.room_item,
			charge_map=[
				{
					"charge_type": "Room Charge",
					"item": self.room_item,
					"tax_template": self.room_tax_template,
				},
				{
					"charge_type": "Minibar",
					"item": self.minibar_item,
					"tax_template": self.minibar_tax_template,
				},
				# Laundry is deliberately left without a tax template: a folio
				# line that bears no tax must post without inventing one.
				{"charge_type": "Laundry", "item": self.laundry_item},
			],
		)

		self.guest = self.fixtures.guest("Posting")

		frappe.db.commit()

	# -- convenience -----------------------------------------------------

	def folio(self) -> str:
		name = self.fixtures.folio(self.property, self.guest)
		frappe.db.commit()

		return name

	def charge(self, folio: str, charge_type: str, amount: float, tax: float, key: str) -> dict:
		"""Post a folio charge carrying an explicit tax amount."""
		return folio_service.post_charge(
			folio,
			charge_type,
			f"{charge_type} {key}",
			amount,
			tax_amount=tax,
			idempotency_key=f"{self.tag}:{key}",
		)

	def payment(self, folio: str, amount: float, key: str, method: str = "Cash") -> dict:
		return folio_service.post_payment(
			folio, amount, method, idempotency_key=f"{self.tag}:{key}"
		)

	def teardown(self):
		self.fixtures.teardown()


# ---------------------------------------------------------------------------
# Reading ERPNext back
# ---------------------------------------------------------------------------


def folio_invoices(folio: str) -> list[str]:
	"""Sales Invoices this folio posted, oldest first.

	Read from the posting log rather than from the folio's charge rows,
	because the charge rows are what the old reconciliation trusted and this
	suite exists to stop trusting them.
	"""
	return frappe.get_all(
		"Financial Posting Log",
		filters={"folio": folio, "posting_type": "Sales Invoice", "erp_document": ("is", "set")},
		fields=["erp_document"],
		order_by="creation asc",
		pluck="erp_document",
	)


def invoice_totals(invoice: str) -> dict:
	"""What ERPNext actually holds for an invoice."""
	return frappe.db.get_value(
		"Sales Invoice",
		invoice,
		["docstatus", "net_total", "total_taxes_and_charges", "grand_total", "outstanding_amount", "currency"],
		as_dict=True,
	)


def invoice_tax_rows(invoice: str) -> list[dict]:
	return frappe.get_all(
		"Sales Taxes and Charges",
		filters={"parent": invoice, "parenttype": "Sales Invoice"},
		fields=["charge_type", "account_head", "tax_amount", "rate"],
		order_by="idx asc",
	)


def gl_amount(voucher_type: str, voucher: str, account: str) -> float:
	"""Net credit posted to an account by one voucher.

	Credit minus debit, so a revenue or tax account reads positive. This is the
	check that the tax reached the ledger rather than merely appearing on a
	document.
	"""
	rows = frappe.get_all(
		"GL Entry",
		filters={
			"voucher_type": voucher_type,
			"voucher_no": voucher,
			"account": account,
			"is_cancelled": 0,
		},
		fields=["debit", "credit"],
	)

	return flt(sum(flt(r["credit"]) - flt(r["debit"]) for r in rows), 2)


def payment_references(payment_entry: str) -> list[dict]:
	return frappe.get_all(
		"Payment Entry Reference",
		filters={"parent": payment_entry, "parenttype": "Payment Entry"},
		fields=["reference_doctype", "reference_name", "allocated_amount", "outstanding_amount"],
		order_by="idx asc",
	)


def payment_totals(payment_entry: str) -> dict:
	return frappe.db.get_value(
		"Payment Entry",
		payment_entry,
		["docstatus", "paid_amount", "total_allocated_amount", "unallocated_amount"],
		as_dict=True,
	)
