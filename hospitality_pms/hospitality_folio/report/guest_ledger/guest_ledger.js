// Filters for the Guest Ledger report.
//
// Property is mandatory: it is the scoping boundary for the folio, charge
// and payment queries.
frappe.query_reports["Guest Ledger"] = {
	filters: [
		{
			fieldname: "property",
			label: __("Property"),
			fieldtype: "Link",
			options: "Hospitality Property",
			reqd: 1,
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
		},
		{
			fieldname: "folio_status",
			label: __("Folio Status"),
			fieldtype: "Select",
			options:
				"\nOpen\nUnder Review\nDisputed\nReady for Settlement\nPartially Settled\nSettled\nClosed",
		},
	],
};
