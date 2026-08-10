// Filters for the Failed Postings report.
//
// Property is mandatory: it is the scoping boundary for the posting log
// query. Status defaults to "Failed" -- the queue this report exists to show
// -- but can be widened to review any other posting state.
frappe.query_reports["Failed Postings"] = {
	filters: [
		hospitality_pms.reports.property_filter(),
		{
			fieldname: "posting_type",
			label: __("Posting Type"),
			fieldtype: "Select",
			options: "\nSales Invoice\nPayment Entry\nJournal Entry\nStock Entry\nCredit Note",
		},
		{
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			options: "Failed\nPending\nPosted\nCancelled\nReconciled",
			default: "Failed",
		},
	],
};
