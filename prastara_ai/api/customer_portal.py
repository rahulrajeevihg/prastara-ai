from __future__ import annotations

import re
import json
import time

import frappe
from frappe import _

# ─── Constants ────────────────────────────────────────────────────────────────
COOKIE_NAME = "cp_token"
TOKEN_PREFIX = "cp_tok:"
FAIL_PREFIX = "cp_fail:"


# ─── Session helpers (internal) ───────────────────────────────────────────────

def _get_portal_session(request) -> dict | None:
	"""Read cp_token cookie, validate Redis entry. Returns session dict or None."""
	try:
		token = request.cookies.get(COOKIE_NAME)
	except Exception:
		return None
	if not token:
		return None
	data = frappe.cache.get_value(f"{TOKEN_PREFIX}{token}")
	if not data:
		return None
	if data.get("exp", 0) < time.time():
		frappe.cache.delete_value(f"{TOKEN_PREFIX}{token}")
		return None
	return data  # {"customer": "CUST-0001", "exp": float}


def _require_portal_session() -> str:
	"""Call from get_context(). Redirects to login if no valid session. Returns customer_name."""
	session = _get_portal_session(frappe.local.request)
	if not session:
		frappe.local.flags.redirect_location = "/customer_portal"
		raise frappe.Redirect
	return session["customer"]


def _validate_portal_request() -> str:
	"""Call from @whitelist API methods. Raises AuthenticationError if no valid session."""
	request = getattr(frappe.local, "request", None)
	token = request.cookies.get(COOKIE_NAME) if request else None
	if not token:
		frappe.throw(_("Not authenticated"), frappe.AuthenticationError)
	data = frappe.cache.get_value(f"{TOKEN_PREFIX}{token}")
	if not data:
		frappe.throw(_("Session expired. Please log in again."), frappe.AuthenticationError)
	if data.get("exp", 0) < time.time():
		frappe.cache.delete_value(f"{TOKEN_PREFIX}{token}")
		frappe.throw(_("Session expired. Please log in again."), frappe.AuthenticationError)
	return data["customer"]


# ─── Password generation ──────────────────────────────────────────────────────

def _generate_expected_password(customer_name: str) -> str | None:
	"""Build portal password from Customer Portal Settings rules."""
	settings = frappe.get_single("Customer Portal Settings")
	customer = frappe.get_doc("Customer", customer_name)

	primary_email = _get_customer_primary_email(customer_name) or ""
	primary_phone = (
		customer.mobile_no
		or _get_customer_primary_phone(customer_name)
		or ""
	)

	sep = settings.separator or ""
	parts: list[str] = []

	if settings.use_customer_name_prefix and settings.customer_name_chars:
		n = int(settings.customer_name_chars)
		# Strip all spaces and uppercase
		name_clean = re.sub(r"\s+", "", customer.customer_name or "")
		parts.append(name_clean[:n].upper())

	if settings.use_tax_id_suffix and settings.tax_id_chars:
		n = int(settings.tax_id_chars)
		tax_digits = re.sub(r"\D", "", customer.tax_id or "")
		parts.append(tax_digits[-n:] if len(tax_digits) >= n else tax_digits)

	if settings.use_email_prefix and settings.email_chars:
		n = int(settings.email_chars)
		email_local = primary_email.split("@")[0]
		parts.append(email_local[:n].lower())

	if settings.use_phone_suffix and settings.phone_chars:
		n = int(settings.phone_chars)
		phone_digits = re.sub(r"\D", "", primary_phone)
		parts.append(phone_digits[-n:] if len(phone_digits) >= n else phone_digits)

	if not parts:
		return None
	return sep.join(parts)


# ─── Customer lookup helpers ──────────────────────────────────────────────────

def _get_customer_primary_email(customer_name: str) -> str | None:
	"""Look up primary email from Customer or linked Contact."""
	email = frappe.db.get_value("Customer", customer_name, "email_id")
	if email:
		return email
	rows = frappe.db.sql(
		"""
		SELECT ce.email_id
		FROM `tabContact Email` ce
		JOIN `tabContact` c ON c.name = ce.parent
		JOIN `tabDynamic Link` dl ON dl.parent = c.name
		WHERE dl.link_doctype = 'Customer'
		  AND dl.link_name = %(customer)s
		  AND ce.is_primary = 1
		LIMIT 1
		""",
		{"customer": customer_name},
		as_dict=True,
	)
	return rows[0].email_id if rows else None


def _get_customer_primary_phone(customer_name: str) -> str | None:
	"""Look up primary mobile/phone from linked Contact."""
	rows = frappe.db.sql(
		"""
		SELECT c.mobile_no
		FROM `tabContact` c
		JOIN `tabDynamic Link` dl ON dl.parent = c.name
		WHERE dl.link_doctype = 'Customer'
		  AND dl.link_name = %(customer)s
		LIMIT 1
		""",
		{"customer": customer_name},
		as_dict=True,
	)
	return rows[0].mobile_no if rows else None


def _lookup_customer_by_identifier(identifier: str) -> str | None:
	"""Find Customer name by email (case-insensitive) or customer name."""
	identifier = (identifier or "").strip()
	identifier_lower = identifier.lower()

	# 1. Case-insensitive direct match on Customer.email_id
	rows = frappe.db.sql(
		"""
		SELECT name
		FROM `tabCustomer`
		WHERE LOWER(TRIM(email_id)) = %(email)s
		LIMIT 1
		""",
		{"email": identifier_lower},
		as_dict=True,
	)
	if rows:
		return rows[0].name

	# 2. Case-insensitive via Contact Email + Dynamic Link
	rows = frappe.db.sql(
		"""
		SELECT dl.link_name
		FROM `tabContact Email` ce
		JOIN `tabContact` c ON c.name = ce.parent
		JOIN `tabDynamic Link` dl ON dl.parent = c.name
		WHERE LOWER(ce.email_id) = %(email)s
		  AND dl.link_doctype = 'Customer'
		LIMIT 1
		""",
		{"email": identifier_lower},
		as_dict=True,
	)
	if rows:
		return rows[0].link_name

	# 3. Fallback: direct customer name match (case-insensitive)
	rows2 = frappe.db.sql(
		"SELECT name FROM `tabCustomer` WHERE LOWER(name) = %(name)s LIMIT 1",
		{"name": identifier_lower},
		as_dict=True,
	)
	return rows2[0].name if rows2 else None


# ─── Rate-limiting helpers ────────────────────────────────────────────────────

def _record_failed_attempt(fail_key: str, lockout_secs: int):
	current = frappe.cache.get_value(f"{FAIL_PREFIX}{fail_key}") or 0
	frappe.cache.set_value(f"{FAIL_PREFIX}{fail_key}", int(current) + 1, expires_in_sec=lockout_secs)


# ─── Whitelisted API endpoints ────────────────────────────────────────────────

@frappe.whitelist(allow_guest=True)
def debug_request():
	"""Temporary: return what Frappe sees in the request."""
	req = frappe.local.request
	raw = req.get_data(as_text=True)
	return {
		"form_dict": dict(frappe.form_dict),
		"content_type": req.content_type,
		"method": req.method,
		"raw_body": raw[:500],
		"form_keys": list(req.form.keys()),
		"args_keys": list(req.args.keys()),
	}


@frappe.whitelist(allow_guest=True)
def portal_login(identifier=None, password=None):
	"""
	Authenticate a customer against the configured portal password rules.
	Parameters are passed by Frappe from form_dict. We also fall back to
	parsing a JSON request body for custom frontend calls.
	"""
	if not identifier or not password:
		request = getattr(frappe.local, "request", None)
		if request:
			raw_body = request.get_data(as_text=True) or ""
			if raw_body:
				try:
					payload = json.loads(raw_body)
				except json.JSONDecodeError:
					payload = {}
				identifier = identifier or payload.get("identifier")
				password = password or payload.get("password")

	identifier = (identifier or "").strip().lower()
	password = (password or "").strip()

	if not identifier or not password:
		frappe.throw(_("Please enter your email and password."), frappe.ValidationError)

	settings = frappe.get_single("Customer Portal Settings")
	max_attempts = int(settings.max_login_attempts or 5)
	lockout_secs = int(settings.lockout_minutes or 15) * 60

	# Rate limit per IP + identifier
	ip = getattr(frappe.local, "request_ip", None) or "unknown"
	fail_key = f"{ip}:{identifier.lower()}"
	fail_count = frappe.cache.get_value(f"{FAIL_PREFIX}{fail_key}") or 0
	if int(fail_count) >= max_attempts:
		frappe.throw(
			_("Too many failed attempts. Please try again later."),
			frappe.AuthenticationError,
		)

	# Look up customer
	customer_name = _lookup_customer_by_identifier(identifier)
	if not customer_name:
		_record_failed_attempt(fail_key, lockout_secs)
		frappe.throw(_("Invalid credentials."), frappe.AuthenticationError)

	# Determine expected password
	custom_pin = frappe.db.get_value("Customer", customer_name, "cp_custom_pin")
	if custom_pin:
		expected = custom_pin.strip()
	else:
		expected = _generate_expected_password(customer_name)

	if not expected or password != expected:
		_record_failed_attempt(fail_key, lockout_secs)
		frappe.throw(_("Invalid credentials."), frappe.AuthenticationError)

	# Success — clear fail counter, issue token
	frappe.cache.delete_value(f"{FAIL_PREFIX}{fail_key}")

	expiry_hours = int(settings.session_expiry_hours or 24)
	expiry_ts = time.time() + (expiry_hours * 3600)
	token = frappe.generate_hash(length=40)
	session_data = {"customer": customer_name, "exp": expiry_ts}
	frappe.cache.set_value(f"{TOKEN_PREFIX}{token}", session_data, expires_in_sec=expiry_hours * 3600)

	frappe.local.cookie_manager.set_cookie(
		COOKIE_NAME,
		token,
		max_age=expiry_hours * 3600,
		httponly=True,
		samesite="Strict",
	)
	return {"success": True, "redirect": "/customer_portal/dashboard"}


@frappe.whitelist(allow_guest=True)
def portal_logout() -> dict:
	"""Clear the portal session token."""
	request = getattr(frappe.local, "request", None)
	token = request.cookies.get(COOKIE_NAME) if request else None
	if token:
		frappe.cache.delete_value(f"{TOKEN_PREFIX}{token}")
	frappe.local.cookie_manager.delete_cookie(COOKIE_NAME)
	return {"success": True}


@frappe.whitelist(allow_guest=True)
def get_dashboard_data() -> dict:
	"""Return summary + recent transactions for the authenticated customer."""
	customer_name = _validate_portal_request()
	return _fetch_dashboard_data(customer_name)


def _fetch_dashboard_data(customer_name: str) -> dict:
	"""Core dashboard data fetch — shared by the API endpoint and get_context()."""
	quotation_count = frappe.db.count(
		"Quotation",
		{"party_name": customer_name, "quotation_to": "Customer", "docstatus": 1},
	)
	order_count = frappe.db.count(
		"Sales Order",
		{
			"customer": customer_name,
			"docstatus": 1,
			"status": ["in", ["To Deliver and Bill", "To Bill", "To Deliver"]],
		},
	)
	outstanding_row = frappe.db.sql(
		"""
		SELECT COALESCE(SUM(outstanding_amount), 0) AS total
		FROM `tabSales Invoice`
		WHERE customer = %(customer)s
		  AND docstatus = 1
		  AND outstanding_amount > 0
		""",
		{"customer": customer_name},
		as_dict=True,
	)
	outstanding = outstanding_row[0].total if outstanding_row else 0

	paid_count = frappe.db.count(
		"Sales Invoice",
		{"customer": customer_name, "docstatus": 1, "status": "Paid"},
	)

	recent_quotations = frappe.get_all(
		"Quotation",
		filters={"party_name": customer_name, "quotation_to": "Customer", "docstatus": 1},
		fields=["name", "transaction_date", "grand_total", "status", "currency"],
		order_by="transaction_date desc",
		limit=5,
	)
	active_orders = frappe.get_all(
		"Sales Order",
		filters={
			"customer": customer_name,
			"docstatus": 1,
			"status": ["in", ["To Deliver and Bill", "To Bill", "To Deliver"]],
		},
		fields=["name", "transaction_date", "grand_total", "status", "currency", "delivery_date"],
		order_by="transaction_date desc",
		limit=5,
	)
	recent_invoices = frappe.get_all(
		"Sales Invoice",
		filters={"customer": customer_name, "docstatus": 1},
		fields=["name", "posting_date", "grand_total", "outstanding_amount", "status", "currency"],
		order_by="posting_date desc",
		limit=5,
	)

	return {
		"customer_name": customer_name,
		"summary": {
			"quotation_count": quotation_count,
			"active_order_count": order_count,
			"outstanding_amount": float(outstanding),
			"paid_invoice_count": paid_count,
		},
		"recent_quotations": recent_quotations,
		"active_orders": active_orders,
		"recent_invoices": recent_invoices,
	}


@frappe.whitelist(allow_guest=True)
def get_quotation_detail(quotation_name: str) -> dict:
	customer_name = _validate_portal_request()
	return _fetch_quotation_detail(quotation_name, customer_name)


def _fetch_quotation_detail(quotation_name: str, customer_name: str) -> dict:
	doc = frappe.get_doc("Quotation", quotation_name)
	if doc.party_name != customer_name or doc.quotation_to != "Customer":
		frappe.throw(_("Not found."), frappe.DoesNotExistError)
	return {
		"name": doc.name,
		"transaction_date": str(doc.transaction_date),
		"valid_till": str(doc.valid_till) if doc.valid_till else None,
		"status": doc.status,
		"grand_total": float(doc.grand_total or 0),
		"total_taxes_and_charges": float(doc.total_taxes_and_charges or 0),
		"currency": doc.currency,
		"items": [
			{
				"item_name": i.item_name,
				"description": i.description,
				"qty": float(i.qty or 0),
				"uom": i.uom,
				"rate": float(i.rate or 0),
				"amount": float(i.amount or 0),
			}
			for i in doc.items
		],
		"taxes": [
			{"description": t.description, "tax_amount": float(t.tax_amount or 0)}
			for t in (doc.taxes or [])
		],
	}


@frappe.whitelist(allow_guest=True)
def get_order_detail(order_name: str) -> dict:
	customer_name = _validate_portal_request()
	return _fetch_order_detail(order_name, customer_name)


def _fetch_order_detail(order_name: str, customer_name: str) -> dict:
	doc = frappe.get_doc("Sales Order", order_name)
	if doc.customer != customer_name:
		frappe.throw(_("Not found."), frappe.DoesNotExistError)
	return {
		"name": doc.name,
		"transaction_date": str(doc.transaction_date),
		"delivery_date": str(doc.delivery_date) if doc.delivery_date else None,
		"status": doc.status,
		"grand_total": float(doc.grand_total or 0),
		"currency": doc.currency,
		"per_billed": float(doc.per_billed or 0),
		"per_delivered": float(doc.per_delivered or 0),
		"items": [
			{
				"item_name": i.item_name,
				"qty": float(i.qty or 0),
				"uom": i.uom,
				"rate": float(i.rate or 0),
				"amount": float(i.amount or 0),
			}
			for i in doc.items
		],
	}


@frappe.whitelist(allow_guest=True)
def get_invoice_detail(invoice_name: str) -> dict:
	customer_name = _validate_portal_request()
	return _fetch_invoice_detail(invoice_name, customer_name)


def _fetch_invoice_detail(invoice_name: str, customer_name: str) -> dict:
	doc = frappe.get_doc("Sales Invoice", invoice_name)
	if doc.customer != customer_name:
		frappe.throw(_("Not found."), frappe.DoesNotExistError)
	return {
		"name": doc.name,
		"posting_date": str(doc.posting_date),
		"due_date": str(doc.due_date) if doc.due_date else None,
		"status": doc.status,
		"grand_total": float(doc.grand_total or 0),
		"outstanding_amount": float(doc.outstanding_amount or 0),
		"currency": doc.currency,
		"items": [
			{
				"item_name": i.item_name,
				"qty": float(i.qty or 0),
				"rate": float(i.rate or 0),
				"amount": float(i.amount or 0),
			}
			for i in doc.items
		],
	}


@frappe.whitelist(allow_guest=True)
def preview_password(customer_name: str) -> dict:
	"""Admin utility — preview the generated portal password for a customer."""
	if frappe.session.user == "Guest":
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	if not frappe.has_permission("Customer Portal Settings", "read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	password = _generate_expected_password(customer_name)
	return {"customer": customer_name, "password": password or "(no rules configured)"}
