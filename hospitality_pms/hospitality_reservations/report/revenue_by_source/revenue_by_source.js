// Filters for the Revenue by Source report.
//
// Property is mandatory: it is the scoping boundary for which reservations
// are considered.
frappe.query_reports["Revenue by Source"] = {
	filters: [
		{
			fieldname: "property",
			label: __("Property"),
			fieldtype: "Link",
			options: "Property",
			reqd: 1,
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_days(frappe.datetime.get_today(), -30),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
	],
};
