// Filters for the Room Status report.
//
// Property is mandatory and defaults to the property this user works in; the
// shared definition lives in hospitality_pms/public/js/reports.js so every
// report scopes the same way.
frappe.query_reports["Room Status"] = {
	filters: [
		hospitality_pms.reports.property_filter(),
		{
			fieldname: "room_type",
			label: __("Room Type"),
			fieldtype: "Link",
			options: "Room Type",
		},
	],
};
