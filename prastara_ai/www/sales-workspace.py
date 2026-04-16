from __future__ import annotations

import frappe

no_cache = 1


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = f"/login?redirect-to={frappe.local.request.path}"
		raise frappe.Redirect

	context.no_cache = 1
	context.show_sidebar = False
	context.full_width = True
	context.no_header = True
	context.title = "Prastara AI Workspace"
	context.page_title = "Prastara AI Workspace"
	return context
