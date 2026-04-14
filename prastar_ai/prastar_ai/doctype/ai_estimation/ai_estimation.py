import json

import frappe
from frappe.model.document import Document
from frappe.utils import now


class AIEstimation(Document):
	def before_save(self):
		self.total_amount = sum(
			(item.qty or 0) * (item.rate or 0) for item in self.items
		)


def build_item_snapshot(doc):
	return [
		{
			"item_code": row.item_code,
			"item_name": row.item_name,
			"item_category": row.item_category,
			"room_zone": getattr(row, "room_zone", ""),
			"description": row.description,
			"qty": row.qty,
			"uom": row.uom,
			"rate": row.rate,
			"amount": row.amount or ((row.qty or 0) * (row.rate or 0)),
			"type": row.type,
			"confidence": row.confidence,
			"source_reference": row.source_reference,
			"pricing_detail_json": getattr(row, "pricing_detail_json", ""),
		}
		for row in doc.items
	]


def append_version_snapshot(doc, source_action: str, summary: str | None = None) -> None:
	version_number = len(doc.get("version_history") or []) + 1
	snapshot_items = build_item_snapshot(doc)
	doc.append("version_history", {
		"version_label": f"V{version_number}",
		"source_action": source_action,
		"created_by": frappe.session.user,
		"created_at": now(),
		"total_amount": doc.total_amount or sum((row.get("amount") or 0) for row in snapshot_items),
		"item_count": len(snapshot_items),
		"snapshot_summary": summary or "",
		"scope_text_snapshot": doc.scope_text or "",
		"items_snapshot_json": json.dumps(snapshot_items, indent=2),
	})


def restore_version_snapshot(doc, version_row) -> None:
	items = json.loads(version_row.items_snapshot_json or "[]")
	doc.set("items", [])
	for item in items:
		doc.append("items", item)
	doc.scope_text = version_row.scope_text_snapshot or doc.scope_text
