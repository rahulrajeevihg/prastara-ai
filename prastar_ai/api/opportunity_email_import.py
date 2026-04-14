from __future__ import annotations

import base64
import json
import os
import re
from typing import Any

import frappe
from frappe import _
from frappe.query_builder import DocType
from frappe.utils import getdate, today

from prastar_ai.api.ai_service import AIService, resolve_file_path

try:
	import openai
except ImportError:
	openai = None


EMAIL_IMPORT_PROMPT = """You extract CRM opportunity-intake data from screenshots of client emails.

Return ONLY valid JSON with this exact top-level structure:
{
  "email_subject": "",
  "sender_email": "",
  "sender_name": "",
  "company_name": "",
  "contact_person": "",
  "contact_email": "",
  "phone": "",
  "mobile_no": "",
  "website": "",
  "project_title": "",
  "scope_summary": "",
  "project_location": "",
  "notes": "",
  "recommended_party_type": "Lead",
  "reasoning": "",
  "confidence": 0.0
}

Rules:
- Extract only what is reasonably visible in the screenshots.
- If sender_email is visible, extract the actual email address.
- contact_email may be the same as sender_email.
- company_name should be the organisation name, not the email domain unless that is the only clue.
- project_title should be short and suitable for an Opportunity title.
- scope_summary should be a concise business summary of the project/request.
- recommended_party_type must be either "Customer" or "Lead".
- If a field is unclear, return an empty string for it.
- confidence must be between 0 and 1.
"""

SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".pdf"}


def _require_create_access() -> None:
	if not frappe.has_permission("Opportunity", "create"):
		frappe.throw(_("You do not have permission to create Opportunities."), frappe.PermissionError)


def _normalize_email(value: str | None) -> str:
	return (value or "").strip().lower()


def _normalize_phone(value: str | None) -> str:
	return re.sub(r"\D+", "", value or "")


def _normalize_text(value: str | None) -> str:
	return re.sub(r"\s+", " ", (value or "").strip()).lower()


def _get_default_company() -> str:
	company = (
		frappe.defaults.get_user_default("Company")
		or frappe.defaults.get_global_default("company")
		or frappe.db.get_single_value("Global Defaults", "default_company")
	)
	if not company:
		company = frappe.db.get_value("Company", {}, "name")
	if not company:
		frappe.throw(_("Please set a default Company before importing Opportunities from email."))
	return company


def _encode_image_file(file_path: str) -> str:
	with open(file_path, "rb") as file_handle:
		return base64.b64encode(file_handle.read()).decode("utf-8")


def _build_user_content(file_urls: list[str], service: AIService) -> list[dict[str, Any]]:
	user_content: list[dict[str, Any]] = [
		{
			"type": "text",
			"text": (
				"Analyze these email screenshots and extract the opportunity intake data. "
				"Treat signatures, quoted email chains, and forwarded headers as useful clues."
			),
		}
	]

	for file_url in file_urls:
		file_path = resolve_file_path(file_url)
		extension = os.path.splitext(file_path)[1].lower()
		file_name = os.path.basename(file_path)

		if extension not in SUPPORTED_EXTENSIONS:
			frappe.throw(_("Unsupported file type for email import: {0}").format(extension))

		if extension == ".pdf":
			images = service._pdf_to_base64_images(file_path, max_pages=6, dpi=150)
			if not images:
				text_content = service.extract_content_from_file(file_url)
				user_content.append({
					"type": "text",
					"text": f"PDF attachment {file_name} text content:\n{text_content[:6000]}",
				})
				continue

			user_content.append({"type": "text", "text": f"PDF attachment: {file_name}"})
			for image_b64 in images:
				user_content.append({
					"type": "image_url",
					"image_url": {"url": f"data:image/png;base64,{image_b64}", "detail": "high"},
				})
			continue

		mime_type = "image/jpeg" if extension in {".jpg", ".jpeg"} else f"image/{extension.lstrip('.')}"
		user_content.append({"type": "text", "text": f"Email screenshot: {file_name}"})
		user_content.append({
			"type": "image_url",
			"image_url": {"url": f"data:{mime_type};base64,{_encode_image_file(file_path)}", "detail": "high"},
		})

	return user_content


def _score_match(*, email_match: bool = False, phone_match: bool = False, name_match: bool = False, contact_match: bool = False) -> int:
	score = 0
	if email_match:
		score += 100
	if phone_match:
		score += 80
	if name_match:
		score += 45
	if contact_match:
		score += 25
	return score


def _merge_match(match_map: dict[str, dict[str, Any]], party_name: str, payload: dict[str, Any]) -> None:
	if not party_name:
		return

	existing = match_map.get(party_name)
	if not existing:
		match_map[party_name] = payload
		return

	existing["score"] = max(existing.get("score", 0), payload.get("score", 0))
	existing_reasons = set(existing.get("reasons") or [])
	existing_reasons.update(payload.get("reasons") or [])
	existing["reasons"] = sorted(existing_reasons)


def _find_customer_matches(extracted: dict[str, Any]) -> list[dict[str, Any]]:
	email = _normalize_email(extracted.get("contact_email") or extracted.get("sender_email"))
	phone = _normalize_phone(extracted.get("mobile_no") or extracted.get("phone"))
	company_name = _normalize_text(extracted.get("company_name"))
	contact_person = _normalize_text(extracted.get("contact_person") or extracted.get("sender_name"))

	customer_map: dict[str, dict[str, Any]] = {}

	if email:
		for row in frappe.get_all(
			"Customer",
			fields=["name", "customer_name", "email_id", "mobile_no", "territory"],
			filters={"email_id": email},
			limit=10,
		):
			_merge_match(customer_map, row.name, {
				"name": row.name,
				"display_name": row.customer_name or row.name,
				"score": _score_match(email_match=True),
				"reasons": [_("Customer email matches extracted email")],
				"territory": row.territory,
			})

		dynamic_link = DocType("Dynamic Link")
		contact = DocType("Contact")
		rows = (
			frappe.qb.from_(dynamic_link)
			.join(contact)
			.on(contact.name == dynamic_link.parent)
			.select(dynamic_link.link_name, contact.first_name, contact.last_name)
			.where(dynamic_link.parenttype == "Contact")
			.where(dynamic_link.link_doctype == "Customer")
			.where(contact.email_id == email)
			.run(as_dict=True)
		)
		for row in rows:
			full_name = " ".join(filter(None, [row.first_name, row.last_name])).strip()
			_merge_match(customer_map, row.link_name, {
				"name": row.link_name,
				"display_name": frappe.db.get_value("Customer", row.link_name, "customer_name") or row.link_name,
				"score": _score_match(email_match=True, contact_match=bool(full_name)),
				"reasons": [_("Linked customer contact email matches extracted email")],
			})

	if phone:
		for row in frappe.get_all(
			"Customer",
			fields=["name", "customer_name", "mobile_no", "territory"],
			filters={"mobile_no": ["like", f"%{phone[-7:]}%"]},
			limit=10,
		):
			if phone and phone[-7:] and phone[-7:] in _normalize_phone(row.mobile_no):
				_merge_match(customer_map, row.name, {
					"name": row.name,
					"display_name": row.customer_name or row.name,
					"score": _score_match(phone_match=True),
					"reasons": [_("Customer mobile number is similar to extracted phone")],
					"territory": row.territory,
				})

	if company_name:
		for row in frappe.get_all(
			"Customer",
			fields=["name", "customer_name", "territory"],
			or_filters={
				"customer_name": ["like", f"%{extracted.get('company_name', '').strip()}%"],
				"name": ["like", f"%{extracted.get('company_name', '').strip()}%"],
			},
			limit=10,
		):
			candidate_name = _normalize_text(row.customer_name or row.name)
			if not candidate_name:
				continue
			_merge_match(customer_map, row.name, {
				"name": row.name,
				"display_name": row.customer_name or row.name,
				"score": _score_match(name_match=(candidate_name == company_name)),
				"reasons": [_("Customer name is similar to extracted company name")],
				"territory": row.territory,
			})

	if contact_person:
		dynamic_link = DocType("Dynamic Link")
		contact = DocType("Contact")
		rows = (
			frappe.qb.from_(dynamic_link)
			.join(contact)
			.on(contact.name == dynamic_link.parent)
			.select(dynamic_link.link_name, contact.first_name, contact.last_name)
			.where(dynamic_link.parenttype == "Contact")
			.where(dynamic_link.link_doctype == "Customer")
			.where(contact.first_name.like(f"%{extracted.get('contact_person', '').strip()}%") | contact.last_name.like(f"%{extracted.get('contact_person', '').strip()}%"))
			.run(as_dict=True)
		)
		for row in rows:
			full_name = _normalize_text(" ".join(filter(None, [row.first_name, row.last_name])))
			if not full_name:
				continue
			_merge_match(customer_map, row.link_name, {
				"name": row.link_name,
				"display_name": frappe.db.get_value("Customer", row.link_name, "customer_name") or row.link_name,
				"score": _score_match(contact_match=(full_name == contact_person)),
				"reasons": [_("Linked customer contact name is similar to extracted contact person")],
			})

	return sorted(customer_map.values(), key=lambda row: (-row.get("score", 0), row.get("display_name") or row.get("name")))


def _find_lead_matches(extracted: dict[str, Any]) -> list[dict[str, Any]]:
	email = _normalize_email(extracted.get("contact_email") or extracted.get("sender_email"))
	phone = _normalize_phone(extracted.get("mobile_no") or extracted.get("phone"))
	company_name = _normalize_text(extracted.get("company_name"))
	contact_person = _normalize_text(extracted.get("contact_person") or extracted.get("sender_name"))

	lead_map: dict[str, dict[str, Any]] = {}

	if email:
		for row in frappe.get_all(
			"Lead",
			fields=["name", "lead_name", "company_name", "status", "email_id", "mobile_no"],
			filters={"email_id": email},
			limit=10,
		):
			_merge_match(lead_map, row.name, {
				"name": row.name,
				"display_name": row.lead_name or row.company_name or row.name,
				"score": _score_match(email_match=True),
				"reasons": [_("Lead email matches extracted email")],
				"status": row.status,
			})

	if phone:
		for row in frappe.get_all(
			"Lead",
			fields=["name", "lead_name", "company_name", "status", "mobile_no", "phone"],
			or_filters={"mobile_no": ["like", f"%{phone[-7:]}%"], "phone": ["like", f"%{phone[-7:]}%"]},
			limit=10,
		):
			lead_phone = _normalize_phone(row.mobile_no) or _normalize_phone(row.phone)
			if phone and phone[-7:] and phone[-7:] in lead_phone:
				_merge_match(lead_map, row.name, {
					"name": row.name,
					"display_name": row.lead_name or row.company_name or row.name,
					"score": _score_match(phone_match=True),
					"reasons": [_("Lead phone number is similar to extracted phone")],
					"status": row.status,
				})

	if company_name or contact_person:
		search_text = extracted.get("company_name") or extracted.get("contact_person") or ""
		for row in frappe.get_all(
			"Lead",
			fields=["name", "lead_name", "company_name", "status"],
			or_filters={
				"company_name": ["like", f"%{search_text.strip()}%"],
				"lead_name": ["like", f"%{search_text.strip()}%"],
			},
			limit=10,
		):
			candidate_name = _normalize_text(row.company_name or row.lead_name)
			exact_name_match = bool(company_name and candidate_name == company_name) or bool(contact_person and candidate_name == contact_person)
			_merge_match(lead_map, row.name, {
				"name": row.name,
				"display_name": row.lead_name or row.company_name or row.name,
				"score": _score_match(name_match=exact_name_match),
				"reasons": [_("Lead name is similar to extracted company/contact name")],
				"status": row.status,
			})

	return sorted(lead_map.values(), key=lambda row: (-row.get("score", 0), row.get("display_name") or row.get("name")))


def _build_match_summary(extracted: dict[str, Any]) -> dict[str, Any]:
	customers = _find_customer_matches(extracted)
	leads = _find_lead_matches(extracted)

	recommended_party_type = extracted.get("recommended_party_type") or "Lead"
	recommended_party_name = ""
	match_reason = _("AI recommended creating a new Lead.")

	if customers:
		recommended_party_type = "Customer"
		recommended_party_name = customers[0]["name"]
		match_reason = _("Matched to existing Customer: {0}").format(customers[0]["display_name"])
	elif leads:
		recommended_party_type = "Lead"
		recommended_party_name = leads[0]["name"]
		match_reason = _("Matched to existing Lead: {0}").format(leads[0]["display_name"])

	return {
		"customers": customers,
		"leads": leads,
		"recommended_party_type": recommended_party_type,
		"recommended_party_name": recommended_party_name,
		"match_reason": match_reason,
	}


def _attach_files_to_document(doctype: str, docname: str, file_urls: list[str]) -> None:
	for file_url in file_urls:
		file_name = frappe.db.get_value("File", {"file_url": file_url}, "name")
		if not file_name:
			continue
		file_doc = frappe.get_doc("File", file_name)
		file_doc.attached_to_doctype = doctype
		file_doc.attached_to_name = docname
		file_doc.save(ignore_permissions=True)


def _build_lead_payload(data: dict[str, Any]) -> dict[str, Any]:
	contact_person = (data.get("contact_person") or data.get("sender_name") or "").strip()
	company_name = (data.get("company_name") or "").strip()
	lead_name = contact_person or company_name or (data.get("contact_email") or data.get("sender_email") or "").strip()

	payload = {
		"doctype": "Lead",
		"lead_name": lead_name or _("Unknown"),
		"company_name": company_name or None,
		"email_id": (data.get("contact_email") or data.get("sender_email") or "").strip() or None,
		"mobile_no": (data.get("mobile_no") or "").strip() or None,
		"phone": (data.get("phone") or "").strip() or None,
		"website": (data.get("website") or "").strip() or None,
	}

	if frappe.db.exists("Lead Source", "Email"):
		payload["source"] = "Email"

	return payload


def _ensure_lead(data: dict[str, Any]) -> str:
	email = _normalize_email(data.get("contact_email") or data.get("sender_email"))
	if email:
		existing_lead = frappe.db.get_value("Lead", {"email_id": email}, "name")
		if existing_lead:
			return existing_lead

	lead = frappe.get_doc(_build_lead_payload(data))
	lead.insert()
	return lead.name


@frappe.whitelist()
def analyze_email_screenshots(file_urls: str) -> dict[str, Any]:
	_require_create_access()

	urls = json.loads(file_urls or "[]")
	if not urls:
		frappe.throw(_("Please upload at least one email screenshot."))

	service = AIService()
	if not service.api_key:
		frappe.throw(_("OpenAI API Key is missing in AI Estimation Settings."))
	if not openai:
		frappe.throw(_("OpenAI library not installed. Run: pip install openai"))

	client = openai.OpenAI(api_key=service.api_key)
	response = client.chat.completions.create(
		model=service.model,
		messages=[
			{"role": "system", "content": EMAIL_IMPORT_PROMPT},
			{"role": "user", "content": _build_user_content(urls, service)},
		],
		response_format={"type": "json_object"},
		temperature=0.1,
		max_tokens=1800,
	)

	extracted = json.loads(response.choices[0].message.content or "{}")
	match_summary = _build_match_summary(extracted)

	return {
		"extracted": extracted,
		"matches": match_summary,
	}


@frappe.whitelist()
def create_opportunity_from_email_import(payload: str) -> dict[str, Any]:
	_require_create_access()

	data = json.loads(payload or "{}")
	file_urls = data.get("file_urls") or []
	if not isinstance(file_urls, list):
		file_urls = []

	party_type = data.get("party_type") or "Lead"
	party_name = (data.get("party_name") or "").strip()

	if party_type == "Customer" and not party_name:
		frappe.throw(_("Please select an existing Customer before creating the Opportunity."))

	if party_type == "Lead" and not party_name:
		if not frappe.has_permission("Lead", "create"):
			frappe.throw(_("You do not have permission to create Leads."), frappe.PermissionError)
		party_name = _ensure_lead(data)

	company = _get_default_company()
	currency = frappe.get_cached_value("Company", company, "default_currency")

	opportunity = frappe.new_doc("Opportunity")
	opportunity.company = company
	opportunity.currency = currency
	opportunity.conversion_rate = 1
	opportunity.transaction_date = getdate(today())
	opportunity.opportunity_from = party_type
	opportunity.party_name = party_name
	opportunity.opportunity_owner = frappe.session.user
	opportunity.contact_email = (data.get("contact_email") or data.get("sender_email") or "").strip()
	opportunity.contact_mobile = (data.get("mobile_no") or "").strip()
	opportunity.phone = (data.get("phone") or "").strip()
	opportunity.website = (data.get("website") or "").strip()
	opportunity.title = (
		(data.get("project_title") or "").strip()
		or (data.get("company_name") or "").strip()
		or (data.get("email_subject") or "").strip()
		or _("Imported from Email")
	)
	opportunity.expected_closing = None
	opportunity.insert()

	_attach_files_to_document("Opportunity", opportunity.name, file_urls)

	comment_parts = [
		_("Imported from email screenshot using Prastar AI."),
	]
	if data.get("email_subject"):
		comment_parts.append(_("Email Subject: {0}").format(data["email_subject"]))
	if data.get("scope_summary"):
		comment_parts.append(_("Scope Summary: {0}").format(data["scope_summary"]))
	if data.get("project_location"):
		comment_parts.append(_("Project Location: {0}").format(data["project_location"]))
	if data.get("notes"):
		comment_parts.append(_("Notes: {0}").format(data["notes"]))
	opportunity.add_comment("Comment", "\n".join(comment_parts))

	return {
		"opportunity_name": opportunity.name,
		"party_type": party_type,
		"party_name": party_name,
	}
