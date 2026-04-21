from __future__ import annotations

import json
import os
from typing import Any

from google_gemini_api import DEFAULT_TEXT_MODEL, extract_response_text, generate_content
from prompt_context import build_prompt_context
from prompt_error_cases import list_error_cases, render_error_case_text
from prompt_templates_config import load_prompt_templates
from runtime_tunables_config import load_runtime_tunables


RUNTIME_TUNABLES = load_runtime_tunables()
PROMPT_TEMPLATES = load_prompt_templates()

PROMPT_COMPOSER_MODEL = os.getenv(
    "PROMPT_COMPOSER_MODEL",
    str(RUNTIME_TUNABLES["model_config"].get("prompt_composer_model") or DEFAULT_TEXT_MODEL),
).strip() or DEFAULT_TEXT_MODEL

PROMPT_COMPOSER_SYSTEM_PROMPT = PROMPT_TEMPLATES["prompt_composer_system_prompt"]


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)):
        return "\n".join(_clean_text(item) for item in value if _clean_text(item))
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, indent=2)
    return str(value).strip()


def _join_parts(*parts: Any) -> str:
    normalized = [_clean_text(part) for part in parts]
    return "\n".join(part for part in normalized if part)


def _compact_dict(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value not in (None, "", [], {}, ())}


def _continuity_summary(continuity: dict[str, Any] | None) -> str:
    if not isinstance(continuity, dict):
        return ""

    parts: list[str] = []
    same_rider_default = _clean_text(continuity.get("same_rider_default"))
    if same_rider_default:
        parts.append(same_rider_default)

    previous_scene = continuity.get("previous_scene")
    if isinstance(previous_scene, dict):
        parts.append(
            _join_parts(
                "Previous scene context:",
                previous_scene.get("theme", ""),
                previous_scene.get("scene_description", ""),
                previous_scene.get("key_message", ""),
            )
        )

    next_scene = continuity.get("next_scene")
    if isinstance(next_scene, dict):
        parts.append(
            _join_parts(
                "Next scene context:",
                next_scene.get("theme", ""),
                next_scene.get("scene_description", ""),
                next_scene.get("key_message", ""),
            )
        )

    return "\n".join(part for part in parts if part)


def _render_fallback_prompt(bundle: dict[str, Any]) -> str:
    blocks: list[str] = [
        f"Create one {bundle['target']} shot for {bundle['hero_product_name']}.",
    ]

    if bundle.get("scene_description"):
        blocks.append(f"Scene: {bundle['scene_description']}")
    if bundle.get("scene_visual_plan"):
        blocks.append(f"Visual direction: {bundle['scene_visual_plan']}")
    if bundle.get("creative_direction"):
        blocks.append(f"Creative direction: {bundle['creative_direction']}")
    if bundle.get("special_emphasis"):
        blocks.append(f"Special emphasis: {bundle['special_emphasis']}")
    if bundle.get("continuity"):
        blocks.append(f"Continuity: {bundle['continuity']}")
    if bundle.get("audio_direction"):
        blocks.append(f"Audio guidance: {bundle['audio_direction']}")
    if bundle.get("product_identity"):
        blocks.append(f"Product identity to preserve: {bundle['product_identity']}")
    if bundle.get("reference_handling"):
        blocks.append(f"Reference handling: {bundle['reference_handling']}")
    if bundle.get("delivery_specs"):
        blocks.append(f"Delivery specs: {bundle['delivery_specs']}")
    if bundle.get("error_cases"):
        avoid_text = "; ".join(str(item).strip().rstrip(".") for item in bundle["error_cases"] if str(item).strip())
        if avoid_text:
            blocks.append(f"Avoid: {avoid_text}.")

    return "\n\n".join(blocks)


def build_generation_prompt_bundle(
    target: str,
    scene_description: str,
    visuals: dict[str, Any] | None,
    scene_audio: dict[str, Any] | None,
    aspect_ratio: str,
    duration_seconds: int,
    continuity: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
    hero_product_name: str | None = None,
    product_reference_signature: str | None = None,
    product_visual_structure: str | None = None,
) -> dict[str, Any]:
    meta = meta or {}
    prompt_context = build_prompt_context({**meta, **({"hero_product_name": hero_product_name} if hero_product_name else {})})
    visuals = visuals or {}
    scene_audio = scene_audio or {}

    scene_visual_plan = _join_parts(
        visuals.get("camera_movement", ""),
        visuals.get("lighting", ""),
        visuals.get("composition_and_set_dressing", ""),
        visuals.get("transition_anchor", ""),
    )
    creative_direction = _join_parts(
        meta.get("custom_style_notes", ""),
        meta.get("style_tone", ""),
        meta.get("reference_style", ""),
        meta.get("prompt_scene_description_notes", ""),
    )
    special_emphasis = _join_parts(
        meta.get("prompt_special_emphasis", ""),
        meta.get("core_selling_points", ""),
        meta.get("additional_info", ""),
    )
    audio_direction = _join_parts(
        scene_audio.get("voice_over", ""),
        scene_audio.get("text", ""),
        scene_audio.get("music", ""),
        scene_audio.get("sfx", ""),
    )
    product_identity = _join_parts(
        meta.get("consistency_anchor", ""),
        product_reference_signature,
        product_visual_structure,
    )

    bundle = _compact_dict(
        {
            "target": str(target or "").strip().lower() or "image",
            "hero_product_name": prompt_context["hero_product_name"],
            "scene_description": _join_parts(scene_description, meta.get("prompt_scene_description_notes", "")),
            "scene_visual_plan": scene_visual_plan,
            "creative_direction": creative_direction,
            "special_emphasis": special_emphasis,
            "continuity": _continuity_summary(continuity),
            "audio_direction": audio_direction if str(target).strip().lower() == "video" else "",
            "product_identity": product_identity,
            "reference_handling": prompt_context["reference_image_instruction"],
            "delivery_specs": f"Aspect ratio {aspect_ratio}; planned duration about {duration_seconds} seconds.",
            "error_case_module": "prompt_error_cases",
            "error_case_text": render_error_case_text(target, meta.get("prompt_error_notes", "")),
            "error_cases": list_error_cases(target, meta.get("prompt_error_notes", "")),
        }
    )
    return bundle


def compose_generation_prompt(
    target: str,
    scene_description: str,
    visuals: dict[str, Any] | None,
    scene_audio: dict[str, Any] | None,
    aspect_ratio: str,
    duration_seconds: int,
    continuity: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
    hero_product_name: str | None = None,
    product_reference_signature: str | None = None,
    product_visual_structure: str | None = None,
) -> dict[str, Any]:
    bundle = build_generation_prompt_bundle(
        target=target,
        scene_description=scene_description,
        visuals=visuals,
        scene_audio=scene_audio,
        aspect_ratio=aspect_ratio,
        duration_seconds=duration_seconds,
        continuity=continuity,
        meta=meta,
        hero_product_name=hero_product_name,
        product_reference_signature=product_reference_signature,
        product_visual_structure=product_visual_structure,
    )
    fallback_prompt = _render_fallback_prompt(bundle)
    messages = [
        {
            "role": "system",
            "content": PROMPT_COMPOSER_SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": (
                f"Compose one final {bundle['target']} prompt from the bundle below.\n\n"
                f"{json.dumps(bundle, ensure_ascii=False, indent=2)}"
            ),
        },
    ]

    prompt_text = ""
    composition_mode = "fallback"
    try:
        response = generate_content(
            model=PROMPT_COMPOSER_MODEL,
            messages=messages,
            timeout_seconds=180.0,
        )
        prompt_text = extract_response_text(response).strip()
        if prompt_text:
            composition_mode = "ai_composed"
    except Exception:
        prompt_text = ""

    return {
        "bundle": bundle,
        "prompt": prompt_text or fallback_prompt,
        "fallback_prompt": fallback_prompt,
        "composition_mode": composition_mode,
        "composer_model": PROMPT_COMPOSER_MODEL,
    }
