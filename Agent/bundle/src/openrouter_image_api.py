from __future__ import annotations

import base64
import mimetypes
import os
import re
import uuid
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from agent_bundle_env import load_agent_bundle_env
from runtime_tunables_config import load_runtime_tunables
from workspace_paths import ensure_active_run


load_agent_bundle_env()


def _load_repo_root_env_fallback() -> None:
    if (os.getenv("OPENROUTER_API_KEY") or "").strip():
        return
    repo_root_env = Path(__file__).resolve().parents[3] / ".env"
    if repo_root_env.exists():
        load_dotenv(dotenv_path=repo_root_env, override=False)


_load_repo_root_env_fallback()

RUNTIME_TUNABLES = load_runtime_tunables()
DEFAULT_IMAGE_MODEL = os.getenv(
    "IMAGE_MODEL",
    str(RUNTIME_TUNABLES["model_config"].get("image_model") or "openai/gpt-5.4-image-2"),
).strip()
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").strip().rstrip("/")
OPENROUTER_CHAT_COMPLETIONS_URL = f"{OPENROUTER_BASE_URL}/chat/completions"
OPENROUTER_APP_NAME = os.getenv("OPENROUTER_APP_NAME", "video_v1").strip()
OPENROUTER_SITE_URL = os.getenv("OPENROUTER_SITE_URL", "").strip()
OPENROUTER_IMAGE_HTTP_TIMEOUT_SECONDS = float(os.getenv("OPENROUTER_IMAGE_HTTP_TIMEOUT_SECONDS", "300") or "300")
OPENROUTER_IMAGE_ONLY_GUARDRAIL = (
    "You are generating the final image now. "
    "Return image output only. Do not explain, do not rewrite the prompt, do not output markdown, and do not describe the image in text."
)


def openrouter_api_key() -> str:
    value = (os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENROUTER_API_TOKEN") or "").strip()
    if value:
        return value
    raise RuntimeError(
        "未配置 OPENROUTER_API_KEY。Agent 图片生成现已走 OpenRouter，请在 Agent/.env 或仓库根目录 .env 中补充该变量。"
    )


def _encode_image_to_base64(image_path: str) -> str:
    return base64.b64encode(Path(image_path).read_bytes()).decode("utf-8")


def _data_url_for_image(image_path: str) -> str:
    mime_type, _ = mimetypes.guess_type(image_path)
    resolved_mime = mime_type or "image/png"
    return f"data:{resolved_mime};base64,{_encode_image_to_base64(image_path)}"


def _guess_ext_from_mime(mime_type: str | None) -> str:
    if not mime_type:
        return ".png"
    ext = mimetypes.guess_extension(str(mime_type).split(";")[0].strip())
    return ext or ".png"


def _save_generated_image(image_url: str, out_dir: str | None = None) -> str:
    target_dir = Path(out_dir or ensure_active_run().pics)
    target_dir.mkdir(parents=True, exist_ok=True)

    if image_url.startswith("data:"):
        header, payload = image_url.split(",", 1)
        mime_type = header[5:].split(";")[0] if header.startswith("data:") else "image/png"
        output_path = target_dir / f"generated_{uuid.uuid4().hex[:8]}{_guess_ext_from_mime(mime_type)}"
        output_path.write_bytes(base64.b64decode(payload))
        return str(output_path)

    response = requests.get(image_url, timeout=OPENROUTER_IMAGE_HTTP_TIMEOUT_SECONDS)
    response.raise_for_status()
    mime_type = response.headers.get("Content-Type")
    suffix = Path(image_url.split("?")[0]).suffix or _guess_ext_from_mime(mime_type)
    output_path = target_dir / f"generated_{uuid.uuid4().hex[:8]}{suffix}"
    output_path.write_bytes(response.content)
    return str(output_path)


def _extract_generated_image_urls(response_payload: dict[str, Any]) -> list[str]:
    image_urls: list[str] = []
    for choice in response_payload.get("choices", []) or []:
        message = choice.get("message") or {}

        for image in message.get("images", []) or []:
            url = (
                ((image.get("image_url") or {}).get("url"))
                or image.get("url")
                or ((image.get("imageUrl") or {}).get("url"))
            )
            if url:
                image_urls.append(str(url))

        content = message.get("content")
        if isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                url = (
                    ((part.get("image_url") or {}).get("url"))
                    or ((part.get("imageUrl") or {}).get("url"))
                    or part.get("url")
                )
                if url and str(url) not in image_urls:
                    image_urls.append(str(url))
        elif isinstance(content, str):
            for match in re.findall(r"!\[[^\]]*\]\((.*?)\)", content):
                if match and match not in image_urls:
                    image_urls.append(match)
    return image_urls


def _extract_text_response(response_payload: dict[str, Any]) -> str:
    chunks: list[str] = []
    for choice in response_payload.get("choices", []) or []:
        message = choice.get("message") or {}
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            chunks.append(content.strip())
        elif isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                text = str(part.get("text") or part.get("content") or "").strip()
                if text:
                    chunks.append(text)
    return "\n".join(chunks).strip()


def _extract_rewritten_prompt(text: str) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    patterns = [
        r"(?is)\*\*prompt\*\*\s*(.+)$",
        r"(?is)image prompt[:：]\s*(.+)$",
        r"(?is)prompt[:：]\s*(.+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            candidate = match.group(1).strip()
            if candidate:
                return candidate
    return normalized


def _request_image_completion(
    *,
    prompt: str,
    model: str,
    aspect_ratio: str,
    reference_pic_paths: list[str] | None,
    system_prompt: str | None,
) -> dict[str, Any]:
    content_items: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for raw_path in reference_pic_paths or []:
        path = Path(raw_path).resolve()
        if not path.exists():
            continue
        content_items.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": _data_url_for_image(str(path)),
                },
            }
        )

    resolved_system_prompt = "\n\n".join(
        part for part in [str(system_prompt or "").strip(), OPENROUTER_IMAGE_ONLY_GUARDRAIL] if part
    )
    messages: list[dict[str, Any]] = [{"role": "user", "content": content_items}]
    if resolved_system_prompt:
        messages.insert(0, {"role": "system", "content": resolved_system_prompt})

    headers = {
        "Authorization": f"Bearer {openrouter_api_key()}",
        "Content-Type": "application/json",
    }
    if OPENROUTER_SITE_URL:
        headers["HTTP-Referer"] = OPENROUTER_SITE_URL
    if OPENROUTER_APP_NAME:
        headers["X-Title"] = OPENROUTER_APP_NAME

    payload = {
        "model": model or DEFAULT_IMAGE_MODEL,
        "messages": messages,
        "modalities": ["image", "text"],
        "image_config": {
            "aspect_ratio": aspect_ratio,
        },
    }

    response = requests.post(
        OPENROUTER_CHAT_COMPLETIONS_URL,
        headers=headers,
        json=payload,
        timeout=OPENROUTER_IMAGE_HTTP_TIMEOUT_SECONDS,
    )
    if not response.ok:
        raise RuntimeError(f"OpenRouter 图片生成失败 {response.status_code}: {response.text[:1200]}")

    result = response.json()
    if isinstance(result, dict) and result.get("error"):
        raise RuntimeError(f"OpenRouter 图片生成错误: {result['error']}")
    return result


def generate_image(
    prompt: str,
    model: str = DEFAULT_IMAGE_MODEL,
    aspect_ratio: str = "9:16",
    reference_pic_paths: list[str] | None = None,
    system_prompt: str | None = None,
    out_dir: str | None = None,
) -> str:
    result = _request_image_completion(
        prompt=prompt,
        model=model or DEFAULT_IMAGE_MODEL,
        aspect_ratio=aspect_ratio,
        reference_pic_paths=reference_pic_paths,
        system_prompt=system_prompt,
    )
    image_urls = _extract_generated_image_urls(result)
    if not image_urls:
        rewritten_prompt = _extract_rewritten_prompt(_extract_text_response(result))
        if rewritten_prompt and rewritten_prompt != str(prompt).strip():
            retry_result = _request_image_completion(
                prompt=rewritten_prompt,
                model=model or DEFAULT_IMAGE_MODEL,
                aspect_ratio=aspect_ratio,
                reference_pic_paths=reference_pic_paths,
                system_prompt=system_prompt,
            )
            image_urls = _extract_generated_image_urls(retry_result)
            if image_urls:
                return _save_generated_image(image_urls[0], out_dir=out_dir)
            raise RuntimeError(
                "OpenRouter 首次返回了重写后的 prompt 文本，二次强制出图仍未返回图片。"
                f" 首次响应: {str(result)[:1200]} 二次响应: {str(retry_result)[:1200]}"
            )
        raise RuntimeError(f"OpenRouter 未返回可保存图片。原始响应: {str(result)[:1200]}")
    return _save_generated_image(image_urls[0], out_dir=out_dir)
