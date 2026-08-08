// Filters for the Payment Reconciliation report.
//
// Property is mandatory: it is the scoping boundary for the folio payment
// query. From/To date narrow the payment date range; leaving both blank
// returns every payment recorded at the property.
frappe.query_reports["Payment Reconciliation"] = {
	filters: [
		{
			fieldname: "property",
			label: __("Property"),
			fieldtype: "Link",
			options: "Hospitality Property",
			reqd: 1,
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
		},
	],
};
