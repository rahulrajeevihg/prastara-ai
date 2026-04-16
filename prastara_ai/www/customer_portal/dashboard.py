from __future__ import annotations
import frappe
from prastara_ai.api.customer_portal import _require_portal_session, _fetch_dashboard_data

no_cache = 1


def get_context(context):
	customer_name = _require_portal_session()

	context.no_cache = 1
	context.show_sidebar = False
	context.no_header = True
	context.no_footer = True
	context.title = "My Portal"
	context.customer_name = customer_name

	try:
		context.dashboard = _fetch_dashboard_data(customer_name)
	except Exception:
		context.dashboard = {
			"summary": {
				"quotation_count": 0,
				"active_order_count": 0,
				"outstanding_amount": 0,
				"paid_invoice_count": 0,
			},
			"recent_quotations": [],
			"active_orders": [],
			"recent_invoices": [],
		}
