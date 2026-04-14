from __future__ import annotations

import base64
import json
import os
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
	import fitz  # pymupdf — for PDF→image rendering
except ImportError:
	fitz = None

try:
	import ezdxf
except ImportError:
	ezdxf = None

# Standard fit-out categories used to group estimation items
FITOUT_CATEGORIES = [
	"Flooring",
	"Walls & Wall Cladding",
	"Ceiling & Gypsum",
	"Joinery & Carpentry",
	"Doors & Windows",
	"Glass & Glazing",
	"Electrical & Lighting",
	"Plumbing & Sanitary",
	"HVAC & MEP",
	"Furniture & FF&E",
	"Paint & Finishes",
	"Stonework & Marble",
	"Services & Labour",
	"Project Management",
	"General",
]

_DEFAULT_ROLE_PROMPT = """You are an expert Estimation Engineer specializing in fit-out and interior decoration projects
in the Middle East (UAE/GCC). Your role is to analyse project scope, client briefs, and design drawings,
then produce a detailed, itemised Bill of Quantities (BOQ) suitable for a sales quotation.

IMPORTANT CONTEXT:
- Company type: Fit-out / Interior Decor contractor
- Currency: AED (UAE Dirhams) unless stated otherwise
- All quantities must reflect realistic fit-out trade measurements (sqft, lm, nos, lot)
- Separate MATERIALS (physical supply items) from SERVICES (labour, installation, professional fees)
- Group every item under one of these standard trade categories:
  Flooring | Walls & Wall Cladding | Ceiling & Gypsum | Joinery & Carpentry |
  Doors & Windows | Glass & Glazing | Electrical & Lighting | Plumbing & Sanitary |
  HVAC & MEP | Furniture & FF&E | Paint & Finishes | Stonework & Marble |
  Services & Labour | Project Management | General"""

_FORMAT_AND_RULES_PROMPT = """
RESPONSE FORMAT — return ONLY valid JSON, no prose:
{
  "project_title": "Short descriptive project name",
  "scope_summary": "2-3 sentence summary of the overall scope",
  "project_area_sqft": 0.0,
  "assumptions": "Key assumptions made (materials grade, brand neutral unless specified, etc.)",
  "exclusions": "What is NOT included (e.g. structural works, MEP design fees, authority approvals)",
  "items": [
    {
      "category": "Flooring",
      "room_zone": "Reception",
      "item_name": "Porcelain Floor Tiles 600x600mm",
      "description": "Supply and install rectified porcelain tiles including adhesive, grout and levelling",
      "qty": 250.0,
      "uom": "Sqft",
      "type": "Material",
      "unit_rate": 28.0,
      "confidence": 0.90,
      "remarks": "Rate includes supply + installation. Grade: mid-range."
    },
    {
      "category": "Services & Labour",
      "room_zone": "Reception",
      "item_name": "Tiling Labour",
      "description": "Skilled tiling labour for floor and skirting installation",
      "qty": 250.0,
      "uom": "Sqft",
      "type": "Service",
      "unit_rate": 8.0,
      "confidence": 0.95,
      "remarks": "Separate line if materials are being procured separately"
    }
  ]
}

RULES:
1. Every item MUST have a category from the approved list above.
2. type must be exactly "Material" or "Service".
3. unit_rate is your best market-rate estimate in AED. Use 0 if truly unknown.
4. confidence is 0.0–1.0 reflecting how certain you are about qty and rate.
5. uom must be one of: Sqft, Sqm, Lm, Nos, Lot, Set, Day, Month.
6. If a drawing or PDF is provided, extract dimensions and areas relevant to your defined scope only — ignore sections of the document outside your scope.
7. Always include a "Project Management" line (typically 5-8% of total material cost as a Service).
8. Include `room_zone` whenever the scope suggests a room, area, zone, level, or section.
9. SCOPE RESTRICTION: Only estimate items that fall within the role and scope defined above. Do not include items from parts of the document that are outside your defined scope."""

SYSTEM_PROMPT = _DEFAULT_ROLE_PROMPT + "\n" + _FORMAT_AND_RULES_PROMPT

MOCKUP_STYLE_PROMPTS = {
	"photorealistic": "Create a photorealistic interior design mockup with realistic materials, lighting, depth, and camera perspective.",
	"concept": "Create a polished concept-render mockup with clean composition, aspirational staging, and presentation quality.",
	"minimal": "Create a calm minimal interior mockup with restrained styling, soft daylight, and premium fit-out detailing.",
}

SOURCE_DRAWING_EXTENSIONS = (".pdf", ".dwg", ".dxf", ".txt")
ITEM_DETAIL_PROMPT = """You are a senior fit-out estimator preparing an internal cost-explanation sheet.

Return ONLY valid JSON with this exact structure:
{
  "item_name": "string",
  "category": "string",
  "scope_summary": "What this line item covers in plain estimator language",
  "drawing_scope": [
    "Specific scope cues interpreted from drawing/brief text"
  ],
  "scope_inclusions": [
    "Included work / materials / accessories"
  ],
  "scope_exclusions": [
    "Not included in this line item"
  ],
  "quantity_basis": "How the quantity appears to have been derived",
  "rate_basis": "How the unit rate appears to have been built up",
  "raw_materials": [
    {
      "name": "string",
      "specification": "string",
      "qty": 0,
      "uom": "string",
      "unit_rate": 0,
      "amount": 0,
      "notes": "string"
    }
  ],
  "labour_components": [
    {
      "name": "string",
      "cost_basis": "string",
      "amount": 0,
      "notes": "string"
    }
  ],
  "other_costs": [
    {
      "name": "string",
      "amount": 0,
      "notes": "string"
    }
  ],
  "cost_summary": {
    "raw_material_cost": 0,
    "labour_cost": 0,
    "other_cost": 0,
    "unit_rate": 0,
    "quantity": 0,
    "total_amount": 0
  },
  "assumptions": [
    "Commercial or technical assumptions"
  ],
  "risks": [
    "Pricing or scope risks to review"
  ],
  "confidence_note": "One short note on how reliable the pricing is"
}

Rules:
- Be commercially realistic for UAE/GCC fit-out pricing.
- Use the row quantity, row rate, and row total as anchors.
- raw_material_cost should explain only material content for this line.
- If the line is a Service item, raw_materials may be empty.
- Do not invent precise dimensions unless the supplied brief/drawings support them.
- Keep scope_inclusions and drawing_scope specific, not generic.
"""

COMMERCIAL_REVIEW_PROMPT = """You are a senior commercial manager reviewing an AI-generated fit-out BOQ before quotation issue.

Return ONLY valid JSON:
{
  "review_score": 0,
  "executive_summary": "string",
  "underpriced_items": [{"item_name":"string","issue":"string","severity":"high|medium|low"}],
  "overpriced_items": [{"item_name":"string","issue":"string","severity":"high|medium|low"}],
  "missing_scope": [{"title":"string","reason":"string","severity":"high|medium|low"}],
  "duplication_risks": [{"title":"string","reason":"string","severity":"high|medium|low"}],
  "margin_risks": [{"title":"string","reason":"string","severity":"high|medium|low"}],
  "recommended_actions": ["string"],
  "confidence_note": "string"
}
"""

DRAWING_TAKEOFF_PROMPT = """You are a quantity surveyor extracting room-wise takeoff cues from a project brief and drawing references.

Return ONLY valid JSON:
{
  "takeoff_summary": "string",
  "rooms": [
    {
      "room_zone": "string",
      "scope_detected": ["string"],
      "dimensions_detected": ["string"],
      "quantity_cues": ["string"]
    }
  ],
  "measurement_notes": ["string"],
  "drawing_gaps": ["string"]
}
"""


class AIService:
	def __init__(self):
		self.settings = frappe.get_single("AI Estimation Settings")
		self.api_key = self.settings.get_password("openai_api_key")
		self.model = self.settings.model_name or "gpt-4o"
		self.system_prompt = self._get_system_prompt()
		self.client = openai.OpenAI(api_key=self.api_key) if openai and self.api_key else None

	def _get_system_prompt(self) -> str:
		custom_prompt = (self.settings.default_prompt or "").strip()
		if not custom_prompt:
			return SYSTEM_PROMPT

		# The custom role from AI settings replaces the default role entirely.
		# The format/rules section is always appended so output stays parseable.
		return custom_prompt + "\n" + _FORMAT_AND_RULES_PROMPT

	def _normalize_item(self, item: dict[str, Any]) -> dict[str, Any]:
		if not isinstance(item, dict):
			return {}

		item_type = item.get("type") or item.get("item_type") or item.get("kind") or "Material"
		if str(item_type).strip().lower() in {"service", "labour", "labor"}:
			item_type = "Service"
		else:
			item_type = "Material"

		unit_rate = item.get("unit_rate")
		if unit_rate is None:
			unit_rate = item.get("rate")
		if unit_rate is None:
			unit_rate = item.get("price")

		description = item.get("description") or item.get("details") or item.get("scope") or ""
		remarks = item.get("remarks")
		if remarks is None:
			remarks = item.get("source_reference")
		if remarks is None:
			remarks = item.get("notes")

		category = item.get("category") or item.get("item_category") or item.get("trade") or "General"

		return {
			"category": category,
			"item_name": item.get("item_name") or item.get("name") or item.get("title") or "Unnamed Item",
			"room_zone": item.get("room_zone") or item.get("zone") or item.get("room") or item.get("area") or item.get("location") or "",
			"description": description,
			"qty": item.get("qty") if item.get("qty") is not None else item.get("quantity", 1),
			"uom": item.get("uom") or item.get("unit") or "Nos",
			"type": item_type,
			"unit_rate": unit_rate if unit_rate is not None else 0,
			"confidence": item.get("confidence", item.get("score", 1.0)),
			"remarks": remarks or "",
		}

	def _normalize_estimation_response(self, parsed: Any) -> dict[str, Any]:
		if isinstance(parsed, list):
			parsed = {"items": parsed}
		elif not isinstance(parsed, dict):
			parsed = {"items": []}

		if "items" not in parsed or not isinstance(parsed.get("items"), list):
			candidate_keys = [
				"boq_items", "line_items", "estimation_items", "boq",
				"bill_of_quantities", "data", "rows",
			]
			for key in candidate_keys:
				value = parsed.get(key)
				if isinstance(value, list):
					parsed["items"] = value
					break
			else:
				for _, value in parsed.items():
					if isinstance(value, list) and (not value or isinstance(value[0], dict)):
						parsed["items"] = value
						break
				else:
					parsed["items"] = []

		parsed["items"] = [
			self._normalize_item(item)
			for item in parsed.get("items", [])
			if isinstance(item, dict)
		]
		parsed["items"] = [item for item in parsed["items"] if item.get("item_name")]
		return parsed

	def build_generation_audit(
		self,
		text: str | None = None,
		file_urls: list[str] | None = None,
		result: dict[str, Any] | None = None,
	) -> str:
		source_files = []
		for file_url in file_urls or []:
			source_files.append({
				"file_url": file_url,
				"file_name": os.path.basename(file_url),
				"file_type": os.path.splitext(file_url)[1].lower().lstrip("."),
			})

		items = (result or {}).get("items", [])
		audit_payload = {
			"generated_at": now(),
			"model": self.model,
			"used_custom_prompt": self.system_prompt != SYSTEM_PROMPT,
			"prompt_length": len(self.system_prompt or ""),
			"prompt_preview": (self.system_prompt or "")[:1200],
			"input_scope_length": len((text or "").strip()),
			"source_file_count": len(source_files),
			"source_files": source_files,
			"used_vision": getattr(self, "_used_vision", False),
			"vision_page_count": getattr(self, "_vision_page_count", 0),
			"result_item_count": len(items),
			"ai_response_keys": list((result or {}).keys()),
			"ai_response_preview": getattr(self, "_last_raw_response", "")[:2000],
		}
		return json.dumps(audit_payload, indent=2)

	def process_input(
		self, text: str | None = None, file_urls: list[str] | None = None
	) -> dict[str, Any]:
		text_parts = []
		vision_images: list[dict] = []  # {file_name, base64_images}

		if text:
			text_parts.append(f"CLIENT BRIEF / SCOPE DESCRIPTION:\n{text}")

		if file_urls:
			for url in file_urls:
				file_path = resolve_file_path(url)
				ext = os.path.splitext(file_path)[1].lower()
				fname = os.path.basename(url)

				if ext == ".pdf":
					extracted = self._extract_from_pdf(file_path)
					if extracted.strip():
						text_parts.append(f"EXTRACTED TEXT FROM PDF ({fname}):\n{extracted}")
					else:
						# No text layer — render as images for GPT-4o vision
						imgs = self._pdf_to_base64_images(file_path)
						if imgs:
							vision_images.append({"file_name": fname, "images": imgs})
						else:
							text_parts.append(f"[PDF {fname} has no extractable text and could not be rendered as images]")
				else:
					file_content = self.extract_content_from_file(url)
					text_parts.append(f"EXTRACTED CONTENT FROM FILE ({fname}):\n{file_content}")

		if not text_parts and not vision_images:
			frappe.throw(_("Please provide a scope description or upload a drawing/brief."))

		full_text = "\n\n---\n\n".join(text_parts)
		return self.get_ai_estimation(full_text, vision_images=vision_images)

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
		else:
			return f"[Unsupported file type: {extension}]"

	def _extract_from_pdf(self, path: str) -> str:
		try:
			reader = PdfReader(path)
			pages_text = []
			for page in reader.pages:
				t = page.extract_text()
				if t:
					pages_text.append(t)
			return "\n".join(pages_text) or ""
		except Exception as e:
			frappe.log_error(f"PDF Extraction Error: {str(e)}")
			return ""

	def _pdf_to_base64_images(self, path: str, max_pages: int = 6, dpi: int = 150) -> list[str]:
		"""Render PDF pages to base64 PNG images using pymupdf (fitz)."""
		if not fitz:
			return []
		images = []
		try:
			doc = fitz.open(path)
			zoom = dpi / 72  # 72 is the default PDF DPI
			mat = fitz.Matrix(zoom, zoom)
			for page_num in range(min(len(doc), max_pages)):
				page = doc[page_num]
				pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
				img_bytes = pix.tobytes("png")
				images.append(base64.b64encode(img_bytes).decode("utf-8"))
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
				f"DWG File Analysis:\n"
				f"Layers ({len(layers)}): {', '.join(layers[:30])}\n"
				f"Total Entities: {entity_count}\n"
				f"Text Annotations: {'; '.join(texts)}"
			)
		except Exception as e:
			frappe.log_error(f"DWG Extraction Error: {str(e)}")
			return f"[Error extracting DWG: {str(e)}]"

	def get_ai_estimation(self, content: str, vision_images: list[dict] | None = None) -> dict[str, Any]:
		if not self.api_key:
			frappe.throw(_("OpenAI API Key is missing in AI Estimation Settings."))
		if not openai:
			frappe.throw(_("OpenAI library not installed. Run: pip install openai"))

		try:
			client = openai.OpenAI(api_key=self.api_key)

			# Build user message content — may be multimodal (text + images)
			self._used_vision = bool(vision_images)
			self._vision_page_count = sum(len(v["images"]) for v in (vision_images or []))
			user_content: list | str
			if vision_images:
				user_content = []
				if content.strip():
					user_content.append({"type": "text", "text": content})
				for entry in vision_images:
					fname = entry["file_name"]
					user_content.append({
						"type": "text",
						"text": f"Shop drawing / reference file: {fname} ({len(entry['images'])} page(s) follow)",
					})
					for b64 in entry["images"]:
						user_content.append({
							"type": "image_url",
							"image_url": {"url": f"data:image/png;base64,{b64}", "detail": "high"},
						})
			else:
				user_content = content

			response = client.chat.completions.create(
				model=self.model,
				messages=[
					{"role": "system", "content": self.system_prompt},
					{"role": "user", "content": user_content},
				],
				response_format={"type": "json_object"},
				temperature=0.2,
				max_tokens=4096,
			)
			parsed = self._normalize_estimation_response(
				json.loads(response.choices[0].message.content)
			)
			self._last_raw_response = json.dumps(parsed)
			return parsed
		except Exception as e:
			frappe.log_error(title=_("OpenAI API Error")[:140], message=str(e))
			frappe.throw(_("Failed to process with AI: {0}").format(str(e)))

	def generate_mockup_images(
		self,
		estimation_name: str,
		scope_text: str | None = None,
		file_urls: list[str] | None = None,
		style: str = "photorealistic",
		additional_prompt: str | None = None,
		count: int = 2,
	) -> list[dict[str, str]]:
		if not self.api_key:
			frappe.throw(_("OpenAI API Key is missing in AI Estimation Settings."))
		if not openai:
			frappe.throw(_("OpenAI library not installed. Run: pip install openai"))

		estimation = frappe.get_doc("AI Estimation", estimation_name)
		count = min(max(int(count or 1), 1), 4)

		prompt_sections = [
			"Use case: ui-mockup",
			"Asset type: interior fit-out presentation mockup",
			"Primary request: Generate an interior mockup concept based on the provided project scope and drawing references.",
			f"Style/medium: {MOCKUP_STYLE_PROMPTS.get(style, MOCKUP_STYLE_PROMPTS['photorealistic'])}",
			"Composition/framing: wide-angle interior perspective, client-presentation ready, coherent space planning",
			"Lighting/mood: realistic architectural lighting, premium commercial interior atmosphere",
			"Constraints: preserve the core spatial intent from the drawings and supplied scope, no watermark, no text overlay",
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
			prompt_sections.append(f"Key BOQ items: {item_summary}")

		if file_urls:
			for file_url in file_urls:
				extracted = self.extract_content_from_file(file_url)
				prompt_sections.append(
					f"Drawing reference from {os.path.basename(file_url)}: {extracted[:6000]}"
				)

		if additional_prompt:
			prompt_sections.append(f"Additional user direction: {additional_prompt}")

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

	def generate_item_pricing_detail(
		self,
		estimation,
		item_row,
		file_urls: list[str] | None = None,
	) -> dict[str, Any]:
		if not self.api_key:
			frappe.throw(_("OpenAI API Key is missing in AI Estimation Settings."))
		if not openai:
			frappe.throw(_("OpenAI library not installed. Run: pip install openai"))

		file_context_blocks = []
		for file_url in file_urls or []:
			try:
				extracted = self.extract_content_from_file(file_url)
			except Exception:
				extracted = "[Could not extract file contents]"
			file_context_blocks.append(
				f"FILE: {os.path.basename(file_url)}\n{(extracted or '')[:4000]}"
			)

		peer_items = []
		for row in estimation.items[:20]:
			if row.name == item_row.name:
				continue
			peer_items.append(
				f"- {row.item_category or 'General'} | {row.item_name} | qty={row.qty or 0} {row.uom or ''} | rate={row.rate or 0} | type={row.type or 'Material'}"
			)

		user_sections = [
			f"Opportunity: {estimation.opportunity}",
			f"Project customer: {estimation.customer or ''}",
			f"Project scope text: {estimation.scope_text or ''}",
			f"AI scope summary: {estimation.ai_summary or ''}",
			f"Project area sqft: {estimation.project_area or 0}",
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
				"amount": item_row.amount or ((item_row.qty or 0) * (item_row.rate or 0)),
				"type": item_row.type,
				"confidence": item_row.confidence,
				"source_reference": item_row.source_reference,
			}, indent=2),
			"RELATED BOQ ITEMS:",
			"\n".join(peer_items) or "None",
			"DRAWING / FILE CONTEXT:",
			"\n\n".join(file_context_blocks) or "No drawing files attached.",
		]

		try:
			response = self.client.chat.completions.create(
				model=self.model,
				messages=[
					{"role": "system", "content": ITEM_DETAIL_PROMPT},
					{"role": "user", "content": "\n\n".join(user_sections)},
				],
				response_format={"type": "json_object"},
				temperature=0.1,
			)
			return json.loads(response.choices[0].message.content)
		except Exception as e:
			frappe.log_error(title=_("OpenAI Item Detail Error")[:140], message=str(e))
			frappe.throw(_("Failed to explain item pricing: {0}").format(str(e)))


def resolve_file_path(file_url: str) -> str:
	"""Resolve a Frappe file URL or site-relative path to a local filesystem path."""
	if not file_url:
		frappe.throw(_("Missing file URL."))

	normalized_url = unquote(str(file_url).strip())
	if os.path.isabs(normalized_url) and os.path.exists(normalized_url):
		return normalized_url

	if normalized_url.startswith(("http://", "https://")):
		frappe.throw(_("Remote file URLs are not supported for local processing: {0}").format(file_url))

	file_doc = frappe.db.get_value(
		"File",
		{"file_url": normalized_url},
		["file_url", "is_private"],
		as_dict=True,
	)
	if not file_doc and "/files/" in normalized_url:
		suffix = normalized_url[normalized_url.index("/files/") :]
		file_doc = frappe.db.get_value(
			"File",
			{"file_url": suffix},
			["file_url", "is_private"],
			as_dict=True,
		)
	if not file_doc and "/private/files/" in normalized_url:
		suffix = normalized_url[normalized_url.index("/private/files/") :]
		file_doc = frappe.db.get_value(
			"File",
			{"file_url": suffix},
			["file_url", "is_private"],
			as_dict=True,
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
		frappe.throw(_("File does not exist on disk: {0}").format(file_url), FileNotFoundError)

	return file_path

	def generate_commercial_review(self, estimation, file_urls: list[str] | None = None) -> dict[str, Any]:
		if not self.api_key or not self.client:
			frappe.throw(_("OpenAI API Key is missing in AI Estimation Settings."))
		if not openai:
			frappe.throw(_("OpenAI library not installed. Run: pip install openai"))

		file_context = []
		for file_url in file_urls or []:
			try:
				file_context.append(
					f"{os.path.basename(file_url)}:\n{self.extract_content_from_file(file_url)[:2500]}"
				)
			except Exception:
				continue

		items_payload = [
			{
				"room_zone": getattr(row, "room_zone", "") or "Unassigned",
				"category": row.item_category,
				"item_name": row.item_name,
				"description": row.description,
				"qty": row.qty,
				"uom": row.uom,
				"rate": row.rate,
				"amount": row.amount or ((row.qty or 0) * (row.rate or 0)),
				"type": row.type,
			}
			for row in estimation.items
		]
		user_prompt = "\n\n".join([
			f"Scope text: {estimation.scope_text or ''}",
			f"AI summary: {estimation.ai_summary or ''}",
			f"Assumptions: {estimation.assumptions or ''}",
			f"Exclusions: {estimation.exclusions or ''}",
			f"Target margin pct: {estimation.target_margin_pct or 0}",
			f"Items: {json.dumps(items_payload, indent=2)}",
			"Drawing context:",
			"\n\n".join(file_context) or "None",
		])

		response = self.client.chat.completions.create(
			model=self.model,
			messages=[
				{"role": "system", "content": COMMERCIAL_REVIEW_PROMPT},
				{"role": "user", "content": user_prompt},
			],
			response_format={"type": "json_object"},
			temperature=0.1,
			max_tokens=2500,
		)
		return json.loads(response.choices[0].message.content)

	def generate_drawing_takeoff(self, estimation, file_urls: list[str] | None = None) -> dict[str, Any]:
		if not self.api_key or not self.client:
			frappe.throw(_("OpenAI API Key is missing in AI Estimation Settings."))
		if not openai:
			frappe.throw(_("OpenAI library not installed. Run: pip install openai"))

		file_context = []
		for file_url in file_urls or []:
			try:
				file_context.append(
					f"{os.path.basename(file_url)}:\n{self.extract_content_from_file(file_url)[:3500]}"
				)
			except Exception:
				continue

		user_prompt = "\n\n".join([
			f"Scope text: {estimation.scope_text or ''}",
			f"AI summary: {estimation.ai_summary or ''}",
			"Current BOQ items:",
			json.dumps([
				{
					"room_zone": getattr(row, "room_zone", ""),
					"item_name": row.item_name,
					"description": row.description,
				}
				for row in estimation.items
			], indent=2),
			"Drawing context:",
			"\n\n".join(file_context) or "None",
		])

		response = self.client.chat.completions.create(
			model=self.model,
			messages=[
				{"role": "system", "content": DRAWING_TAKEOFF_PROMPT},
				{"role": "user", "content": user_prompt},
			],
			response_format={"type": "json_object"},
			temperature=0.1,
			max_tokens=2500,
		)
		return json.loads(response.choices[0].message.content)


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


def _get_estimation_source_files(estimation_name: str) -> list[dict[str, str | int]]:
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
		file_doc for file_doc in files
		if (file_doc.get("file_name") or "").lower().endswith(SOURCE_DRAWING_EXTENSIONS)
	]


def _attach_files_to_estimation(estimation_name: str, file_urls: list[str] | None = None) -> None:
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
			{
				"attached_to_doctype": "AI Estimation",
				"attached_to_name": estimation_name,
			},
			update_modified=False,
		)


@frappe.whitelist()
def process_estimation(
	opportunity: str,
	text: str | None = None,
	file_urls: str | None = None,
	context_text: str | None = None,
):
	"""
	Whitelisted API to trigger AI processing and create an AI Estimation record.
	file_urls must be a JSON array of Frappe file URLs (e.g. ['/files/brief.pdf']).
	"""
	urls = json.loads(file_urls) if file_urls else []
	service = AIService()
	combined_text = "\n\n---\n\n".join(part for part in [text, context_text] if part)
	result = service.process_input(text=combined_text, file_urls=urls)
	result_items = result.get("items") or []
	if not result_items:
		frappe.throw(
			_("AI could not generate any BOQ items from the provided scope/drawings. Please review the prompt, uploaded files, or try again.")
		)

	opp = frappe.get_doc("Opportunity", opportunity)

	estimation = frappe.new_doc("AI Estimation")
	estimation.opportunity = opportunity
	estimation.customer = opp.customer_name or opp.party_name
	estimation.currency = opp.currency or "AED"
	estimation.ai_summary = result.get("scope_summary", "")
	estimation.project_area = result.get("project_area_sqft", 0)
	estimation.assumptions = result.get("assumptions", "")
	estimation.exclusions = result.get("exclusions", "")
	estimation.generation_audit = service.build_generation_audit(text=combined_text, file_urls=urls, result=result)
	estimation.status = "Completed"
	estimation.scope_text = text or ""

	for item in result_items:
		item_name = item.get("item_name", "")
		item_type = item.get("type", "Material")  # "Material" or "Service"

		# Try to match an existing ERPNext Item by exact name first
		matched_item = frappe.db.get_value("Item", {"item_name": item_name}, "name")
		if not matched_item:
			items_found = frappe.get_all(
				"Item",
				filters={"item_name": ["like", f"%{item_name[:30]}%"]},
				limit=1,
			)
			if items_found:
				matched_item = items_found[0].name

		estimation.append("items", {
			"item_code": matched_item,
			"item_name": item_name,
			"item_category": item.get("category", "General"),
			"room_zone": item.get("room_zone", ""),
			"description": item.get("description", ""),
			"qty": item.get("qty", 1),
			"uom": item.get("uom", "Nos"),
			"rate": item.get("unit_rate", 0),
			"type": item_type if item_type in ("Material", "Service") else "Material",
			"confidence": item.get("confidence", 1.0),
			"source_reference": item.get("remarks", ""),
			"pricing_detail_json": "",
		})

	append_version_snapshot(estimation, "AI Generated", summary="Initial AI estimation created")
	estimation.insert()
	_attach_files_to_estimation(estimation.name, urls)
	return estimation.name


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

	urls = json.loads(file_urls) if file_urls else []
	service = AIService()
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

	service = AIService()
	source_files = [file_doc.get("file_url") for file_doc in _get_estimation_source_files(estimation_name)]
	review = service.generate_commercial_review(estimation, source_files)

	if frappe.has_permission("AI Estimation", "write", estimation_name):
		estimation.db_set("commercial_review_json", json.dumps(review, indent=2), update_modified=False)

	return {"review": review}


@frappe.whitelist()
def get_estimation_drawing_takeoff(estimation_name: str, refresh: int | str = 0):
	if not frappe.has_permission("AI Estimation", "read", estimation_name):
		frappe.throw(_("No permission to access this estimation."), frappe.PermissionError)

	estimation = frappe.get_doc("AI Estimation", estimation_name)
	force_refresh = str(refresh).strip() in {"1", "true", "True"}
	if estimation.drawing_takeoff_json and not force_refresh:
		return {"takeoff": json.loads(estimation.drawing_takeoff_json)}

	service = AIService()
	source_files = [file_doc.get("file_url") for file_doc in _get_estimation_source_files(estimation_name)]
	takeoff = service.generate_drawing_takeoff(estimation, source_files)

	if frappe.has_permission("AI Estimation", "write", estimation_name):
		estimation.db_set("drawing_takeoff_json", json.dumps(takeoff, indent=2), update_modified=False)

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
	item_row = next((row for row in estimation.items if row.name == item_row_name), None)
	if not item_row:
		frappe.throw(_("The requested estimation item could not be found."))

	force_refresh = str(refresh).strip() in {"1", "true", "True"}
	if item_row.pricing_detail_json and not force_refresh:
		try:
			return {"detail": json.loads(item_row.pricing_detail_json)}
		except Exception:
			pass

	service = AIService()
	source_files = [file_doc.get("file_url") for file_doc in _get_estimation_source_files(estimation_name)]
	detail = service.generate_item_pricing_detail(
		estimation=estimation,
		item_row=item_row,
		file_urls=source_files,
	)

	if frappe.has_permission("AI Estimation", "write", estimation_name):
		item_row.db_set("pricing_detail_json", json.dumps(detail, indent=2), update_modified=False)

	return {"detail": detail}


@frappe.whitelist()
def generate_estimation_cost_breakdown(estimation_name: str, refresh: int | str = 0):
	if not frappe.has_permission("AI Estimation", "read", estimation_name):
		frappe.throw(_("No permission to access this estimation."), frappe.PermissionError)

	estimation = frappe.get_doc("AI Estimation", estimation_name)
	force_refresh = str(refresh).strip() in {"1", "true", "True"}
	service = AIService()
	source_files = [file_doc.get("file_url") for file_doc in _get_estimation_source_files(estimation_name)]
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
				item_row.db_set("pricing_detail_json", json.dumps(detail, indent=2), update_modified=False)
			generated_count += 1
		except Exception as e:
			failed_items.append({
				"item_name": item_row.item_name or item_row.name,
				"error": str(e),
			})
			frappe.log_error(
				title="AI Estimation Cost Breakdown Failure",
				message=f"Estimation: {estimation_name}\nItem: {item_row.item_name or item_row.name}\nError: {str(e)}",
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
