// Filters for the Maintenance Response Times report.
//
// Property is mandatory and defaults to the property this user works in; the
// shared definition lives in hospitality_pms/public/js/reports.js so every
// report scopes the same way.
frappe.query_reports["Maintenance Response Times"] = {
	filters: [
		hospitality_pms.reports.property_filter(),
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: hospitality_pms.reports.business_date(),
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: hospitality_pms.reports.business_date(),
		},
	],
};
