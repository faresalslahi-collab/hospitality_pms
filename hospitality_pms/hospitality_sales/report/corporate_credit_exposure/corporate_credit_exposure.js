// Filters for the Corporate Credit Exposure report.
//
// Property is mandatory: it is the scoping boundary for which corporate
// accounts and folios are considered.
frappe.query_reports["Corporate Credit Exposure"] = {
	filters: [
		{
			fieldname: "property",
			label: __("Property"),
			fieldtype: "Link",
			options: "Property",
			reqd: 1,
		},
		{
			fieldname: "credit_status",
			label: __("Credit Status"),
			fieldtype: "Select",
			options: "\nActive\nException Required\nSuspended",
		},
	],
};
