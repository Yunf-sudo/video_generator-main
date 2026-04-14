import base64
import http.client
import json
import mimetypes
import os
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode, urlparse

import cv2
import numpy as np
from dotenv import load_dotenv

from media_pipeline import generate_local_clip, probe_media_duration
from prompt_context import build_prompt_context
from prompt_overrides import apply_override
from prompts_en import video_generate_prompt
from product_reference_images import (
    get_product_reference_images,
    get_product_reference_signature,
    get_product_visual_structure_json,
)
from rustfs_util import upload_file_to_rustfs
from workspace_paths import ensure_active_run


load_dotenv()

API_HOST = "jeniya.cn"
API_PATH = "/v1/video/create"
VIDEO_PROVIDER = os.getenv("VIDEO_PROVIDER", "jeniya").strip().lower()
VIDEO_MODEL = os.getenv("VIDEO_MODEL", "veo3.1-pro")
VIDEO_REFERENCE_MODE = os.getenv("VIDEO_REFERENCE_MODE", "image").strip().lower()
VIDEO_SIZE = os.getenv("VIDEO_SIZE", "large").strip() or "large"
VIDEO_ENHANCE_PROMPT = os.getenv("VIDEO_ENHANCE_PROMPT", "true").strip().lower() in {"1", "true", "yes", "on"}
VIDEO_ENABLE_UPSAMPLE = os.getenv("VIDEO_ENABLE_UPSAMPLE", "true").strip().lower() in {"1", "true", "yes", "on"}
VIDEO_GENERATE_AUDIO = os.getenv("VIDEO_GENERATE_AUDIO", "false").strip().lower() in {"1", "true", "yes", "on"}
VIDEO_302_SUBMIT_URL = os.getenv("VIDEO_302_SUBMIT_URL", "https://api.302.ai/302/submit/veo3-pro-frames").strip()
VIDEO_302_QUERY_URL = os.getenv("VIDEO_302_QUERY_URL", VIDEO_302_SUBMIT_URL).strip()
VIDEO_302_IMAGE_BUCKET = os.getenv("VIDEO_302_IMAGE_BUCKET", "video-input-images").strip() or "video-input-images"


def _is_302_provider() -> bool:
    return VIDEO_PROVIDER in {"302", "302ai", "302.ai", "302-ai"}


def _video_api_token(token: Optional[str] = None) -> str:
    if token:
        return token
    if _is_302_provider():
        value = (
            os.getenv("V302_API_KEY")
            or os.getenv("VIDEO_302_API_KEY")
            or os.getenv("302_API_KEY")
            or os.getenv("JENIYA_API_TOKEN")
        )
        if not value:
            raise ValueError("Missing V302_API_KEY for 302.ai video generation.")
        return value.strip().strip('"')
    value = os.getenv("JENIYA_API_TOKEN")
    if not value:
        raise ValueError("Missing JENIYA_API_TOKEN for remote video generation.")
    return value.strip().strip('"')


def _request_json(method: str, url: str, token: str, payload_json: Optional[dict[str, Any]] = None) -> Dict[str, Any]:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid API URL: {url}")
    connection_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    conn = connection_cls(parsed.netloc, timeout=60)
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"

    body = json.dumps(payload_json or {}, ensure_ascii=False).encode("utf-8") if payload_json is not None else b""
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    conn.request(method.upper(), path, body=body if payload_json is not None else None, headers=headers)
    res = conn.getresponse()
    raw = res.read()
    text = raw.decode("utf-8", errors="replace")
    if res.status < 200 or res.status >= 300:
        raise RuntimeError(f"API request failed: {res.status} {res.reason}; response: {text}")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}


def _append_query(url: str, params: dict[str, str]) -> str:
    parsed = urlparse(url)
    existing = parsed.query
    extra = urlencode(params)
    query = f"{existing}&{extra}" if existing else extra
    return parsed._replace(query=query).geturl()


def _find_video_url(value: Any) -> str | None:
    if isinstance(value, str):
        if value.startswith(("http://", "https://")) and (".mp4" in value or "video" in value):
            return value
        return None
    if isinstance(value, dict):
        for key in ("upsample_video_url", "video_url", "url"):
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
    for key in ("id", "video_id", "task_id", "request_id"):
        value = response.get(key)
        if value:
            return str(value)
    data = response.get("data")
    if isinstance(data, str) and data.strip():
        return data.strip()
    if isinstance(data, dict):
        for key in ("id", "video_id", "task_id", "request_id"):
            value = data.get(key)
            if value:
                return str(value)
    return None


def _extract_status(response: dict[str, Any]) -> str | None:
    status = response.get("status") or response.get("code")
    data = response.get("data")
    if status is None and isinstance(data, dict):
        status = data.get("status") or data.get("task_status") or data.get("code")
    if status is None and _find_video_url(response):
        return "completed"
    if status is None:
        return None
    raw = str(status).strip().lower()
    if raw in {"completed", "complete", "succeeded", "succeed", "success", "done", "10000"}:
        return "completed"
    if raw in {"failed", "failure", "error", "canceled", "cancelled"}:
        return "failed"
    return raw


def _upload_image_for_remote_video(file_path: str | None) -> str | None:
    if not file_path:
        return None
    if not _is_302_provider():
        return _file_to_data_url(file_path)
    resolved = Path(file_path)
    if not resolved.exists():
        return None
    object_name = f"{uuid.uuid4().hex}{resolved.suffix or '.jpg'}"
    url = upload_file_to_rustfs(str(resolved), VIDEO_302_IMAGE_BUCKET, object_name=object_name)
    if not url.startswith(("http://", "https://")):
        raise RuntimeError(
            "302.ai requires a public HTTP(S) input image URL, but image upload did not return one."
        )
    return url


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


def _orientation_for_ratio(aspect_ratio: str) -> str:
    if aspect_ratio == "9:16":
        return "portrait"
    if aspect_ratio == "1:1":
        return "square"
    return "landscape"


def generate_video_from_image_url(
    image_url: str | None,
    token: Optional[str] = None,
    prompt: str = "",
    model: str = VIDEO_MODEL,
    enhance_prompt: bool = False,
    enable_upsample: bool = False,
    aspect_ratio: str = "9:16",
    last_frame_url: Optional[str] = None,
    extra_image_urls: Optional[list[str]] = None,
) -> Dict[str, Any]:
    token = _video_api_token(token)

    if _is_302_provider():
        if not image_url:
            raise ValueError("302.ai veo3-pro-frames requires input_image.")
        payload_json = {
            "text_prompt": prompt,
            "input_image": image_url,
        }
        response = _request_json("POST", VIDEO_302_SUBMIT_URL, token, payload_json)
        video_id = _extract_video_id(response)
        if video_id and "id" not in response:
            response["id"] = video_id
        response["provider"] = "302.ai"
        response["model"] = VIDEO_MODEL
        return response

    conn = http.client.HTTPSConnection(API_HOST, timeout=60)
    payload_json = {
        "prompt": prompt,
        "model": model,
        "enhance_prompt": enhance_prompt,
        "enable_upsample": enable_upsample,
        "aspect_ratio": aspect_ratio,
        "orientation": _orientation_for_ratio(aspect_ratio),
        "size": VIDEO_SIZE,
        "generate_audio": VIDEO_GENERATE_AUDIO,
        "audio": VIDEO_GENERATE_AUDIO,
    }
    images = [value for value in [image_url, *(extra_image_urls or []), last_frame_url] if value]
    if images:
        payload_json["images"] = images

    payload = json.dumps(payload_json, ensure_ascii=False)
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    conn.request("POST", API_PATH, body=payload.encode("utf-8"), headers=headers)
    res = conn.getresponse()
    raw = res.read()
    text = raw.decode("utf-8", errors="replace")

    if res.status < 200 or res.status >= 300:
        raise RuntimeError(f"API request failed: {res.status} {res.reason}; response: {text}")

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}


def query_video(video_id: str, token: Optional[str] = None) -> Dict[str, Any]:
    token = _video_api_token(token)

    if _is_302_provider():
        query_url = _append_query(VIDEO_302_QUERY_URL, {"request_id": video_id})
        response = _request_json("GET", query_url, token)
        response["provider"] = "302.ai"
        return response

    conn = http.client.HTTPSConnection(API_HOST, timeout=60)
    query = urlencode({"id": video_id})
    path = f"/v1/video/query?{query}"
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    conn.request("GET", path, body="", headers=headers)
    res = conn.getresponse()
    raw = res.read()
    text = raw.decode("utf-8", errors="replace")

    if res.status < 200 or res.status >= 300:
        raise RuntimeError(f"API query failed: {res.status} {res.reason}; response: {text}")

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}


def wait_for_video_completion(
    video_id: str,
    token: Optional[str] = None,
    poll_interval: float = 15.0,
    timeout: Optional[float] = 1200.0,
) -> Tuple[Dict[str, Any], Optional[str]]:
    start = time.time()
    while True:
        try:
            resp = query_video(video_id, token=token)
        except Exception as exc:
            message = str(exc)
            transient_markers = [
                "Too many connections",
                "429",
                "500 Internal Server Error",
                "502 Bad Gateway",
                "503 Service Unavailable",
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


def _download_completed_video(video_id: str, video_url: str, clips_dir: Path) -> Dict[str, Any]:
    video_name = f"{uuid.uuid4()}.mp4"
    video_path = clips_dir / video_name
    with urllib.request.urlopen(video_url) as response:
        video_bytes = response.read()
    video_path.write_bytes(video_bytes)

    cap = cv2.VideoCapture(str(video_path))
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    last_frame_index = frame_count - 1 if frame_count > 0 else 0
    cap.set(cv2.CAP_PROP_POS_FRAMES, last_frame_index)
    _, frame = cap.read()
    cap.release()

    last_frame_path = clips_dir / f"{video_path.stem}_last_frame.jpg"
    cv2.imwrite(str(last_frame_path), frame)
    actual_duration_seconds = probe_media_duration(str(video_path))
    return {
        "video_id": video_id,
        "video_url": video_url,
        "video_path": str(video_path),
        "last_frame_path": str(last_frame_path),
        "generation_mode": "remote",
        "duration_seconds": actual_duration_seconds,
    }


def _should_use_reference_images() -> bool:
    return VIDEO_REFERENCE_MODE in {"image", "images", "hybrid"}


def _create_remote_video_with_retries(
    image_url: str | None,
    prompt: str,
    last_frame_url: str | None,
    aspect_ratio: str,
    extra_image_urls: Optional[list[str]] = None,
    max_attempts: int = 3,
) -> Dict[str, Any]:
    last_error: Exception | None = None
    for attempt_index in range(1, max_attempts + 1):
        try:
            return generate_video_from_image_url(
                image_url,
                prompt=prompt,
                model=VIDEO_MODEL,
                enhance_prompt=VIDEO_ENHANCE_PROMPT,
                enable_upsample=VIDEO_ENABLE_UPSAMPLE,
                last_frame_url=last_frame_url,
                aspect_ratio=aspect_ratio,
                extra_image_urls=extra_image_urls,
            )
        except Exception as exc:
            last_error = exc
            message = str(exc)
            if attempt_index >= max_attempts or not any(
                marker in message
                for marker in [
                    "429",
                    "Too Many Requests",
                    "上游负载已饱和",
                    "500 Internal Server Error",
                    "502 Bad Gateway",
                    "503 Service Unavailable",
                    "Too many connections",
                ]
            ):
                raise
            time.sleep(15.0 * attempt_index)
    if last_error is not None:
        raise last_error
    raise RuntimeError("Remote video creation failed before any attempt was made.")


def _build_video_prompt(
    scene_info: str,
    visuals: Dict[str, Any],
    aspect_ratio: str,
    duration_seconds: int,
    continuity: Dict[str, Any] | None = None,
    generic_only: bool = False,
    meta: dict[str, Any] | None = None,
    hero_product_name: str | None = None,
    product_reference_signature: str | None = None,
    product_visual_structure: str | None = None,
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
                "must_keep": list(resolved_product_visual_structure.get("must_keep", []))[:6],
                "colors_and_materials": list(resolved_product_visual_structure.get("colors_and_materials", []))[:4],
            }
        else:
            compact_structure = {
                "summary": str(resolved_product_visual_structure or "")[:500],
            }

        compact_signature_parts = [part.strip() for part in str(resolved_product_reference_signature or "").splitlines() if part.strip()]
        resolved_product_reference_signature = "\n".join(compact_signature_parts[:8])
        resolved_product_visual_structure = compact_structure

    prompt_context = build_prompt_context({**(meta or {}), **({"hero_product_name": hero_product_name} if hero_product_name else {})})
    payload = {
        "scene_description": "" if generic_only else scene_info,
        "visuals": visuals,
        "continuity": continuity or {},
        "duration_seconds": duration_seconds,
        "aspect_ratio": aspect_ratio,
        "product_reference_signature": resolved_product_reference_signature,
        "product_visual_structure": resolved_product_visual_structure,
    }
    return apply_override(
        video_generate_prompt.format(info=json.dumps(payload, ensure_ascii=False), **prompt_context),
        "video_prompt_append",
    )


def build_video_prompt(
    scene_info: str,
    visuals: Dict[str, Any],
    aspect_ratio: str,
    duration_seconds: int,
    continuity: Dict[str, Any] | None = None,
    generic_only: bool = False,
    meta: dict[str, Any] | None = None,
    hero_product_name: str | None = None,
    product_reference_signature: str | None = None,
    product_visual_structure: str | None = None,
) -> str:
    return _build_video_prompt(
        scene_info=scene_info,
        visuals=visuals,
        aspect_ratio=aspect_ratio,
        duration_seconds=duration_seconds,
        continuity=continuity,
        generic_only=generic_only,
        meta=meta,
        hero_product_name=hero_product_name,
        product_reference_signature=product_reference_signature,
        product_visual_structure=product_visual_structure,
    )


def generate_video_from_image_path(
    image_path,
    scene_info,
    visuals,
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
):
    clips_dir = ensure_active_run().clips
    clips_dir.mkdir(parents=True, exist_ok=True)
    cropped_path = crop_image_to_ratio(image_path, aspect_ratio)
    prompt_text = _build_video_prompt(
        scene_info,
        visuals,
        aspect_ratio,
        duration_seconds,
        continuity=continuity,
        meta=meta,
        hero_product_name=hero_product_name,
        product_reference_signature=product_reference_signature,
        product_visual_structure=product_visual_structure,
    )
    product_reference_urls = []
    allow_product_reference_images_in_video = bool((meta or {}).get("allow_product_reference_images_in_video", False))
    if include_product_reference_images and allow_product_reference_images_in_video:
        reference_source_paths = product_reference_paths
        if reference_source_paths is None:
            reference_source_paths = get_product_reference_images(limit=1 if strict_reference_only else 2)
        product_reference_urls = [
            _upload_image_for_remote_video(path)
            for path in reference_source_paths
            if Path(path).resolve() != Path(cropped_path).resolve()
        ]
        product_reference_urls = [url for url in product_reference_urls if url]

    if force_local:
        local_result = generate_local_clip(
            cropped_path,
            duration_seconds=duration_seconds,
            aspect_ratio=aspect_ratio,
            output_dir=clips_dir,
        )
        local_result["video_prompt"] = prompt_text
        return local_result

    remote_errors = []
    remote_attempts = []
    if _should_use_reference_images():
        remote_attempts.append(
            {
                "image_url": _upload_image_for_remote_video(cropped_path),
                "extra_image_urls": product_reference_urls,
                "last_frame_url": _upload_image_for_remote_video(last_frame) if last_frame else None,
                "prompt": prompt_text,
            }
        )
    if not strict_reference_only:
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
                    aspect_ratio,
                    duration_seconds,
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
                extra_image_urls=attempt.get("extra_image_urls"),
            )
            video_id = _extract_video_id(response)
            if not video_id:
                raise ValueError("Remote video API did not return a video_id.")
            if not until_finish:
                return {
                    "video_id": video_id,
                    "video_model": VIDEO_MODEL,
                    "image_url": attempt["image_url"],
                    "extra_image_urls": attempt.get("extra_image_urls") or [],
                    "last_frame_url": attempt["last_frame_url"],
                    "video_prompt": attempt["prompt"],
                    "generation_mode": "remote_pending",
                    "planned_duration_seconds": duration_seconds,
                }

            _, video_url = wait_for_video_completion(video_id)
            if not video_url:
                raise RuntimeError("Remote video finished without a downloadable URL.")
            downloaded = _download_completed_video(video_id, video_url, clips_dir)
            downloaded["video_model"] = VIDEO_MODEL
            downloaded["planned_duration_seconds"] = duration_seconds
            downloaded["video_prompt"] = attempt["prompt"]
            return downloaded
        except Exception as err:
            remote_errors.append(str(err))

    print("Remote video generation failed, falling back to local clip: " + " | ".join(remote_errors))
    try:
        local_result = generate_local_clip(
            cropped_path,
            duration_seconds=duration_seconds,
            aspect_ratio=aspect_ratio,
            output_dir=clips_dir,
        )
        local_result["fallback_reason"] = " | ".join(remote_errors)
        local_result["video_prompt"] = prompt_text
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
            "status": resp.get("status"),
            "message": f"status {resp.get('status')}; response: {json.dumps(resp, ensure_ascii=False)}",
        }
    return _download_completed_video(video_id, video_url, clips_dir)
