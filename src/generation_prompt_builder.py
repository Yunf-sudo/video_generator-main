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


def _normalized_lines(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, dict):
        lines: list[str] = []
        summary = _clean_text(value.get("summary", ""))
        if summary:
            lines.extend([line.strip() for line in summary.splitlines() if line.strip()])
        field_groups = [
            ("frame", "车架/轮廓"),
            ("seat_and_backrest", "座椅/靠背"),
            ("armrests", "扶手"),
            ("controller", "控制器"),
            ("rear_wheels", "后轮"),
            ("front_casters", "前万向轮"),
            ("footrests", "脚踏"),
            ("rear_details", "后部可见细节"),
            ("must_keep", "必须保留"),
            ("colors_and_materials", "材质/颜色"),
            ("must_avoid", "严格避免"),
        ]
        for key, label in field_groups:
            items = value.get(key)
            if isinstance(items, (list, tuple)):
                normalized = [_clean_text(item) for item in items if _clean_text(item)]
                if normalized:
                    limit = 6 if key != "must_avoid" else 5
                    lines.append(f"{label}：{', '.join(normalized[:limit])}")
        return lines
    return [line.strip() for line in _clean_text(value).splitlines() if line.strip()]


def _summarize_guidance(*parts: Any, max_lines: int = 6, line_limit: int = 180) -> str:
    seen: set[str] = set()
    lines: list[str] = []
    for part in parts:
        for line in _normalized_lines(part):
            compact = " ".join(str(line or "").split())
            if not compact:
                continue
            key = compact.lower()
            if key in seen:
                continue
            seen.add(key)
            if len(compact) > line_limit:
                compact = compact[: max(0, line_limit - 1)].rstrip() + "…"
            lines.append(compact)
            if len(lines) >= max_lines:
                return "\n".join(lines)
    return "\n".join(lines)


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
                "上一场景上下文：",
                previous_scene.get("theme", ""),
                previous_scene.get("scene_description", ""),
                previous_scene.get("key_message", ""),
            )
        )

    next_scene = continuity.get("next_scene")
    if isinstance(next_scene, dict):
        parts.append(
            _join_parts(
                "下一场景上下文：",
                next_scene.get("theme", ""),
                next_scene.get("scene_description", ""),
                next_scene.get("key_message", ""),
            )
        )

    return "\n".join(part for part in parts if part)


def _render_fallback_prompt(bundle: dict[str, Any]) -> str:
    blocks: list[str] = [
        (
            f"请为 {bundle['hero_product_name']} 生成一条可直接用于生产的 {bundle['target']} 提示词。"
            f"{bundle.get('delivery_specs', '')}".strip()
        ),
    ]

    if bundle.get("scene_description"):
        blocks.append(f"场景目标：{bundle['scene_description']}")

    shot_plan = _join_parts(bundle.get("scene_visual_plan", ""), bundle.get("continuity", ""))
    if shot_plan:
        blocks.append(f"镜头流程：{shot_plan}")

    creative_priorities = _join_parts(bundle.get("creative_direction", ""), bundle.get("special_emphasis", ""))
    if creative_priorities:
        blocks.append(f"画面方向与重点：{creative_priorities}")

    if bundle.get("product_identity"):
        blocks.append(f"需要保持一致：{bundle['product_identity']}")

    if bundle.get("audio_direction"):
        blocks.append(f"音频方向：{bundle['audio_direction']}")

    if bundle.get("reference_handling"):
        blocks.append(f"参考图使用方式：{bundle['reference_handling']}")

    if bundle.get("product_geometry_lock"):
        blocks.append(f"产品结构底线：{bundle['product_geometry_lock']}")

    if bundle.get("error_cases"):
        avoid_text = "; ".join(str(item).strip().rstrip(".") for item in bundle["error_cases"] if str(item).strip())
        if avoid_text:
            blocks.append(f"注意避免：{avoid_text}。")

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

    scene_visual_plan = _summarize_guidance(
        visuals.get("camera_movement", ""),
        visuals.get("lighting", ""),
        visuals.get("composition_and_set_dressing", ""),
        visuals.get("transition_anchor", ""),
        max_lines=4,
    )
    creative_direction = _summarize_guidance(
        meta.get("custom_style_notes", ""),
        meta.get("style_tone", ""),
        meta.get("reference_style", ""),
        meta.get("prompt_scene_description_notes", ""),
        max_lines=5,
    )
    special_emphasis = _summarize_guidance(
        meta.get("prompt_special_emphasis", ""),
        meta.get("core_selling_points", ""),
        meta.get("additional_info", ""),
        max_lines=6,
    )
    audio_direction = _summarize_guidance(
        scene_audio.get("voice_over", ""),
        scene_audio.get("text", ""),
        scene_audio.get("music", ""),
        scene_audio.get("sfx", ""),
        max_lines=4,
    )
    product_identity = _summarize_guidance(
        meta.get("consistency_anchor", ""),
        meta.get("product_geometry_notes", ""),
        product_reference_signature,
        product_visual_structure,
        max_lines=8,
    )
    product_geometry_lock = _summarize_guidance(meta.get("product_geometry_notes", ""), max_lines=4)
    risk_notes = list_error_cases(target, meta.get("prompt_error_notes", ""))[:4]

    bundle = _compact_dict(
        {
            "target": str(target or "").strip().lower() or "image",
            "hero_product_name": prompt_context["hero_product_name"],
            "scene_description": _summarize_guidance(
                scene_description,
                meta.get("prompt_scene_description_notes", ""),
                max_lines=5,
            ),
            "scene_visual_plan": scene_visual_plan,
            "creative_direction": creative_direction,
            "special_emphasis": special_emphasis,
            "product_geometry_lock": product_geometry_lock,
            "continuity": _continuity_summary(continuity),
            "audio_direction": audio_direction if str(target).strip().lower() == "video" else "",
            "product_identity": product_identity,
            "reference_handling": prompt_context["reference_image_instruction"],
            "delivery_specs": f"画幅 {aspect_ratio}；计划时长约 {duration_seconds} 秒。",
            "error_case_module": "prompt_error_cases",
            "error_case_text": render_error_case_text(target, meta.get("prompt_error_notes", "")),
            "error_cases": risk_notes,
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
    allow_ai_composer: bool = True,
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
                f"请根据下面这份提示词信息包，整理出一条最终可用的 {bundle['target']} 提示词。\n\n"
                f"{json.dumps(bundle, ensure_ascii=False, indent=2)}"
            ),
        },
    ]

    composition_mode = "fallback"
    prompt_text = ""
    if allow_ai_composer:
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
