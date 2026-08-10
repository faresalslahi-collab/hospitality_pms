// Filters for the Availability Forecast report.
//
// Property is mandatory and defaults to the property this user works in; the
// shared definition lives in hospitality_pms/public/js/reports.js so every
// report scopes the same way.
frappe.query_reports["Availability Forecast"] = {
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
			label: __("To Date (blank = From Date + 30 days)"),
			fieldtype: "Date",
		},
		{
			fieldname: "room_type",
			label: __("Room Type"),
			fieldtype: "Link",
			options: "Room Type",
		},
	],
};
