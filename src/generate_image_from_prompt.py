import base64
import mimetypes
import os
import re
import time
import uuid
from pathlib import Path

import cv2
import numpy as np
import requests
from dotenv import load_dotenv

from workspace_paths import ensure_active_run


load_dotenv()

OPENROUTER_API_KEY = os.getenv("JENIYA_API_TOKEN")
OPENROUTER_URL = os.getenv("JIANYI_ENDPOINT", "http://jeniya.cn/v1/chat/completions")
DEFAULT_MODEL = os.getenv("IMAGE_MODEL", "gpt-image-1-all")
def _http_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    return session


def _encode_image_to_base64(image_path: str) -> str:
    image_bytes = Path(image_path).read_bytes()
    if len(image_bytes) <= 2_000_000:
        return base64.b64encode(image_bytes).decode("utf-8")

    image_buffer = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(image_buffer, cv2.IMREAD_COLOR)
    if image is None:
        return base64.b64encode(image_bytes).decode("utf-8")

    height, width = image.shape[:2]
    longest_edge = max(height, width)
    if longest_edge > 1600:
        scale = 1600.0 / float(longest_edge)
        resized_width = max(1, int(round(width * scale)))
        resized_height = max(1, int(round(height * scale)))
        image = cv2.resize(image, (resized_width, resized_height), interpolation=cv2.INTER_AREA)

    ok, encoded = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    if not ok:
        return base64.b64encode(image_bytes).decode("utf-8")
    return base64.b64encode(encoded.tobytes()).decode("utf-8")


def _data_url_for_image(image_path: str) -> str:
    mime, _ = mimetypes.guess_type(image_path)
    mime = mime or "image/jpeg"
    base64_image = _encode_image_to_base64(image_path)
    return f"data:{mime};base64,{base64_image}"


def _guess_ext_from_mime(mime: str | None) -> str:
    if not mime:
        return ".jpg"
    base = mime.split(";")[0]
    ext = mimetypes.guess_extension(base)
    return ext or ".jpg"


def _save_data_url(data_url: str, out_dir: str) -> str:
    header, b64 = data_url.split(",", 1)
    mime = header[5:].split(";")[0] if header.startswith("data:") else "image/jpeg"
    ext = _guess_ext_from_mime(mime)
    filename = f"generated_{uuid.uuid4().hex[:8]}{ext}"
    out_path = Path(out_dir) / filename
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(base64.b64decode(b64))
    return str(out_path)


def _save_url(url: str, out_dir: str) -> str:
    target_dir = Path(out_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    with _http_session() as session:
        resp = session.get(url, timeout=120)
    resp.raise_for_status()
    mime = resp.headers.get("Content-Type")
    ext = _guess_ext_from_mime(mime)
    url_path = url.split("?")[0].split("#")[0]
    ext_from_url = os.path.splitext(url_path)[1]
    if ext_from_url:
        ext = ext_from_url
    out_path = target_dir / f"generated_{uuid.uuid4().hex[:8]}{ext}"
    out_path.write_bytes(resp.content)
    return str(out_path)


def _extract_image_urls(result: dict) -> list[str]:
    image_urls: list[str] = []
    choices = result.get("choices", [])
    if not choices:
        return image_urls

    message = choices[0].get("message", {})
    content = message.get("content", "")

    if isinstance(content, str):
        markdown_matches = re.findall(r"!\[.*?\]\((.*?)\)", content)
        image_urls.extend(markdown_matches)
        data_urls = re.findall(r"(data:image\/[a-zA-Z0-9.+-]+;base64,[A-Za-z0-9+/=]+)", content)
        image_urls.extend(data_urls)
        return image_urls

    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "image_url":
                value = item.get("image_url")
                if isinstance(value, str):
                    image_urls.append(value)
            if item.get("type") == "output_image":
                value = item.get("image_url") or item.get("url")
                if isinstance(value, str):
                    image_urls.append(value)
    return image_urls


def generate_image_from_prompt(
    prompt: str,
    out_dir: str | None = None,
    model: str = DEFAULT_MODEL,
    aspect_ratio: str = "9:16",
    reference_pic_paths: list[str] | None = None,
    system_prompt: str | None = None,
) -> str:
    if not OPENROUTER_API_KEY:
        raise RuntimeError("JENIYA_API_TOKEN is not set in environment.")

    content_items = [{"type": "text", "text": prompt}]
    if reference_pic_paths:
        for path in reference_pic_paths:
            content_items.append({"type": "image_url", "image_url": _data_url_for_image(path)})

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": content_items})

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "modalities": ["image", "text"],
        "image_config": {"aspect_ratio": aspect_ratio},
    }
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            with _http_session() as session:
                response = session.post(OPENROUTER_URL, headers=headers, json=payload, timeout=300)
            if not response.ok:
                if response.status_code in {429, 500, 502, 503, 504} and attempt < 3:
                    time.sleep(5 * attempt)
                    continue
                raise RuntimeError(f"Image generation returned {response.status_code}: {response.text}")

            result = response.json()
            if isinstance(result, dict) and result.get("error"):
                error_text = str(result["error"])
                if attempt < 3 and any(marker in error_text for marker in ["502", "503", "timeout", "temporarily"]):
                    time.sleep(5 * attempt)
                    continue
                raise RuntimeError(f"Image generation error: {result['error']}")
            break
        except requests.RequestException as exc:
            last_error = exc
            if attempt >= 3:
                raise RuntimeError(f"Image generation request failed after retries: {exc}") from exc
            time.sleep(5 * attempt)
    else:
        raise RuntimeError(f"Image generation failed after retries: {last_error}")

    image_urls = _extract_image_urls(result)
    saved_paths = []
    active_out_dir = out_dir or str(ensure_active_run().pics)
    for image_url in image_urls:
        if image_url.startswith("data:"):
            saved_paths.append(_save_data_url(image_url, out_dir=active_out_dir))
        elif image_url.startswith("http"):
            saved_paths.append(_save_url(image_url, out_dir=active_out_dir))

    if not saved_paths:
        raise RuntimeError(f"No image asset returned by image model {model}. Raw response: {result}")
    return saved_paths[0]
