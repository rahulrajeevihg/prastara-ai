from __future__ import annotations
import frappe
from prastara_ai.api.customer_portal import _require_portal_session

no_cache = 1


def get_context(context):
	customer_name = _require_portal_session()

	context.no_cache = 1
	context.show_sidebar = False
	context.no_header = True
	context.no_footer = True
	context.title = "Invoices"
	context.customer_name = customer_name

	context.invoices = frappe.get_all(
		"Sales Invoice",
		filters={"customer": customer_name, "docstatus": 1},
		fields=["name", "posting_date", "due_date", "grand_total", "outstanding_amount", "status", "currency"],
		order_by="posting_date desc",
		limit=100,
	)
