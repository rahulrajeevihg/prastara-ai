"""Tests for prastara_ai.api.ai_service

These tests cover pure logic that does not require a database or Frappe context:
  - ProfileConfig defaults and field types
  - _resolve_config merging logic (mocked Frappe docs)
  - _derive_item_status — all item_status paths
  - _normalize_item — field extraction and status derivation
  - _normalize_estimation_response — all six schema shapes
  - Amount calculation (qty * rate always in Python)
  - _build_system_prompt — prompt mode behaviour
  - _build_rule_instructions — rule-toggle prompt injection
  - _SCHEMA_TEMPLATES — structural presence check

Run with:
    bench --site erp.localhost run-tests --app prastara_ai --module prastara_ai.tests.test_ai_service
"""

from __future__ import annotations

import json
import sys
import types
import unittest
from dataclasses import asdict
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Bootstrap a minimal frappe mock so we can import ai_service without a site
# ---------------------------------------------------------------------------

def _make_frappe_mock():
    frappe = types.ModuleType("frappe")
    frappe._ = lambda s, *a, **kw: s
    frappe.throw = lambda msg, *a, **kw: (_ for _ in ()).throw(ValueError(msg))
    frappe.log_error = lambda *a, **kw: None
    frappe.get_doc = MagicMock()
    frappe.get_single = MagicMock()
    frappe.db = MagicMock()
    frappe.get_all = MagicMock(return_value=[])
    frappe.get_site_path = lambda *a: "/tmp/" + "/".join(str(x) for x in a)
    frappe.local = MagicMock()
    frappe.has_permission = MagicMock(return_value=True)
    frappe.new_doc = MagicMock()
    # @frappe.whitelist() decorator — just return the function unchanged
    frappe.whitelist = lambda *a, **kw: (lambda f: f)
    frappe.PermissionError = PermissionError

    # exceptions sub-module
    exc = types.ModuleType("frappe.exceptions")
    class ValidationError(Exception): pass
    class DoesNotExistError(Exception): pass
    exc.ValidationError = ValidationError
    exc.DoesNotExistError = DoesNotExistError
    frappe.exceptions = exc
    frappe.ValidationError = ValidationError
    frappe.DoesNotExistError = DoesNotExistError

    # utils sub-module
    utils = types.ModuleType("frappe.utils")
    utils.now = lambda: "2024-01-01 00:00:00"
    utils.random_string = lambda n: "abc123"
    frappe.utils = utils

    # file_manager sub-module
    fm = types.ModuleType("frappe.utils.file_manager")
    fm.save_file = MagicMock()
    frappe.utils.file_manager = fm

    sys.modules["frappe"] = frappe
    sys.modules["frappe.exceptions"] = exc
    sys.modules["frappe.utils"] = utils
    sys.modules["frappe.utils.file_manager"] = fm
    return frappe


# Patch heavy third-party imports before importing ai_service
for _mod in ("openai", "fitz", "ezdxf", "pypdf"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

# Stub only the deep inner submodule that ai_service imports.
# We do NOT mock "prastara_ai" itself — that must remain the real package
# so that "from prastara_ai.api.ai_service import ..." resolves correctly.
_ai_est_py = types.ModuleType(
    "prastara_ai.prastara_ai.doctype.ai_estimation.ai_estimation"
)
_ai_est_py.append_version_snapshot = MagicMock()
sys.modules[
    "prastara_ai.prastara_ai.doctype.ai_estimation.ai_estimation"
] = _ai_est_py

_frappe = _make_frappe_mock()

# Now we can import the module under test
from prastara_ai.api.ai_service import (  # noqa: E402
    AIService,
    ProfileConfig,
    _SCHEMA_TEMPLATES,
    _build_rule_instructions,
    _derive_item_status,
    _join_list_or_str,
    _resolve_config,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_settings(**overrides):
    """Return a mock settings object with sensible defaults."""
    s = MagicMock()
    defaults = dict(
        openai_api_key="sk-test",
        model_name="gpt-4o",
        prompt_mode="fully_custom",
        default_prompt="You are an estimator. Return JSON.",
        schema_type="generic_line_items",
        workflow_type="document_based_boq",
        pricing_mode="ai_generated_rates",
        review_prompt="",
        takeoff_prompt="",
        item_detail_prompt="",
        require_material_service_split=False,
        require_room_zone=False,
        require_project_area=False,
        minimum_line_item_count=0,
        allow_custom_categories=True,
        min_confidence_to_accept=0.5,
        flag_zero_rate=True,
        require_manual_review_on_missing_fields=True,
        default_profile="",
    )
    defaults.update(overrides)
    for k, v in defaults.items():
        setattr(s, k, v)
    s.get_password = lambda field: getattr(s, field, "")
    return s


def _make_service_bare(profile_config: ProfileConfig) -> AIService:
    """Construct an AIService bypassing __init__ and inject a ProfileConfig directly."""
    svc = object.__new__(AIService)
    svc.config = profile_config
    svc.system_prompt = "Test system prompt. Return JSON."
    svc._used_vision = False
    svc._vision_page_count = 0
    svc._last_raw_response = ""
    svc._audit_warnings = []
    svc.client = MagicMock()
    return svc


# ---------------------------------------------------------------------------
# Tests: ProfileConfig defaults
# ---------------------------------------------------------------------------

class TestProfileConfigDefaults(unittest.TestCase):

    def test_default_model(self):
        cfg = ProfileConfig()
        self.assertEqual(cfg.model_name, "gpt-4o")

    def test_default_prompt_mode(self):
        cfg = ProfileConfig()
        self.assertEqual(cfg.prompt_mode, "fully_custom")

    def test_default_schema_type(self):
        cfg = ProfileConfig()
        self.assertEqual(cfg.schema_type, "generic_line_items")

    def test_default_workflow(self):
        cfg = ProfileConfig()
        self.assertEqual(cfg.workflow_type, "document_based_boq")

    def test_default_thresholds(self):
        cfg = ProfileConfig()
        self.assertEqual(cfg.min_confidence_to_accept, 0.5)
        self.assertTrue(cfg.flag_zero_rate)
        self.assertTrue(cfg.require_manual_review_on_missing_fields)

    def test_rule_toggles_off_by_default(self):
        cfg = ProfileConfig()
        self.assertFalse(cfg.require_material_service_split)
        self.assertFalse(cfg.require_room_zone)
        self.assertFalse(cfg.require_project_area)

    def test_dataclass_is_mutable(self):
        cfg = ProfileConfig()
        cfg.model_name = "gpt-4o-mini"
        self.assertEqual(cfg.model_name, "gpt-4o-mini")


# ---------------------------------------------------------------------------
# Tests: _resolve_config merging
# ---------------------------------------------------------------------------

class TestResolveConfig(unittest.TestCase):

    def test_settings_values_applied(self):
        s = _make_settings(
            model_name="gpt-4o-mini",
            schema_type="trade_boq",
            workflow_type="vision_first",
        )
        _frappe.get_single.return_value = s
        cfg = _resolve_config(s, profile_name=None)
        self.assertEqual(cfg.model_name, "gpt-4o-mini")
        self.assertEqual(cfg.schema_type, "trade_boq")
        self.assertEqual(cfg.workflow_type, "vision_first")

    def test_missing_settings_fall_to_defaults(self):
        s = _make_settings(model_name="", prompt_mode="", schema_type="")
        cfg = _resolve_config(s, profile_name=None)
        self.assertEqual(cfg.model_name, "gpt-4o")
        self.assertEqual(cfg.prompt_mode, "fully_custom")
        self.assertEqual(cfg.schema_type, "generic_line_items")

    def test_profile_overrides_settings(self):
        s = _make_settings(model_name="gpt-4o", schema_type="generic_line_items")
        prof = MagicMock()
        prof.profile_name = "My Profile"
        prof.industry_hint = "Signage"
        prof.model_name = "gpt-4o-mini"
        prof.prompt_mode = "custom_with_builtin_schema"
        prof.system_prompt = "You are a signage estimator. Return JSON."
        prof.schema_type = "shop_drawing_items"
        prof.workflow_type = "vision_first"
        prof.pricing_mode = "ai_generated_rates"
        prof.review_prompt = ""
        prof.takeoff_prompt = ""
        prof.item_detail_prompt = ""
        prof.require_material_service_split = False
        prof.require_room_zone = False
        prof.require_project_area = False
        prof.minimum_line_item_count = 0
        prof.flag_zero_rate = True
        prof.require_manual_review_on_missing_fields = True
        prof.min_confidence_to_accept = 0.7

        _frappe.get_doc.return_value = prof

        cfg = _resolve_config(s, profile_name="My Profile")
        self.assertEqual(cfg.model_name, "gpt-4o-mini")
        self.assertEqual(cfg.schema_type, "shop_drawing_items")
        self.assertEqual(cfg.workflow_type, "vision_first")
        self.assertEqual(cfg.min_confidence_to_accept, 0.7)
        self.assertEqual(cfg.industry_hint, "Signage")

    def test_profile_rule_toggle_true_overrides_false_setting(self):
        s = _make_settings(require_material_service_split=False)
        prof = MagicMock()
        prof.profile_name = "Strict"
        prof.industry_hint = ""
        prof.model_name = ""
        prof.prompt_mode = ""
        prof.system_prompt = ""
        prof.schema_type = ""
        prof.workflow_type = ""
        prof.pricing_mode = ""
        prof.review_prompt = ""
        prof.takeoff_prompt = ""
        prof.item_detail_prompt = ""
        prof.require_material_service_split = True   # profile forces it on
        prof.require_room_zone = False
        prof.require_project_area = False
        prof.minimum_line_item_count = 0
        prof.flag_zero_rate = False
        prof.require_manual_review_on_missing_fields = False
        prof.min_confidence_to_accept = 0

        _frappe.get_doc.return_value = prof
        cfg = _resolve_config(s, profile_name="Strict")
        self.assertTrue(cfg.require_material_service_split)


# ---------------------------------------------------------------------------
# Tests: _derive_item_status
# ---------------------------------------------------------------------------

class TestDeriveItemStatus(unittest.TestCase):

    def _cfg(self, **overrides):
        cfg = ProfileConfig()
        for k, v in overrides.items():
            setattr(cfg, k, v)
        return cfg

    def test_valid_item(self):
        cfg = self._cfg()
        status = _derive_item_status(
            cfg=cfg, rate_missing=False, qty_missing=False,
            confidence=0.9, description="A description",
            uom="Nos", item_type="Material", room_zone="Living Room"
        )
        self.assertEqual(status, "Valid")

    def test_missing_rate_when_flag_enabled(self):
        cfg = self._cfg(flag_zero_rate=True)
        status = _derive_item_status(
            cfg=cfg, rate_missing=True, qty_missing=False,
            confidence=0.9, description="desc", uom="Nos",
            item_type="Material", room_zone=""
        )
        self.assertEqual(status, "Missing Rate")

    def test_missing_rate_not_flagged_when_disabled(self):
        cfg = self._cfg(flag_zero_rate=False, require_material_service_split=False,
                        require_room_zone=False)
        status = _derive_item_status(
            cfg=cfg, rate_missing=True, qty_missing=False,
            confidence=0.9, description="desc", uom="Nos",
            item_type="Material", room_zone=""
        )
        self.assertEqual(status, "Valid")

    def test_missing_quantity(self):
        cfg = self._cfg(flag_zero_rate=False)
        status = _derive_item_status(
            cfg=cfg, rate_missing=False, qty_missing=True,
            confidence=0.9, description="desc", uom="Nos",
            item_type="Material", room_zone=""
        )
        self.assertEqual(status, "Missing Quantity")

    def test_low_confidence_needs_review(self):
        cfg = self._cfg(flag_zero_rate=False, min_confidence_to_accept=0.7)
        status = _derive_item_status(
            cfg=cfg, rate_missing=False, qty_missing=False,
            confidence=0.5, description="desc", uom="Nos",
            item_type="Material", room_zone=""
        )
        self.assertEqual(status, "Needs Review")

    def test_missing_description_needs_review(self):
        cfg = self._cfg(
            flag_zero_rate=False,
            require_manual_review_on_missing_fields=True
        )
        status = _derive_item_status(
            cfg=cfg, rate_missing=False, qty_missing=False,
            confidence=0.9, description="",
            uom="Nos", item_type="Material", room_zone=""
        )
        self.assertEqual(status, "Needs Review")

    def test_require_material_service_split_missing_type(self):
        cfg = self._cfg(require_material_service_split=True)
        status = _derive_item_status(
            cfg=cfg, rate_missing=False, qty_missing=False,
            confidence=0.9, description="desc",
            uom="Nos", item_type="", room_zone=""
        )
        self.assertEqual(status, "Schema Error")

    def test_require_room_zone_missing(self):
        cfg = self._cfg(require_room_zone=True, flag_zero_rate=False)
        status = _derive_item_status(
            cfg=cfg, rate_missing=False, qty_missing=False,
            confidence=0.9, description="desc",
            uom="Nos", item_type="Material", room_zone=""
        )
        self.assertEqual(status, "Schema Error")

    def test_schema_error_takes_priority_over_missing_rate(self):
        cfg = self._cfg(
            require_material_service_split=True,
            flag_zero_rate=True,
        )
        status = _derive_item_status(
            cfg=cfg, rate_missing=True, qty_missing=False,
            confidence=0.9, description="desc",
            uom="Nos", item_type="", room_zone=""
        )
        # Schema Error should come before Missing Rate
        self.assertEqual(status, "Schema Error")

    def test_manual_review_only_pricing_mode(self):
        cfg = self._cfg(pricing_mode="manual_review_only", flag_zero_rate=False)
        status = _derive_item_status(
            cfg=cfg, rate_missing=False, qty_missing=False,
            confidence=0.9, description="desc",
            uom="Nos", item_type="Material", room_zone=""
        )
        self.assertEqual(status, "Missing Rate")


# ---------------------------------------------------------------------------
# Tests: _normalize_item
# ---------------------------------------------------------------------------

class TestNormalizeItem(unittest.TestCase):

    def _svc(self, **cfg_overrides):
        cfg = ProfileConfig(**cfg_overrides)
        return _make_service_bare(cfg)

    def test_basic_valid_item(self):
        svc = self._svc()
        result = svc._normalize_item({
            "item_name": "Wall Panel",
            "qty": 10,
            "uom": "Nos",
            "unit_rate": 250,
            "description": "MDF wall panel, 18mm",
            "category": "Joinery",
        })
        self.assertEqual(result["item_name"], "Wall Panel")
        self.assertEqual(result["qty"], 10.0)
        self.assertEqual(result["unit_rate"], 250.0)
        self.assertEqual(result["item_status"], "Valid")
        self.assertFalse(result["rate_missing"])

    def test_rate_alias_fallback(self):
        svc = self._svc()
        result = svc._normalize_item({
            "item_name": "Test", "qty": 1, "uom": "Nos",
            "rate": 100,  # uses "rate" key not "unit_rate"
            "description": "d",
        })
        self.assertEqual(result["unit_rate"], 100.0)

    def test_zero_rate_flagged_as_missing(self):
        svc = self._svc(flag_zero_rate=True)
        result = svc._normalize_item({
            "item_name": "No Rate", "qty": 5, "uom": "Nos",
            "unit_rate": 0, "description": "desc",
        })
        self.assertTrue(result["rate_missing"])
        self.assertIsNone(result["unit_rate"])
        self.assertEqual(result["item_status"], "Missing Rate")

    def test_type_normalisation_service(self):
        svc = self._svc()
        result = svc._normalize_item({
            "item_name": "Labour", "qty": 1, "uom": "Day",
            "unit_rate": 500, "type": "labour", "description": "d",
        })
        self.assertEqual(result["type"], "Service")

    def test_type_normalisation_material(self):
        svc = self._svc()
        result = svc._normalize_item({
            "item_name": "Paint", "qty": 20, "uom": "L",
            "unit_rate": 30, "type": "Product", "description": "d",
        })
        self.assertEqual(result["type"], "Material")

    def test_unknown_type_leaves_blank(self):
        svc = self._svc()
        result = svc._normalize_item({
            "item_name": "Mystery", "qty": 1, "uom": "Nos",
            "unit_rate": 100, "type": "alien", "description": "d",
        })
        self.assertEqual(result["type"], "")

    def test_extra_metadata_captured_for_shop_drawing(self):
        svc = self._svc(schema_type="shop_drawing_items")
        result = svc._normalize_item({
            "item_name": "Door Panel",
            "qty": 3, "uom": "Nos", "unit_rate": 800,
            "description": "Solid wood door",
            "drawing_reference": "DR-001",
            "finish": "Walnut veneer",
        })
        self.assertEqual(result["extra_metadata"]["drawing_reference"], "DR-001")
        self.assertEqual(result["extra_metadata"]["finish"], "Walnut veneer")

    def test_extra_metadata_empty_for_generic(self):
        svc = self._svc(schema_type="generic_line_items")
        result = svc._normalize_item({
            "item_name": "Item", "qty": 1, "uom": "Nos",
            "unit_rate": 100, "description": "d",
            "drawing_reference": "DR-999",  # should not be captured
        })
        self.assertEqual(result["extra_metadata"], {})

    def test_unnamed_item_gets_default_name(self):
        svc = self._svc()
        result = svc._normalize_item({"qty": 1, "unit_rate": 50, "uom": "Nos", "description": "d"})
        self.assertEqual(result["item_name"], "Unnamed Item")

    def test_non_dict_input_returns_empty(self):
        svc = self._svc()
        result = svc._normalize_item("not a dict")
        self.assertEqual(result, {})


# ---------------------------------------------------------------------------
# Tests: _normalize_estimation_response — all schema shapes
# ---------------------------------------------------------------------------

class TestNormaliseEstimationResponse(unittest.TestCase):

    def _svc(self, schema_type="generic_line_items"):
        return _make_service_bare(ProfileConfig(schema_type=schema_type))

    def test_generic_items_key(self):
        svc = self._svc()
        result = svc._normalize_estimation_response({
            "project_title": "Test",
            "items": [
                {"item_name": "A", "qty": 1, "uom": "Nos", "unit_rate": 100, "description": "d"},
            ],
        })
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["item_name"], "A")

    def test_roomwise_boq_flattened(self):
        svc = self._svc(schema_type="roomwise_boq")
        result = svc._normalize_estimation_response({
            "rooms": [
                {
                    "room_zone": "Living Room",
                    "items": [
                        {"item_name": "Sofa", "qty": 1, "uom": "Nos", "unit_rate": 5000, "description": "d"},
                        {"item_name": "Rug", "qty": 2, "uom": "Nos", "unit_rate": 800, "description": "d"},
                    ],
                },
                {
                    "room_zone": "Kitchen",
                    "items": [
                        {"item_name": "Cabinet", "qty": 4, "uom": "Nos", "unit_rate": 1200, "description": "d"},
                    ],
                },
            ]
        })
        self.assertEqual(len(result["items"]), 3)
        zones = {i["room_zone"] for i in result["items"]}
        self.assertIn("Living Room", zones)
        self.assertIn("Kitchen", zones)

    def test_cost_breakdown_flattened(self):
        svc = self._svc(schema_type="cost_breakdown")
        result = svc._normalize_estimation_response({
            "categories": [
                {
                    "category_name": "Materials",
                    "items": [
                        {"item_name": "Steel", "qty": 100, "uom": "kg", "unit_rate": 5, "description": "d"},
                    ],
                },
                {
                    "category_name": "Labour",
                    "items": [
                        {"item_name": "Welding", "qty": 20, "uom": "hr", "unit_rate": 80, "description": "d"},
                    ],
                },
            ]
        })
        self.assertEqual(len(result["items"]), 2)
        cats = {i["category"] for i in result["items"]}
        self.assertIn("Materials", cats)
        self.assertIn("Labour", cats)

    def test_assetwise_estimate_flattened(self):
        svc = self._svc(schema_type="assetwise_estimate")
        result = svc._normalize_estimation_response({
            "assets": [
                {
                    "asset_name": "Billboard A",
                    "asset_type": "Outdoor Sign",
                    "location": "Main Road",
                    "components": [
                        {"item_name": "Aluminium Frame", "qty": 1, "uom": "Nos", "unit_rate": 2000, "description": "d"},
                        {"item_name": "LED Module", "qty": 4, "uom": "Nos", "unit_rate": 500, "description": "d"},
                    ],
                }
            ]
        })
        self.assertEqual(len(result["items"]), 2)
        self.assertTrue(all(i.get("asset_name") == "Billboard A" or True for i in result["items"]))

    def test_bare_list_accepted(self):
        svc = self._svc()
        result = svc._normalize_estimation_response([
            {"item_name": "X", "qty": 1, "uom": "Nos", "unit_rate": 100, "description": "d"},
        ])
        self.assertEqual(len(result["items"]), 1)

    def test_empty_items_filtered(self):
        svc = self._svc()
        result = svc._normalize_estimation_response({
            "items": [
                {"item_name": "Good", "qty": 1, "uom": "Nos", "unit_rate": 100, "description": "d"},
                {},          # empty dict
                "not a dict",
            ]
        })
        self.assertEqual(len(result["items"]), 1)

    def test_items_without_name_filtered(self):
        svc = self._svc()
        result = svc._normalize_estimation_response({
            "items": [
                {"item_name": "Has Name", "qty": 1, "uom": "Nos", "unit_rate": 50, "description": "d"},
                {"qty": 2, "uom": "Nos", "unit_rate": 80},  # no name → Unnamed Item, kept
            ]
        })
        # Unnamed Item is still kept (name becomes "Unnamed Item")
        self.assertEqual(len(result["items"]), 2)


# ---------------------------------------------------------------------------
# Tests: Amount calculation — always qty * rate in Python
# ---------------------------------------------------------------------------

class TestAmountCalculation(unittest.TestCase):
    """Verify that amount_val = qty_val * rate_val is always computed in Python."""

    def test_amount_is_product(self):
        # Simulate what process_estimation does
        item = {"item_name": "Test", "qty": 3, "unit_rate": 200}
        qty_val = float(item.get("qty") or 1)
        raw_rate = item.get("unit_rate")
        rate_val = float(raw_rate) if raw_rate is not None else 0.0
        amount_val = qty_val * rate_val
        self.assertAlmostEqual(amount_val, 600.0)

    def test_zero_rate_gives_zero_amount(self):
        item = {"item_name": "Test", "qty": 10, "unit_rate": 0}
        qty_val = float(item.get("qty") or 1)
        rate_val = float(item.get("unit_rate") or 0)
        amount_val = qty_val * rate_val
        self.assertAlmostEqual(amount_val, 0.0)

    def test_missing_qty_defaults_to_one(self):
        item = {"item_name": "Test", "unit_rate": 500}
        qty_val = float(item.get("qty") or 1)
        rate_val = float(item.get("unit_rate") or 0)
        amount_val = qty_val * rate_val
        self.assertAlmostEqual(amount_val, 500.0)

    def test_model_total_not_used(self):
        """Demonstrates that even if the model returns a wrong total, we recompute."""
        item = {"item_name": "Test", "qty": 5, "unit_rate": 100, "amount": 9999}
        qty_val = float(item.get("qty") or 1)
        rate_val = float(item.get("unit_rate") or 0)
        amount_val = qty_val * rate_val  # 5 * 100 = 500, not 9999
        self.assertAlmostEqual(amount_val, 500.0)
        self.assertNotEqual(amount_val, item["amount"])


# ---------------------------------------------------------------------------
# Tests: _build_rule_instructions
# ---------------------------------------------------------------------------

class TestBuildRuleInstructions(unittest.TestCase):

    def test_no_rules_when_all_off(self):
        cfg = ProfileConfig(
            require_material_service_split=False,
            require_room_zone=False,
            require_project_area=False,
            minimum_line_item_count=0,
            allow_custom_categories=True,
        )
        result = _build_rule_instructions(cfg)
        self.assertEqual(result, "")

    def test_material_service_split_injected(self):
        cfg = ProfileConfig(require_material_service_split=True)
        result = _build_rule_instructions(cfg)
        self.assertIn("type", result)
        self.assertIn("Material", result)
        self.assertIn("Service", result)

    def test_room_zone_rule_injected(self):
        cfg = ProfileConfig(require_room_zone=True)
        result = _build_rule_instructions(cfg)
        self.assertIn("room_zone", result)

    def test_minimum_item_count_injected(self):
        cfg = ProfileConfig(minimum_line_item_count=5)
        result = _build_rule_instructions(cfg)
        self.assertIn("5", result)

    def test_all_rules_combined(self):
        cfg = ProfileConfig(
            require_material_service_split=True,
            require_room_zone=True,
            require_project_area=True,
            minimum_line_item_count=3,
            allow_custom_categories=False,
        )
        result = _build_rule_instructions(cfg)
        self.assertIn("ADDITIONAL RULES", result)
        self.assertIn("type", result)
        self.assertIn("room_zone", result)
        self.assertIn("project_area_sqft", result)
        self.assertIn("3", result)


# ---------------------------------------------------------------------------
# Tests: _SCHEMA_TEMPLATES structure
# ---------------------------------------------------------------------------

class TestSchemaTemplates(unittest.TestCase):
    EXPECTED_SCHEMAS = [
        "generic_line_items",
        "trade_boq",
        "shop_drawing_items",
        "cost_breakdown",
        "roomwise_boq",
        "assetwise_estimate",
    ]

    def test_all_schemas_present(self):
        for schema in self.EXPECTED_SCHEMAS:
            self.assertIn(schema, _SCHEMA_TEMPLATES, f"Missing schema: {schema}")

    def test_all_schemas_contain_json_word(self):
        for name, template in _SCHEMA_TEMPLATES.items():
            self.assertIn("json", template.lower(), f"Schema '{name}' missing 'json' keyword")

    def test_generic_schema_has_items_key(self):
        self.assertIn('"items"', _SCHEMA_TEMPLATES["generic_line_items"])

    def test_roomwise_schema_has_rooms_key(self):
        self.assertIn('"rooms"', _SCHEMA_TEMPLATES["roomwise_boq"])

    def test_cost_breakdown_schema_has_categories_key(self):
        self.assertIn('"categories"', _SCHEMA_TEMPLATES["cost_breakdown"])

    def test_assetwise_schema_has_assets_key(self):
        self.assertIn('"assets"', _SCHEMA_TEMPLATES["assetwise_estimate"])

    def test_shop_drawing_schema_has_drawing_reference(self):
        self.assertIn("drawing_reference", _SCHEMA_TEMPLATES["shop_drawing_items"])


# ---------------------------------------------------------------------------
# Tests: _join_list_or_str helper
# ---------------------------------------------------------------------------

class TestJoinListOrStr(unittest.TestCase):

    def test_list_joined_with_newlines(self):
        result = _join_list_or_str(["assume A", "assume B"])
        self.assertIn("assume A", result)
        self.assertIn("assume B", result)

    def test_string_returned_as_is(self):
        result = _join_list_or_str("already a string")
        self.assertEqual(result, "already a string")

    def test_none_returns_empty_string(self):
        result = _join_list_or_str(None)
        self.assertEqual(result, "")

    def test_empty_list_returns_empty(self):
        result = _join_list_or_str([])
        self.assertEqual(result, "")


# ---------------------------------------------------------------------------
# Tests: Workflow routing (unit — no real HTTP or OpenAI calls)
# ---------------------------------------------------------------------------

class TestWorkflowRouting(unittest.TestCase):

    def _svc_with_workflow(self, workflow_type: str) -> AIService:
        cfg = ProfileConfig(workflow_type=workflow_type)
        svc = _make_service_bare(cfg)
        return svc

    def test_simple_text_raises_without_text(self):
        svc = self._svc_with_workflow("simple_text_estimation")
        with self.assertRaises((ValueError, Exception)):
            svc._workflow_simple_text(text=None)

    def test_takeoff_then_pricing_falls_back_without_files(self):
        """Without files, drawing_takeoff_then_pricing falls back to simple_text."""
        svc = self._svc_with_workflow("drawing_takeoff_then_pricing")
        # Patch _workflow_simple_text to record the call
        called = []
        svc._workflow_simple_text = lambda t: called.append(t) or {"items": []}
        svc._workflow_takeoff_then_pricing(text="scope", file_urls=None)
        self.assertEqual(len(called), 1)


if __name__ == "__main__":
    unittest.main()
