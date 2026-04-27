from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from pprint import pformat
from types import ModuleType
from typing import Any

from agent.config import agent_root, resolve_path, save_settings
from agent.env import load_agent_env, meta_access_token_source, resolve_meta_access_token
from agent.history import append_history


_DEFAULT_META_LAUNCH = {
    "base_ad_ops_config_path": "config/ad_ops/material_flow_settings.py",
    "runtime_override_path": "runtime/ad_ops.generated.py",
    "default_page_id": "325789213957232",
    "default_target_adset_id": "120244986089430635",
    "default_landing_page_url": "https://anywellshop.com/products/150kg-capacity-electric-wheelchair",
    "default_video_name": "test",
    "default_ad_name": "test",
    "default_creative_name": "[Agent] test",
    "default_upload_mode": "library_only",
    "enabled_by_default": False,
}

_AD_OPS_KEYS = ["META_POOL_STATE", "META_ADS", "MONITOR_RULES"]


def _normalize_upload_mode(value: str) -> str:
    raw = str(value or "").strip().lower()
    if raw == "direct_adset":
        return "direct_adset"
    if raw in {"library_only", "material_only"}:
        return "library_only"
    return "library_only"


def _load_module_from_path(path: Path) -> ModuleType:
    if not path.exists():
        raise FileNotFoundError(f"未找到广告业务配置文件：{path}")
    spec = importlib.util.spec_from_file_location("agent_ad_ops_source", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载广告业务配置文件：{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _module_value(module: ModuleType, name: str, default: Any) -> Any:
    return copy.deepcopy(getattr(module, name, default))


def load_meta_launch_preferences(settings: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(_DEFAULT_META_LAUNCH)
    payload.update(settings.get("meta_launch", {}) if isinstance(settings.get("meta_launch"), dict) else {})
    payload["default_video_name"] = str(
        payload.get("default_video_name") or payload.get("default_ad_name") or _DEFAULT_META_LAUNCH["default_video_name"]
    ).strip()
    payload["default_upload_mode"] = _normalize_upload_mode(str(payload.get("default_upload_mode") or "library_only"))
    return payload


def save_meta_launch_preferences(settings: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    current = load_meta_launch_preferences(settings)
    current.update(
        {
            "default_page_id": str(payload.get("default_page_id") or current["default_page_id"]).strip(),
            "default_target_adset_id": str(payload.get("default_target_adset_id") or current["default_target_adset_id"]).strip(),
            "default_landing_page_url": str(payload.get("default_landing_page_url") or current["default_landing_page_url"]).strip(),
            "default_video_name": str(payload.get("default_video_name") or current["default_video_name"]).strip(),
            "default_ad_name": str(payload.get("default_ad_name") or current["default_ad_name"]).strip(),
            "default_creative_name": str(payload.get("default_creative_name") or current["default_creative_name"]).strip(),
            "default_upload_mode": _normalize_upload_mode(str(payload.get("default_upload_mode") or current["default_upload_mode"])),
            "enabled_by_default": bool(payload.get("enabled_by_default", current["enabled_by_default"])),
        }
    )
    settings["meta_launch"] = {
        "base_ad_ops_config_path": current["base_ad_ops_config_path"],
        "runtime_override_path": current["runtime_override_path"],
        "default_page_id": current["default_page_id"],
        "default_target_adset_id": current["default_target_adset_id"],
        "default_landing_page_url": current["default_landing_page_url"],
        "default_video_name": current["default_video_name"],
        "default_ad_name": current["default_ad_name"],
        "default_creative_name": current["default_creative_name"],
        "default_upload_mode": current["default_upload_mode"],
        "enabled_by_default": current["enabled_by_default"],
    }
    config_path = save_settings(settings)
    append_history(
        settings,
        event_type="meta_launch_settings_save",
        status="success",
        title="保存 Meta 上传默认值",
        payload={"config_path": str(config_path), "meta_launch": settings["meta_launch"]},
    )
    return {"config_path": str(config_path), "meta_launch": settings["meta_launch"]}


def base_ad_ops_config_path(settings: dict[str, Any]) -> Path:
    prefs = load_meta_launch_preferences(settings)
    return resolve_path(str(prefs.get("base_ad_ops_config_path") or _DEFAULT_META_LAUNCH["base_ad_ops_config_path"]))


def runtime_override_path(settings: dict[str, Any]) -> Path:
    prefs = load_meta_launch_preferences(settings)
    return resolve_path(str(prefs.get("runtime_override_path") or _DEFAULT_META_LAUNCH["runtime_override_path"]))


def _load_base_ad_ops_payload(settings: dict[str, Any]) -> dict[str, Any]:
    module = _load_module_from_path(base_ad_ops_config_path(settings))
    return {key: _module_value(module, key, {}) for key in _AD_OPS_KEYS}


def materialize_ad_ops_runtime(
    settings: dict[str, Any],
    *,
    read_only: bool,
    dry_run: bool = False,
    page_id: str = "",
    target_adset_id: str = "",
    landing_page_url: str = "",
) -> dict[str, Any]:
    prefs = load_meta_launch_preferences(settings)
    payload = _load_base_ad_ops_payload(settings)
    meta_ads = copy.deepcopy(payload.get("META_ADS", {}))
    meta_ads["read_only_mode"] = bool(read_only)
    meta_ads["dry_run_mode"] = bool(dry_run)
    if page_id or prefs.get("default_page_id"):
        meta_ads["page_id"] = str(page_id or prefs.get("default_page_id") or "").strip()
    if target_adset_id or prefs.get("default_target_adset_id"):
        meta_ads["default_target_adset_ids"] = [str(target_adset_id or prefs.get("default_target_adset_id") or "").strip()]
    if landing_page_url or prefs.get("default_landing_page_url"):
        meta_ads["default_landing_page_url"] = str(landing_page_url or prefs.get("default_landing_page_url") or "").strip()
    payload["META_ADS"] = meta_ads

    target_path = runtime_override_path(settings)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["from __future__ import annotations", "", "# Auto-generated by Agent Meta upload settings.", ""]
    for key in _AD_OPS_KEYS:
        lines.append(f"{key} = {pformat(payload.get(key, {}), width=100, sort_dicts=False)}")
        lines.append("")
    target_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return {"path": str(target_path), "exists": target_path.exists(), "meta_ads": meta_ads}


def validate_meta_upload_bridge(settings: dict[str, Any]) -> dict[str, Any]:
    load_agent_env()
    prefs = load_meta_launch_preferences(settings)
    base_path = base_ad_ops_config_path(settings)
    override_path = runtime_override_path(settings)
    token_present = bool(resolve_meta_access_token())
    meta_ads = _load_base_ad_ops_payload(settings).get("META_ADS", {})
    return {
        "ok": base_path.exists(),
        "token_present": token_present,
        "token_source": meta_access_token_source(),
        "resolved_ad_account_id": str(meta_ads.get("ad_account_id") or "").strip(),
        "base_ad_ops_config_path": str(base_path),
        "base_exists": base_path.exists(),
        "runtime_override_path": str(override_path),
        "runtime_override_exists": override_path.exists(),
        "preferences": prefs,
        "bundle_stage_script": str((agent_root() / "scripts" / "bundle_meta_stage.py").resolve()),
        "bundle_stage_script_exists": (agent_root() / "scripts" / "bundle_meta_stage.py").exists(),
    }


def stage_concept_to_meta(
    settings: dict[str, Any],
    concept_report_path: str,
    *,
    upload_mode: str = "library_only",
    allow_write: bool = False,
    page_id: str = "",
    target_adset_id: str = "",
    landing_page_url: str = "",
    video_name: str = "",
    ad_name: str = "",
    creative_name: str = "",
) -> dict[str, Any]:
    load_agent_env()
    normalized_upload_mode = _normalize_upload_mode(upload_mode)
    requires_write = normalized_upload_mode in {"library_only", "direct_adset"}
    if requires_write and not allow_write:
        result = {"status": "blocked", "message": "Meta 上传开关未开启。"}
        append_history(
            settings,
            event_type="meta_stage_concept",
            status="blocked",
            title="上传最近生成成片到 Meta",
            payload=result,
        )
        return result

    if requires_write and not resolve_meta_access_token():
        result = {"status": "blocked", "message": "缺少 META_ACCESS_TOKEN 或 FACEBOOK_ACCESS_TOKEN。"}
        append_history(
            settings,
            event_type="meta_stage_concept",
            status="blocked",
            title="上传最近生成成片到 Meta",
            payload=result,
        )
        return result

    runtime_override = materialize_ad_ops_runtime(
        settings,
        read_only=not requires_write,
        dry_run=False,
        page_id=page_id,
        target_adset_id=target_adset_id,
        landing_page_url=landing_page_url,
    )
    script_path = agent_root() / "scripts" / "bundle_meta_stage.py"
    env = dict(os.environ)
    env["AD_OPS_CONFIG_PATH"] = runtime_override["path"]
    command = [
        sys.executable,
        str(script_path),
        "--mode",
        "concept",
        "--concept-report-path",
        str(Path(concept_report_path).resolve()),
        "--action",
        normalized_upload_mode,
        "--page-id",
        str(page_id or "").strip(),
        "--target-adset-id",
        str(target_adset_id or "").strip(),
        "--landing-page-url",
        str(landing_page_url or "").strip(),
        "--video-name",
        str(video_name or "").strip(),
        "--ad-name",
        str(ad_name or "").strip(),
        "--creative-name",
        str(creative_name or "").strip(),
    ]
    completed = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
    try:
        result = json.loads(completed.stdout or "{}")
    except Exception:
        result = {
            "status": "failed",
            "message": "无法解析 Meta 上传结果。",
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
    result["returncode"] = completed.returncode
    result["runtime_override_path"] = runtime_override["path"]
    append_history(
        settings,
        event_type="meta_stage_concept",
        status="success" if int(completed.returncode or 1) == 0 else "failed",
        title="上传最近生成成片到 Meta",
        payload={
            "concept_report_path": str(Path(concept_report_path).resolve()),
            "upload_mode": normalized_upload_mode,
            "returncode": completed.returncode,
            "runtime_override_path": runtime_override["path"],
            "stdout_tail": (completed.stdout or "")[-2000:],
            "stderr_tail": (completed.stderr or "")[-2000:],
        },
    )
    return result


def stage_material_to_meta(
    settings: dict[str, Any],
    material_id: str,
    *,
    upload_mode: str = "library_only",
    allow_write: bool = False,
    page_id: str = "",
    target_adset_id: str = "",
    landing_page_url: str = "",
    video_name: str = "",
    ad_name: str = "",
    creative_name: str = "",
) -> dict[str, Any]:
    load_agent_env()
    normalized_upload_mode = _normalize_upload_mode(upload_mode)
    requires_write = normalized_upload_mode in {"library_only", "direct_adset"}
    if requires_write and not allow_write:
        result = {"status": "blocked", "message": "Meta 上传开关未开启。"}
        append_history(
            settings,
            event_type="meta_stage_material",
            status="blocked",
            title="上传已入库素材到 Meta",
            payload={"material_id": material_id, **result},
        )
        return result

    if requires_write and not resolve_meta_access_token():
        result = {"status": "blocked", "message": "缺少 META_ACCESS_TOKEN 或 FACEBOOK_ACCESS_TOKEN。"}
        append_history(
            settings,
            event_type="meta_stage_material",
            status="blocked",
            title="上传已入库素材到 Meta",
            payload={"material_id": material_id, **result},
        )
        return result

    runtime_override = materialize_ad_ops_runtime(
        settings,
        read_only=not requires_write,
        dry_run=False,
        page_id=page_id,
        target_adset_id=target_adset_id,
        landing_page_url=landing_page_url,
    )
    script_path = agent_root() / "scripts" / "bundle_meta_stage.py"
    env = dict(os.environ)
    env["AD_OPS_CONFIG_PATH"] = runtime_override["path"]
    command = [
        sys.executable,
        str(script_path),
        "--mode",
        "material",
        "--material-id",
        str(material_id).strip(),
        "--action",
        normalized_upload_mode,
        "--page-id",
        str(page_id or "").strip(),
        "--target-adset-id",
        str(target_adset_id or "").strip(),
        "--landing-page-url",
        str(landing_page_url or "").strip(),
        "--video-name",
        str(video_name or "").strip(),
        "--ad-name",
        str(ad_name or "").strip(),
        "--creative-name",
        str(creative_name or "").strip(),
    ]
    completed = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
    try:
        result = json.loads(completed.stdout or "{}")
    except Exception:
        result = {
            "status": "failed",
            "message": "无法解析 Meta 上传结果。",
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
    result["returncode"] = completed.returncode
    result["runtime_override_path"] = runtime_override["path"]
    append_history(
        settings,
        event_type="meta_stage_material",
        status="success" if int(completed.returncode or 1) == 0 else "failed",
        title="上传已入库素材到 Meta",
        payload={
            "material_id": str(material_id).strip(),
            "upload_mode": normalized_upload_mode,
            "returncode": completed.returncode,
            "runtime_override_path": runtime_override["path"],
            "stdout_tail": (completed.stdout or "")[-2000:],
            "stderr_tail": (completed.stderr or "")[-2000:],
        },
    )
    return result
