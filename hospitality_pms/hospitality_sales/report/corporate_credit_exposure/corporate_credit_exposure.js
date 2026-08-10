// Filters for the Corporate Credit Exposure report.
//
// Property is mandatory: it is the scoping boundary for which corporate
// accounts and folios are considered.
frappe.query_reports["Corporate Credit Exposure"] = {
	filters: [
		hospitality_pms.reports.property_filter(),
		{
			fieldname: "credit_status",
			label: __("Credit Status"),
			fieldtype: "Select",
			options: "\nActive\nException Required\nSuspended",
		},
	],
};
