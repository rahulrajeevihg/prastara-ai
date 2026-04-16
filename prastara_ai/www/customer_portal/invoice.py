from __future__ import annotations
import frappe
from prastara_ai.api.customer_portal import _require_portal_session, _fetch_invoice_detail

no_cache = 1


def get_context(context):
	customer_name = _require_portal_session()

	invoice_name = frappe.form_dict.get("name")
	if not invoice_name:
		frappe.local.flags.redirect_location = "/customer_portal/dashboard"
		raise frappe.Redirect

	try:
		doc = _fetch_invoice_detail(invoice_name, customer_name)
	except (frappe.DoesNotExistError, frappe.PermissionError, Exception):
		frappe.local.flags.redirect_location = "/customer_portal/dashboard"
		raise frappe.Redirect

	context.no_cache = 1
	context.show_sidebar = False
	context.no_header = True
	context.no_footer = True
	context.title = f"Invoice {invoice_name}"
	context.customer_name = customer_name
	context.doc = doc
