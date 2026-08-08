"""Folio vs Invoice.

Financial question answered: for every folio opened at a property in a period,
does the operational subledger (the folio) agree with what actually reached
ERPNext as a Sales Invoice and Payment Entry?

This report never recomputes the comparison itself. It calls
`hospitality_pms.services.posting.reconcile_folio` per folio, which is the one
place that definition of "reconciled" lives (HPMS-DEC-002/031). Reimplementing
the comparison here would let this report and the reconciliation screen drift
apart and disagree about the same folio.

What a non-zero variance means:

- **Charge variance** (folio charges minus ERPNext invoiced) > 0 means the
  folio has charged the guest for more than has reached the sales ledger --
  typically unposted or failed-to-post charges, revenue not yet in ERPNext.
  A negative value means ERPNext shows more invoiced than the folio currently
  totals, which should not happen under normal operation and warrants review.
- **Payment variance** (folio payments minus ERPNext paid) works the same way
  for money collected versus money receipted in ERPNext via Payment Entry.
- **Unposted charge count** > 0 means charges exist on the folio that have
  never been sent to ERPNext at all (as opposed to sent and failed).
- **Reconciled** is "Yes" only when both variances are effectively zero
  (matching the 0.005 tolerance `reconcile_folio` itself uses) and there are
  no Failed postings outstanding against the folio.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate

from hospitality_pms.services.posting import reconcile_folio

FOLIO_DOCTYPE = "Hospitality Guest Folio"


def execute(filters=None):
	filters = frappe._dict(filters or {})

	if not filters.get("property"):
		frappe.throw(_("Property is mandatory."))

	columns = get_columns()
	folios = get_folios(filters)

	if not folios:
		return columns, []

	data = []
	for folio in folios:
		result = reconcile_folio(folio.name)

		data.append(
			{
				"folio": folio.name,
				"guest": folio.guest,
				"guest_name": folio.guest_name,
				"stay": folio.stay,
				"folio_status": folio.folio_status,
				"folio_charges": flt(result["folio_charges"], 2),
				"erp_invoiced": flt(result["erp_invoiced"], 2),
				"charge_variance": flt(result["charge_variance"], 2),
				"folio_payments": flt(result["folio_payments"], 2),
				"erp_paid": flt(result["erp_paid"], 2),
				"payment_variance": flt(result["payment_variance"], 2),
				"unposted_charge_count": len(result["unposted_charges"]),
				"reconciled": _("Yes") if result["is_reconciled"] else _("No"),
			}
		)

	return columns, data


def get_folios(filters):
	"""Folios in scope, using the ORM. Property is the mandatory scoping filter."""
	conditions = {"property": filters.property}

	if filters.get("folio_status"):
		conditions["folio_status"] = filters.folio_status

	from_date = getdate(filters.from_date) if filters.get("from_date") else None
	to_date = getdate(filters.to_date) if filters.get("to_date") else None

	if from_date and to_date:
		conditions["opened_on"] = ["between", [from_date, to_date]]
	elif from_date:
		conditions["opened_on"] = [">=", from_date]
	elif to_date:
		conditions["opened_on"] = ["<=", to_date]

	return frappe.get_all(
		FOLIO_DOCTYPE,
		filters=conditions,
		fields=["name", "guest", "guest_name", "stay", "folio_status"],
		order_by="opened_on asc",
	)


def get_columns():
	return [
		{
			"fieldname": "folio",
			"label": _("Folio"),
			"fieldtype": "Link",
			"options": "Hospitality Guest Folio",
			"width": 140,
		},
		{
			"fieldname": "guest",
			"label": _("Guest"),
			"fieldtype": "Link",
			"options": "Hospitality Guest",
			"width": 140,
		},
		{
			"fieldname": "stay",
			"label": _("Stay"),
			"fieldtype": "Link",
			"options": "Hospitality Stay",
			"width": 120,
		},
		{
			"fieldname": "folio_status",
			"label": _("Status"),
			"fieldtype": "Data",
			"width": 130,
		},
		{
			"fieldname": "folio_charges",
			"label": _("Folio Charges"),
			"fieldtype": "Currency",
			"width": 120,
		},
		{
			"fieldname": "erp_invoiced",
			"label": _("ERPNext Invoiced"),
			"fieldtype": "Currency",
			"width": 130,
		},
		{
			"fieldname": "charge_variance",
			"label": _("Charge Variance"),
			"fieldtype": "Currency",
			"width": 130,
		},
		{
			"fieldname": "folio_payments",
			"label": _("Folio Payments"),
			"fieldtype": "Currency",
			"width": 120,
		},
		{
			"fieldname": "erp_paid",
			"label": _("ERPNext Paid"),
			"fieldtype": "Currency",
			"width": 120,
		},
		{
			"fieldname": "payment_variance",
			"label": _("Payment Variance"),
			"fieldtype": "Currency",
			"width": 130,
		},
		{
			"fieldname": "unposted_charge_count",
			"label": _("Unposted Charge Count"),
			"fieldtype": "Int",
			"width": 130,
		},
		{
			"fieldname": "reconciled",
			"label": _("Reconciled"),
			"fieldtype": "Data",
			"width": 90,
		},
	]
