app_name = "hospitality_pms"
app_title = "Hospitality PMS"
app_publisher = "Globcom Qatar"
app_description = "Hospitality Property Management System for Frappe/ERPNext v16"
app_email = "waheed@globcomqatar.com"
app_license = "mit"

# ERPNext is the financial and enterprise system of record (HPMS-DEC-002).
required_apps = ["frappe/erpnext"]

# ------------------------------------------------------------------------------
# Installation
# ------------------------------------------------------------------------------

after_install = "hospitality_pms.install.after_install"
after_migrate = "hospitality_pms.install.after_migrate"
before_uninstall = "hospitality_pms.install.before_uninstall"

# ------------------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------------------
# Fixtures must stay reproducible across benches. Only export records the app
# owns; never export site-specific or ERPNext master data.
#
# Workspaces ship as JSON under each module's workspace/ folder (developer
# mode export), so they reach every bench automatically with the app source.
# Number Card is not a "Document Export" doctype -- developer mode does not
# write it to disk -- so the eight cards the "Hospitality PMS" workspace
# displays would otherwise exist only in the database they were created in.
# Listing them here makes `bench --site x export-fixtures` / `import-fixtures`
# carry them to every other bench the same way the workspace JSON already does.
fixtures = [
	{
		"dt": "Number Card",
		"filters": [
			[
				"name",
				"in",
				[
					"Arrivals Today",
					"In House",
					"Rooms Out of Order",
					"Housekeeping Tasks Pending",
					"Open Maintenance Tickets",
					"Failed Postings",
					"Integration Failures Pending",
					"Overdue Guest Requests",
				],
			]
		],
	},
]

# ------------------------------------------------------------------------------
# Permissions
# ------------------------------------------------------------------------------
# Property-aware access is enforced server side (HPMS-DEC-052). Query conditions
# are registered per DocType as the domain builds land.

permission_query_conditions = {}
has_permission = {}

# ------------------------------------------------------------------------------
# Document Events
# ------------------------------------------------------------------------------

doc_events = {}

# ------------------------------------------------------------------------------
# Scheduled Tasks
# ------------------------------------------------------------------------------

scheduler_events = {}

# ------------------------------------------------------------------------------
# Desk
# ------------------------------------------------------------------------------

app_include_js = []
app_include_css = []

# ------------------------------------------------------------------------------
# Website / Operational Frontend
# ------------------------------------------------------------------------------
# The Vue operational frontend is served from the Frappe site at /pms
# (HPMS-DEC-043, HPMS-DEC-050). No standalone Node runtime in production.

# Deep links such as /pms/reservations/RES-0001 are resolved by the Vue router,
# so every path under /pms is served by the same page.
website_route_rules = [
	{"from_route": "/pms/<path:app_path>", "to_route": "pms"},
]

# ------------------------------------------------------------------------------
# Jinja
# ------------------------------------------------------------------------------

jinja = {"methods": [], "filters": []}
