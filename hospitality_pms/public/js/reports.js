// Shared filter definitions for the Hospitality PMS query reports.
//
// Every operational report is scoped to a property, and every one of them was
// asking the user to pick it again. The default comes from `frappe.boot`
// (see hospitality_pms/boot.py) because report filters are built synchronously
// when the report opens — an async lookup would render the filter empty and
// fill it in afterwards, which reads as the report loading twice.
//
// Defined here rather than repeated per report so a change to how the property
// filter behaves is one edit, not twenty-one.

frappe.provide("hospitality_pms.reports");

function boot_value(key) {
	return (frappe.boot && frappe.boot.hospitality_pms && frappe.boot.hospitality_pms[key]) || "";
}

/** The property this user works in, or "" when none can be resolved. */
hospitality_pms.reports.default_property = function () {
	return boot_value("default_property");
};

/**
 * The property's operating day — what every report date should default to.
 *
 * Not the same as today. A property that has not run its Night Audit is still
 * working yesterday's date, and that is the date its arrivals, departures and
 * room charges are filed under. Defaulting a report to the server calendar date
 * opens it on a day the desk has not reached yet, showing an empty or partial
 * list that reads as missing data.
 *
 * Falls back to the calendar date only when no property resolves, so a report
 * still opens on something sensible on a site with no property configured.
 */
hospitality_pms.reports.business_date = function () {
	return boot_value("business_date") || frappe.datetime.get_today();
};

/**
 * The standard property filter.
 *
 * Mandatory by default: a report that aggregates rooms, folios or reservations
 * across every property is not a report anyone at a front desk asked for.
 * `overrides` is merged last so a report can relax that if it ever needs to.
 */
hospitality_pms.reports.property_filter = function (overrides) {
	return Object.assign(
		{
			fieldname: "property",
			label: __("Property"),
			fieldtype: "Link",
			options: "Property",
			reqd: 1,
			default: hospitality_pms.reports.default_property(),
		},
		overrides || {}
	);
};
