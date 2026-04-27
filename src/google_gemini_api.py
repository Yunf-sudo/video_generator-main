from __future__ import annotations

import base64
import json
import mimetypes
import os
import random
import time
from datetime import datetime, timezone
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from dotenv import load_dotenv

from runtime_tunables_config import load_runtime_tunables
from workspace_paths import ensure_active_run, write_run_json


load_dotenv()

RUNTIME_TUNABLES = load_runtime_tunables()
GOOGLE_API_RUNTIME = RUNTIME_TUNABLES["google_api_runtime"]
GOOGLE_API_BASE_URL = os.getenv(
    "GOOGLE_API_BASE_URL",
    str(GOOGLE_API_RUNTIME.get("google_api_base_url") or "https://generativelanguage.googleapis.com/v1beta"),
).strip()
DEFAULT_TEXT_MODEL = os.getenv(
    "TEXT_MODEL",
    os.getenv("SCRIPT_MODEL", str(RUNTIME_TUNABLES["model_config"].get("text_model") or "gemini-2.5-flash")),
)
DEFAULT_IMAGE_MODEL = os.getenv(
    "IMAGE_MODEL",
    str(RUNTIME_TUNABLES["model_config"].get("image_model") or "gemini-2.5-flash-image"),
)


class GoogleAPIConfigurationError(RuntimeError):
    pass


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def google_api_error_report_path() -> Path:
    return ensure_active_run().meta / "google_api_last_error.json"


def load_last_google_api_error_report() -> dict[str, Any]:
    path = google_api_error_report_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"report_path": str(path), "status": "unreadable"}


def _clear_google_api_error_report() -> None:
    try:
        path = google_api_error_report_path()
        if path.exists():
            path.unlink()
    except Exception:
        pass


def google_api_key() -> str:
    value = (
        os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
        or os.getenv("GOOGLE_GENAI_API_KEY")
    )
    if not value:
        report = _record_google_api_failure(
            method="POST",
            url="",
            attempts_used=0,
            failure_type="missing_api_key",
            failure_reason="未配置 Google API Key",
            suggestion="请在 .env 中补充 GEMINI_API_KEY、GOOGLE_API_KEY 或 GOOGLE_GENAI_API_KEY。",
            summary="Missing GEMINI_API_KEY or GOOGLE_API_KEY for Google Gemini API.",
            raw_error="Missing GEMINI_API_KEY or GOOGLE_API_KEY for Google Gemini API.",
        )
        raise GoogleAPIConfigurationError(
            "Google 请求失败：未配置 Google API Key。"
            f"请检查当前环境中的 GEMINI_API_KEY / GOOGLE_API_KEY。诊断文件：{report.get('report_path', '')}"
        )
    return value.strip().strip('"')


def _model_action_url(model: str, action: str = "generateContent") -> str:
    normalized = (model or "").strip() or DEFAULT_TEXT_MODEL
    if not normalized.startswith("models/"):
        normalized = f"models/{normalized}"
    return f"{GOOGLE_API_BASE_URL}/{normalized}:{action}"


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _coerce_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _request_max_attempts(default: int | None) -> int:
    configured = os.getenv(
        "GEMINI_REQUEST_MAX_ATTEMPTS",
        str(GOOGLE_API_RUNTIME.get("google_gemini_request_max_attempts") or ""),
    ).strip()
    fallback = default if default is not None else 5
    return max(1, _coerce_int(configured, fallback))


def _configured_text_fallback_models() -> list[str]:
    raw = (os.getenv("GEMINI_TEXT_FALLBACK_MODELS") or "").strip()
    if raw:
        parts = [item.strip() for item in raw.split(",")]
        return [item for item in parts if item]
    configured = GOOGLE_API_RUNTIME.get("google_gemini_text_fallback_models") or []
    if isinstance(configured, str):
        configured = [part.strip() for part in configured.split(",")]
    if not isinstance(configured, list):
        return []
    return [str(item).strip() for item in configured if str(item).strip()]


def _text_fallback_models_for(model: str) -> list[str]:
    normalized = (model or "").strip()
    if "image" in normalized.lower():
        return []
    fallbacks: list[str] = []
    for candidate in _configured_text_fallback_models():
        if candidate and candidate != normalized and candidate not in fallbacks:
            fallbacks.append(candidate)
    return fallbacks


def _should_try_text_model_fallback(exc: Exception) -> bool:
    message = str(exc or "").lower()
    return any(
        token in message
        for token in [
            "http 429",
            "http 503",
            "too many requests",
            "service unavailable",
            "high demand",
            "unavailable",
            "quota",
            "resource_exhausted",
        ]
    )


def _retry_backoff_seconds(attempt: int, *, is_rate_limited: bool, retry_after_seconds: float | None) -> float:
    base_seconds = _coerce_float(
        os.getenv(
            "GEMINI_RETRY_BASE_SECONDS",
            str(GOOGLE_API_RUNTIME.get("google_gemini_retry_base_seconds") or ""),
        ).strip(),
        5.0,
    )
    max_seconds = _coerce_float(
        os.getenv(
            "GEMINI_RETRY_MAX_SECONDS",
            str(GOOGLE_API_RUNTIME.get("google_gemini_retry_max_seconds") or ""),
        ).strip(),
        45.0,
    )
    rate_limit_floor = _coerce_float(
        os.getenv(
            "GEMINI_RATE_LIMIT_COOLDOWN_SECONDS",
            str(GOOGLE_API_RUNTIME.get("google_gemini_rate_limit_cooldown_seconds") or ""),
        ).strip(),
        30.0,
    )
    jitter_seconds = max(
        0.0,
        _coerce_float(
            os.getenv(
                "GEMINI_RETRY_JITTER_SECONDS",
                str(GOOGLE_API_RUNTIME.get("google_gemini_retry_jitter_seconds") or ""),
            ).strip(),
            1.0,
        ),
    )
    retry_after_floor = max(0.0, retry_after_seconds or 0.0)
    backoff = min(max_seconds, max(base_seconds, 0.5) * (2 ** max(0, attempt - 1)))
    if is_rate_limited:
        backoff = max(backoff, rate_limit_floor)
    backoff = max(backoff, retry_after_floor)
    return backoff + (random.uniform(0.0, jitter_seconds) if jitter_seconds > 0 else 0.0)


def _read_http_error_body(exc: urllib.error.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", errors="ignore").strip()
    except Exception:
        return ""


def _retry_after_seconds(exc: urllib.error.HTTPError) -> float | None:
    retry_after = ""
    try:
        retry_after = str(exc.headers.get("Retry-After") or "").strip()
    except Exception:
        retry_after = ""
    if not retry_after:
        return None
    try:
        return max(0.0, float(retry_after))
    except ValueError:
        return None


def _format_http_error_summary(exc: urllib.error.HTTPError, body: str = "") -> str:
    summary = f"HTTP {exc.code}: {exc.reason}"
    if body:
        compact_body = " ".join(body.split())
        if compact_body:
            summary = f"{summary} | {compact_body[:240]}"
    return summary


def _is_retryable_http_error(exc: urllib.error.HTTPError) -> bool:
    return int(getattr(exc, "code", 0) or 0) in {408, 429, 500, 502, 503, 504}


def _parse_google_error_body(body: str) -> dict[str, Any]:
    if not body:
        return {}
    try:
        parsed = json.loads(body)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _request_identity(url: str) -> dict[str, str]:
    identity = {"model": "", "action": "", "path": ""}
    try:
        parsed = urllib.parse.urlparse(url)
        identity["path"] = parsed.path
        tail = parsed.path.rsplit("/", 1)[-1]
        if ":" in tail:
            model_part, action = tail.split(":", 1)
            identity["model"] = model_part.replace("models/", "", 1)
            identity["action"] = action
    except Exception:
        pass
    return identity


def _classify_google_api_failure(
    *,
    http_status: int | None,
    body: str,
    summary: str,
    raw_error: str,
) -> dict[str, str]:
    text = " ".join(part for part in [body, summary, raw_error] if part).lower()
    if (
        "missing gemini_api_key" in text
        or "missing google_api_key" in text
        or "未配置 google api key" in text
        or "未配置 google api" in text
    ):
        return {
            "failure_type": "missing_api_key",
            "failure_reason": "未配置 Google API Key",
            "suggestion": "请在 .env 中补充 GEMINI_API_KEY、GOOGLE_API_KEY 或 GOOGLE_GENAI_API_KEY。",
        }
    if http_status == 429:
        if any(token in text for token in ["quota", "resource_exhausted", "rate limit exceeded", "exceeded your current quota"]):
            return {
                "failure_type": "quota_or_rate_limit",
                "failure_reason": "Google 配额耗尽或请求过于频繁",
                "suggestion": "先等待 1-2 分钟再试；如果持续出现，请检查 Google 项目配额、计费状态或降低调用频率。",
            }
        return {
            "failure_type": "rate_limited",
            "failure_reason": "Google 接口限流",
            "suggestion": "先等待 1-2 分钟再试，并避免连续重复提交。",
        }
    if http_status in {401, 403}:
        if any(token in text for token in ["api_key_invalid", "api key not valid", "invalid api key"]):
            return {
                "failure_type": "invalid_api_key",
                "failure_reason": "Google API Key 无效",
                "suggestion": "请检查当前运行环境中的 GEMINI_API_KEY / GOOGLE_API_KEY 是否填写正确。",
            }
        if any(token in text for token in ["service_disabled", "api has not been used", "generativelanguageapi has not been used"]):
            return {
                "failure_type": "service_disabled",
                "failure_reason": "Google Generative Language API 未开通",
                "suggestion": "请到 Google Cloud 项目中启用 Generative Language API。",
            }
        if "billing" in text:
            return {
                "failure_type": "billing_disabled",
                "failure_reason": "Google Cloud 计费未启用或已失效",
                "suggestion": "请检查当前 Google Cloud 项目的 Billing 状态。",
            }
        return {
            "failure_type": "permission_denied",
            "failure_reason": "Google 权限不足或访问被拒绝",
            "suggestion": "请确认 API Key 所属项目、API 开通状态和权限配置是否正确。",
        }
    if http_status == 404 or "model" in text and "not found" in text:
        return {
            "failure_type": "model_not_found",
            "failure_reason": "请求的 Google 模型不存在或当前账号不可用",
            "suggestion": "请检查模型名称以及当前 API Key 是否有权限访问该模型。",
        }
    if http_status == 400:
        if any(token in text for token in ["safety", "blocked", "policy"]):
            return {
                "failure_type": "blocked_by_policy",
                "failure_reason": "Google 安全策略拦截了请求",
                "suggestion": "请调整提示词，移除可能触发平台策略的内容。",
            }
        return {
            "failure_type": "bad_request",
            "failure_reason": "Google 请求参数无效",
            "suggestion": "请检查模型名、请求体结构和输入内容是否符合接口要求。",
        }
    if http_status and http_status >= 500:
        return {
            "failure_type": "server_error",
            "failure_reason": "Google 服务端暂时异常",
            "suggestion": "稍后重试；如果连续失败，请保留诊断文件进一步排查。",
        }
    if "timed out" in text or "timeout" in text:
        return {
            "failure_type": "timeout",
            "failure_reason": "连接 Google 超时",
            "suggestion": "请检查本机网络或适当提高请求超时时间。",
        }
    if any(token in text for token in ["temporary failure in name resolution", "name or service not known", "nodename nor servname", "connection reset"]):
        return {
            "failure_type": "network_error",
            "failure_reason": "连接 Google 时网络异常",
            "suggestion": "请检查网络、代理或 DNS 配置。",
        }
    return {
        "failure_type": "unknown_google_error",
        "failure_reason": "Google 请求失败，原因未自动识别",
        "suggestion": "请查看诊断文件中的原始响应内容进一步确认。",
    }


def _record_google_api_failure(
    *,
    method: str,
    url: str,
    attempts_used: int,
    failure_type: str,
    failure_reason: str,
    suggestion: str,
    summary: str,
    raw_error: str,
    http_status: int | None = None,
    response_body: str = "",
    response_json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    identity = _request_identity(url)
    payload: dict[str, Any] = {
        "status": "failed",
        "failed_at": _utc_now_iso(),
        "failure_type": failure_type,
        "failure_reason": failure_reason,
        "suggestion": suggestion,
        "summary": summary,
        "raw_error": raw_error,
        "http_status": http_status,
        "attempts_used": attempts_used,
        "request": {
            "method": method.upper(),
            "url": url,
            "model": identity.get("model", ""),
            "action": identity.get("action", ""),
            "path": identity.get("path", ""),
        },
        "response_body_preview": response_body[:1000] if response_body else "",
        "response_json": response_json or {},
    }
    report_path = write_run_json("google_api_last_error.json", payload)
    payload["report_path"] = str(report_path)
    return payload


def request_json(
    method: str,
    url: str,
    payload_json: dict[str, Any] | None = None,
    timeout_seconds: float = 300.0,
    max_attempts: int | None = None,
) -> dict[str, Any]:
    last_error: Exception | None = None
    resolved_attempts = _request_max_attempts(max_attempts)
    last_summary = ""
    for attempt in range(1, resolved_attempts + 1):
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
                _clear_google_api_error_report()
                return json.loads(response.read().decode("utf-8"))
        except GoogleAPIConfigurationError:
            raise
        except urllib.error.HTTPError as exc:
            body = _read_http_error_body(exc)
            last_error = exc
            last_summary = _format_http_error_summary(exc, body)
            if not _is_retryable_http_error(exc) or attempt >= resolved_attempts:
                failure_meta = _classify_google_api_failure(
                    http_status=exc.code,
                    body=body,
                    summary=last_summary,
                    raw_error=str(exc),
                )
                report = _record_google_api_failure(
                    method=method,
                    url=url,
                    attempts_used=attempt,
                    http_status=exc.code,
                    response_body=body,
                    response_json=_parse_google_error_body(body),
                    summary=last_summary,
                    raw_error=str(exc),
                    failure_type=failure_meta["failure_type"],
                    failure_reason=failure_meta["failure_reason"],
                    suggestion=failure_meta["suggestion"],
                )
                if exc.code == 429:
                    raise RuntimeError(
                        f"Google 请求失败：{failure_meta['failure_reason']}。"
                        f"已重试 {resolved_attempts} 次。建议：{failure_meta['suggestion']} "
                        f"诊断文件：{report.get('report_path', '')}。最后响应：{last_summary}"
                    ) from exc
                raise RuntimeError(
                    f"Google 请求失败：{failure_meta['failure_reason']}。"
                    f"建议：{failure_meta['suggestion']} "
                    f"诊断文件：{report.get('report_path', '')}。最后响应：{last_summary}"
                ) from exc
            time.sleep(
                _retry_backoff_seconds(
                    attempt,
                    is_rate_limited=exc.code == 429,
                    retry_after_seconds=_retry_after_seconds(exc),
                )
            )
        except urllib.error.URLError as exc:
            last_error = exc
            last_summary = str(exc.reason or exc)
            if attempt >= resolved_attempts:
                failure_meta = _classify_google_api_failure(
                    http_status=None,
                    body="",
                    summary=last_summary,
                    raw_error=str(exc),
                )
                report = _record_google_api_failure(
                    method=method,
                    url=url,
                    attempts_used=attempt,
                    summary=last_summary,
                    raw_error=str(exc),
                    failure_type=failure_meta["failure_type"],
                    failure_reason=failure_meta["failure_reason"],
                    suggestion=failure_meta["suggestion"],
                )
                raise RuntimeError(
                    f"Google 请求失败：{failure_meta['failure_reason']}。"
                    f"建议：{failure_meta['suggestion']} "
                    f"诊断文件：{report.get('report_path', '')}。原始错误：{last_summary}"
                ) from exc
            time.sleep(_retry_backoff_seconds(attempt, is_rate_limited=False, retry_after_seconds=None))
        except Exception as exc:
            last_error = exc
            last_summary = str(exc)
            if attempt >= resolved_attempts:
                failure_meta = _classify_google_api_failure(
                    http_status=None,
                    body="",
                    summary=last_summary,
                    raw_error=str(exc),
                )
                report = _record_google_api_failure(
                    method=method,
                    url=url,
                    attempts_used=attempt,
                    summary=last_summary,
                    raw_error=str(exc),
                    failure_type=failure_meta["failure_type"],
                    failure_reason=failure_meta["failure_reason"],
                    suggestion=failure_meta["suggestion"],
                )
                raise RuntimeError(
                    f"Google 请求失败：{failure_meta['failure_reason']}。"
                    f"建议：{failure_meta['suggestion']} "
                    f"诊断文件：{report.get('report_path', '')}。原始错误：{last_summary}"
                ) from exc
            time.sleep(_retry_backoff_seconds(attempt, is_rate_limited=False, retry_after_seconds=None))
    raise RuntimeError(f"Gemini API请求重试失败：{last_summary or last_error}")


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
    candidate_models = [str(model or "").strip() or DEFAULT_TEXT_MODEL, *_text_fallback_models_for(model)]
    last_error: Exception | None = None
    for index, candidate_model in enumerate(candidate_models):
        try:
            return request_json(
                "POST",
                _model_action_url(candidate_model, "generateContent"),
                payload_json=payload,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            last_error = exc
            if index >= len(candidate_models) - 1 or not _should_try_text_model_fallback(exc):
                raise
    if last_error is not None:
        raise last_error
    raise RuntimeError("Google 请求失败：未能从 Gemini 获取响应。")


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
