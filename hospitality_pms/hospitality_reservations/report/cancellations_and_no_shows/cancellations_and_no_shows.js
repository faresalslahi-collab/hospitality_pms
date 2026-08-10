// Filters for the Cancellations and No Shows report.
//
// Property is mandatory: it is the scoping boundary for which reservations
// are considered.
frappe.query_reports["Cancellations and No Shows"] = {
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
