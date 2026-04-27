from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import requests

from agent.config import load_settings, resolve_path
from agent.env import (
    google_api_key_source,
    load_agent_env,
    meta_access_token_source,
    resolve_google_api_key,
    resolve_meta_access_token,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _diag_path(settings: dict[str, Any]) -> str:
    runtime = settings.get("runtime", {}) if isinstance(settings.get("runtime"), dict) else {}
    path = resolve_path(str(runtime.get("api_diagnostics_report_path") or "runtime/api_diagnostics_report.json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def _service_status(service: str, status: str, summary: str, **extra: Any) -> dict[str, Any]:
    payload = {
        "service": service,
        "status": status,
        "summary": summary,
    }
    payload.update(extra)
    return payload


def _extract_google_text(body: dict[str, Any]) -> str:
    texts: list[str] = []
    for candidate in body.get("candidates", []) or []:
        content = candidate.get("content", {})
        for part in content.get("parts", []) or []:
            text = part.get("text")
            if text:
                texts.append(str(text))
    return "".join(texts).strip()


def _google_model_name() -> str:
    return (
        os.getenv("SCRIPT_MODEL")
        or os.getenv("TEXT_MODEL")
        or "gemini-2.5-flash"
    ).strip()


def probe_google_api() -> dict[str, Any]:
    key = resolve_google_api_key()
    if not key:
        return _service_status(
            "google_gemini",
            "blocked",
            "缺少 Google API Key。",
            reason="请在 Agent/.env 中补充 GEMINI_API_KEY、GOOGLE_API_KEY 或 GOOGLE_GENAI_API_KEY。",
            key_source="",
            model=_google_model_name(),
        )

    model = _google_model_name()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": "Reply with exactly: OK"}],
            }
        ],
        "generationConfig": {"temperature": 0},
    }
    try:
        response = requests.post(
            url,
            headers={
                "x-goog-api-key": key,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "Anywell-Agent-Diagnostics/1.0",
            },
            json=payload,
            timeout=45,
        )
    except requests.RequestException as exc:
        return _service_status(
            "google_gemini",
            "failed",
            "Google Gemini 网络连接失败。",
            reason=str(exc),
            key_source=google_api_key_source(),
            model=model,
        )

    try:
        body = response.json()
    except Exception:
        body = {"raw": response.text}

    if response.ok:
        return _service_status(
            "google_gemini",
            "success",
            "Google Gemini 文本接口可用。",
            key_source=google_api_key_source(),
            model=model,
            response_preview=_extract_google_text(body)[:120],
        )

    body_text = json.dumps(body, ensure_ascii=False)
    lower = body_text.lower()
    if response.status_code == 429:
        summary = "Google Gemini 接口限流或配额不足。"
    elif response.status_code in {401, 403} and "api key" in lower:
        summary = "Google API Key 无效或权限不足。"
    elif response.status_code in {401, 403} and "service_disabled" in lower:
        summary = "Google Generative Language API 未开通。"
    elif response.status_code in {401, 403} and "billing" in lower:
        summary = "Google Cloud 计费未启用或已失效。"
    elif response.status_code == 404:
        summary = "Google 模型不存在或当前账号不可用。"
    else:
        summary = "Google Gemini 接口调用失败。"
    return _service_status(
        "google_gemini",
        "failed",
        summary,
        http_status=response.status_code,
        key_source=google_api_key_source(),
        model=model,
        response_body=body,
    )


def _meta_ad_account_id(settings: dict[str, Any]) -> str:
    meta = settings.get("meta", {}) if isinstance(settings.get("meta"), dict) else {}
    return str(os.getenv("META_AD_ACCOUNT_ID") or meta.get("ad_account_id") or "").strip()


def probe_meta_api(settings: dict[str, Any]) -> dict[str, Any]:
    token = resolve_meta_access_token()
    ad_account_id = _meta_ad_account_id(settings)
    if not token:
        return _service_status(
            "meta_ads",
            "blocked",
            "缺少 Meta Access Token。",
            reason="请在 Agent/.env 中补充 META_ACCESS_TOKEN。",
            token_source="",
            ad_account_id=ad_account_id,
        )
    if not ad_account_id:
        return _service_status(
            "meta_ads",
            "blocked",
            "缺少广告账户 ID。",
            reason="请在 Agent/.env 或 agent_settings.json 中补充 META_AD_ACCOUNT_ID。",
            token_source=meta_access_token_source(),
            ad_account_id="",
        )

    version = str((settings.get("meta", {}) or {}).get("api_version") or "v19.0").strip()
    try:
        response = requests.get(
            f"https://graph.facebook.com/{version}/{ad_account_id}",
            params={
                "fields": "id,name,account_status",
                "access_token": token,
            },
            timeout=45,
        )
    except requests.RequestException as exc:
        return _service_status(
            "meta_ads",
            "failed",
            "Meta Graph API 网络连接失败。",
            reason=str(exc),
            token_source=meta_access_token_source(),
            ad_account_id=ad_account_id,
        )

    try:
        body = response.json()
    except Exception:
        body = {"raw": response.text}

    if response.ok:
        return _service_status(
            "meta_ads",
            "success",
            "Meta 广告账户读取正常。",
            token_source=meta_access_token_source(),
            ad_account_id=str(body.get("id") or ad_account_id),
            account_name=str(body.get("name") or ""),
            account_status=body.get("account_status"),
        )

    body_text = json.dumps(body, ensure_ascii=False)
    lower = body_text.lower()
    if response.status_code in {401, 403} and "access token" in lower:
        summary = "Meta Access Token 无效或已过期。"
    elif response.status_code in {401, 403} and "permissions" in lower:
        summary = "Meta Token 权限不足，无法访问广告账户。"
    else:
        summary = "Meta Graph API 调用失败。"
    return _service_status(
        "meta_ads",
        "failed",
        summary,
        token_source=meta_access_token_source(),
        ad_account_id=ad_account_id,
        http_status=response.status_code,
        response_body=body,
    )


def probe_optional_services() -> list[dict[str, Any]]:
    youtube_ready = bool((os.getenv("YOUTUBE_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip())
    rustfs_ready = all(
        bool((os.getenv(name) or "").strip())
        for name in ["RUSTFS_ENDPOINT", "RUSTFS_ACCESS_KEY", "RUSTFS_ACCESS_SECRET"]
    )
    dashscope_ready = bool((os.getenv("DASHSCOPE_API_KEY") or "").strip())
    return [
        _service_status(
            "youtube_api",
            "ready" if youtube_ready else "optional_missing",
            "YouTube 分析接口已配置。" if youtube_ready else "YouTube 分析接口未配置，竞品视频分析功能将不可用。",
        ),
        _service_status(
            "rustfs",
            "ready" if rustfs_ready else "optional_fallback",
            "RustFS 已配置。" if rustfs_ready else "RustFS 未配置，音频/字幕会回退到本地文件地址。",
        ),
        _service_status(
            "dashscope_asr",
            "ready" if dashscope_ready else "optional_missing",
            "DashScope ASR 已配置。" if dashscope_ready else "DashScope ASR 未配置，部分自动转字幕能力可能不可用。",
        ),
    ]


def run_api_diagnostics(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    load_agent_env()
    resolved_settings = settings or load_settings()
    services = [
        probe_google_api(),
        probe_meta_api(resolved_settings),
        *probe_optional_services(),
    ]
    summary = {
        "success": sum(1 for item in services if item.get("status") == "success"),
        "failed": sum(1 for item in services if item.get("status") == "failed"),
        "blocked": sum(1 for item in services if item.get("status") == "blocked"),
        "optional_missing": sum(1 for item in services if item.get("status") in {"optional_missing", "optional_fallback"}),
    }
    report = {
        "run_time": _utc_now_iso(),
        "services": services,
        "summary": summary,
    }
    report_path = _diag_path(resolved_settings)
    with open(report_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    report["report_path"] = report_path
    return report
