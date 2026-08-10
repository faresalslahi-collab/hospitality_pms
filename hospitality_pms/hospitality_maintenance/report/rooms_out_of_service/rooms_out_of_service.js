// Filters for the Rooms Out of Service report.
//
// Property is mandatory and defaults to the property this user works in; the
// shared definition lives in hospitality_pms/public/js/reports.js so every
// report scopes the same way.
frappe.query_reports["Rooms Out of Service"] = {
	filters: [
		hospitality_pms.reports.property_filter(),
		{
			fieldname: "as_of_date",
			label: __("As Of Date"),
			fieldtype: "Date",
			default: hospitality_pms.reports.business_date(),
		},
	],
};
