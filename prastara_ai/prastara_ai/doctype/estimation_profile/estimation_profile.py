from __future__ import annotations
import frappe
from frappe.model.document import Document


class EstimationProfile(Document):
    def validate(self):
        if self.prompt_mode in ("fully_custom", "custom_with_builtin_schema"):
            if not (self.system_prompt or "").strip():
                frappe.throw(
                    frappe._("A System Prompt is required when Prompt Mode is '{0}'.").format(
                        self.prompt_mode
                    )
                )

    def before_save(self):
        # Normalise: strip accidental whitespace from prompt fields
        for field in ("system_prompt", "review_prompt", "takeoff_prompt", "item_detail_prompt"):
            value = getattr(self, field, None)
            if value:
                setattr(self, field, value.strip())
