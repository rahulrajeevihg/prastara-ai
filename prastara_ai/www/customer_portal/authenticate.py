from __future__ import annotations

from urllib.parse import quote

import frappe

no_cache = 1


def get_context(context):
	from prastara_ai.api.customer_portal import portal_login

	context.no_cache = 1

	if frappe.request.method != "POST":
		frappe.local.flags.redirect_location = "/customer_portal"
		raise frappe.Redirect

	identifier = frappe.form_dict.get("identifier")
	password = frappe.form_dict.get("password")

	try:
		portal_login(identifier=identifier, password=password)
		frappe.local.flags.redirect_location = "/customer_portal/dashboard"
	except Exception as exc:
		message = frappe.utils.strip_html(getattr(exc, "message", None) or str(exc) or "Invalid credentials.")
		frappe.local.flags.redirect_location = f"/customer_portal?error={quote(message)}"

	raise frappe.Redirect
