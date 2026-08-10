// Filters for the In House report.
//
// Property is mandatory and defaults to the property this user works in; the
// shared definition lives in hospitality_pms/public/js/reports.js so every
// report scopes the same way.
frappe.query_reports["In House"] = {
	filters: [
		hospitality_pms.reports.property_filter(),
		{
			fieldname: "date",
			label: __("As Of Date"),
			fieldtype: "Date",
			default: hospitality_pms.reports.business_date(),
		},
	],
};
