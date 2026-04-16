from __future__ import annotations
import frappe
from prastara_ai.api.customer_portal import COOKIE_NAME, TOKEN_PREFIX

no_cache = 1


def get_context(context):
	request = getattr(frappe.local, "request", None)
	token = request.cookies.get(COOKIE_NAME) if request else None
	if token:
		frappe.cache.delete_value(f"{TOKEN_PREFIX}{token}")
	frappe.local.cookie_manager.delete_cookie(COOKIE_NAME)
	frappe.local.flags.redirect_location = "/customer_portal"
	raise frappe.Redirect
