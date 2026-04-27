from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from agent_bundle_env import load_agent_bundle_env

from google_gemini_api import DEFAULT_TEXT_MODEL, extract_response_text, generate_content, image_part_from_path
from runtime_tunables_config import load_runtime_tunables
from workspace_paths import PROJECT_ROOT, cache_root

try:
    import json_repair
except ImportError:  # pragma: no cover - optional dependency
    json_repair = None


load_agent_bundle_env()

CACHE_PATH = cache_root() / "product_visual_structure_cache.json"
LEGACY_CACHE_PATHS = [
    PROJECT_ROOT / "product_visual_structure_cache.json",
]
RUNTIME_TUNABLES = load_runtime_tunables()
VISION_MODEL = os.getenv(
    "VISION_MODEL",
    os.getenv("META_MODEL", str(RUNTIME_TUNABLES["model_config"].get("vision_model") or DEFAULT_TEXT_MODEL)),
)
VISION_PROMPT_VERSION = "2026-04-27-reference-sheet-v1"

VISION_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "array", "items": {"type": "string"}},
        "frame": {"type": "array", "items": {"type": "string"}},
        "seat_and_backrest": {"type": "array", "items": {"type": "string"}},
        "armrests": {"type": "array", "items": {"type": "string"}},
        "controller": {"type": "array", "items": {"type": "string"}},
        "side_housing": {"type": "array", "items": {"type": "string"}},
        "rear_wheels": {"type": "array", "items": {"type": "string"}},
        "front_casters": {"type": "array", "items": {"type": "string"}},
        "footrests": {"type": "array", "items": {"type": "string"}},
        "rear_details": {"type": "array", "items": {"type": "string"}},
        "colors_and_materials": {"type": "array", "items": {"type": "string"}},
        "must_keep": {"type": "array", "items": {"type": "string"}},
        "must_avoid": {"type": "array", "items": {"type": "string"}},
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
        return json.loads(sliced)
    return {}


def _reference_cache_key(reference_image_paths: list[str], model: str = VISION_MODEL) -> str:
    parts: list[str] = [f"model={model}", f"prompt_version={VISION_PROMPT_VERSION}"]
    for raw_path in reference_image_paths:
        path = Path(raw_path).resolve()
        stat = path.stat()
        parts.append(f"{path}|{stat.st_mtime_ns}|{stat.st_size}")
    return hashlib.sha256("||".join(parts).encode("utf-8")).hexdigest()


def _is_valid_cached_payload(payload: object) -> bool:
    return isinstance(payload, dict) and isinstance(payload.get("structure"), dict) and bool(payload["structure"])


def _load_cached_payload(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if _is_valid_cached_payload(payload) else {}


def _read_cache() -> dict:
    current_payload = _load_cached_payload(CACHE_PATH)
    if current_payload:
        return current_payload
    for legacy_path in LEGACY_CACHE_PATHS:
        legacy_payload = _load_cached_payload(legacy_path)
        if not legacy_payload:
            continue
        try:
            _write_cache(legacy_payload)
        except Exception:
            pass
        return legacy_payload
    return {}


def _write_cache(payload: dict) -> None:
    CACHE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def analyze_product_visual_structure(reference_image_paths: list[str], force_refresh: bool = False) -> dict:
    resolved_paths = [str(Path(path).resolve()) for path in reference_image_paths if Path(path).exists()]
    if not resolved_paths:
        return {}

    cache_key = _reference_cache_key(resolved_paths)
    cached = _read_cache()
    if not force_refresh and cached.get("cache_key") == cache_key and isinstance(cached.get("structure"), dict):
        return cached["structure"]

    user_parts = [
        {
            "text": (
                "Analyze the wheelchair shown in these product reference images. "
                "The inputs may be white-background photos, multi-view reference sheets, or close-up collages. "
                "Ignore panel labels, Chinese text, divider lines, margins, and collage layout. "
                "Identify only visible physical structure and appearance that belong to the actual wheelchair. "
                "For advertising generation, treat any rear/lower removable battery pack or exposed battery cable as an omitted accessory, not a required visible feature. "
                "Do not describe folded, semi-folded, collapsed, storage, or folding/unfolding configurations as required output. "
                "Do not infer hidden geometry from unseen angles, and do not treat the sheet layout itself as a product feature. "
                "Return one JSON object only with these keys exactly: "
                "summary, frame, seat_and_backrest, armrests, controller, side_housing, rear_wheels, front_casters, footrests, rear_details, colors_and_materials, must_keep, must_avoid."
            )
        }
    ]
    for path in resolved_paths:
        user_parts.append(image_part_from_path(path))

    response = generate_content(
        model=VISION_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a product visual structure analyst. "
                    "Summarize exact visible geometry and appearance only. "
                    "The reference may include multi-view montage images with labels and close-up panels; ignore those editorial elements. "
                    "Exclude rear/lower removable battery packs, exposed battery cables, and folding-state demonstrations from required advertising visuals."
                ),
            },
            {
                "role": "user",
                "content": user_parts,
            },
        ],
        response_mime_type="application/json",
        response_json_schema=VISION_SCHEMA,
        timeout_seconds=180.0,
    )
    content = extract_response_text(response)
    structure = _load_json_object(content)
    if not isinstance(structure, dict) or not structure:
        raise RuntimeError(f"Unable to parse product visual structure JSON: {content}")

    _write_cache(
        {
            "cache_key": cache_key,
            "model": VISION_MODEL,
            "prompt_version": VISION_PROMPT_VERSION,
            "reference_image_paths": resolved_paths,
            "structure": structure,
        }
    )
    return structure


def _as_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def format_product_visual_structure(structure: dict) -> str:
    if not structure:
        return ""

    ordered_keys = [
        ("summary", "Overall silhouette"),
        ("frame", "Frame"),
        ("seat_and_backrest", "Seat/backrest"),
        ("armrests", "Armrests"),
        ("controller", "Controller"),
        ("side_housing", "Side housing"),
        ("rear_wheels", "Rear wheels"),
        ("front_casters", "Front casters"),
        ("footrests", "Footrests"),
        ("rear_details", "Rear details"),
        ("colors_and_materials", "Colors/materials"),
        ("must_keep", "Must keep"),
        ("must_avoid", "Must avoid"),
    ]
    lines: list[str] = []
    for key, label in ordered_keys:
        values = _as_list(structure.get(key))
        if not values:
            continue
        lines.append(f"{label}: {'; '.join(values)}")
    return "\n".join(lines)
