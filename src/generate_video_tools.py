from __future__ import annotations

import base64
from collections import deque
import json
import mimetypes
import os
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import cv2
import numpy as np
from dotenv import load_dotenv

from generation_prompt_builder import compose_generation_prompt
from media_pipeline import generate_local_clip, probe_media_duration
from prompt_overrides import apply_override
from product_reference_images import (
    get_product_reference_images,
    get_product_reference_signature,
    get_product_visual_structure_json,
)
from runtime_tunables_config import load_runtime_tunables
from workspace_paths import cache_root, ensure_active_run


load_dotenv()

RUNTIME_TUNABLES = load_runtime_tunables()
VIDEO_RUNTIME = RUNTIME_TUNABLES["video_runtime"]

GOOGLE_VIDEO_BASE_URL = os.getenv(
    "GOOGLE_VIDEO_BASE_URL",
    str(VIDEO_RUNTIME.get("google_video_base_url") or "https://generativelanguage.googleapis.com/v1beta"),
).strip()
VIDEO_PROVIDER = str(VIDEO_RUNTIME.get("video_provider") or "google").strip() or "google"
VIDEO_MODEL = os.getenv(
    "VIDEO_MODEL",
    str(RUNTIME_TUNABLES["model_config"].get("video_model") or "veo-3.1-generate-preview"),
).strip() or "veo-3.1-generate-preview"
VIDEO_REFERENCE_MODE = os.getenv(
    "VIDEO_REFERENCE_MODE",
    str(VIDEO_RUNTIME.get("video_reference_mode") or "image"),
).strip().lower()
VIDEO_RESOLUTION = (
    os.getenv("VIDEO_RESOLUTION", str(VIDEO_RUNTIME.get("video_resolution") or "1080p")).strip() or "1080p"
).lower()
VIDEO_NEGATIVE_PROMPT = os.getenv(
    "VIDEO_NEGATIVE_PROMPT",
    str(VIDEO_RUNTIME.get("video_negative_prompt") or ""),
).strip()
VIDEO_HTTP_TIMEOUT_SECONDS = max(
    60.0,
    float(os.getenv("VIDEO_HTTP_TIMEOUT_SECONDS", str(VIDEO_RUNTIME.get("video_http_timeout_seconds") or 180)).strip() or 180),
)
GOOGLE_VEO_COST_SAFE_MODE = str(
    os.getenv("GOOGLE_VEO_COST_SAFE_MODE", str(VIDEO_RUNTIME.get("google_veo_cost_safe_mode", True)))
).strip().lower() not in {"0", "false", "no", "off"}
GOOGLE_VEO_MAX_REQUESTS_PER_MINUTE = max(
    1,
    int(
        os.getenv(
            "GOOGLE_VEO_MAX_REQUESTS_PER_MINUTE",
            str(VIDEO_RUNTIME.get("google_veo_max_requests_per_minute") or 2),
        ).strip()
        or 2
    ),
)
GOOGLE_VEO_RATE_WINDOW_SECONDS = float(VIDEO_RUNTIME.get("google_veo_rate_window_seconds") or 60.0)
GOOGLE_VEO_SUBMIT_MAX_ATTEMPTS = max(
    1,
    int(
        os.getenv(
            "GOOGLE_VEO_SUBMIT_MAX_ATTEMPTS",
            str(
                VIDEO_RUNTIME.get("google_veo_submit_max_attempts")
                or ("1" if GOOGLE_VEO_COST_SAFE_MODE else "3")
            ),
        ).strip()
        or 1
    ),
)
GOOGLE_VEO_QUERY_MAX_ATTEMPTS = max(
    1,
    int(os.getenv("GOOGLE_VEO_QUERY_MAX_ATTEMPTS", str(VIDEO_RUNTIME.get("google_veo_query_max_attempts") or 3)).strip() or 3),
)
GOOGLE_VEO_ALLOW_PROMPT_FALLBACKS = str(
    os.getenv(
        "GOOGLE_VEO_ALLOW_PROMPT_FALLBACKS",
        str(
            VIDEO_RUNTIME.get("google_veo_allow_prompt_fallbacks")
            if VIDEO_RUNTIME.get("google_veo_allow_prompt_fallbacks") is not None
            else (False if GOOGLE_VEO_COST_SAFE_MODE else True)
        ),
    )
).strip().lower() not in {"0", "false", "no", "off"}
GOOGLE_VEO_PREFLIGHT_TTL_SECONDS = max(
    60.0,
    float(
        os.getenv(
            "GOOGLE_VEO_PREFLIGHT_TTL_SECONDS",
            str(VIDEO_RUNTIME.get("google_veo_preflight_ttl_seconds") or 600),
        ).strip()
        or 600
    ),
)
GOOGLE_VEO_QUOTA_COOLDOWN_SECONDS = max(
    60.0,
    float(
        os.getenv(
            "GOOGLE_VEO_QUOTA_COOLDOWN_SECONDS",
            str(VIDEO_RUNTIME.get("google_veo_quota_cooldown_seconds") or 1800),
        ).strip()
        or 1800
    ),
)
GOOGLE_VEO_PROMPT_MAX_CHARS = max(
    800,
    int(
        os.getenv(
            "GOOGLE_VEO_PROMPT_MAX_CHARS",
            str(VIDEO_RUNTIME.get("google_veo_prompt_max_chars") or 950),
        ).strip()
        or 950
    ),
)


_GOOGLE_REQUEST_TIMESTAMPS: deque[float] = deque()
_GOOGLE_REQUEST_LOCK = threading.Lock()
_GOOGLE_PREFLIGHT_LOCK = threading.Lock()
_GOOGLE_PREFLIGHT_CACHE: dict[str, float | str] = {}


def _google_preflight_cache_path() -> Path:
    return cache_root() / "google_veo_preflight.json"


def _google_quota_guard_path() -> Path:
    return cache_root() / "google_veo_quota_guard.json"


def _google_api_key() -> str:
    value = (
        os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
        or os.getenv("GOOGLE_GENAI_API_KEY")
    )
    if not value:
        raise ValueError("Missing GEMINI_API_KEY or GOOGLE_API_KEY for Google Veo generation.")
    return value.strip().strip('"')


def _normalized_model_name(model: str | None = None) -> str:
    normalized = (model or VIDEO_MODEL).strip() or VIDEO_MODEL
    if not normalized.startswith("models/"):
        normalized = f"models/{normalized}"
    return normalized


def _read_guard_payload(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _write_guard_payload(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _extract_error_text(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return f"{exc}; body: {body[:4000]}".strip()
    return str(exc)


def _is_quota_exhausted_message(message: str) -> bool:
    lowered = (message or "").lower()
    return any(
        marker in lowered
        for marker in (
            "resource_exhausted",
            "exceeded your current quota",
            "current quota",
            "billing details",
            "rate-limits",
        )
    )


def _set_google_quota_cooldown(reason: str) -> None:
    expires_at = time.time() + GOOGLE_VEO_QUOTA_COOLDOWN_SECONDS
    _write_guard_payload(
        _google_quota_guard_path(),
        {
            "expires_at": expires_at,
            "reason": reason.strip()[:4000],
            "updated_at": time.time(),
        },
    )


def _active_google_quota_cooldown_reason() -> str:
    payload = _read_guard_payload(_google_quota_guard_path())
    expires_at = float(payload.get("expires_at") or 0)
    if expires_at <= time.time():
        return ""
    remaining_seconds = max(0, int(round(expires_at - time.time())))
    remaining_minutes = max(1, (remaining_seconds + 59) // 60)
    reason = str(payload.get("reason") or "").strip()
    return (
        f"Google Veo remote submit is paused for about {remaining_minutes} more minute(s) "
        f"after a quota/billing exhaustion response. Last reason: {reason}"
    ).strip()


def _ensure_google_model_preflight(model: str | None = None) -> None:
    normalized_model = _normalized_model_name(model)
    with _GOOGLE_PREFLIGHT_LOCK:
        now = time.time()
        cached_model = str(_GOOGLE_PREFLIGHT_CACHE.get("model") or "")
        cached_at = float(_GOOGLE_PREFLIGHT_CACHE.get("checked_at") or 0)
        if cached_model == normalized_model and now - cached_at < GOOGLE_VEO_PREFLIGHT_TTL_SECONDS:
            return

        payload = _read_guard_payload(_google_preflight_cache_path())
        cached_model = str(payload.get("model") or "")
        cached_at = float(payload.get("checked_at") or 0)
        if cached_model == normalized_model and now - cached_at < GOOGLE_VEO_PREFLIGHT_TTL_SECONDS:
            _GOOGLE_PREFLIGHT_CACHE["model"] = cached_model
            _GOOGLE_PREFLIGHT_CACHE["checked_at"] = cached_at
            return

        models_response = _request_json("GET", f"{GOOGLE_VIDEO_BASE_URL}/models")
        visible_models = {
            str(item.get("name") or "").strip()
            for item in models_response.get("models", [])
            if isinstance(item, dict)
        }
        if normalized_model not in visible_models:
            raise RuntimeError(
                f"Google Veo preflight failed: {normalized_model} is not visible to the current API key."
            )

        _GOOGLE_PREFLIGHT_CACHE["model"] = normalized_model
        _GOOGLE_PREFLIGHT_CACHE["checked_at"] = now
        _write_guard_payload(
            _google_preflight_cache_path(),
            {
                "model": normalized_model,
                "checked_at": now,
            },
        )


def _ensure_google_submit_allowed(model: str | None = None) -> None:
    cooldown_reason = _active_google_quota_cooldown_reason()
    if cooldown_reason:
        raise RuntimeError(cooldown_reason)
    _ensure_google_model_preflight(model)


def _throttle_google_request() -> None:
    while True:
        sleep_seconds = 0.0
        with _GOOGLE_REQUEST_LOCK:
            now = time.monotonic()
            while _GOOGLE_REQUEST_TIMESTAMPS and now - _GOOGLE_REQUEST_TIMESTAMPS[0] >= GOOGLE_VEO_RATE_WINDOW_SECONDS:
                _GOOGLE_REQUEST_TIMESTAMPS.popleft()

            if len(_GOOGLE_REQUEST_TIMESTAMPS) < GOOGLE_VEO_MAX_REQUESTS_PER_MINUTE:
                _GOOGLE_REQUEST_TIMESTAMPS.append(now)
                return

            sleep_seconds = max(
                0.0,
                GOOGLE_VEO_RATE_WINDOW_SECONDS - (now - _GOOGLE_REQUEST_TIMESTAMPS[0]),
            )

        if sleep_seconds > 0:
            # Keep the whole process within the configured Veo request budget.
            time.sleep(sleep_seconds)


def _request_json(method: str, url: str, payload_json: Optional[dict[str, Any]] = None) -> Dict[str, Any]:
    last_error: Exception | None = None
    max_attempts = GOOGLE_VEO_QUERY_MAX_ATTEMPTS if method.upper() == "GET" else GOOGLE_VEO_SUBMIT_MAX_ATTEMPTS
    for attempt in range(1, max_attempts + 1):
        _throttle_google_request()
        request = urllib.request.Request(
            url,
            data=json.dumps(payload_json or {}, ensure_ascii=False).encode("utf-8") if payload_json is not None else None,
            headers={
                "x-goog-api-key": _google_api_key(),
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0",
            },
            method=method.upper(),
        )
        try:
            with urllib.request.urlopen(request, timeout=VIDEO_HTTP_TIMEOUT_SECONDS) as response:
                raw = response.read()
            text = raw.decode("utf-8", errors="replace")
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"raw": text}
        except Exception as exc:
            last_error = exc
            message = _extract_error_text(exc)
            if _is_quota_exhausted_message(message):
                _set_google_quota_cooldown(message)
            transient_markers = [
                "Remote end closed connection without response",
                "timed out",
                "timeout",
                "UNEXPECTED_EOF_WHILE_READING",
                "EOF occurred in violation of protocol",
                "EOF occurred",
                "SSL:",
                "429",
                "500",
                "502",
                "503",
                "RESOURCE_EXHAUSTED",
            ]
            if attempt >= max_attempts or not any(marker in message for marker in transient_markers):
                raise RuntimeError(f"Google Veo API request failed: {message}") from exc
            time.sleep(5.0 * attempt)
    raise RuntimeError(f"Google Veo API request failed after retries: {last_error}")


def _google_submit_url(model: str) -> str:
    normalized = model.strip() or VIDEO_MODEL
    if not normalized.startswith("models/"):
        normalized = f"models/{normalized}"
    return f"{GOOGLE_VIDEO_BASE_URL}/{normalized}:predictLongRunning"


def _google_operation_url(operation_name: str) -> str:
    normalized = operation_name.strip()
    if normalized.startswith(("http://", "https://")):
        return normalized
    normalized = normalized.lstrip("/")
    if normalized.startswith("models/"):
        return f"{GOOGLE_VIDEO_BASE_URL}/{normalized}"
    if not normalized.startswith("operations/"):
        normalized = f"operations/{normalized}"
    return f"{GOOGLE_VIDEO_BASE_URL}/{normalized}"


def _find_video_url(value: Any) -> str | None:
    if isinstance(value, str):
        if value.startswith(("http://", "https://")) and (".mp4" in value or "/files/" in value or "video" in value):
            return value
        return None
    if isinstance(value, dict):
        for key in ("uri", "url", "videoUri", "video_url", "downloadUri", "download_uri"):
            found = _find_video_url(value.get(key))
            if found:
                return found
        for nested in value.values():
            found = _find_video_url(nested)
            if found:
                return found
    if isinstance(value, list):
        for item in value:
            found = _find_video_url(item)
            if found:
                return found
    return None


def _extract_video_id(response: dict[str, Any]) -> str | None:
    for key in ("name", "id", "video_id", "task_id", "request_id"):
        value = response.get(key)
        if value:
            return str(value)
    return None


def _extract_status(response: dict[str, Any]) -> str | None:
    if response.get("error"):
        return "failed"
    if "done" in response:
        return "completed" if bool(response.get("done")) else "running"
    if _find_video_url(response):
        return "completed"
    return None


def _file_to_data_url(file_path: str | None) -> str | None:
    if not file_path:
        return None
    resolved = Path(file_path)
    if not resolved.exists():
        return None
    mime = mimetypes.guess_type(str(resolved))[0] or "image/png"
    image_bytes = resolved.read_bytes()
    if len(image_bytes) > 1_500_000:
        image_buffer = np.frombuffer(image_bytes, dtype=np.uint8)
        image = cv2.imdecode(image_buffer, cv2.IMREAD_COLOR)
        if image is not None:
            height, width = image.shape[:2]
            longest_edge = max(height, width)
            if longest_edge > 1280:
                scale = 1280.0 / float(longest_edge)
                resized_width = max(1, int(round(width * scale)))
                resized_height = max(1, int(round(height * scale)))
                image = cv2.resize(image, (resized_width, resized_height), interpolation=cv2.INTER_AREA)
            ok, encoded_image = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
            if ok:
                mime = "image/jpeg"
                image_bytes = encoded_image.tobytes()
    encoded = base64.b64encode(image_bytes).decode("utf-8")
    return f"data:{mime};base64,{encoded}"


def _inline_asset_from_value(asset_value: str | None) -> dict[str, str] | None:
    if not asset_value:
        return None

    normalized = asset_value
    if normalized.startswith("data:") and ";base64," in normalized:
        header, encoded = normalized.split(",", 1)
        mime_type = header[5:].split(";", 1)[0] or "image/jpeg"
        return {
            "mimeType": mime_type,
            "bytesBase64Encoded": encoded,
        }

    if asset_value.startswith(("http://", "https://")):
        request = urllib.request.Request(asset_value, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=VIDEO_HTTP_TIMEOUT_SECONDS) as response:
            payload = response.read()
            mime_type = response.headers.get_content_type() or "image/jpeg"
        return {
            "mimeType": mime_type,
            "bytesBase64Encoded": base64.b64encode(payload).decode("utf-8"),
        }

    try:
        if Path(asset_value).exists():
            normalized = _file_to_data_url(asset_value)
    except OSError:
        return None

    if normalized and normalized.startswith("data:") and ";base64," in normalized:
        header, encoded = normalized.split(",", 1)
        mime_type = header[5:].split(";", 1)[0] or "image/jpeg"
        return {
            "mimeType": mime_type,
            "bytesBase64Encoded": encoded,
        }
    return None


def _google_duration_seconds(duration_seconds: int | float) -> int:
    if VIDEO_RESOLUTION == "1080p":
        return 8
    target = int(round(float(duration_seconds or 0))) if duration_seconds else 0
    allowed = (4, 6, 8)
    if target in allowed:
        return target
    if target <= 0:
        target = 8
    return min(allowed, key=lambda option: (abs(option - target), option))


def _google_person_generation(has_reference_image: bool) -> str:
    return "allow_adult" if has_reference_image else "allow_all"


def _should_use_reference_images() -> bool:
    return VIDEO_REFERENCE_MODE in {"image", "images", "hybrid"}


def _compact_value_list(value: Any, limit: int) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()][:limit]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _single_line(value: Any, limit: int = 280) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _visuals_summary(visuals: Dict[str, Any] | None) -> str:
    visuals = visuals or {}
    parts = [
        _single_line(visuals.get("camera_movement", ""), 80),
        _single_line(visuals.get("composition_and_set_dressing", ""), 80),
        _single_line(visuals.get("transition_anchor", ""), 60),
    ]
    return " ".join(part for part in parts if part)


def _truncate_to_max_bytes(text: str, max_bytes: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore").rstrip()


def _build_compact_veo_prompt(
    scene_info: str,
    visuals: Dict[str, Any] | None,
    scene_audio: Dict[str, Any] | None,
    aspect_ratio: str,
    duration_seconds: int,
) -> str:
    voiceover = ""
    if isinstance(scene_audio, dict):
        voiceover = _single_line(scene_audio.get("voice_over") or scene_audio.get("text") or "", 140)

    blocks = [
        f"Photorealistic live-action {duration_seconds}s vertical video ({aspect_ratio}) from storyboard image.",
        "Preserve same heavyset Western elderly rider, AnyWell powered wheelchair, wardrobe, location, lighting.",
        "Right hand pinches joystick with thumb and index finger; no hands-free driving.",
        "Front caster: pivot ahead, fork/yoke trails backward, axle behind pivot.",
        "Both armrests stay present and symmetric. Seat underside stays open: tubular frame and ground visible; no black box, battery, bag, or solid block.",
        "Camera stays front-side, joystick-side, or clean side profile; never finish rear/back-only.",
        "No morphing, scene reset, cartoon, CGI, plastic people, side logos, rear poles, exposed battery, text, watermark, or UI.",
        f"Action: {_single_line(scene_info, 140)}",
        f"Camera/motion: {_visuals_summary(visuals)}",
        "Animate believable wheel roll and smooth camera motion.",
    ]
    if voiceover:
        blocks.append(f"Emotional tone: {voiceover}")
    return "\n".join(block for block in blocks if block.strip())


def _fit_veo_prompt(
    prompt: str,
    scene_info: str,
    visuals: Dict[str, Any] | None,
    scene_audio: Dict[str, Any] | None,
    aspect_ratio: str,
    duration_seconds: int,
) -> tuple[str, bool]:
    prompt = str(prompt or "").strip()
    if len(prompt.encode("utf-8")) <= GOOGLE_VEO_PROMPT_MAX_CHARS:
        return prompt, False

    compact_prompt = _build_compact_veo_prompt(
        scene_info=scene_info,
        visuals=visuals,
        scene_audio=scene_audio,
        aspect_ratio=aspect_ratio,
        duration_seconds=duration_seconds,
    )
    if len(compact_prompt.encode("utf-8")) <= GOOGLE_VEO_PROMPT_MAX_CHARS:
        return compact_prompt, True
    return _truncate_to_max_bytes(compact_prompt, GOOGLE_VEO_PROMPT_MAX_CHARS), True


def crop_image_to_ratio(src_path: str, ratio: str = "9:16") -> str:
    img = cv2.imread(src_path)
    if img is None:
        return src_path
    h, w = img.shape[:2]
    if h == 0 or w == 0:
        return src_path

    try:
        ratio_w, ratio_h = (float(part) for part in ratio.split(":", 1))
    except Exception:
        return src_path

    if ratio_w <= 0 or ratio_h <= 0:
        return src_path

    target_h = int(w * ratio_h / ratio_w)
    if 0 < target_h <= h:
        y0 = (h - target_h) // 2
        cropped = img[y0 : y0 + target_h, 0:w]
    else:
        target_w = int(h * ratio_w / ratio_h)
        if target_w <= 0 or target_w > w:
            return src_path
        x0 = (w - target_w) // 2
        cropped = img[0:h, x0 : x0 + target_w]

    ratio_suffix = ratio.replace(":", "")
    dst_path = str(Path(src_path).with_name(f"{Path(src_path).stem}_{ratio_suffix}{Path(src_path).suffix}"))
    try:
        ok = cv2.imwrite(dst_path, cropped)
        return dst_path if ok else src_path
    except Exception:
        return src_path


def generate_video_from_image_url(
    image_url: str | None,
    prompt: str = "",
    model: str = VIDEO_MODEL,
    aspect_ratio: str = "9:16",
    duration_seconds: int = 8,
    last_frame_url: Optional[str] = None,
    extra_image_urls: Optional[list[str]] = None,
) -> Dict[str, Any]:
    _ensure_google_submit_allowed(model)
    image_part = _inline_asset_from_value(image_url)
    last_frame_part = _inline_asset_from_value(last_frame_url)
    reference_parts = [part for part in (_inline_asset_from_value(url) for url in (extra_image_urls or [])[:3]) if part]

    instance: dict[str, Any] = {"prompt": prompt}
    if image_part:
        instance["image"] = image_part
    if last_frame_part:
        instance["lastFrame"] = last_frame_part
    if reference_parts:
        instance["referenceImages"] = reference_parts

    payload_json = {
        "instances": [instance],
        "parameters": {
            "aspectRatio": aspect_ratio,
            "resolution": VIDEO_RESOLUTION,
            "durationSeconds": _google_duration_seconds(duration_seconds),
            "personGeneration": _google_person_generation(bool(image_part or last_frame_part or reference_parts)),
        },
    }
    if VIDEO_NEGATIVE_PROMPT:
        payload_json["parameters"]["negativePrompt"] = VIDEO_NEGATIVE_PROMPT

    response = _request_json("POST", _google_submit_url(model), payload_json)
    if "id" not in response and response.get("name"):
        response["id"] = response["name"]
    response["provider"] = VIDEO_PROVIDER
    response["model"] = model
    return response


def query_video(video_id: str) -> Dict[str, Any]:
    response = _request_json("GET", _google_operation_url(video_id))
    response["provider"] = VIDEO_PROVIDER
    return response


def wait_for_video_completion(
    video_id: str,
    poll_interval: float = 30.0,
    timeout: Optional[float] = 1200.0,
) -> Tuple[Dict[str, Any], Optional[str]]:
    start = time.time()
    poll_interval = max(30.0, float(poll_interval))
    while True:
        try:
            resp = query_video(video_id)
        except Exception as exc:
            message = str(exc)
            transient_markers = [
                "429",
                "RESOURCE_EXHAUSTED",
                "timeout",
                "timed out",
                "500",
                "502",
                "503",
            ]
            if any(marker in message for marker in transient_markers):
                if timeout is not None and (time.time() - start) > timeout:
                    raise TimeoutError(
                        f"Timed out while waiting for video generation after transient query errors. Last error: {message}"
                    ) from exc
                time.sleep(max(poll_interval, 15.0))
                continue
            raise

        status = _extract_status(resp)
        video_url = _find_video_url(resp)
        if status == "completed" or video_url:
            return resp, video_url
        if status in {"failed", "error", "canceled", "cancelled"}:
            raise RuntimeError(f"Video generation failed with status {status}: {json.dumps(resp, ensure_ascii=False)}")
        if timeout is not None and (time.time() - start) > timeout:
            raise TimeoutError(f"Timed out while waiting for video generation. Last status: {status}")
        time.sleep(poll_interval)


def _download_completed_video(video_id: str, video_url: str, clips_dir: Path) -> Dict[str, Any]:
    video_name = f"{uuid.uuid4()}.mp4"
    video_path = clips_dir / video_name
    _throttle_google_request()
    request = urllib.request.Request(
        video_url,
        headers={
            "x-goog-api-key": _google_api_key(),
            "User-Agent": "Mozilla/5.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=VIDEO_HTTP_TIMEOUT_SECONDS) as response:
            video_bytes = response.read()
    except Exception as exc:
        raise RuntimeError(f"Unable to download completed video from Google Veo URL: {video_url}. Error: {exc}") from exc
    video_path.write_bytes(video_bytes)

    cap = cv2.VideoCapture(str(video_path))
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    last_frame_index = frame_count - 1 if frame_count > 0 else 0
    cap.set(cv2.CAP_PROP_POS_FRAMES, last_frame_index)
    ok, frame = cap.read()
    cap.release()

    last_frame_path = clips_dir / f"{video_path.stem}_last_frame.jpg"
    if ok and frame is not None:
        cv2.imwrite(str(last_frame_path), frame)
    else:
        last_frame_path = Path("")

    actual_duration_seconds = probe_media_duration(str(video_path))
    return {
        "video_id": video_id,
        "video_url": video_url,
        "video_path": str(video_path),
        "last_frame_path": str(last_frame_path) if str(last_frame_path) else "",
        "generation_mode": "remote",
        "duration_seconds": actual_duration_seconds,
        "video_model": VIDEO_MODEL,
    }


def _create_remote_video_with_retries(
    image_url: str | None,
    prompt: str,
    last_frame_url: str | None,
    aspect_ratio: str,
    duration_seconds: int,
    extra_image_urls: Optional[list[str]] = None,
    max_attempts: int = GOOGLE_VEO_SUBMIT_MAX_ATTEMPTS,
) -> Dict[str, Any]:
    last_error: Exception | None = None
    for attempt_index in range(1, max_attempts + 1):
        try:
            return generate_video_from_image_url(
                image_url=image_url,
                prompt=prompt,
                model=VIDEO_MODEL,
                aspect_ratio=aspect_ratio,
                duration_seconds=duration_seconds,
                last_frame_url=last_frame_url,
                extra_image_urls=extra_image_urls,
            )
        except Exception as exc:
            last_error = exc
            message = str(exc)
            transient_markers = [
                "429",
                "Too Many Requests",
                "RESOURCE_EXHAUSTED",
                "500",
                "502",
                "503",
            ]
            if attempt_index >= max_attempts or not any(marker in message for marker in transient_markers):
                raise
            time.sleep(15.0 * attempt_index)
    if last_error is not None:
        raise last_error
    raise RuntimeError("Remote video creation failed before any attempt was made.")


def _build_video_prompt(
    scene_info: str,
    visuals: Dict[str, Any],
    scene_audio: Dict[str, Any] | None,
    aspect_ratio: str,
    duration_seconds: int,
    continuity: Dict[str, Any] | None = None,
    generic_only: bool = False,
    meta: dict[str, Any] | None = None,
    hero_product_name: str | None = None,
    product_reference_signature: str | None = None,
    product_visual_structure: str | None = None,
    allow_ai_composer: bool = True,
) -> str:
    compact_product_context = bool((meta or {}).get("compact_video_product_context", False))
    if str((meta or {}).get("video_reference_strategy", "") or "").strip().lower() == "storyboard_only":
        compact_product_context = True

    resolved_product_reference_signature = (
        product_reference_signature
        if product_reference_signature is not None
        else (get_product_reference_signature() if bool((meta or {}).get("use_product_reference_images", True)) else "")
    )
    resolved_product_visual_structure = (
        product_visual_structure
        if product_visual_structure is not None
        else (get_product_visual_structure_json() if bool((meta or {}).get("use_product_reference_images", True)) else "")
    )

    if compact_product_context:
        compact_structure: Dict[str, Any]
        if isinstance(resolved_product_visual_structure, dict):
            compact_structure = {
                "summary": resolved_product_visual_structure.get("summary", ""),
                "must_keep": _compact_value_list(resolved_product_visual_structure.get("must_keep", []), 6),
                "colors_and_materials": _compact_value_list(
                    resolved_product_visual_structure.get("colors_and_materials", []),
                    4,
                ),
            }
        else:
            compact_structure = {"summary": str(resolved_product_visual_structure or "")[:500]}

        compact_signature_parts = [
            part.strip()
            for part in str(resolved_product_reference_signature or "").splitlines()
            if part.strip()
        ]
        resolved_product_reference_signature = "\n".join(compact_signature_parts[:8])
        resolved_product_visual_structure = compact_structure

    prompt_composition = compose_generation_prompt(
        target="video",
        scene_description="" if generic_only else scene_info,
        visuals=visuals,
        scene_audio=scene_audio or {},
        continuity=continuity or {},
        aspect_ratio=aspect_ratio,
        duration_seconds=duration_seconds,
        meta=meta,
        hero_product_name=hero_product_name,
        product_reference_signature=resolved_product_reference_signature,
        product_visual_structure=resolved_product_visual_structure,
        allow_ai_composer=allow_ai_composer,
    )
    return apply_override(
        prompt_composition["prompt"],
        "video_prompt_append",
    )


def build_video_prompt(
    scene_info: str,
    visuals: Dict[str, Any],
    scene_audio: Dict[str, Any] | None,
    aspect_ratio: str,
    duration_seconds: int,
    continuity: Dict[str, Any] | None = None,
    generic_only: bool = False,
    meta: dict[str, Any] | None = None,
    hero_product_name: str | None = None,
    product_reference_signature: str | None = None,
    product_visual_structure: str | None = None,
    allow_ai_composer: bool = True,
) -> str:
    return _build_video_prompt(
        scene_info=scene_info,
        visuals=visuals,
        scene_audio=scene_audio,
        aspect_ratio=aspect_ratio,
        duration_seconds=duration_seconds,
        continuity=continuity,
        generic_only=generic_only,
        meta=meta,
        hero_product_name=hero_product_name,
        product_reference_signature=product_reference_signature,
        product_visual_structure=product_visual_structure,
        allow_ai_composer=allow_ai_composer,
    )


def generate_video_from_image_path(
    image_path,
    scene_info,
    visuals,
    scene_audio: Dict[str, Any] | None = None,
    continuity: Dict[str, Any] | None = None,
    last_frame=None,
    until_finish: bool = True,
    aspect_ratio: str = "9:16",
    duration_seconds: int = 8,
    force_local: bool = False,
    strict_reference_only: bool = False,
    include_product_reference_images: bool = True,
    product_reference_paths: Optional[list[str]] = None,
    meta: Optional[dict[str, Any]] = None,
    hero_product_name: Optional[str] = None,
    product_reference_signature: Optional[str] = None,
    product_visual_structure: Optional[str] = None,
    prompt_override: Optional[str] = None,
):
    clips_dir = ensure_active_run().clips
    clips_dir.mkdir(parents=True, exist_ok=True)
    use_original_storyboard = bool((meta or {}).get("skip_storyboard_crop_for_video", True))
    prepared_path = str(image_path) if use_original_storyboard else crop_image_to_ratio(image_path, aspect_ratio)

    requested_duration = _google_duration_seconds(duration_seconds)
    prompt_text = str(prompt_override or "").strip()
    if not prompt_text:
        prompt_text = _build_video_prompt(
            scene_info,
            visuals,
            scene_audio,
            aspect_ratio,
            requested_duration,
            continuity=continuity,
            meta=meta,
            hero_product_name=hero_product_name,
            product_reference_signature=product_reference_signature,
            product_visual_structure=product_visual_structure,
        )
    prompt_text, prompt_was_compacted = _fit_veo_prompt(
        prompt_text,
        scene_info,
        visuals,
        scene_audio,
        aspect_ratio,
        requested_duration,
    )

    product_reference_urls: list[str] = []
    allow_product_reference_images_in_video = bool((meta or {}).get("allow_product_reference_images_in_video", False))
    if include_product_reference_images and allow_product_reference_images_in_video:
        reference_source_paths = product_reference_paths or get_product_reference_images(limit=1 if strict_reference_only else 2)
        product_reference_urls = [
            _file_to_data_url(path)
            for path in reference_source_paths
            if Path(path).resolve() != Path(prepared_path).resolve()
        ]
        product_reference_urls = [url for url in product_reference_urls if url]

    if force_local:
        local_result = generate_local_clip(
            prepared_path,
            duration_seconds=requested_duration,
            aspect_ratio=aspect_ratio,
            output_dir=clips_dir,
        )
        local_result["video_prompt"] = prompt_text
        local_result["video_prompt_was_compacted"] = prompt_was_compacted
        return local_result

    remote_errors = []
    remote_attempts = []
    if _should_use_reference_images():
        remote_attempts.append(
            {
                "image_url": _file_to_data_url(prepared_path),
                "extra_image_urls": product_reference_urls,
                "last_frame_url": _file_to_data_url(last_frame) if last_frame else None,
                "prompt": prompt_text,
            }
        )
    if not strict_reference_only and GOOGLE_VEO_ALLOW_PROMPT_FALLBACKS:
        remote_attempts.append(
            {
                "image_url": None,
                "extra_image_urls": None,
                "last_frame_url": None,
                "prompt": prompt_text,
            }
        )
        remote_attempts.append(
            {
                "image_url": None,
                "extra_image_urls": None,
                "last_frame_url": None,
                "prompt": _build_video_prompt(
                    scene_info,
                    visuals,
                    scene_audio,
                    aspect_ratio,
                    requested_duration,
                    continuity=continuity,
                    generic_only=True,
                    meta=meta,
                    hero_product_name=hero_product_name,
                    product_reference_signature=product_reference_signature,
                    product_visual_structure=product_visual_structure,
                ),
            }
        )

    for attempt in remote_attempts:
        try:
            response = _create_remote_video_with_retries(
                attempt["image_url"],
                attempt["prompt"],
                attempt["last_frame_url"],
                aspect_ratio,
                requested_duration,
                extra_image_urls=attempt.get("extra_image_urls"),
            )
            video_id = _extract_video_id(response)
            if not video_id:
                raise ValueError("Google Veo API did not return an operation name.")
            if not until_finish:
                return {
                    "video_id": video_id,
                    "video_model": VIDEO_MODEL,
                    "image_url": attempt["image_url"],
                    "extra_image_urls": attempt.get("extra_image_urls") or [],
                    "last_frame_url": attempt["last_frame_url"],
                    "video_prompt": attempt["prompt"],
                    "video_prompt_was_compacted": prompt_was_compacted,
                    "generation_mode": "remote_pending",
                    "planned_duration_seconds": requested_duration,
                }

            _, video_url = wait_for_video_completion(video_id)
            if not video_url:
                raise RuntimeError("Google Veo finished without a downloadable URL.")
            downloaded = _download_completed_video(video_id, video_url, clips_dir)
            downloaded["planned_duration_seconds"] = requested_duration
            downloaded["video_prompt"] = attempt["prompt"]
            downloaded["video_prompt_was_compacted"] = prompt_was_compacted
            return downloaded
        except Exception as err:
            remote_errors.append(str(err))

    print("Remote video generation failed, falling back to local clip: " + " | ".join(remote_errors))
    try:
        local_result = generate_local_clip(
            prepared_path,
            duration_seconds=requested_duration,
            aspect_ratio=aspect_ratio,
            output_dir=clips_dir,
        )
        local_result["fallback_reason"] = " | ".join(remote_errors)
        local_result["video_prompt"] = prompt_text
        local_result["video_prompt_was_compacted"] = prompt_was_compacted
        return local_result
    except Exception as local_err:
        raise RuntimeError(
            "Remote video generation failed and local fallback could not run. "
            f"Remote errors: {' | '.join(remote_errors)}. Local error: {local_err}"
        ) from local_err


def get_video_path_from_video_id(video_id: str):
    if video_id.startswith("local:"):
        return {
            "video_id": video_id,
            "status": "completed",
            "message": "Local clips are generated immediately.",
        }

    clips_dir = ensure_active_run().clips
    clips_dir.mkdir(parents=True, exist_ok=True)
    resp, video_url = wait_for_video_completion(video_id)
    if not video_url:
        return {
            "video_id": video_id,
            "status": _extract_status(resp),
            "message": f"status {_extract_status(resp)}; response: {json.dumps(resp, ensure_ascii=False)}",
        }
    return _download_completed_video(video_id, video_url, clips_dir)
