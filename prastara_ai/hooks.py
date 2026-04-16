app_name = "prastara_ai"
app_title = "Prastara AI"
app_publisher = "ledworld"
app_description = "Prastara AI app"
app_email = "admin@example.com"
app_license = "mit"
frappe_version = ">=15.0.0 <16.0.0"

# Apps
# ------------------

required_apps = ["erpnext"]

# Customer Portal — redirect hyphenated URLs to underscore equivalents
# (Python module names can't contain hyphens; www/ uses customer_portal/)
website_redirects = [
	{"source": "/portal", "target": "/customer_portal"},
	{"source": "/customer-portal", "target": "/customer_portal"},
	{"source": "/customer-portal/(.*)", "target": "/customer_portal/\\1"},
]

# Fixtures — export cp_custom_pin custom field on Customer after adding it via Customize Form
fixtures = [
	{
		"dt": "Custom Field",
		"filters": [["dt", "=", "Customer"], ["fieldname", "=", "cp_custom_pin"]],
	}
]

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "prastara_ai",
# 		"logo": "/assets/prastara_ai/logo.png",
# 		"title": "prastar-ai",
# 		"route": "/prastara_ai",
# 		"has_permission": "prastara_ai.api.permission.has_app_permission"
# 	}
# ]
add_to_apps_screen = [
	{
		"name": "prastara_ai",
		"title": "Prastara AI",
		"logo": "/assets/prastara_ai/images/logo.svg",
		"route": "/sales-workspace",
	}
]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/prastara_ai/css/prastara_ai.css"
# app_include_js = "/assets/prastara_ai/js/prastara_ai.js"

# include js, css files in header of web template
# web_include_css = "/assets/prastara_ai/css/prastara_ai.css"
# web_include_js = "/assets/prastara_ai/js/prastara_ai.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "prastara_ai/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
doctype_js = {
	"AI Estimation Settings": "public/js/ai_estimation_settings.js",
	"Opportunity": "public/js/opportunity_email_import.js",
}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "prastara_ai/public/icons.svg"

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

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "prastara_ai.utils.jinja_methods",
# 	"filters": "prastara_ai.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "prastara_ai.install.before_install"
# after_install = "prastara_ai.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "prastara_ai.uninstall.before_uninstall"
# after_uninstall = "prastara_ai.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "prastara_ai.utils.before_app_install"
# after_app_install = "prastara_ai.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "prastara_ai.utils.before_app_uninstall"
# after_app_uninstall = "prastara_ai.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "prastara_ai.notifications.get_notification_config"

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

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
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
# 		"prastara_ai.tasks.all"
# 	],
# 	"daily": [
# 		"prastara_ai.tasks.daily"
# 	],
# 	"hourly": [
# 		"prastara_ai.tasks.hourly"
# 	],
# 	"weekly": [
# 		"prastara_ai.tasks.weekly"
# 	],
# 	"monthly": [
# 		"prastara_ai.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "prastara_ai.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "prastara_ai.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "prastara_ai.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["prastara_ai.utils.before_request"]
# after_request = ["prastara_ai.utils.after_request"]

# Job Events
# ----------
# before_job = ["prastara_ai.utils.before_job"]
# after_job = ["prastara_ai.utils.after_job"]

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
# 	"prastara_ai.auth.validate"
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
