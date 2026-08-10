// Filters for the Occupancy and Revenue report.
//
// Property is mandatory: it is the scoping boundary for which rooms and
// folios are considered.
frappe.query_reports["Occupancy and Revenue"] = {
	filters: [
		hospitality_pms.reports.property_filter(),
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_days(hospitality_pms.reports.business_date(), -30),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: hospitality_pms.reports.business_date(),
			reqd: 1,
		},
	],
};
