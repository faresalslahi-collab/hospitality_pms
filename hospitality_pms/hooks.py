app_name = "hospitality_pms"
app_title = "Hospitality PMS"
app_publisher = "Globcom Qatar"
app_description = "Hospitality Property Management System for Frappe/ERPNext v16"
app_email = "waheed@globcomqatar.com"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "hospitality_pms",
# 		"logo": "/assets/hospitality_pms/logo.png",
# 		"title": "Hospitality PMS",
# 		"route": "/hospitality_pms",
# 		"has_permission": "hospitality_pms.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/hospitality_pms/css/hospitality_pms.css"
# app_include_js = "/assets/hospitality_pms/js/hospitality_pms.js"

# include js, css files in header of web template
# web_include_css = "/assets/hospitality_pms/css/hospitality_pms.css"
# web_include_js = "/assets/hospitality_pms/js/hospitality_pms.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "hospitality_pms/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "hospitality_pms/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "hospitality_pms.utils.jinja_methods",
# 	"filters": "hospitality_pms.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "hospitality_pms.install.before_install"
# after_install = "hospitality_pms.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "hospitality_pms.uninstall.before_uninstall"
# after_uninstall = "hospitality_pms.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "hospitality_pms.utils.before_app_install"
# after_app_install = "hospitality_pms.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "hospitality_pms.utils.before_app_uninstall"
# after_app_uninstall = "hospitality_pms.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "hospitality_pms.build.after_build"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "hospitality_pms.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"hospitality_pms.tasks.all"
# 	],
# 	"daily": [
# 		"hospitality_pms.tasks.daily"
# 	],
# 	"hourly": [
# 		"hospitality_pms.tasks.hourly"
# 	],
# 	"weekly": [
# 		"hospitality_pms.tasks.weekly"
# 	],
# 	"monthly": [
# 		"hospitality_pms.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "hospitality_pms.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "hospitality_pms.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "hospitality_pms.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "hospitality_pms.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["hospitality_pms.utils.before_request"]
# after_request = ["hospitality_pms.utils.after_request"]

# Job Events
# ----------
# before_job = ["hospitality_pms.utils.before_job"]
# after_job = ["hospitality_pms.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"hospitality_pms.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

