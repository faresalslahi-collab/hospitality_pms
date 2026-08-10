// Filters for the Payment Reconciliation report.
//
// Property is mandatory: it is the scoping boundary for the folio payment
// query. From/To date narrow the payment date range; leaving both blank
// returns every payment recorded at the property.
frappe.query_reports["Payment Reconciliation"] = {
	filters: [
		hospitality_pms.reports.property_filter(),
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(hospitality_pms.reports.business_date(), -1),
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: hospitality_pms.reports.business_date(),
		},
	],
};
