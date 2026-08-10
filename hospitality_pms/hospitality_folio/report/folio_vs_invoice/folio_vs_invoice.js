// Filters for the Folio vs Invoice report.
//
// Property is mandatory: it is the scoping boundary for everything the
// server side computes, per the reconciliation service it delegates to.
frappe.query_reports["Folio vs Invoice"] = {
	filters: [
		hospitality_pms.reports.property_filter(),
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(hospitality_pms.reports.business_date(), -1),
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: hospitality_pms.reports.business_date(),
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
