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
	context.title = "Quotations"
	context.customer_name = customer_name

	context.quotations = frappe.get_all(
		"Quotation",
		filters={"party_name": customer_name, "quotation_to": "Customer", "docstatus": 1},
		fields=["name", "transaction_date", "valid_till", "grand_total", "status", "currency"],
		order_by="transaction_date desc",
		limit=100,
	)
