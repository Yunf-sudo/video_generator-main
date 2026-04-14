from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
from pathlib import Path

import cv2
import numpy as np
from dotenv import load_dotenv
from openai import OpenAI
from workspace_paths import PROJECT_ROOT, cache_root

try:
    import json_repair
except ImportError:  # pragma: no cover - optional dependency
    json_repair = None


load_dotenv()

CACHE_PATH = cache_root() / "product_visual_structure_cache.json"
LEGACY_CACHE_PATHS = [
    PROJECT_ROOT / "product_visual_structure_cache.json",
]
VISION_MODEL = os.getenv("VISION_MODEL", os.getenv("META_MODEL", "gpt-5.2-all"))
VISION_TIMEOUT_SECONDS = float(os.getenv("VISION_TIMEOUT_SECONDS", "45"))
client = OpenAI(
    base_url="http://jeniya.cn/v1",
    api_key=os.getenv("JENIYA_API_TOKEN"),
    timeout=VISION_TIMEOUT_SECONDS,
)


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


def _encode_reference_image(path: str, max_edge: int = 1280, jpeg_quality: int = 82) -> str:
    resolved = Path(path).resolve()
    image_bytes = resolved.read_bytes()
    image_buffer = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(image_buffer, cv2.IMREAD_COLOR)
    mime = mimetypes.guess_type(str(resolved))[0] or "image/jpeg"
    payload = image_bytes

    if image is not None:
        height, width = image.shape[:2]
        longest_edge = max(height, width)
        if longest_edge > max_edge:
            scale = max_edge / float(longest_edge)
            resized_width = max(1, int(round(width * scale)))
            resized_height = max(1, int(round(height * scale)))
            image = cv2.resize(image, (resized_width, resized_height), interpolation=cv2.INTER_AREA)
        ok, encoded = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality])
        if ok:
            payload = encoded.tobytes()
            mime = "image/jpeg"

    encoded_text = base64.b64encode(payload).decode("utf-8")
    return f"data:{mime};base64,{encoded_text}"


def _reference_cache_key(reference_image_paths: list[str], model: str = VISION_MODEL) -> str:
    parts: list[str] = [f"model={model}"]
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

    user_content = [
        {
            "type": "text",
            "text": (
                "Analyze the wheelchair shown in these white-background product photos. "
                "Identify only visible physical structure and appearance. "
                "For advertising generation, treat any rear/lower removable battery pack or exposed battery cable as an omitted accessory, not a required visible feature. "
                "Do not describe folded, semi-folded, collapsed, storage, or folding/unfolding configurations as required output; the product should be represented in normal open riding position. "
                "Return one valid JSON object with these keys exactly: "
                "summary, frame, seat_and_backrest, armrests, controller, side_housing, rear_wheels, "
                "front_casters, footrests, rear_details, colors_and_materials, must_keep, must_avoid. "
                "Use concise phrases or short sentences. "
                "Do not describe the studio background, humans, marketing claims, or speculative internals."
            ),
        }
    ]
    for path in resolved_paths:
        user_content.append({"type": "image_url", "image_url": _encode_reference_image(path)})

    completion = client.chat.completions.create(
        model=VISION_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a product visual structure analyst. "
                    "You inspect multiple reference photos of the same product and summarize the exact visible structure. "
                    "Be strict about observable geometry and appearance, while excluding rear/lower removable battery packs, exposed battery cables, and folding-state demonstrations from required advertising visuals."
                ),
            },
            {
                "role": "user",
                "content": user_content,
            },
        ],
    )
    content = completion.choices[0].message.content
    structure = _load_json_object(content)
    if not isinstance(structure, dict) or not structure:
        raise RuntimeError(f"Unable to parse product visual structure JSON: {content}")

    _write_cache(
        {
            "cache_key": cache_key,
            "model": VISION_MODEL,
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
        joined = "; ".join(values)
        lines.append(f"{label}: {joined}")
    return "\n".join(lines)
