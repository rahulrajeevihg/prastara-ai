from __future__ import annotations

import json
import re
from typing import Any

import frappe
from frappe import _
from frappe.query_builder import DocType
from frappe.query_builder.functions import Count
from frappe.utils import cint, random_string
from prastar_ai.prastar_ai.doctype.ai_estimation.ai_estimation import append_version_snapshot, restore_version_snapshot


DEFAULT_PAGE_SIZE = 12
MAX_PAGE_SIZE = 48

# Map AI-generated UOM aliases → ERPNext UOM names (checked in order; falls back to "Nos")
_UOM_ALIASES: dict[str, str] = {
    "Sqft": "Square Foot",
    "sqft": "Square Foot",
    "Sq Ft": "Square Foot",
    "Sqm": "Square Meter",
    "sqm": "Square Meter",
    "Sq m": "Square Meter",
    "Lm": "Meter",
    "lm": "Meter",
    "Nos": "Nos",
    "nos": "Nos",
    "Lot": "Lot",
    "lot": "Lot",
    "Set": "Set",
    "set": "Set",
    "Day": "Day",
    "day": "Day",
    "Month": "Month",
    "month": "Month",
}


def _resolve_uom(uom_str: str | None) -> str:
    """Return a UOM name that exists in ERPNext, or 'Nos' as fallback."""
    if not uom_str:
        return "Nos"
    candidate = _UOM_ALIASES.get(uom_str, uom_str)
    for name in (candidate, uom_str, "Nos"):
        if frappe.db.exists("UOM", name):
            return name
    return "Nos"


def _coerce_page_size(value: int | str | None) -> int:
	page_size = cint(value) or DEFAULT_PAGE_SIZE
	return min(max(page_size, 1), MAX_PAGE_SIZE)


def _build_quotation_item_description(item) -> str:
	description_parts = [item.description or item.item_name]
	if item.source_reference:
		description_parts.append(f"AI Notes: {item.source_reference}")
	return "\n\n".join(part for part in description_parts if part)


def _validate_estimation_row(row) -> list[str]:
	errors: list[str] = []
	qty = float(row.qty or 0)
	rate = float(row.rate or 0)

	if qty <= 0:
		errors.append(_("Quantity must be greater than 0."))
	if rate < 0:
		errors.append(_("Rate cannot be negative."))

	return errors


def _validate_estimation_for_save(doc) -> None:
	validation_errors: list[str] = []
	for row in doc.items:
		for message in _validate_estimation_row(row):
			validation_errors.append(_("{0}: {1}").format(row.item_name or row.name, message))

	if validation_errors:
		frappe.throw(
			_("Please correct the BOQ before saving:\n{0}").format("\n".join(validation_errors[:10]))
		)


def _validate_estimation_for_quotation(doc) -> None:
	validation_errors: list[str] = []
	for row in doc.items:
		for message in _validate_estimation_row(row):
			validation_errors.append(_("{0}: {1}").format(row.item_name or row.name, message))

	if validation_errors:
		frappe.throw(
			_("Please correct the BOQ before creating the quotation:\n{0}").format("\n".join(validation_errors[:10]))
		)


def _get_default_item_group() -> str:
	for item_group_name in ("Products", "All Item Groups"):
		if frappe.db.exists("Item Group", item_group_name):
			return item_group_name

	item_group = frappe.db.get_value("Item Group", {"is_group": 0}, "name")
	if item_group:
		return item_group

	frappe.throw(_("Please create at least one leaf Item Group before converting estimations to quotations."))


def _get_ai_generated_item_group() -> str:
	ai_group_name = "AI Generated Items"
	if frappe.db.exists("Item Group", ai_group_name):
		return ai_group_name

	parent_item_group = _get_default_item_group()
	parent_is_group = frappe.db.get_value("Item Group", parent_item_group, "is_group")
	if not parent_is_group:
		parent_item_group = frappe.db.get_value("Item Group", parent_item_group, "parent_item_group") or "All Item Groups"

	item_group = frappe.new_doc("Item Group")
	item_group.item_group_name = ai_group_name
	item_group.parent_item_group = parent_item_group
	item_group.is_group = 0
	item_group.insert(ignore_permissions=True)
	return item_group.name


def _create_material_item_for_estimation_row(item) -> str:
	item_code = f"AI-MAT-{random_string(8).upper()}"
	item_doc = frappe.new_doc("Item")
	item_doc.item_code = item_code
	item_doc.item_name = item.item_name or item_code
	item_doc.description = "\n\n".join(filter(None, [
		"AI Generated Material Item",
		_build_quotation_item_description(item),
	]))
	item_doc.item_group = _get_ai_generated_item_group()
	item_doc.stock_uom = _resolve_uom(item.uom)
	item_doc.is_stock_item = 0
	item_doc.is_sales_item = 1
	item_doc.is_purchase_item = 1
	item_doc.include_item_in_manufacturing = 0
	item_doc.disabled = 0
	item_doc.standard_rate = item.rate or 0
	item_doc.insert(ignore_permissions=True)
	return item_doc.name


def _tokenize_service_text(*parts: str | None) -> set[str]:
	stop_words = {
		"and", "the", "for", "with", "from", "into", "including", "supply", "install",
		"installation", "service", "services", "labour", "labor", "work", "works",
		"item", "items", "general", "project",
	}
	tokens: set[str] = set()
	for part in parts:
		if not part:
			continue
		for token in re.findall(r"[a-z0-9]+", part.lower()):
			if len(token) > 2 and token not in stop_words:
				tokens.add(token)
	return tokens


def _score_service_item_match(item, candidate: dict[str, Any], target_tokens: set[str]) -> int:
	score = 0
	candidate_name = (candidate.get("item_name") or "").lower()
	candidate_code = (candidate.get("name") or "").lower()
	candidate_desc = (candidate.get("description") or "").lower()
	item_name = (item.item_name or "").lower()
	item_category = (item.item_category or "").lower()

	if item_name and candidate_name == item_name:
		score += 120
	elif item_name and item_name in candidate_name:
		score += 70

	if item_name and item_name in candidate_code:
		score += 45

	if item_category:
		if item_category in candidate_name:
			score += 20
		if item_category in candidate_desc:
			score += 15

	candidate_tokens = _tokenize_service_text(candidate.get("name"), candidate.get("item_name"), candidate.get("description"))
	overlap = target_tokens & candidate_tokens
	score += len(overlap) * 12

	if any(keyword in candidate_name or keyword in candidate_desc for keyword in ("service", "labour", "labor", "installation")):
		score += 10

	return score


def _get_existing_service_item(item) -> str | None:
	item_code = item.item_code
	if item_code and frappe.db.exists("Item", {"name": item_code, "is_stock_item": 0, "disabled": 0}):
		return item_code

	target_tokens = _tokenize_service_text(item.item_name, item.description, item.item_category, item.source_reference)
	search_terms = list(target_tokens)[:6]

	filters: list[list[Any]] = [["is_stock_item", "=", 0], ["disabled", "=", 0]]
	or_filters: list[list[Any]] = []
	for term in search_terms:
		like_term = f"%{term}%"
		or_filters.extend([
			["Item", "name", "like", like_term],
			["Item", "item_name", "like", like_term],
			["Item", "description", "like", like_term],
		])

	candidates = frappe.get_all(
		"Item",
		fields=["name", "item_name", "description", "modified"],
		filters=filters,
		or_filters=or_filters or None,
		order_by="modified desc",
		limit=40,
	)

	if not candidates:
		candidates = frappe.get_all(
			"Item",
			fields=["name", "item_name", "description", "modified"],
			filters=filters,
			order_by="modified desc",
			limit=20,
		)

	if not candidates:
		return None

	best_candidate = max(
		candidates,
		key=lambda candidate: (_score_service_item_match(item, candidate, target_tokens), candidate.get("modified") or ""),
	)
	best_score = _score_service_item_match(item, best_candidate, target_tokens)

	if best_score <= 0:
		return None

	return best_candidate.get("name")


def _build_search_filters(search: str | None = None) -> list[list[Any]]:
	or_filters: list[list[Any]] = []

	if search:
		search_value = f"%{search.strip()}%"
		or_filters.append(["Opportunity", "name", "like", search_value])
		or_filters.append(["Opportunity", "party_name", "like", search_value])
		or_filters.append(["Opportunity", "customer_name", "like", search_value])
		or_filters.append(["Opportunity", "title", "like", search_value])

	return or_filters


def _get_opportunity_reference_context(opportunity) -> dict[str, Any]:
	files = frappe.get_all(
		"File",
		filters={
			"attached_to_doctype": "Opportunity",
			"attached_to_name": opportunity.name,
			"is_folder": 0,
		},
		fields=["name", "file_name", "file_url", "file_size", "is_private", "creation"],
		order_by="creation asc",
	)

	comments = frappe.get_all(
		"Comment",
		filters={
			"reference_doctype": "Opportunity",
			"reference_name": opportunity.name,
			"comment_type": ["in", ["Comment", "Info"]],
		},
		fields=["name", "content", "comment_by", "creation", "comment_type"],
		order_by="creation desc",
		limit=12,
	)

	note_text = (frappe.utils.strip_html(opportunity.get("notes") or "") or "").strip()
	comment_entries: list[dict[str, Any]] = []
	context_parts: list[str] = []

	if note_text:
		context_parts.append(f"OPPORTUNITY NOTES:\n{note_text}")

	for comment in comments:
		content = (frappe.utils.strip_html(comment.get("content") or "") or "").strip()
		if not content:
			continue
		entry = {
			"name": comment.get("name"),
			"content": content,
			"comment_by": comment.get("comment_by"),
			"creation": comment.get("creation"),
			"comment_type": comment.get("comment_type"),
		}
		comment_entries.append(entry)
		context_parts.append(f"OPPORTUNITY COMMENT ({entry['comment_by'] or 'Unknown'}):\n{content}")

	return {
		"files": files,
		"notes_text": note_text,
		"comments": comment_entries,
		"context_text": "\n\n".join(part for part in context_parts if part),
	}


def _get_status_summary() -> list[dict[str, Any]]:
	opportunity = DocType("Opportunity")
	rows = (
		frappe.qb.from_(opportunity)
		.select(opportunity.status, Count(opportunity.name).as_("count"))
		.groupby(opportunity.status)
		.orderby(opportunity.status)
	).run(as_dict=True)

	return [
		{
			"label": row.status or _("Unspecified"),
			"value": row.status or "",
			"count": row.count,
		}
		for row in rows
	]


def _get_owner_options() -> list[dict[str, str]]:
	owners = frappe.get_all(
		"Opportunity",
		distinct=True,
		pluck="opportunity_owner",
		order_by="opportunity_owner asc",
	)
	user_labels = {}
	if owners:
		user_labels = {
			row.name: row.full_name
			for row in frappe.get_all(
				"User",
				filters={"name": ["in", owners]},
				fields=["name", "full_name"],
			)
		}

	return [
		{
			"value": owner,
			"label": user_labels.get(owner) or owner,
		}
		for owner in owners
		if owner
	]


def _get_stage_options() -> list[dict[str, str]]:
	stages = frappe.get_all(
		"Opportunity",
		distinct=True,
		pluck="sales_stage",
		order_by="sales_stage asc",
	)
	return [
		{
			"value": stage,
			"label": stage,
		}
		for stage in stages
		if stage
	]


def _get_workspace_summary(
	filters: list[list[Any]],
	or_filters: list[list[Any]],
) -> dict[str, int | float]:
	rows = frappe.get_all(
		"Opportunity",
		fields=["status", "count(name) as count", "sum(opportunity_amount) as total_value"],
		filters=filters,
		or_filters=or_filters,
		group_by="status",
		limit_page_length=0,
	)

	total_count = sum((row.count or 0) for row in rows)
	total_value = sum((row.total_value or 0) for row in rows)
	total_open = sum((row.count or 0) for row in rows if row.status != "Lost")
	active_pipeline = sum((row.count or 0) for row in rows if row.status not in {"Lost", "Closed"})

	return {
		"total_count": total_count,
		"total_value": total_value,
		"total_open": total_open,
		"active_pipeline": active_pipeline,
	}


@frappe.whitelist()
def get_opportunity_workspace_data(
	search: str | None = None,
	status: str | None = None,
	owner: str | None = None,
	stage: str | None = None,
	page_length: int | str | None = None,
	start: int | str | None = None,
	sort_by: str | None = None,
	sort_order: str | None = None,
) -> dict[str, Any]:
	if frappe.session.user == "Guest" and not frappe.flags.in_test:
		return {
			"items": [],
			"error": "Authentication required. Please log in to your ERPNext account.",
			"summary": {"total_open": 0, "total_value": 0, "active_pipeline": 0},
		}

	if not frappe.has_permission("Opportunity", "read"):
		frappe.throw(_("You do not have permission to view opportunities."), frappe.PermissionError)

	page_length = _coerce_page_size(page_length)
	start = max(cint(start), 0)

	sort_field = (
		sort_by
		if sort_by in {"modified", "transaction_date", "expected_closing", "opportunity_amount"}
		else "modified"
	)
	sort_direction = "asc" if (sort_order or "").lower() == "asc" else "desc"

	or_filters = _build_search_filters(search=search)
	filters = []
	if status:
		filters.append(["status", "=", status])
	if owner:
		filters.append(["opportunity_owner", "=", owner])
	if stage:
		filters.append(["sales_stage", "=", stage])

	fields = [
		"name", "title", "party_name", "customer_name", "status",
		"opportunity_owner", "sales_stage", "probability", "expected_closing",
		"company", "transaction_date", "opportunity_amount", "currency", "modified",
	]

	items = frappe.get_list(
		"Opportunity",
		fields=fields,
		filters=filters,
		or_filters=or_filters,
		start=start,
		page_length=page_length,
		order_by=f"{sort_field} {sort_direction}",
	)

	if items:
		opportunity_names = [row.name for row in items]
		estimation_rows = frappe.get_all(
			"AI Estimation",
			filters={"opportunity": ["in", opportunity_names]},
			fields=["name", "opportunity", "modified"],
			order_by="modified desc",
		)
		latest_estimations: dict[str, str] = {}
		for row in estimation_rows:
			if row.opportunity not in latest_estimations:
				latest_estimations[row.opportunity] = row.name

		for row in items:
			row["latest_estimation"] = latest_estimations.get(row.name)

	summary = _get_workspace_summary(filters, or_filters)
	total_count = summary["total_count"]

	return {
		"items": items,
		"meta": {
			"start": start,
			"page_length": page_length,
			"has_more": (start + page_length) < total_count,
			"total_count": total_count,
			"sort_by": sort_field,
			"sort_order": sort_direction,
		},
		"filters": {
			"status_options": _get_status_summary(),
			"owner_options": _get_owner_options(),
			"stage_options": _get_stage_options(),
		},
		"summary": {
			"total_open": summary["total_open"],
			"total_value": summary["total_value"],
			"active_pipeline": summary["active_pipeline"],
		},
	}


@frappe.whitelist()
def get_opportunity_details(opportunity_name: str) -> dict[str, Any]:
	if not frappe.has_permission("Opportunity", "read", opportunity_name):
		frappe.throw(_("No permission to view this Opportunity"), frappe.PermissionError)

	opportunity = frappe.get_doc("Opportunity", opportunity_name)
	estimations = frappe.get_all(
		"AI Estimation",
		filters={"opportunity": opportunity_name},
		fields=["name", "status", "quotation", "total_amount", "currency", "creation", "modified", "ai_summary"],
		order_by="creation desc",
	)
	for estimation in estimations:
		estimation["item_count"] = frappe.db.count(
			"AI Estimation Item",
			{
				"parenttype": "AI Estimation",
				"parent": estimation.get("name"),
			},
		)
	existing_quotation = next((row.quotation for row in estimations if row.get("quotation")), None)
	if not existing_quotation:
		existing_quotation = frappe.db.get_value(
			"Quotation",
			{"opportunity": opportunity_name},
			"name",
			order_by="creation desc",
		)

	return {
		"opportunity": opportunity,
		"estimations": estimations,
		"quotation": existing_quotation,
		"templates": get_cost_templates().get("templates", []),
		"references": _get_opportunity_reference_context(opportunity),
		"summary": {
			"customer": opportunity.customer_name or opportunity.party_name,
			"amount": opportunity.opportunity_amount,
			"currency": opportunity.currency,
			"status": opportunity.status,
			"probability": opportunity.probability,
			"expected_closing": opportunity.expected_closing,
		},
	}


@frappe.whitelist()
def update_estimation_items(
	estimation_name: str,
	items: str,
	scope_text: str = None,
	target_margin_pct: float | str | None = None,
) -> dict[str, Any]:
	"""
	Save user-edited qty/rate values back to the AI Estimation child table.
	Called by the frontend before converting to quotation so the DB reflects
	the reviewed values.

	:param estimation_name: Name of the AI Estimation doc
	:param items: JSON array of {name, qty, rate} objects
	:param scope_text: Raw project requirements entered by user
	:returns: Updated total_amount and status
	"""
	if not frappe.has_permission("AI Estimation", "write", estimation_name):
		frappe.throw(_("You do not have write permission on this estimation."), frappe.PermissionError)

	updates = json.loads(items) if isinstance(items, str) else items
	updates_by_name = {u["name"]: u for u in updates if u.get("name")}

	doc = frappe.get_doc("AI Estimation", estimation_name)
	for row in doc.items:
		if row.name in updates_by_name:
			u = updates_by_name[row.name]
			row.qty = u.get("qty", row.qty)
			row.rate = u.get("rate", row.rate)
			row.amount = (row.qty or 0) * (row.rate or 0)
			
	if scope_text is not None:
		doc.scope_text = scope_text
	if target_margin_pct is not None:
		doc.target_margin_pct = float(target_margin_pct or 0)

	_validate_estimation_for_save(doc)
	append_version_snapshot(doc, "Manual Draft Save", summary="Draft quantities/rates updated")
	doc.save()
	return {
		"total_amount": doc.total_amount,
		"status": doc.status,
		"target_margin_pct": doc.target_margin_pct,
	}


@frappe.whitelist()
def restore_estimation_version(estimation_name: str, version_name: str) -> dict[str, Any]:
	if not frappe.has_permission("AI Estimation", "write", estimation_name):
		frappe.throw(_("You do not have write permission on this estimation."), frappe.PermissionError)

	doc = frappe.get_doc("AI Estimation", estimation_name)
	version_row = next((row for row in doc.version_history if row.name == version_name), None)
	if not version_row:
		frappe.throw(_("The selected version snapshot could not be found."))

	restore_version_snapshot(doc, version_row)
	append_version_snapshot(doc, "Version Restore", summary=f"Restored {version_row.version_label}")
	doc.save()
	return {"name": doc.name, "total_amount": doc.total_amount, "status": doc.status}


def _template_code_from_name(template_name: str) -> str:
	slug = re.sub(r"[^a-z0-9]+", "-", (template_name or "").lower()).strip("-")
	return f"TPL-{slug[:30]}-{random_string(4).upper()}"


@frappe.whitelist()
def get_cost_templates() -> dict[str, Any]:
	if not frappe.has_permission("AI Cost Template", "read"):
		return {"templates": []}

	templates = frappe.get_all(
		"AI Cost Template",
		filters={"is_active": 1},
		fields=["name", "template_name", "template_code", "category", "room_zone", "default_margin_pct", "notes", "modified"],
		order_by="modified desc",
	)
	return {"templates": templates}


@frappe.whitelist()
def save_estimation_as_template(estimation_name: str, template_name: str, notes: str | None = None) -> dict[str, Any]:
	if not frappe.has_permission("AI Estimation", "read", estimation_name):
		frappe.throw(_("No permission to access this estimation."), frappe.PermissionError)
	if not frappe.has_permission("AI Cost Template", "create"):
		frappe.throw(_("No permission to create cost templates."), frappe.PermissionError)

	estimation = frappe.get_doc("AI Estimation", estimation_name)
	template = frappe.new_doc("AI Cost Template")
	template.template_name = template_name
	template.template_code = _template_code_from_name(template_name)
	template.default_margin_pct = estimation.target_margin_pct or 0
	template.notes = notes or f"Saved from estimation {estimation_name}"
	template.scope_text_snapshot = estimation.scope_text or ""
	template.category = estimation.items[0].item_category if estimation.items else ""
	template.room_zone = getattr(estimation.items[0], "room_zone", "") if estimation.items else ""
	template.items_json = json.dumps([
		{
			"item_code": row.item_code,
			"item_name": row.item_name,
			"item_category": row.item_category,
			"room_zone": getattr(row, "room_zone", ""),
			"description": row.description,
			"qty": row.qty,
			"uom": row.uom,
			"rate": row.rate,
			"type": row.type,
			"confidence": row.confidence,
			"source_reference": row.source_reference,
			"pricing_detail_json": getattr(row, "pricing_detail_json", ""),
		}
		for row in estimation.items
	], indent=2)
	template.insert()
	return {"name": template.name, "template_name": template.template_name}


@frappe.whitelist()
def apply_cost_template(estimation_name: str, template_name: str, merge_mode: str = "append") -> dict[str, Any]:
	if not frappe.has_permission("AI Estimation", "write", estimation_name):
		frappe.throw(_("No permission to update this estimation."), frappe.PermissionError)

	estimation = frappe.get_doc("AI Estimation", estimation_name)
	template = frappe.get_doc("AI Cost Template", template_name)
	template_items = json.loads(template.items_json or "[]")

	if merge_mode == "replace":
		estimation.set("items", [])

	for item in template_items:
		estimation.append("items", item)

	if template.default_margin_pct:
		estimation.target_margin_pct = template.default_margin_pct

	append_version_snapshot(estimation, "Template Applied", summary=f"Applied template {template.template_name}")
	estimation.save()
	return {"name": estimation.name, "total_amount": estimation.total_amount, "status": estimation.status}


@frappe.whitelist()
def convert_to_quotation(estimation_name: str) -> dict[str, Any]:
	"""
	Create an ERPNext Quotation from an approved AI Estimation.
	Items are split so Materials map to stock/product lines and
	Services map to service item lines.
	"""
	if not frappe.has_permission("AI Estimation", "read", estimation_name):
		frappe.throw(_("No permission to access this estimation."), frappe.PermissionError)

	estimation = frappe.get_doc("AI Estimation", estimation_name)
	opp = frappe.get_doc("Opportunity", estimation.opportunity)
	_validate_estimation_for_quotation(estimation)

	if estimation.status == "Quotation Generated":
		if getattr(estimation, "quotation", None):
			return {"name": estimation.quotation, "existing": True}
		existing_quotation = frappe.db.get_value(
			"Quotation",
			{"opportunity": estimation.opportunity},
			"name",
			order_by="creation desc",
		)
		if existing_quotation:
			return {"name": existing_quotation, "existing": True}
		frappe.throw(_("A quotation has already been created from this estimation."))

	quotation = frappe.new_doc("Quotation")
	quotation.opportunity = estimation.opportunity
	quotation.company = (
		opp.company
		or frappe.defaults.get_user_default("company")
		or frappe.get_all("Company", limit=1)[0].name
	)

	if opp.opportunity_from == "Customer":
		quotation.quotation_to = "Customer"
		quotation.party_name = opp.party_name
	else:
		quotation.quotation_to = "Lead"
		quotation.party_name = opp.party_name

	quotation.transaction_date = frappe.utils.today()
	quotation.currency = estimation.currency or opp.currency or "AED"

	quotation_item_payloads = []

	for item in estimation.items:
		if item.type == "Service":
			item_code = _get_existing_service_item(item)
		else:
			item_code = _create_material_item_for_estimation_row(item)

		if not item_code:
			frappe.log_error(
				title="AI Estimation: Missing service item",
				message=f"Service item '{item.item_name}' could not be matched to an existing service Item.",
			)
			continue

		quotation_item_payloads.append({
			"item_code": item_code,
			"item_name": item.item_name,
			"description": _build_quotation_item_description(item),
			"qty": item.qty or 1,
			"uom": _resolve_uom(item.uom),
			"rate": item.rate or 0,
		})

	for row in quotation_item_payloads:
		quotation.append("items", row)

	if not quotation.items:
		frappe.throw(
			_("No items could be mapped to the Quotation. Please ensure ERPNext has at least one "
			  "Item record, or link items manually to the estimation before converting.")
		)

	if hasattr(quotation, "ignore_pricing_rule"):
		quotation.ignore_pricing_rule = 1

	quotation.set_missing_values()

	for quotation_row, source_row in zip(quotation.items, quotation_item_payloads):
		quotation_row.item_name = source_row["item_name"]
		quotation_row.description = source_row["description"]
		quotation_row.qty = source_row["qty"]
		quotation_row.uom = source_row["uom"]
		quotation_row.rate = source_row["rate"]
		quotation_row.price_list_rate = source_row["rate"]
		quotation_row.discount_percentage = 0
		quotation_row.margin_type = ""
		quotation_row.margin_rate_or_amount = 0

	quotation.calculate_taxes_and_totals()
	quotation.insert()

	# Mark estimation and opportunity
	estimation.status = "Quotation Generated"
	estimation.quotation = quotation.name
	estimation.save()

	if opp.status != "Quotation":
		opp.status = "Quotation"
		opp.save()

	return {"name": quotation.name, "existing": False}
