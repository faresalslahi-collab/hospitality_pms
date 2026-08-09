// Filters for the Folio vs Invoice report.
//
// Property is mandatory: it is the scoping boundary for everything the
// server side computes, per the reconciliation service it delegates to.
frappe.query_reports["Folio vs Invoice"] = {
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
