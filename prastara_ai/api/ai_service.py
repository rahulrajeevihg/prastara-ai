from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import unquote

import frappe
from frappe import _
from frappe.utils import now, random_string
from frappe.utils.file_manager import save_file
from pypdf import PdfReader
from prastara_ai.prastara_ai.doctype.ai_estimation.ai_estimation import append_version_snapshot

try:
    import openai
except ImportError:
    openai = None

try:
    import fitz  # pymupdf — PDF → image rendering
except ImportError:
    fitz = None

try:
    import ezdxf
except ImportError:
    ezdxf = None


# ---------------------------------------------------------------------------
# ProfileConfig — the single resolved configuration object
# All AIService methods read from this; nothing reads settings/profile directly.
# ---------------------------------------------------------------------------

@dataclass
class ProfileConfig:
    """Holds the fully resolved configuration for one estimation run.

    Priority: Estimation Profile (per-job) > AI Estimation Settings (global) > dataclass defaults.
    """
    # Source metadata
    profile_name: str = ""
    industry_hint: str = ""

    # AI model
    model_name: str = "gpt-4o"

    # Prompt governance
    prompt_mode: str = "fully_custom"          # fully_custom | custom_with_builtin_schema | strict_builtin
    system_prompt: str = ""
    schema_type: str = "generic_line_items"    # see _SCHEMA_TEMPLATES
    workflow_type: str = "document_based_boq"  # see _WORKFLOW_* methods
    pricing_mode: str = "ai_generated_rates"   # ai_generated_rates | manual_review_only | rate_card_with_ai_fallback

    # Specialized prompts (empty → use built-in generic defaults)
    review_prompt: str = ""
    takeoff_prompt: str = ""
    item_detail_prompt: str = ""

    # Rule toggles (affect both prompt injection and validation)
    require_material_service_split: bool = False
    require_room_zone: bool = False
    require_project_area: bool = False
    minimum_line_item_count: int = 0
    allow_custom_categories: bool = True

    # Validation thresholds
    min_confidence_to_accept: float = 0.5
    flag_zero_rate: bool = True
    require_manual_review_on_missing_fields: bool = True


def _resolve_config(
    settings,
    profile_name: str | None = None,
) -> ProfileConfig:
    """Build a ProfileConfig by merging global settings + optional profile.

    Profile values win over global settings for every non-blank/non-zero field.
    Global settings win over dataclass defaults.
    """
    # --- helpers ---
    def _str(obj, attr, default=""):
        v = getattr(obj, attr, None)
        return (v or "").strip() if v else default

    def _bool(obj, attr, default=False):
        v = getattr(obj, attr, None)
        return bool(v) if v is not None else default

    def _float(obj, attr, default=0.0):
        try:
            return float(getattr(obj, attr) or 0) or default
        except (TypeError, ValueError):
            return default

    def _int(obj, attr, default=0):
        try:
            return int(getattr(obj, attr) or 0)
        except (TypeError, ValueError):
            return default

    # 1. Start from global settings
    cfg = ProfileConfig(
        model_name=_str(settings, "model_name") or "gpt-4o",
        prompt_mode=_str(settings, "prompt_mode") or "fully_custom",
        system_prompt=_str(settings, "default_prompt"),
        schema_type=_str(settings, "schema_type") or "generic_line_items",
        workflow_type=_str(settings, "workflow_type") or "document_based_boq",
        pricing_mode=_str(settings, "pricing_mode") or "ai_generated_rates",
        review_prompt=_str(settings, "review_prompt"),
        takeoff_prompt=_str(settings, "takeoff_prompt"),
        item_detail_prompt=_str(settings, "item_detail_prompt"),
        require_material_service_split=_bool(settings, "require_material_service_split"),
        require_room_zone=_bool(settings, "require_room_zone"),
        require_project_area=_bool(settings, "require_project_area"),
        minimum_line_item_count=_int(settings, "minimum_line_item_count"),
        allow_custom_categories=_bool(settings, "allow_custom_categories", default=True),
        min_confidence_to_accept=_float(settings, "min_confidence_to_accept", default=0.5),
        flag_zero_rate=_bool(settings, "flag_zero_rate", default=True),
        require_manual_review_on_missing_fields=_bool(
            settings, "require_manual_review_on_missing_fields", default=True
        ),
    )

    # 2. Resolve which profile to load
    resolved_profile_name = profile_name
    if not resolved_profile_name:
        resolved_profile_name = _str(settings, "default_profile")

    if resolved_profile_name:
        try:
            prof = frappe.get_doc("Estimation Profile", resolved_profile_name)
        except frappe.DoesNotExistError:
            frappe.log_error(
                title="Estimation Profile not found",
                message=f"Profile '{resolved_profile_name}' does not exist — using global settings.",
            )
            prof = None

        if prof:
            cfg.profile_name = prof.profile_name
            cfg.industry_hint = _str(prof, "industry_hint")

            # Profile wins for every non-blank value
            if _str(prof, "model_name"):
                cfg.model_name = prof.model_name
            if _str(prof, "prompt_mode"):
                cfg.prompt_mode = prof.prompt_mode
            if _str(prof, "system_prompt"):
                cfg.system_prompt = prof.system_prompt
            if _str(prof, "schema_type"):
                cfg.schema_type = prof.schema_type
            if _str(prof, "workflow_type"):
                cfg.workflow_type = prof.workflow_type
            if _str(prof, "pricing_mode"):
                cfg.pricing_mode = prof.pricing_mode
            if _str(prof, "review_prompt"):
                cfg.review_prompt = prof.review_prompt
            if _str(prof, "takeoff_prompt"):
                cfg.takeoff_prompt = prof.takeoff_prompt
            if _str(prof, "item_detail_prompt"):
                cfg.item_detail_prompt = prof.item_detail_prompt

            # Rule toggles: profile's True wins; profile's False does not suppress global True
            if prof.require_material_service_split:
                cfg.require_material_service_split = True
            if prof.require_room_zone:
                cfg.require_room_zone = True
            if prof.require_project_area:
                cfg.require_project_area = True
            if _int(prof, "minimum_line_item_count") > 0:
                cfg.minimum_line_item_count = prof.minimum_line_item_count

            # Thresholds: profile overrides if non-zero
            pct = _float(prof, "min_confidence_to_accept")
            if pct > 0:
                cfg.min_confidence_to_accept = pct
            if prof.flag_zero_rate:
                cfg.flag_zero_rate = True
            if prof.require_manual_review_on_missing_fields:
                cfg.require_manual_review_on_missing_fields = True

    return cfg


# ---------------------------------------------------------------------------
# Schema templates — appended when prompt_mode = custom_with_builtin_schema
# Also used as the sole prompt when prompt_mode = strict_builtin
# ---------------------------------------------------------------------------

_STRICT_BUILTIN_ROLE = (
    "You are a professional estimator. Analyse the supplied scope and/or drawings "
    "and return a structured estimation in the JSON format specified below. "
    "Return ONLY valid JSON — no markdown, no commentary."
)

_SCHEMA_TEMPLATES: dict[str, str] = {
    "generic_line_items": """

OUTPUT SCHEMA — return valid JSON matching this structure exactly:
{
  "project_title": "string",
  "summary": "Brief description of what was estimated",
  "assumptions": ["string"],
  "exclusions": ["string"],
  "items": [
    {
      "item_name": "string",
      "description": "string",
      "qty": 0,
      "uom": "string",
      "unit_rate": 0,
      "amount": 0,
      "category": "string",
      "remarks": "string",
      "confidence": 0.9
    }
  ]
}""",

    "trade_boq": """

OUTPUT SCHEMA — return valid JSON matching this structure exactly:
{
  "project_title": "string",
  "summary": "string",
  "assumptions": ["string"],
  "exclusions": ["string"],
  "items": [
    {
      "item_name": "string",
      "category": "string",
      "trade": "string",
      "room_zone": "string",
      "type": "Material|Service",
      "description": "string",
      "qty": 0,
      "uom": "string",
      "unit_rate": 0,
      "amount": 0,
      "confidence": 0.9,
      "remarks": "string"
    }
  ]
}""",

    "shop_drawing_items": """

OUTPUT SCHEMA — return valid JSON matching this structure exactly:
{
  "project_title": "string",
  "summary": "string",
  "items": [
    {
      "item_name": "string",
      "drawing_reference": "Drawing or sheet number this item was taken from",
      "finish": "Material finish or specification",
      "qty": 0,
      "uom": "string",
      "unit_rate": 0,
      "amount": 0,
      "category": "string",
      "remarks": "string",
      "confidence": 0.9
    }
  ]
}""",

    "cost_breakdown": """

OUTPUT SCHEMA — return valid JSON matching this structure exactly:
{
  "project_title": "string",
  "summary": "string",
  "categories": [
    {
      "category_name": "string",
      "items": [
        {
          "item_name": "string",
          "description": "string",
          "qty": 0,
          "uom": "string",
          "unit_rate": 0,
          "amount": 0,
          "remarks": "string",
          "confidence": 0.9
        }
      ]
    }
  ],
  "totals": {
    "subtotal": 0,
    "notes": "string"
  }
}""",

    "roomwise_boq": """

OUTPUT SCHEMA — return valid JSON matching this structure exactly:
{
  "project_title": "string",
  "summary": "string",
  "assumptions": ["string"],
  "rooms": [
    {
      "room_zone": "string",
      "items": [
        {
          "item_name": "string",
          "description": "string",
          "qty": 0,
          "uom": "string",
          "unit_rate": 0,
          "amount": 0,
          "category": "string",
          "type": "Material|Service",
          "remarks": "string",
          "confidence": 0.9
        }
      ]
    }
  ]
}""",

    "assetwise_estimate": """

OUTPUT SCHEMA — return valid JSON matching this structure exactly:
{
  "project_title": "string",
  "summary": "string",
  "assumptions": ["string"],
  "assets": [
    {
      "asset_name": "string",
      "asset_type": "string",
      "location": "string",
      "components": [
        {
          "item_name": "string",
          "description": "string",
          "qty": 0,
          "uom": "string",
          "unit_rate": 0,
          "amount": 0,
          "remarks": "string",
          "confidence": 0.9
        }
      ],
      "asset_total": 0
    }
  ],
  "totals": {
    "grand_total": 0,
    "notes": "string"
  }
}""",
}

# Fields from schema-specific structures that go into extra_metadata_json
# (standard columns: item_name, category/item_category, room_zone, description, qty, uom, rate/unit_rate, amount, type, confidence, remarks/source_reference)
_EXTRA_METADATA_FIELDS: dict[str, list[str]] = {
    "shop_drawing_items": ["drawing_reference", "finish"],
    "trade_boq": ["trade"],
    "assetwise_estimate": ["asset_name", "asset_type", "location"],
    "cost_breakdown": [],
    "roomwise_boq": [],
    "generic_line_items": [],
}


# ---------------------------------------------------------------------------
# Module-level item status derivation — pure function, no side effects.
# Kept at module level so tests can import and exercise it directly.
# ---------------------------------------------------------------------------

def _derive_item_status(
    cfg: ProfileConfig,
    rate_missing: bool,
    qty_missing: bool,
    confidence: float,
    description: str,
    uom: str,
    item_type: str,
    room_zone: str,
) -> str:
    """Return the item status string based on profile rules and thresholds.

    Check priority:
      1. Schema Error  — a mandatory profile rule is violated
      2. Missing Rate  — pricing data is absent
      3. Missing Quantity — quantity is zero / absent
      4. Needs Review  — low confidence or missing optional fields
      5. Valid
    """
    # 1. Schema errors (hard violations of profile rules)
    if cfg.require_material_service_split and not item_type:
        return "Schema Error"
    if cfg.require_room_zone and not room_zone:
        return "Schema Error"

    # 2. Missing Rate
    if cfg.pricing_mode == "manual_review_only":
        return "Missing Rate"
    if rate_missing and cfg.flag_zero_rate:
        return "Missing Rate"

    # 3. Missing Quantity
    if qty_missing:
        return "Missing Quantity"

    # 4. Needs Review
    if confidence < cfg.min_confidence_to_accept:
        return "Needs Review"
    if cfg.require_manual_review_on_missing_fields and (not description or not uom):
        return "Needs Review"

    return "Valid"


# ---------------------------------------------------------------------------
# Rule-toggle prompt instructions (injected in custom_with_builtin_schema mode)
# ---------------------------------------------------------------------------

def _build_rule_instructions(cfg: ProfileConfig) -> str:
    rules = []
    if cfg.require_material_service_split:
        rules.append(
            "Every item must include a 'type' field set to either 'Material' (physical goods/products) "
            "or 'Service' (labour, installation, professional service)."
        )
    if cfg.require_room_zone:
        rules.append(
            "Every item must include a 'room_zone' field identifying the room, area, or zone it belongs to."
        )
    if cfg.require_project_area:
        rules.append(
            "Include a top-level 'project_area_sqft' field with the total project area in square feet."
        )
    if cfg.minimum_line_item_count > 0:
        rules.append(
            f"The items array must contain at least {cfg.minimum_line_item_count} line items."
        )
    if not cfg.allow_custom_categories:
        rules.append(
            "Use only standard, well-defined category names. Do not invent novel category labels."
        )
    if not rules:
        return ""
    return "\n\nADDITIONAL RULES:\n" + "\n".join(f"- {r}" for r in rules)


# ---------------------------------------------------------------------------
# Default prompts for specialized features — generic, no industry assumptions.
# Settings and profiles override these.
# ---------------------------------------------------------------------------

_DEFAULT_ITEM_DETAIL_PROMPT = """You are a senior estimator preparing an internal cost-explanation sheet.

Return ONLY valid JSON with this exact structure:
{
  "item_name": "string",
  "category": "string",
  "scope_summary": "What this line item covers in plain language",
  "drawing_scope": ["Specific scope cues from drawing/brief"],
  "scope_inclusions": ["Included work / materials / accessories"],
  "scope_exclusions": ["Not included in this line item"],
  "quantity_basis": "How the quantity appears to have been derived",
  "rate_basis": "How the unit rate appears to have been built up",
  "raw_materials": [
    {"name": "string", "specification": "string", "qty": 0, "uom": "string", "unit_rate": 0, "amount": 0, "notes": "string"}
  ],
  "labour_components": [
    {"name": "string", "cost_basis": "string", "amount": 0, "notes": "string"}
  ],
  "other_costs": [
    {"name": "string", "amount": 0, "notes": "string"}
  ],
  "cost_summary": {
    "raw_material_cost": 0, "labour_cost": 0, "other_cost": 0,
    "unit_rate": 0, "quantity": 0, "total_amount": 0
  },
  "assumptions": ["string"],
  "risks": ["string"],
  "confidence_note": "One short note on pricing reliability"
}

Rules:
- Use the supplied row quantity, rate, and total as anchors.
- Do not invent dimensions unless the brief/drawings support them.
- Keep scope_inclusions specific, not generic.
"""

_DEFAULT_COMMERCIAL_REVIEW_PROMPT = """You are a senior commercial manager reviewing an AI-generated estimation before issue.

Return ONLY valid JSON:
{
  "review_score": 0,
  "executive_summary": "string",
  "underpriced_items": [{"item_name": "string", "issue": "string", "severity": "high|medium|low"}],
  "overpriced_items": [{"item_name": "string", "issue": "string", "severity": "high|medium|low"}],
  "missing_scope": [{"title": "string", "reason": "string", "severity": "high|medium|low"}],
  "duplication_risks": [{"title": "string", "reason": "string", "severity": "high|medium|low"}],
  "margin_risks": [{"title": "string", "reason": "string", "severity": "high|medium|low"}],
  "recommended_actions": ["string"],
  "confidence_note": "string"
}
"""

_DEFAULT_DRAWING_TAKEOFF_PROMPT = """You are an estimator extracting quantity takeoff cues from project drawings and briefs.

Return ONLY valid JSON:
{
  "takeoff_summary": "string",
  "zones": [
    {
      "zone_name": "string",
      "scope_detected": ["string"],
      "dimensions_detected": ["string"],
      "quantity_cues": ["string"]
    }
  ],
  "measurement_notes": ["string"],
  "drawing_gaps": ["string"]
}
"""

# Stub prompts — used for strict_builtin mode takeoff pass in drawing_takeoff_then_pricing workflow
_STRICT_TAKEOFF_PROMPT = (
    _STRICT_BUILTIN_ROLE + "\n" + _DEFAULT_DRAWING_TAKEOFF_PROMPT
)

MOCKUP_STYLE_PROMPTS = {
    "photorealistic": "Create a photorealistic presentation mockup with realistic materials, lighting, depth, and camera perspective.",
    "concept": "Create a polished concept-render mockup with clean composition, aspirational staging, and presentation quality.",
    "minimal": "Create a calm minimal mockup with restrained styling, soft natural light, and premium detailing.",
}

SOURCE_DRAWING_EXTENSIONS = (".pdf", ".dwg", ".dxf", ".txt")


# ---------------------------------------------------------------------------
# AIService
# ---------------------------------------------------------------------------

class AIService:
    """Core AI estimation engine.

    All behaviour is driven by a ProfileConfig — no hardcoded industry logic.
    Instantiate with an optional profile_name to override the global default.
    """

    def __init__(self, profile_name: str | None = None):
        self.settings = frappe.get_single("AI Estimation Settings")
        self.api_key = self.settings.get_password("openai_api_key")

        if not self.api_key:
            frappe.throw(_("OpenAI API Key is missing. Configure it in AI Estimation Settings."))

        self.config = _resolve_config(self.settings, profile_name=profile_name)
        self.system_prompt = self._build_system_prompt()
        self.client = openai.OpenAI(api_key=self.api_key) if openai and self.api_key else None

        # Runtime state (set during processing)
        self._used_vision: bool = False
        self._vision_page_count: int = 0
        self._last_raw_response: str = ""
        self._audit_warnings: list[str] = []

    # ------------------------------------------------------------------
    # System prompt construction
    # ------------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        cfg = self.config
        mode = cfg.prompt_mode
        schema_block = _SCHEMA_TEMPLATES.get(cfg.schema_type, _SCHEMA_TEMPLATES["generic_line_items"])
        rule_block = _build_rule_instructions(cfg)

        if mode == "strict_builtin":
            prompt = _STRICT_BUILTIN_ROLE + schema_block + rule_block

        elif mode == "custom_with_builtin_schema":
            base = cfg.system_prompt
            if not base:
                frappe.throw(_(
                    "Prompt Mode is 'custom_with_builtin_schema' but no System Prompt is configured. "
                    "Add a System Prompt to the selected Estimation Profile or AI Estimation Settings."
                ))
            prompt = base + schema_block + rule_block

        else:  # fully_custom
            base = cfg.system_prompt
            if not base:
                frappe.throw(_(
                    "No System Prompt is configured. "
                    "Add a Default Prompt in AI Estimation Settings or configure an Estimation Profile."
                ))
            prompt = base + rule_block

        # OpenAI requires the word "json" somewhere in messages when using json_object response format
        if "json" not in prompt.lower():
            prompt += "\n\nRespond with valid JSON only."

        return prompt

    # ------------------------------------------------------------------
    # Specialized prompt resolution (settings → profile → default)
    # ------------------------------------------------------------------

    def _get_review_prompt(self) -> str:
        return self.config.review_prompt or _DEFAULT_COMMERCIAL_REVIEW_PROMPT

    def _get_takeoff_prompt(self) -> str:
        return self.config.takeoff_prompt or _DEFAULT_DRAWING_TAKEOFF_PROMPT

    def _get_item_detail_prompt(self) -> str:
        return self.config.item_detail_prompt or _DEFAULT_ITEM_DETAIL_PROMPT

    # ------------------------------------------------------------------
    # Item normalisation
    # ------------------------------------------------------------------

    def _normalize_item(self, item: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(item, dict):
            return {}

        cfg = self.config

        # --- type ---
        raw_type = item.get("type") or item.get("item_type") or item.get("kind") or ""
        if str(raw_type).strip().lower() in {"service", "labour", "labor"}:
            item_type = "Service"
        elif str(raw_type).strip().lower() in {"material", "product", "goods"}:
            item_type = "Material"
        else:
            item_type = ""  # blank — only required when rule toggle is on

        # --- rate ---
        unit_rate = item.get("unit_rate") or item.get("rate") or item.get("price")
        try:
            rate_val = float(unit_rate) if unit_rate is not None else 0.0
        except (TypeError, ValueError):
            rate_val = 0.0
        rate_missing = rate_val <= 0

        # --- qty ---
        raw_qty = item.get("qty") if item.get("qty") is not None else item.get("quantity")
        try:
            qty_val = float(raw_qty) if raw_qty is not None else 1.0
        except (TypeError, ValueError):
            qty_val = 1.0
        qty_missing = qty_val <= 0

        # --- confidence ---
        try:
            confidence = float(item.get("confidence", item.get("score", 1.0)) or 1.0)
        except (TypeError, ValueError):
            confidence = 1.0

        # --- other standard fields ---
        item_name = (
            item.get("item_name") or item.get("name") or item.get("title") or ""
        ).strip()
        category = (
            item.get("category") or item.get("item_category") or item.get("trade") or "General"
        ).strip()
        room_zone = (
            item.get("room_zone") or item.get("zone") or item.get("room")
            or item.get("area") or item.get("location") or ""
        ).strip()
        description = (
            item.get("description") or item.get("details") or item.get("scope") or ""
        ).strip()
        uom = (item.get("uom") or item.get("unit") or "Nos").strip()
        remarks = (
            item.get("remarks") or item.get("source_reference") or item.get("notes") or ""
        ).strip()

        # --- derive item_status ---
        status = _derive_item_status(
            cfg=cfg,
            rate_missing=rate_missing,
            qty_missing=qty_missing,
            confidence=confidence,
            description=description,
            uom=uom,
            item_type=item_type,
            room_zone=room_zone,
        )

        # --- schema-specific extra metadata ---
        extra_keys = _EXTRA_METADATA_FIELDS.get(cfg.schema_type, [])
        extra_meta = {k: item.get(k, "") for k in extra_keys if item.get(k)}

        return {
            "category": category,
            "item_name": item_name or "Unnamed Item",
            "room_zone": room_zone,
            "description": description,
            "qty": qty_val,
            "uom": uom,
            "type": item_type,
            "unit_rate": None if rate_missing else rate_val,
            "rate_missing": rate_missing,
            "confidence": confidence,
            "remarks": remarks,
            "item_status": status,
            "extra_metadata": extra_meta,
        }

    # ------------------------------------------------------------------
    # Response normalisation — handles all 6 schema shapes
    # ------------------------------------------------------------------

    def _normalize_estimation_response(self, parsed: Any) -> dict[str, Any]:
        if isinstance(parsed, list):
            parsed = {"items": parsed}
        elif not isinstance(parsed, dict):
            parsed = {"items": []}

        raw_items: list[dict] = []

        # --- roomwise_boq: flatten rooms[].items ---
        rooms = parsed.get("rooms")
        if isinstance(rooms, list) and not parsed.get("items"):
            for room in rooms:
                for room_item in (room.get("items") or []):
                    if isinstance(room_item, dict):
                        room_item.setdefault("room_zone", room.get("room_zone", ""))
                        raw_items.append(room_item)

        # --- cost_breakdown: flatten categories[].items ---
        elif isinstance(parsed.get("categories"), list) and not parsed.get("items"):
            for cat in parsed["categories"]:
                for cat_item in (cat.get("items") or []):
                    if isinstance(cat_item, dict):
                        cat_item.setdefault("category", cat.get("category_name", "General"))
                        raw_items.append(cat_item)

        # --- assetwise_estimate: flatten assets[].components ---
        elif isinstance(parsed.get("assets"), list) and not parsed.get("items"):
            for asset in parsed["assets"]:
                for comp in (asset.get("components") or []):
                    if isinstance(comp, dict):
                        comp.setdefault("asset_name", asset.get("asset_name", ""))
                        comp.setdefault("asset_type", asset.get("asset_type", ""))
                        comp.setdefault("location", asset.get("location", ""))
                        raw_items.append(comp)

        # --- standard items key ---
        elif isinstance(parsed.get("items"), list):
            raw_items = [i for i in parsed["items"] if isinstance(i, dict)]

        else:
            # Last resort: find the first list value whose elements are dicts
            candidate_keys = [
                "boq_items", "line_items", "estimation_items", "boq",
                "bill_of_quantities", "data", "rows",
            ]
            for key in candidate_keys:
                val = parsed.get(key)
                if isinstance(val, list) and val:
                    raw_items = [i for i in val if isinstance(i, dict)]
                    break
            if not raw_items:
                for val in parsed.values():
                    if isinstance(val, list) and val and isinstance(val[0], dict):
                        raw_items = val
                        break

        normalised = [self._normalize_item(i) for i in raw_items if i]  # skip empty dicts
        normalised = [i for i in normalised if i.get("item_name")]

        parsed["items"] = normalised
        return parsed

    # ------------------------------------------------------------------
    # Post-generation audit warnings (schema-level checks)
    # ------------------------------------------------------------------

    def _run_schema_audit(self, result: dict[str, Any]) -> list[str]:
        cfg = self.config
        warnings: list[str] = []
        items = result.get("items", [])

        item_count = len(items)
        if cfg.minimum_line_item_count > 0 and item_count < cfg.minimum_line_item_count:
            warnings.append(
                f"Item count ({item_count}) is below the minimum required "
                f"({cfg.minimum_line_item_count}) for this profile."
            )

        if cfg.require_project_area:
            area = (
                result.get("project_area_sqft")
                or result.get("project_area")
                or result.get("area_sqft")
                or 0
            )
            try:
                area = float(area or 0)
            except (TypeError, ValueError):
                area = 0.0
            if area <= 0:
                warnings.append(
                    "Profile requires a project area but none was returned by the AI."
                )

        schema_errors = [i for i in items if i.get("item_status") == "Schema Error"]
        if schema_errors:
            warnings.append(
                f"{len(schema_errors)} item(s) failed profile rule checks (Schema Error)."
            )

        missing_rate = [i for i in items if i.get("item_status") == "Missing Rate"]
        if missing_rate:
            warnings.append(f"{len(missing_rate)} item(s) have no unit rate (Missing Rate).")

        return warnings

    # ------------------------------------------------------------------
    # Audit log
    # ------------------------------------------------------------------

    def build_generation_audit(
        self,
        text: str | None = None,
        file_urls: list[str] | None = None,
        result: dict[str, Any] | None = None,
    ) -> str:
        cfg = self.config
        items = (result or {}).get("items", [])
        status_counts: dict[str, int] = {}
        for item in items:
            s = item.get("item_status", "Valid")
            status_counts[s] = status_counts.get(s, 0) + 1

        source_files = [
            {
                "file_url": url,
                "file_name": os.path.basename(url),
                "file_type": os.path.splitext(url)[1].lower().lstrip("."),
            }
            for url in (file_urls or [])
        ]

        warnings = self._run_schema_audit(result or {})
        warnings += self._audit_warnings  # any warnings accumulated during processing

        audit_payload = {
            "generated_at": now(),
            "model": cfg.model_name,
            "profile_name": cfg.profile_name or "(global settings)",
            "industry_hint": cfg.industry_hint,
            "prompt_mode": cfg.prompt_mode,
            "schema_type": cfg.schema_type,
            "workflow_type": cfg.workflow_type,
            "pricing_mode": cfg.pricing_mode,
            "rule_toggles": {
                "require_material_service_split": cfg.require_material_service_split,
                "require_room_zone": cfg.require_room_zone,
                "require_project_area": cfg.require_project_area,
                "minimum_line_item_count": cfg.minimum_line_item_count,
            },
            "thresholds": {
                "min_confidence_to_accept": cfg.min_confidence_to_accept,
                "flag_zero_rate": cfg.flag_zero_rate,
            },
            "prompt_length": len(self.system_prompt or ""),
            "prompt_preview": (self.system_prompt or "")[:1200],
            "input_scope_length": len((text or "").strip()),
            "source_file_count": len(source_files),
            "source_files": source_files,
            "used_vision": self._used_vision,
            "vision_page_count": self._vision_page_count,
            "result_item_count": len(items),
            "item_status_counts": status_counts,
            "validation_warnings": warnings,
            "ai_response_preview": self._last_raw_response[:2000],
        }
        return json.dumps(audit_payload, indent=2)

    # ------------------------------------------------------------------
    # File handling helpers
    # ------------------------------------------------------------------

    _IMAGE_MIME_TYPES = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }

    def _collect_file_inputs(
        self, file_urls: list[str] | None
    ) -> tuple[list[str], list[dict]]:
        """Return (text_parts, vision_images) from a list of file URLs."""
        text_parts: list[str] = []
        vision_images: list[dict] = []

        for url in (file_urls or []):
            file_path = resolve_file_path(url)
            ext = os.path.splitext(file_path)[1].lower()
            fname = os.path.basename(url)

            if ext == ".pdf":
                imgs = self._pdf_to_base64_images(file_path)
                if imgs:
                    vision_images.append({
                        "file_name": fname, "images": imgs, "mime_type": "image/png"
                    })
                extracted = self._extract_from_pdf(file_path)
                if extracted.strip():
                    text_parts.append(
                        f"EXTRACTED TEXT FROM PDF ({fname}):\n{extracted[:6000]}"
                    )
                if not imgs and not extracted.strip():
                    text_parts.append(
                        f"[PDF {fname} could not be processed — no text and no renderable pages]"
                    )

            elif ext in self._IMAGE_MIME_TYPES:
                try:
                    with open(file_path, "rb") as img_f:
                        b64 = base64.b64encode(img_f.read()).decode("utf-8")
                    vision_images.append({
                        "file_name": fname,
                        "images": [b64],
                        "mime_type": self._IMAGE_MIME_TYPES[ext],
                    })
                except Exception as e:
                    frappe.log_error(f"Image read error ({fname}): {e}")
                    text_parts.append(f"[Could not read image file: {fname}]")

            elif ext in [".dwg", ".dxf"]:
                text_parts.append(
                    f"EXTRACTED CONTENT FROM DWG/DXF ({fname}):\n{self._extract_from_dwg(file_path)}"
                )

            elif ext in [".txt", ".csv"]:
                try:
                    with open(file_path, encoding="utf-8", errors="ignore") as f:
                        text_parts.append(
                            f"EXTRACTED CONTENT FROM FILE ({fname}):\n{f.read()[:8000]}"
                        )
                except Exception:
                    text_parts.append(f"[Could not read text file: {fname}]")

            else:
                text_parts.append(f"[Unsupported file type: {ext} — {fname}]")

        return text_parts, vision_images

    def _collect_file_inputs_vision_first(
        self, file_urls: list[str] | None
    ) -> tuple[list[str], list[dict]]:
        """Vision-first variant: renders PDFs as images only, skips text extraction."""
        text_parts: list[str] = []
        vision_images: list[dict] = []

        for url in (file_urls or []):
            file_path = resolve_file_path(url)
            ext = os.path.splitext(file_path)[1].lower()
            fname = os.path.basename(url)

            if ext == ".pdf":
                imgs = self._pdf_to_base64_images(file_path)
                if imgs:
                    vision_images.append({
                        "file_name": fname, "images": imgs, "mime_type": "image/png"
                    })
                else:
                    # Fallback to text if vision not possible
                    extracted = self._extract_from_pdf(file_path)
                    if extracted.strip():
                        text_parts.append(f"TEXT FROM PDF ({fname}):\n{extracted[:6000]}")
                    else:
                        text_parts.append(f"[PDF {fname} could not be rendered or extracted]")

            elif ext in self._IMAGE_MIME_TYPES:
                try:
                    with open(file_path, "rb") as img_f:
                        b64 = base64.b64encode(img_f.read()).decode("utf-8")
                    vision_images.append({
                        "file_name": fname,
                        "images": [b64],
                        "mime_type": self._IMAGE_MIME_TYPES[ext],
                    })
                except Exception as e:
                    frappe.log_error(f"Image read error ({fname}): {e}")

            elif ext in [".dwg", ".dxf"]:
                text_parts.append(
                    f"DWG/DXF ({fname}):\n{self._extract_from_dwg(file_path)}"
                )

            elif ext in [".txt", ".csv"]:
                try:
                    with open(file_path, encoding="utf-8", errors="ignore") as f:
                        text_parts.append(f"FILE ({fname}):\n{f.read()[:8000]}")
                except Exception:
                    pass

            else:
                text_parts.append(f"[Unsupported: {ext} — {fname}]")

        return text_parts, vision_images

    # ------------------------------------------------------------------
    # Four workflow routes
    # ------------------------------------------------------------------

    def process_input(
        self, text: str | None = None, file_urls: list[str] | None = None
    ) -> dict[str, Any]:
        """Entry point — routes to the correct workflow based on ProfileConfig."""
        wf = self.config.workflow_type

        if wf == "simple_text_estimation":
            return self._workflow_simple_text(text)

        elif wf == "vision_first":
            return self._workflow_vision_first(text, file_urls)

        elif wf == "drawing_takeoff_then_pricing":
            return self._workflow_takeoff_then_pricing(text, file_urls)

        else:  # document_based_boq (default)
            return self._workflow_document_boq(text, file_urls)

    def _workflow_simple_text(self, text: str | None) -> dict[str, Any]:
        """Simple text-only workflow — no file processing."""
        if not (text or "").strip():
            frappe.throw(_("simple_text_estimation workflow requires a scope description."))
        self._used_vision = False
        self._vision_page_count = 0
        self._audit_warnings.append("Workflow: simple_text_estimation — files ignored.")
        return self.get_ai_estimation(
            f"SCOPE DESCRIPTION:\n{text}",
            vision_images=None,
        )

    def _workflow_document_boq(
        self, text: str | None, file_urls: list[str] | None
    ) -> dict[str, Any]:
        """Standard workflow: text extraction + vision from every file."""
        text_parts: list[str] = []
        if text:
            text_parts.append(f"CLIENT BRIEF / SCOPE DESCRIPTION:\n{text}")

        file_text_parts, vision_images = self._collect_file_inputs(file_urls)
        text_parts.extend(file_text_parts)

        if not text_parts and not vision_images:
            frappe.throw(_("Please provide a scope description or upload a file."))

        return self.get_ai_estimation(
            "\n\n---\n\n".join(text_parts),
            vision_images=vision_images,
        )

    def _workflow_vision_first(
        self, text: str | None, file_urls: list[str] | None
    ) -> dict[str, Any]:
        """Vision-first workflow: renders all PDFs as images, skips text extraction."""
        text_parts: list[str] = []
        if text:
            text_parts.append(f"CLIENT BRIEF / SCOPE DESCRIPTION:\n{text}")

        file_text_parts, vision_images = self._collect_file_inputs_vision_first(file_urls)
        text_parts.extend(file_text_parts)

        if not text_parts and not vision_images:
            frappe.throw(_("Please provide a scope description or upload a file."))

        return self.get_ai_estimation(
            "\n\n---\n\n".join(text_parts),
            vision_images=vision_images,
        )

    def _workflow_takeoff_then_pricing(
        self, text: str | None, file_urls: list[str] | None
    ) -> dict[str, Any]:
        """Two-pass workflow: takeoff extraction → pricing estimation.

        Pass 1: Run files through the takeoff prompt to get structured
                zone/quantity data.
        Pass 2: Feed the original brief + takeoff results into the main
                system prompt to produce the priced estimation.
        """
        if not file_urls:
            self._audit_warnings.append(
                "drawing_takeoff_then_pricing workflow: no files provided — "
                "falling back to single-pass text estimation."
            )
            return self._workflow_simple_text(text)

        # --- Pass 1: takeoff extraction ---
        file_text_parts, vision_images = self._collect_file_inputs(file_urls)
        text_parts_pass1: list[str] = []
        if text:
            text_parts_pass1.append(f"PROJECT BRIEF:\n{text}")
        text_parts_pass1.extend(file_text_parts)

        takeoff_prompt = self._get_takeoff_prompt()

        # Ensure takeoff prompt has "json" for response_format requirement
        if "json" not in takeoff_prompt.lower():
            takeoff_prompt += "\n\nRespond with valid JSON only."

        if not self.client:
            frappe.throw(_("OpenAI client is not initialised. Check the API key."))

        try:
            resp1 = self.client.chat.completions.create(
                model=self.config.model_name,
                messages=[
                    {"role": "system", "content": takeoff_prompt},
                    {"role": "user", "content": self._build_user_content(
                        "\n\n---\n\n".join(text_parts_pass1), vision_images
                    )},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=4000,
            )
            takeoff_json = json.loads(resp1.choices[0].message.content or "{}")
            self._audit_warnings.append(
                "Workflow: drawing_takeoff_then_pricing — takeoff pass completed "
                f"({len(takeoff_json.get('zones', takeoff_json.get('rooms', [])))} zones extracted)."
            )
        except Exception as e:
            frappe.log_error(title="Takeoff Pass Error", message=str(e))
            self._audit_warnings.append(
                f"Takeoff pass failed ({e}) — falling back to single-pass document_based_boq."
            )
            return self._workflow_document_boq(text, file_urls)

        # --- Pass 2: pricing estimation ---
        takeoff_context = (
            "DRAWING TAKEOFF RESULTS (use these quantities and zones as anchors):\n"
            + json.dumps(takeoff_json, indent=2)[:6000]
        )
        brief = f"CLIENT BRIEF:\n{text}" if text else ""
        combined = "\n\n---\n\n".join(p for p in [brief, takeoff_context] if p)

        return self.get_ai_estimation(combined, vision_images=None)

    # ------------------------------------------------------------------
    # Core AI call
    # ------------------------------------------------------------------

    @staticmethod
    def _build_user_content(text: str, vision_images: list[dict]) -> list | str:
        if not vision_images:
            return text
        content: list = []
        if text.strip():
            content.append({"type": "text", "text": text})
        for entry in vision_images:
            fname = entry["file_name"]
            mime_type = entry.get("mime_type", "image/png")
            content.append({
                "type": "text",
                "text": f"File: {fname} — {len(entry['images'])} page(s):",
            })
            for b64 in entry["images"]:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{b64}", "detail": "high"},
                })
        return content

    def get_ai_estimation(
        self, content: str, vision_images: list[dict] | None = None
    ) -> dict[str, Any]:
        if not openai:
            frappe.throw(_("OpenAI library not installed. Run: pip install openai"))
        if not self.client:
            frappe.throw(_("OpenAI client not initialised. Check the API key."))

        self._used_vision = bool(vision_images)
        self._vision_page_count = sum(len(v["images"]) for v in (vision_images or []))
        user_content = self._build_user_content(content, vision_images or [])

        try:
            response = self.client.chat.completions.create(
                model=self.config.model_name,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": user_content},
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
                max_tokens=16000,
            )

            choice = response.choices[0]
            raw_content = choice.message.content

            if not raw_content:
                finish_reason = getattr(choice, "finish_reason", "unknown")
                frappe.log_error(
                    title=_("OpenAI Empty Response"),
                    message=(
                        f"finish_reason={finish_reason}. The model returned no content. "
                        "Try reducing input size or number of uploaded pages."
                    ),
                )
                frappe.throw(_(
                    "The AI returned an empty response (finish_reason: {0}). "
                    "Try a shorter scope or fewer pages."
                ).format(finish_reason))

            if choice.finish_reason == "length":
                self._audit_warnings.append(
                    "AI response was truncated at max_tokens — the estimation may be incomplete."
                )
                frappe.log_error(
                    title=_("OpenAI Response Truncated"),
                    message="Response hit max_tokens. The BOQ may be incomplete.",
                )

            try:
                parsed_json = json.loads(raw_content)
            except json.JSONDecodeError as je:
                frappe.log_error(
                    title=_("OpenAI JSON Parse Error"),
                    message=(
                        f"Could not parse AI response as JSON: {je}\n\n"
                        f"Raw content (first 1000 chars):\n{raw_content[:1000]}"
                    ),
                )
                frappe.throw(_(
                    "The AI response could not be parsed as JSON. "
                    "Try fewer pages or a shorter scope."
                ))

            parsed = self._normalize_estimation_response(parsed_json)
            self._last_raw_response = json.dumps(parsed)
            return parsed

        except frappe.exceptions.ValidationError:
            raise
        except Exception as e:
            frappe.log_error(title=_("OpenAI API Error")[:140], message=str(e))
            frappe.throw(_("Failed to process with AI: {0}").format(str(e)))

    # ------------------------------------------------------------------
    # Utility: content extraction
    # ------------------------------------------------------------------

    def extract_content_from_file(self, file_url: str) -> str:
        file_path = resolve_file_path(file_url)
        extension = os.path.splitext(file_path)[1].lower()
        if extension == ".pdf":
            return self._extract_from_pdf(file_path)
        elif extension in [".dwg", ".dxf"]:
            return self._extract_from_dwg(file_path)
        elif extension in [".txt", ".csv"]:
            try:
                with open(file_path, encoding="utf-8", errors="ignore") as f:
                    return f.read()[:8000]
            except Exception:
                return "[Could not read text file]"
        elif extension in self._IMAGE_MIME_TYPES:
            return f"[Image file — processed via vision: {os.path.basename(file_url)}]"
        else:
            return f"[Unsupported file type: {extension}]"

    def _extract_from_pdf(self, path: str) -> str:
        try:
            reader = PdfReader(path)
            pages_text = [page.extract_text() for page in reader.pages if page.extract_text()]
            return "\n".join(pages_text) or ""
        except Exception as e:
            frappe.log_error(f"PDF Extraction Error: {str(e)}")
            return ""

    def _pdf_to_base64_images(
        self, path: str, max_pages: int = 20, dpi: int = 200
    ) -> list[str]:
        if not fitz:
            return []
        images = []
        try:
            doc = fitz.open(path)
            zoom = dpi / 72
            mat = fitz.Matrix(zoom, zoom)
            for page_num in range(min(len(doc), max_pages)):
                page = doc[page_num]
                pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
                images.append(base64.b64encode(pix.tobytes("png")).decode("utf-8"))
            doc.close()
        except Exception as e:
            frappe.log_error(f"PDF→Image Render Error: {str(e)}")
        return images

    def _extract_from_dwg(self, path: str) -> str:
        if not ezdxf:
            return "[ezdxf not installed — DWG/DXF files cannot be parsed]"
        try:
            doc = ezdxf.readfile(path)
            msp = doc.modelspace()
            layers = [layer.dxf.name for layer in doc.layers]
            entity_count = len(list(msp))
            texts = [
                e.dxf.text
                for e in msp
                if e.dxftype() in ("TEXT", "MTEXT") and hasattr(e.dxf, "text")
            ][:50]
            return (
                f"File Analysis:\n"
                f"Layers ({len(layers)}): {', '.join(layers[:30])}\n"
                f"Total Entities: {entity_count}\n"
                f"Text Annotations: {'; '.join(texts)}"
            )
        except Exception as e:
            frappe.log_error(f"DWG Extraction Error: {str(e)}")
            return f"[Error extracting DWG: {str(e)}]"

    # ------------------------------------------------------------------
    # Mockup image generation
    # ------------------------------------------------------------------

    def generate_mockup_images(
        self,
        estimation_name: str,
        scope_text: str | None = None,
        file_urls: list[str] | None = None,
        style: str = "photorealistic",
        additional_prompt: str | None = None,
        count: int = 2,
    ) -> list[dict[str, str]]:
        if not self.client:
            frappe.throw(_("OpenAI client not initialised. Check the API key."))

        estimation = frappe.get_doc("AI Estimation", estimation_name)
        count = min(max(int(count or 1), 1), 4)

        industry = self.config.industry_hint or "general"

        prompt_sections = [
            "Use case: ui-mockup",
            f"Industry/context: {industry}",
            "Asset type: project concept presentation mockup",
            "Primary request: Generate a visual concept mockup based on the provided project scope and references.",
            f"Style/medium: {MOCKUP_STYLE_PROMPTS.get(style, MOCKUP_STYLE_PROMPTS['photorealistic'])}",
            "Composition/framing: client-presentation ready, coherent spatial planning",
            "Constraints: preserve the core intent from the supplied scope and references, no watermark, no text overlay",
        ]

        if scope_text or estimation.scope_text:
            prompt_sections.append(f"Project brief: {scope_text or estimation.scope_text}")
        if estimation.ai_summary:
            prompt_sections.append(f"AI scope summary: {estimation.ai_summary}")
        if estimation.assumptions:
            prompt_sections.append(f"Assumptions: {estimation.assumptions}")
        if estimation.project_area:
            prompt_sections.append(f"Approximate project area: {estimation.project_area} sqft")
        if estimation.items:
            item_summary = "; ".join(
                f"{row.item_category}: {row.item_name} ({row.description or 'no description'})"
                for row in estimation.items[:16]
            )
            prompt_sections.append(f"Key items: {item_summary}")
        if file_urls:
            for file_url in file_urls:
                extracted = self.extract_content_from_file(file_url)
                prompt_sections.append(
                    f"Reference from {os.path.basename(file_url)}: {extracted[:6000]}"
                )
        if additional_prompt:
            prompt_sections.append(f"Additional direction: {additional_prompt}")

        prompt = "\n".join(prompt_sections)

        try:
            response = self.client.images.generate(
                model="gpt-image-1",
                prompt=prompt,
                size="1536x1024",
                quality="medium",
                n=count,
            )
            images = []
            for index, image in enumerate(response.data, start=1):
                if not getattr(image, "b64_json", None):
                    continue
                file_doc = save_file(
                    f"mockup-{estimation_name}-{random_string(6).lower()}-{index}.png",
                    image.b64_json,
                    "AI Estimation",
                    estimation_name,
                    folder="Home/Attachments",
                    decode=True,
                    is_private=0,
                )
                images.append({
                    "name": file_doc.name,
                    "file_name": file_doc.file_name,
                    "file_url": file_doc.file_url,
                })
            if not images:
                frappe.throw(_("No mockup images were returned by the image model."))
            return images
        except Exception as e:
            frappe.log_error(title=_("OpenAI Image Generation Error")[:140], message=str(e))
            frappe.throw(_("Failed to generate mockups: {0}").format(str(e)))

    # ------------------------------------------------------------------
    # Item pricing detail
    # ------------------------------------------------------------------

    def generate_item_pricing_detail(
        self,
        estimation,
        item_row,
        file_urls: list[str] | None = None,
    ) -> dict[str, Any]:
        if not self.client:
            frappe.throw(_("OpenAI client not initialised. Check the API key."))

        file_context_blocks = []
        for file_url in file_urls or []:
            try:
                extracted = self.extract_content_from_file(file_url)
            except Exception:
                extracted = "[Could not extract file contents]"
            file_context_blocks.append(
                f"FILE: {os.path.basename(file_url)}\n{(extracted or '')[:4000]}"
            )

        peer_items = [
            f"- {row.item_category or 'General'} | {row.item_name} | "
            f"qty={row.qty or 0} {row.uom or ''} | rate={row.rate or 0} | type={row.type or ''}"
            for row in estimation.items[:20]
            if row.name != item_row.name
        ]

        target_amount = (item_row.qty or 0) * (item_row.rate or 0)

        user_sections = [
            f"Opportunity: {estimation.opportunity}",
            f"Customer: {estimation.customer or ''}",
            f"Scope text: {estimation.scope_text or ''}",
            f"AI scope summary: {estimation.ai_summary or ''}",
            f"Project area: {estimation.project_area or 0}",
            f"Assumptions: {estimation.assumptions or ''}",
            f"Exclusions: {estimation.exclusions or ''}",
            "TARGET ITEM:",
            json.dumps({
                "name": item_row.item_name,
                "category": item_row.item_category,
                "description": item_row.description,
                "qty": item_row.qty,
                "uom": item_row.uom,
                "rate": item_row.rate,
                "amount": item_row.amount or target_amount,
                "type": item_row.type,
                "confidence": item_row.confidence,
                "source_reference": item_row.source_reference,
            }, indent=2),
            "RELATED ITEMS:",
            "\n".join(peer_items) or "None",
            "FILE CONTEXT:",
            "\n\n".join(file_context_blocks) or "No files attached.",
        ]

        try:
            response = self.client.chat.completions.create(
                model=self.config.model_name,
                messages=[
                    {"role": "system", "content": self._get_item_detail_prompt()},
                    {"role": "user", "content": "\n\n".join(user_sections)},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            frappe.log_error(title=_("OpenAI Item Detail Error")[:140], message=str(e))
            frappe.throw(_("Failed to explain item pricing: {0}").format(str(e)))

    # ------------------------------------------------------------------
    # Commercial review
    # ------------------------------------------------------------------

    def generate_commercial_review(
        self, estimation, file_urls: list[str] | None = None
    ) -> dict[str, Any]:
        if not self.client:
            frappe.throw(_("OpenAI client not initialised. Check the API key."))

        file_context = []
        for file_url in file_urls or []:
            try:
                file_context.append(
                    f"{os.path.basename(file_url)}:\n"
                    f"{self.extract_content_from_file(file_url)[:2500]}"
                )
            except Exception:
                continue

        items_payload = [
            {
                "room_zone": getattr(row, "room_zone", "") or "",
                "category": row.item_category,
                "item_name": row.item_name,
                "description": row.description,
                "qty": row.qty,
                "uom": row.uom,
                "rate": row.rate,
                "amount": row.amount or ((row.qty or 0) * (row.rate or 0)),
                "type": row.type,
                "item_status": getattr(row, "item_status", ""),
            }
            for row in estimation.items
        ]

        user_prompt = "\n\n".join([
            f"Scope text: {estimation.scope_text or ''}",
            f"AI summary: {estimation.ai_summary or ''}",
            f"Assumptions: {estimation.assumptions or ''}",
            f"Exclusions: {estimation.exclusions or ''}",
            f"Target margin %: {getattr(estimation, 'target_margin_pct', 0) or 0}",
            f"Items: {json.dumps(items_payload, indent=2)}",
            "File context:",
            "\n\n".join(file_context) or "None",
        ])

        try:
            response = self.client.chat.completions.create(
                model=self.config.model_name,
                messages=[
                    {"role": "system", "content": self._get_review_prompt()},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=2500,
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            frappe.log_error(title=_("OpenAI Review Error")[:140], message=str(e))
            frappe.throw(_("Failed to generate commercial review: {0}").format(str(e)))

    # ------------------------------------------------------------------
    # Drawing takeoff
    # ------------------------------------------------------------------

    def generate_drawing_takeoff(
        self, estimation, file_urls: list[str] | None = None
    ) -> dict[str, Any]:
        if not self.client:
            frappe.throw(_("OpenAI client not initialised. Check the API key."))

        file_context = []
        for file_url in file_urls or []:
            try:
                file_context.append(
                    f"{os.path.basename(file_url)}:\n"
                    f"{self.extract_content_from_file(file_url)[:3500]}"
                )
            except Exception:
                continue

        user_prompt = "\n\n".join([
            f"Scope text: {estimation.scope_text or ''}",
            f"AI summary: {estimation.ai_summary or ''}",
            "Current items:",
            json.dumps([
                {
                    "room_zone": getattr(row, "room_zone", ""),
                    "item_name": row.item_name,
                    "description": row.description,
                }
                for row in estimation.items
            ], indent=2),
            "File context:",
            "\n\n".join(file_context) or "None",
        ])

        try:
            response = self.client.chat.completions.create(
                model=self.config.model_name,
                messages=[
                    {"role": "system", "content": self._get_takeoff_prompt()},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=2500,
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            frappe.log_error(title=_("OpenAI Takeoff Error")[:140], message=str(e))
            frappe.throw(_("Failed to generate drawing takeoff: {0}").format(str(e)))


# ---------------------------------------------------------------------------
# Module-level utilities
# ---------------------------------------------------------------------------

def resolve_file_path(file_url: str) -> str:
    """Resolve a Frappe file URL or site-relative path to a local filesystem path."""
    if not file_url:
        frappe.throw(_("Missing file URL."))

    normalized_url = unquote(str(file_url).strip())
    if os.path.isabs(normalized_url) and os.path.exists(normalized_url):
        return normalized_url

    if normalized_url.startswith(("http://", "https://")):
        frappe.throw(
            _("Remote file URLs are not supported: {0}").format(file_url)
        )

    file_doc = frappe.db.get_value(
        "File", {"file_url": normalized_url}, ["file_url", "is_private"], as_dict=True
    )
    if not file_doc and "/files/" in normalized_url:
        suffix = normalized_url[normalized_url.index("/files/"):]
        file_doc = frappe.db.get_value(
            "File", {"file_url": suffix}, ["file_url", "is_private"], as_dict=True
        )
    if not file_doc and "/private/files/" in normalized_url:
        suffix = normalized_url[normalized_url.index("/private/files/"):]
        file_doc = frappe.db.get_value(
            "File", {"file_url": suffix}, ["file_url", "is_private"], as_dict=True
        )

    canonical_url = (file_doc.file_url if file_doc else normalized_url).strip()

    if "/private/files/" in canonical_url:
        filename = canonical_url.rsplit("/private/files/", 1)[-1].lstrip("/")
        file_path = frappe.get_site_path("private", "files", filename)
    elif "/files/" in canonical_url:
        filename = canonical_url.rsplit("/files/", 1)[-1].lstrip("/")
        file_path = frappe.get_site_path("public", "files", filename)
    else:
        trimmed = canonical_url.lstrip("./")
        if trimmed.startswith("private/files/"):
            file_path = frappe.get_site_path(trimmed)
        elif trimmed.startswith("files/"):
            file_path = frappe.get_site_path("public", trimmed)
        else:
            file_path = frappe.get_site_path(trimmed)

    if not os.path.exists(file_path):
        frappe.throw(
            _("File does not exist on disk: {0}").format(file_url), FileNotFoundError
        )
    return file_path


def _get_mockup_images(estimation_name: str) -> list[dict[str, str]]:
    return frappe.get_all(
        "File",
        filters={
            "attached_to_doctype": "AI Estimation",
            "attached_to_name": estimation_name,
            "file_name": ["like", "mockup-%"],
        },
        fields=["name", "file_name", "file_url"],
        order_by="creation desc",
    )


def _get_estimation_source_files(estimation_name: str) -> list[dict]:
    files = frappe.get_all(
        "File",
        filters={
            "attached_to_doctype": "AI Estimation",
            "attached_to_name": estimation_name,
        },
        fields=["name", "file_name", "file_url", "file_size", "is_private"],
        order_by="creation asc",
    )
    return [
        f for f in files
        if (f.get("file_name") or "").lower().endswith(SOURCE_DRAWING_EXTENSIONS)
    ]


def _attach_files_to_estimation(
    estimation_name: str, file_urls: list[str] | None = None
) -> None:
    if not estimation_name or not file_urls:
        return
    for file_url in file_urls:
        if not file_url:
            continue
        file_name = frappe.db.get_value("File", {"file_url": file_url}, "name")
        if not file_name:
            continue
        frappe.db.set_value(
            "File",
            file_name,
            {"attached_to_doctype": "AI Estimation", "attached_to_name": estimation_name},
            update_modified=False,
        )


# ---------------------------------------------------------------------------
# Whitelisted API endpoints
# ---------------------------------------------------------------------------

@frappe.whitelist()
def process_estimation(
    opportunity: str,
    text: str | None = None,
    file_urls: str | None = None,
    context_text: str | None = None,
    estimation_profile: str | None = None,
):
    """Trigger AI processing and create an AI Estimation record.

    estimation_profile: optional Estimation Profile name — overrides global default.
    file_urls: JSON array of Frappe file URLs.
    """
    urls = json.loads(file_urls) if file_urls else []
    service = AIService(profile_name=estimation_profile or None)
    combined_text = "\n\n---\n\n".join(part for part in [text, context_text] if part)

    result = service.process_input(text=combined_text, file_urls=urls)
    result_items = result.get("items") or []

    if not result_items:
        frappe.throw(_(
            "AI could not generate any estimation items from the provided scope/drawings. "
            "Please review the prompt, uploaded files, or try again."
        ))

    opp = frappe.get_doc("Opportunity", opportunity)

    estimation = frappe.new_doc("AI Estimation")
    estimation.opportunity = opportunity
    estimation.estimation_profile = estimation_profile or ""
    estimation.customer = opp.customer_name or opp.party_name
    estimation.currency = opp.currency or "AED"
    estimation.ai_summary = (
        result.get("scope_summary") or result.get("summary") or ""
    )
    estimation.project_area = (
        result.get("project_area_sqft") or result.get("project_area") or 0
    )
    estimation.assumptions = _join_list_or_str(result.get("assumptions"))
    estimation.exclusions = _join_list_or_str(result.get("exclusions"))
    estimation.generation_audit = service.build_generation_audit(
        text=combined_text, file_urls=urls, result=result
    )
    estimation.status = "Completed"
    estimation.scope_text = text or ""

    for item in result_items:
        item_name = item.get("item_name", "")
        item_type = item.get("type") or ""

        # ERPNext Item lookup
        matched_item = frappe.db.get_value("Item", {"item_name": item_name}, "name")
        if not matched_item:
            candidates = frappe.get_all(
                "Item",
                filters={"item_name": ["like", f"%{item_name[:30]}%"]},
                limit=1,
            )
            if candidates:
                matched_item = candidates[0].name

        # Always compute amount in Python — never trust the model total
        try:
            qty_val = float(item.get("qty") or 1)
        except (TypeError, ValueError):
            qty_val = 1.0

        raw_rate = item.get("unit_rate")
        try:
            rate_val = float(raw_rate) if raw_rate is not None else 0.0
        except (TypeError, ValueError):
            rate_val = 0.0

        amount_val = qty_val * rate_val

        confidence_val = float(item.get("confidence") or 1.0)
        if rate_val == 0.0:
            confidence_val = min(confidence_val, 0.3)

        # Normalised item_status from ProfileConfig-aware normalisation
        item_status_raw = item.get("item_status", "Valid")
        # Map internal snake_case to the display Select options
        _status_map = {
            "valid": "Valid",
            "needs_review": "Needs Review",
            "missing_rate": "Missing Rate",
            "missing_quantity": "Missing Quantity",
            "schema_error": "Schema Error",
        }
        item_status = _status_map.get(item_status_raw.lower().replace(" ", "_"), "Valid")

        # Extra schema-specific metadata
        extra_meta = item.get("extra_metadata") or {}
        extra_meta_json = json.dumps(extra_meta) if extra_meta else ""

        estimation.append("items", {
            "item_code": matched_item,
            "item_name": item_name,
            "item_category": item.get("category", "General"),
            "room_zone": item.get("room_zone", ""),
            "description": item.get("description", ""),
            "qty": qty_val,
            "uom": item.get("uom", "Nos"),
            "rate": rate_val,
            "amount": amount_val,
            "type": item_type if item_type in ("Material", "Service") else "",
            "confidence": confidence_val,
            "item_status": item_status,
            "source_reference": item.get("remarks", ""),
            "pricing_detail_json": "",
            "extra_metadata_json": extra_meta_json,
        })

    append_version_snapshot(estimation, "AI Generated", summary="Initial AI estimation created")
    estimation.insert()
    _attach_files_to_estimation(estimation.name, urls)
    return estimation.name


def _join_list_or_str(value) -> str:
    if isinstance(value, list):
        return "\n".join(str(v) for v in value)
    return str(value or "")


@frappe.whitelist()
def generate_estimation_mockups(
    estimation_name: str,
    scope_text: str | None = None,
    file_urls: str | None = None,
    style: str = "photorealistic",
    additional_prompt: str | None = None,
    count: int | str = 2,
):
    if not frappe.has_permission("AI Estimation", "read", estimation_name):
        frappe.throw(_("No permission to access this estimation."), frappe.PermissionError)

    estimation = frappe.get_doc("AI Estimation", estimation_name)
    profile = getattr(estimation, "estimation_profile", None)
    urls = json.loads(file_urls) if file_urls else []
    service = AIService(profile_name=profile or None)
    images = service.generate_mockup_images(
        estimation_name=estimation_name,
        scope_text=scope_text,
        file_urls=urls,
        style=style,
        additional_prompt=additional_prompt,
        count=int(count or 2),
    )
    return {"images": images}


@frappe.whitelist()
def get_estimation_mockups(estimation_name: str):
    if not frappe.has_permission("AI Estimation", "read", estimation_name):
        frappe.throw(_("No permission to access this estimation."), frappe.PermissionError)
    return {"images": _get_mockup_images(estimation_name)}


@frappe.whitelist()
def get_estimation_commercial_review(estimation_name: str, refresh: int | str = 0):
    if not frappe.has_permission("AI Estimation", "read", estimation_name):
        frappe.throw(_("No permission to access this estimation."), frappe.PermissionError)

    estimation = frappe.get_doc("AI Estimation", estimation_name)
    force_refresh = str(refresh).strip() in {"1", "true", "True"}
    if estimation.commercial_review_json and not force_refresh:
        return {"review": json.loads(estimation.commercial_review_json)}

    profile = getattr(estimation, "estimation_profile", None)
    service = AIService(profile_name=profile or None)
    source_files = [f.get("file_url") for f in _get_estimation_source_files(estimation_name)]
    review = service.generate_commercial_review(estimation, source_files)

    if frappe.has_permission("AI Estimation", "write", estimation_name):
        estimation.db_set(
            "commercial_review_json", json.dumps(review, indent=2), update_modified=False
        )
    return {"review": review}


@frappe.whitelist()
def get_estimation_drawing_takeoff(estimation_name: str, refresh: int | str = 0):
    if not frappe.has_permission("AI Estimation", "read", estimation_name):
        frappe.throw(_("No permission to access this estimation."), frappe.PermissionError)

    estimation = frappe.get_doc("AI Estimation", estimation_name)
    force_refresh = str(refresh).strip() in {"1", "true", "True"}
    if estimation.drawing_takeoff_json and not force_refresh:
        return {"takeoff": json.loads(estimation.drawing_takeoff_json)}

    profile = getattr(estimation, "estimation_profile", None)
    service = AIService(profile_name=profile or None)
    source_files = [f.get("file_url") for f in _get_estimation_source_files(estimation_name)]
    takeoff = service.generate_drawing_takeoff(estimation, source_files)

    if frappe.has_permission("AI Estimation", "write", estimation_name):
        estimation.db_set(
            "drawing_takeoff_json", json.dumps(takeoff, indent=2), update_modified=False
        )
    return {"takeoff": takeoff}


@frappe.whitelist()
def get_estimation_item_pricing_detail(
    estimation_name: str,
    item_row_name: str,
    refresh: int | str = 0,
):
    if not frappe.has_permission("AI Estimation", "read", estimation_name):
        frappe.throw(_("No permission to access this estimation."), frappe.PermissionError)

    estimation = frappe.get_doc("AI Estimation", estimation_name)
    item_row = next((r for r in estimation.items if r.name == item_row_name), None)
    if not item_row:
        frappe.throw(_("The requested estimation item could not be found."))

    force_refresh = str(refresh).strip() in {"1", "true", "True"}
    if item_row.pricing_detail_json and not force_refresh:
        try:
            return {"detail": json.loads(item_row.pricing_detail_json)}
        except Exception:
            pass

    profile = getattr(estimation, "estimation_profile", None)
    service = AIService(profile_name=profile or None)
    source_files = [f.get("file_url") for f in _get_estimation_source_files(estimation_name)]
    detail = service.generate_item_pricing_detail(
        estimation=estimation,
        item_row=item_row,
        file_urls=source_files,
    )

    if frappe.has_permission("AI Estimation", "write", estimation_name):
        item_row.db_set(
            "pricing_detail_json", json.dumps(detail, indent=2), update_modified=False
        )
    return {"detail": detail}


@frappe.whitelist()
def generate_estimation_cost_breakdown(estimation_name: str, refresh: int | str = 0):
    if not frappe.has_permission("AI Estimation", "read", estimation_name):
        frappe.throw(_("No permission to access this estimation."), frappe.PermissionError)

    estimation = frappe.get_doc("AI Estimation", estimation_name)
    force_refresh = str(refresh).strip() in {"1", "true", "True"}
    profile = getattr(estimation, "estimation_profile", None)
    service = AIService(profile_name=profile or None)
    source_files = [f.get("file_url") for f in _get_estimation_source_files(estimation_name)]
    generated_count = 0
    cached_count = 0
    failed_items: list[dict[str, str]] = []

    for item_row in estimation.items:
        if item_row.pricing_detail_json and not force_refresh:
            cached_count += 1
            continue
        try:
            detail = service.generate_item_pricing_detail(
                estimation=estimation,
                item_row=item_row,
                file_urls=source_files,
            )
            if frappe.has_permission("AI Estimation", "write", estimation_name):
                item_row.db_set(
                    "pricing_detail_json", json.dumps(detail, indent=2), update_modified=False
                )
            generated_count += 1
        except Exception as e:
            failed_items.append({
                "item_name": item_row.item_name or item_row.name,
                "error": str(e),
            })
            frappe.log_error(
                title="AI Cost Breakdown Failure",
                message=(
                    f"Estimation: {estimation_name}\n"
                    f"Item: {item_row.item_name or item_row.name}\n"
                    f"Error: {str(e)}"
                ),
            )

    return {
        "generated_count": generated_count,
        "cached_count": cached_count,
        "total_items": len(estimation.items),
        "failed_count": len(failed_items),
        "failed_items": failed_items[:10],
    }


@frappe.whitelist()
def get_estimation_source_files(estimation_name: str):
    if not frappe.has_permission("AI Estimation", "read", estimation_name):
        frappe.throw(_("No permission to access this estimation."), frappe.PermissionError)
    return {"files": _get_estimation_source_files(estimation_name)}


@frappe.whitelist()
def get_estimation_profiles():
    """Return all Estimation Profiles for use in frontend dropdowns."""
    return frappe.get_all(
        "Estimation Profile",
        fields=["name", "profile_name", "industry_hint", "schema_type", "workflow_type"],
        order_by="profile_name asc",
    )
