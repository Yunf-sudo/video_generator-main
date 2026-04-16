from __future__ import annotations

import base64
import json
import mimetypes
import os
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from dotenv import load_dotenv

from workspace_paths import ensure_active_run


load_dotenv()

GOOGLE_API_BASE_URL = os.getenv("GOOGLE_API_BASE_URL", "https://generativelanguage.googleapis.com/v1beta").strip()
DEFAULT_TEXT_MODEL = os.getenv("TEXT_MODEL", os.getenv("SCRIPT_MODEL", "gemini-2.5-flash"))
DEFAULT_IMAGE_MODEL = os.getenv("IMAGE_MODEL", "gemini-2.5-flash-image")


def google_api_key() -> str:
    value = (
        os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
        or os.getenv("GOOGLE_GENAI_API_KEY")
    )
    if not value:
        raise RuntimeError("Missing GEMINI_API_KEY or GOOGLE_API_KEY for Google Gemini API.")
    return value.strip().strip('"')


def _model_action_url(model: str, action: str = "generateContent") -> str:
    normalized = (model or "").strip() or DEFAULT_TEXT_MODEL
    if not normalized.startswith("models/"):
        normalized = f"models/{normalized}"
    return f"{GOOGLE_API_BASE_URL}/{normalized}:{action}"


def request_json(
    method: str,
    url: str,
    payload_json: dict[str, Any] | None = None,
    timeout_seconds: float = 300.0,
    max_attempts: int = 3,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            request = urllib.request.Request(
                url,
                data=json.dumps(payload_json or {}, ensure_ascii=False).encode("utf-8"),
                headers={
                    "x-goog-api-key": google_api_key(),
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": "Mozilla/5.0",
                },
                method=method.upper(),
            )
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            last_error = exc
            if attempt >= max_attempts:
                raise RuntimeError(f"Gemini API request failed after retries: {exc}") from exc
            time.sleep(4.0 * attempt)
    raise RuntimeError(f"Gemini API request failed after retries: {last_error}")


def encode_image_base64(image_path: str, max_edge: int = 1600, jpeg_quality: int = 85) -> tuple[str, str]:
    resolved = Path(image_path).resolve()
    image_bytes = resolved.read_bytes()
    mime = mimetypes.guess_type(str(resolved))[0] or "image/jpeg"

    if len(image_bytes) > 2_000_000:
        image_buffer = np.frombuffer(image_bytes, dtype=np.uint8)
        image = cv2.imdecode(image_buffer, cv2.IMREAD_COLOR)
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
                mime = "image/jpeg"
                image_bytes = encoded.tobytes()
    return mime, base64.b64encode(image_bytes).decode("utf-8")


def image_part_from_path(image_path: str) -> dict[str, Any]:
    mime, encoded = encode_image_base64(image_path)
    return {
        "inline_data": {
            "mime_type": mime,
            "data": encoded,
        }
    }


def _data_url_to_part(data_url: str) -> dict[str, Any]:
    header, encoded = data_url.split(",", 1)
    mime_type = header[5:].split(";", 1)[0] if header.startswith("data:") else "image/jpeg"
    return {
        "inline_data": {
            "mime_type": mime_type or "image/jpeg",
            "data": encoded,
        }
    }


def _content_to_parts(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"text": content}]
    if not isinstance(content, list):
        return [{"text": str(content)}]

    parts: list[dict[str, Any]] = []
    for item in content:
        if not isinstance(item, dict):
            parts.append({"text": str(item)})
            continue
        if item.get("type") == "text":
            parts.append({"text": str(item.get("text", ""))})
            continue
        if item.get("type") == "image_url":
            image_value = str(item.get("image_url", "") or "").strip()
            if image_value.startswith("data:") and ";base64," in image_value:
                parts.append(_data_url_to_part(image_value))
            elif image_value and Path(image_value).exists():
                parts.append(image_part_from_path(image_value))
            continue
        if "text" in item:
            parts.append({"text": str(item.get("text", ""))})
    return parts or [{"text": ""}]


def chat_messages_to_gemini(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    system_chunks: list[str] = []
    contents: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role", "user")).strip().lower()
        content = message.get("content", "")
        if role == "system":
            for part in _content_to_parts(content):
                if part.get("text"):
                    system_chunks.append(part["text"])
            continue
        mapped_role = "model" if role in {"assistant", "model"} else "user"
        contents.append(
            {
                "role": mapped_role,
                "parts": _content_to_parts(content),
            }
        )
    return "\n\n".join(chunk for chunk in system_chunks if chunk.strip()), contents


def generate_content(
    model: str,
    messages: list[dict[str, Any]],
    response_mime_type: str | None = None,
    response_json_schema: dict[str, Any] | None = None,
    generation_config: dict[str, Any] | None = None,
    timeout_seconds: float = 300.0,
) -> dict[str, Any]:
    system_instruction, contents = chat_messages_to_gemini(messages)
    payload: dict[str, Any] = {"contents": contents}
    if system_instruction:
        payload["systemInstruction"] = {
            "parts": [{"text": system_instruction}],
        }
    merged_generation_config = dict(generation_config or {})
    if response_mime_type:
        merged_generation_config["responseMimeType"] = response_mime_type
    if response_json_schema:
        merged_generation_config["responseJsonSchema"] = response_json_schema
    if merged_generation_config:
        payload["generationConfig"] = merged_generation_config
    return request_json(
        "POST",
        _model_action_url(model, "generateContent"),
        payload_json=payload,
        timeout_seconds=timeout_seconds,
    )


def extract_response_text(response: dict[str, Any]) -> str:
    texts: list[str] = []
    for candidate in response.get("candidates", []) or []:
        content = candidate.get("content", {})
        for part in content.get("parts", []) or []:
            text = part.get("text")
            if text:
                texts.append(str(text))
    return "".join(texts).strip()


def extract_inline_images(response: dict[str, Any]) -> list[dict[str, str]]:
    images: list[dict[str, str]] = []
    for candidate in response.get("candidates", []) or []:
        content = candidate.get("content", {})
        for part in content.get("parts", []) or []:
            inline_data = part.get("inline_data") or part.get("inlineData")
            if not isinstance(inline_data, dict):
                continue
            data = str(inline_data.get("data", "") or "").strip()
            mime_type = str(inline_data.get("mime_type") or inline_data.get("mimeType") or "image/png").strip()
            if data:
                images.append(
                    {
                        "mime_type": mime_type,
                        "data": data,
                    }
                )
    return images


def save_inline_image(image_payload: dict[str, str], out_dir: str | None = None) -> str:
    target_dir = Path(out_dir or ensure_active_run().pics)
    target_dir.mkdir(parents=True, exist_ok=True)
    mime_type = image_payload.get("mime_type", "image/png")
    ext = mimetypes.guess_extension(mime_type.split(";")[0]) or ".png"
    output_path = target_dir / f"generated_{uuid.uuid4().hex[:8]}{ext}"
    output_path.write_bytes(base64.b64decode(image_payload["data"]))
    return str(output_path)


def generate_image(
    prompt: str,
    model: str = DEFAULT_IMAGE_MODEL,
    aspect_ratio: str = "9:16",
    reference_pic_paths: list[str] | None = None,
    system_prompt: str | None = None,
    out_dir: str | None = None,
) -> str:
    message_parts: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for path in reference_pic_paths or []:
        if Path(path).exists():
            message_parts.append({"type": "image_url", "image_url": str(Path(path).resolve())})
    messages = [{"role": "user", "content": message_parts}]
    if system_prompt:
        messages.insert(0, {"role": "system", "content": system_prompt})
    response = generate_content(
        model=model,
        messages=messages,
        generation_config={
            "responseModalities": ["TEXT", "IMAGE"],
            "imageConfig": {
                "aspectRatio": aspect_ratio,
            },
        },
        timeout_seconds=300.0,
    )
    images = extract_inline_images(response)
    if not images:
        raise RuntimeError(f"No inline image returned by Gemini image model. Raw response: {json.dumps(response, ensure_ascii=False)[:1000]}")
    return save_inline_image(images[0], out_dir=out_dir)
