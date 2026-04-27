from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

from google_gemini_api import DEFAULT_TEXT_MODEL, extract_response_text, generate_content
from runtime_tunables_config import load_runtime_tunables

try:
    import json_repair
except ImportError:  # pragma: no cover - optional dependency
    json_repair = None


load_dotenv()

RUNTIME_TUNABLES = load_runtime_tunables()
STORYBOARD_GUARDRAIL_MODEL = os.getenv(
    "STORYBOARD_GUARDRAIL_MODEL",
    os.getenv("VISION_MODEL", str(RUNTIME_TUNABLES["model_config"].get("vision_model") or DEFAULT_TEXT_MODEL)),
).strip() or DEFAULT_TEXT_MODEL
STORYBOARD_GUARDRAIL_PROMPT_VERSION = "2026-04-27-storyboard-guardrails-v2"

STORYBOARD_IMAGE_GUARDRAIL_SCHEMA = {
    "type": "object",
    "properties": {
        "has_disallowed_text": {"type": "boolean"},
        "detected_text_kind": {"type": "string"},
        "reason": {"type": "string"},
        "evidence": {"type": "array", "items": {"type": "string"}},
    },
}

STORYBOARD_VISUAL_GUARDRAIL_SCHEMA = {
    "type": "object",
    "properties": {
        "is_photorealistic": {"type": "boolean"},
        "has_identity_drift": {"type": "boolean"},
        "has_wheelchair_drift": {"type": "boolean"},
        "has_control_interaction_error": {"type": "boolean"},
        "has_backrest_logo_error": {"type": "boolean"},
        "reason": {"type": "string"},
        "evidence": {"type": "array", "items": {"type": "string"}},
    },
}


def _load_json_object(raw_text: str) -> dict:
    text = (raw_text or "").strip()
    if not text:
        return {}
    if json_repair is not None:
        try:
            return json_repair.loads(text)
        except Exception:
            pass
    try:
        return json.loads(text)
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        sliced = text[start : end + 1]
        if json_repair is not None:
            try:
                return json_repair.loads(sliced)
            except Exception:
                pass
        try:
            return json.loads(sliced)
        except Exception:
            return {}
    return {}


def _resolved_existing_paths(paths: list[str] | None) -> list[Path]:
    resolved_paths: list[Path] = []
    for path in paths or []:
        resolved = Path(str(path or "").strip()).resolve()
        if resolved.exists() and resolved not in resolved_paths:
            resolved_paths.append(resolved)
    return resolved_paths


def inspect_storyboard_image_cleanliness(image_path: str) -> dict:
    resolved = Path(image_path).resolve()
    if not resolved.exists():
        return {
            "status": "missing_image",
            "has_disallowed_text": False,
            "reason": f"Image not found: {resolved}",
            "evidence": [],
            "detected_text_kind": "",
            "validator_model": STORYBOARD_GUARDRAIL_MODEL,
            "prompt_version": STORYBOARD_GUARDRAIL_PROMPT_VERSION,
        }

    try:
        response = generate_content(
            model=STORYBOARD_GUARDRAIL_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是一名广告分镜图质检员。"
                        "你的任务是判断画面中是否出现了不该有的可读文字或文字化叠加。"
                        "必须拦截的内容包括：字幕、lower-third、价格字、促销文案、贴片、角标、水印、UI、按钮、对话框、"
                        "社媒界面元素、海报式大字、屏幕字幕、以及看起来像文字的乱码字形。"
                        "如果画面只是给后期预留空白区域，但区域里没有实际文字，那不算失败。"
                        "如果轮椅靠背布面上有很小的产品自带品牌标识，并且它明显是产品一部分而不是叠加字幕，可以不算失败。"
                        "只返回一个 JSON 对象。"
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "请检查这张分镜图是否含有不该出现的画面文字或字幕。"
                                "如果存在，只按肉眼可见证据总结，不要猜。"
                            ),
                        },
                        {"type": "image_url", "image_url": str(resolved)},
                    ],
                },
            ],
            response_mime_type="application/json",
            response_json_schema=STORYBOARD_IMAGE_GUARDRAIL_SCHEMA,
            timeout_seconds=90.0,
        )
        parsed = _load_json_object(extract_response_text(response))
    except Exception as exc:
        return {
            "status": "unknown",
            "has_disallowed_text": False,
            "reason": str(exc),
            "evidence": [],
            "detected_text_kind": "",
            "validator_model": STORYBOARD_GUARDRAIL_MODEL,
            "prompt_version": STORYBOARD_GUARDRAIL_PROMPT_VERSION,
        }

    has_disallowed_text = bool(parsed.get("has_disallowed_text"))
    evidence = parsed.get("evidence")
    if not isinstance(evidence, list):
        evidence = []
    return {
        "status": "failed" if has_disallowed_text else "passed",
        "has_disallowed_text": has_disallowed_text,
        "reason": str(parsed.get("reason", "") or "").strip(),
        "evidence": [str(item).strip() for item in evidence if str(item).strip()][:5],
        "detected_text_kind": str(parsed.get("detected_text_kind", "") or "").strip(),
        "validator_model": STORYBOARD_GUARDRAIL_MODEL,
        "prompt_version": STORYBOARD_GUARDRAIL_PROMPT_VERSION,
    }


def inspect_storyboard_image_visual_quality(
    image_path: str,
    continuity_reference_paths: list[str] | None = None,
    expect_joystick_pinch_visible: bool = False,
    expect_backrest_logo_visible: bool = False,
) -> dict:
    resolved = Path(image_path).resolve()
    if not resolved.exists():
        return {
            "status": "missing_image",
            "is_photorealistic": True,
            "has_identity_drift": False,
            "has_wheelchair_drift": False,
            "has_control_interaction_error": False,
            "has_backrest_logo_error": False,
            "reason": f"Image not found: {resolved}",
            "evidence": [],
            "validator_model": STORYBOARD_GUARDRAIL_MODEL,
            "prompt_version": STORYBOARD_GUARDRAIL_PROMPT_VERSION,
            "reference_count": 0,
        }

    reference_paths = [path for path in _resolved_existing_paths(continuity_reference_paths) if path != resolved][:2]
    user_content: list[dict] = [
        {
            "type": "text",
            "text": (
                "第一张图是当前待检分镜图。"
                "后面若还有图片，则它们是同一条广告前序场景的参考帧。"
                "请判断当前图是否仍然是照片级真实的真人商业分镜，"
                "并且在有人物时，是否保持同一个乘坐者与同一台轮椅。"
                f"{' 这张图还必须能看清乘坐者右手用大拇指和食指捏住右侧摇杆。' if expect_joystick_pinch_visible else ''}"
                f"{' 这张图还必须在可见的靠背上半部布面上看到居中的 AnyWell 标识。' if expect_backrest_logo_visible else ''}"
            ),
        },
        {"type": "image_url", "image_url": str(resolved)},
    ]
    for path in reference_paths:
        user_content.append({"type": "image_url", "image_url": str(path)})

    try:
        response = generate_content(
            model=STORYBOARD_GUARDRAIL_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是一名广告分镜图质检员。"
                        "你要检查当前分镜图是否保持照片级真实，而不是卡通、动画、插画、3D 渲染、CGI、塑料假人或游戏资产风格。"
                        "如果后面提供了前序场景参考图，还要检查当前图是否保持同一个人物和同一台轮椅。"
                        "人物连续性只按肉眼可见证据判断：脸、发型、体型、肤色、服装、年龄感。"
                        "轮椅连续性只按肉眼可见证据判断：车架轮廓、轮组比例、座椅/靠背、扶手、摇杆侧。"
                        "如果用户要求可见的自驾操控手势，就要检查右手是否真的用大拇指和食指捏住右侧摇杆，而不是随便搭着、握拳、平掌盖住或根本没碰到。"
                        "如果用户要求可见的靠背品牌标识，就要检查靠背上半部布面是否确实出现居中的 AnyWell 标识，而不是缺失或跑到别的位置。"
                        "只返回一个 JSON 对象。"
                    ),
                },
                {"role": "user", "content": user_content},
            ],
            response_mime_type="application/json",
            response_json_schema=STORYBOARD_VISUAL_GUARDRAIL_SCHEMA,
            timeout_seconds=90.0,
        )
        parsed = _load_json_object(extract_response_text(response))
    except Exception as exc:
        return {
            "status": "unknown",
            "is_photorealistic": True,
            "has_identity_drift": False,
            "has_wheelchair_drift": False,
            "has_control_interaction_error": False,
            "has_backrest_logo_error": False,
            "reason": str(exc),
            "evidence": [],
            "validator_model": STORYBOARD_GUARDRAIL_MODEL,
            "prompt_version": STORYBOARD_GUARDRAIL_PROMPT_VERSION,
            "reference_count": len(reference_paths),
        }

    is_photorealistic = bool(parsed.get("is_photorealistic", True))
    has_identity_drift = bool(parsed.get("has_identity_drift", False))
    has_wheelchair_drift = bool(parsed.get("has_wheelchair_drift", False))
    has_control_interaction_error = bool(parsed.get("has_control_interaction_error", False))
    has_backrest_logo_error = bool(parsed.get("has_backrest_logo_error", False))
    evidence = parsed.get("evidence")
    if not isinstance(evidence, list):
        evidence = []
    failed = (
        (not is_photorealistic)
        or has_identity_drift
        or has_wheelchair_drift
        or has_control_interaction_error
        or has_backrest_logo_error
    )
    return {
        "status": "failed" if failed else "passed",
        "is_photorealistic": is_photorealistic,
        "has_identity_drift": has_identity_drift,
        "has_wheelchair_drift": has_wheelchair_drift,
        "has_control_interaction_error": has_control_interaction_error,
        "has_backrest_logo_error": has_backrest_logo_error,
        "reason": str(parsed.get("reason", "") or "").strip(),
        "evidence": [str(item).strip() for item in evidence if str(item).strip()][:5],
        "validator_model": STORYBOARD_GUARDRAIL_MODEL,
        "prompt_version": STORYBOARD_GUARDRAIL_PROMPT_VERSION,
        "reference_count": len(reference_paths),
    }
