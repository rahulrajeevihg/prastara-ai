from __future__ import annotations
import frappe

no_cache = 1


def get_context(context):
	# If customer already has a valid portal session, skip login
	from prastara_ai.api.customer_portal import _get_portal_session

	session = _get_portal_session(frappe.local.request)
	if session:
		frappe.local.flags.redirect_location = "/customer_portal/dashboard"
		raise frappe.Redirect

	context.no_cache = 1
	context.show_sidebar = False
	context.no_header = True
	context.no_footer = True
	context.title = "Customer Portal"
	context.login_error = frappe.form_dict.get("error")
