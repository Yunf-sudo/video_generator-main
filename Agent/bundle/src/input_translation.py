from __future__ import annotations

import json
import os
from typing import Any

from google_gemini_api import DEFAULT_TEXT_MODEL, extract_response_text, generate_content
from prompt_templates_config import load_prompt_templates
from runtime_tunables_config import load_runtime_tunables

try:
    import json_repair
except ImportError:  # pragma: no cover - optional dependency
    json_repair = None


RUNTIME_TUNABLES = load_runtime_tunables()
PROMPT_TEMPLATES = load_prompt_templates()

TRANSLATION_MODEL = os.getenv(
    "TRANSLATION_MODEL",
    str(RUNTIME_TUNABLES["model_config"].get("translation_model") or DEFAULT_TEXT_MODEL),
).strip() or DEFAULT_TEXT_MODEL

TRANSLATION_SYSTEM_PROMPT = PROMPT_TEMPLATES["translation_system_prompt"]

TRANSLATABLE_INPUT_KEYS = [
    "product_name",
    "product_category",
    "campaign_goal",
    "target_market",
    "target_audience",
    "core_selling_points",
    "use_scenarios",
    "style_preset",
    "custom_style_notes",
    "style_tone",
    "consistency_anchor",
    "product_geometry_notes",
    "additional_info",
    "prompt_scene_description_notes",
    "prompt_special_emphasis",
    "prompt_error_notes",
    "reference_style",
]


def _contains_chinese(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in str(text or ""))


def _load_json_object(text: str) -> dict[str, Any]:
    candidate = (text or "").strip()
    if not candidate:
        return {}
    if json_repair is not None:
        try:
            loaded = json_repair.loads(candidate)
            return loaded if isinstance(loaded, dict) else {}
        except Exception:
            pass
    try:
        loaded = json.loads(candidate)
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def translate_text_to_english(text: str) -> str:
    source = str(text or "").strip()
    if not source:
        return source
    if not _contains_chinese(source):
        return source

    response = generate_content(
        model=TRANSLATION_MODEL,
        messages=[
            {"role": "system", "content": TRANSLATION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Translate the following production input into English.\n"
                    "Keep bullets, formatting, numbers, and brand/product names.\n\n"
                    f"{source}"
                ),
            },
        ],
        timeout_seconds=120.0,
    )
    translated = extract_response_text(response).strip()
    return translated or source


def translate_inputs_to_english(inputs: dict[str, Any]) -> dict[str, Any]:
    translated = dict(inputs)
    pending = {
        key: str(inputs.get(key, "") or "")
        for key in TRANSLATABLE_INPUT_KEYS
        if isinstance(inputs.get(key), str) and _contains_chinese(str(inputs.get(key) or ""))
    }
    if not pending:
        return translated

    payload = {"fields": pending}
    response = generate_content(
        model=TRANSLATION_MODEL,
        messages=[
            {"role": "system", "content": TRANSLATION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Translate every string value in the JSON object into English.\n"
                    "Keep the same JSON structure and keys.\n"
                    "Preserve brand/product names, numbers, bullets, and formatting.\n"
                    "Return one raw JSON object only.\n\n"
                    f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
                ),
            },
        ],
        response_mime_type="application/json",
        timeout_seconds=180.0,
    )
    translated_payload = _load_json_object(extract_response_text(response))
    translated_fields = translated_payload.get("fields", {}) if isinstance(translated_payload.get("fields"), dict) else {}

    for key, source_value in pending.items():
        translated[key] = str(translated_fields.get(key) or source_value).strip()

    return translated
