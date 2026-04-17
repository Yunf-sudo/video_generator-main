from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any
import uuid

import requests

from ad_ops_config import load_ad_ops_config
from material_library import append_material_event, load_material_record, update_material_record


AD_OPS_CONFIG = load_ad_ops_config()
META_ADS_CONFIG = AD_OPS_CONFIG["meta_ads"]
MATERIAL_LIBRARY_CONFIG = AD_OPS_CONFIG["material_library"]


def _meta_access_token() -> str:
    token = (os.getenv("META_ACCESS_TOKEN") or os.getenv("FACEBOOK_ACCESS_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("缺少 META_ACCESS_TOKEN 或 FACEBOOK_ACCESS_TOKEN。")
    return token


def _api_version() -> str:
    return str(META_ADS_CONFIG.get("api_version") or "v19.0").strip()


def _graph_url(path: str) -> str:
    return f"https://graph.facebook.com/{_api_version()}/{path.lstrip('/')}"


def _ad_account_id() -> str:
    value = (os.getenv("META_AD_ACCOUNT_ID") or str(META_ADS_CONFIG.get("ad_account_id") or "")).strip()
    if not value:
        raise RuntimeError("缺少 META_AD_ACCOUNT_ID 或配置中的 ad_account_id。")
    return value


def _page_id(material: dict[str, Any]) -> str:
    value = str(material.get("page_id") or os.getenv("META_PAGE_ID") or str(META_ADS_CONFIG.get("page_id") or "")).strip()
    if not value:
        raise RuntimeError("缺少 Page ID。请在素材记录、环境变量或配置文件里设置。")
    return value


def _target_adset_id(material: dict[str, Any]) -> str:
    value = str(material.get("target_adset_id") or os.getenv("META_DEFAULT_ADSET_ID") or "").strip()
    if value:
        return value
    default_ids = META_ADS_CONFIG.get("default_target_adset_ids") or []
    if isinstance(default_ids, list):
        for candidate in default_ids:
            if str(candidate or "").strip():
                return str(candidate).strip()
    raise RuntimeError("缺少 target_adset_id。请在素材记录、环境变量或配置文件里设置。")


def _landing_page_url(material: dict[str, Any]) -> str:
    value = str(material.get("landing_page_url") or os.getenv("META_DEFAULT_LANDING_PAGE_URL") or str(META_ADS_CONFIG.get("default_landing_page_url") or "")).strip()
    if not value:
        raise RuntimeError("缺少 landing_page_url。")
    return value


def _default_initial_status() -> str:
    return str(MATERIAL_LIBRARY_CONFIG.get("default_meta_ad_status") or "PAUSED").strip().upper()


def _dry_run_enabled() -> bool:
    return str(
        os.getenv(
            "META_ADS_DRY_RUN",
            str(META_ADS_CONFIG.get("dry_run_mode", False)),
        )
    ).strip().lower() in {"1", "true", "yes", "on"}


def _request(method: str, path: str, *, data: dict[str, Any] | None = None, files: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(data or {})
    payload["access_token"] = _meta_access_token()
    response = requests.request(
        method.upper(),
        _graph_url(path),
        data=payload,
        files=files,
        timeout=180,
    )
    try:
        body = response.json()
    except Exception:
        body = {"raw": response.text}
    if not response.ok:
        raise RuntimeError(f"Meta API 调用失败: {json.dumps(body, ensure_ascii=False)}")
    return body if isinstance(body, dict) else {}


def upload_video_to_meta(material_id: str) -> dict[str, Any]:
    material = load_material_record(material_id)
    video_path = str(material.get("storage_uri") or "").strip()
    if not video_path or not Path(video_path).exists():
        raise FileNotFoundError(f"素材视频不存在：{video_path}")

    if _dry_run_enabled():
        response = {"id": f"dry_video_{uuid.uuid4().hex[:10]}"}
    else:
        with open(video_path, "rb") as handle:
            response = _request(
                "POST",
                f"{_ad_account_id()}/advideos",
                data={
                    "name": f"{META_ADS_CONFIG.get('ad_name_prefix', '[Auto-Gen]')} {material_id}",
                },
                files={"source": handle},
            )

    video_id = str(response.get("id") or "").strip()
    if not video_id:
        raise RuntimeError(f"Meta 视频上传成功但未返回 video_id: {response}")

    material = update_material_record(
        material_id,
        {
            "meta_mapping": {
                **(material.get("meta_mapping") or {}),
                "video_id": video_id,
            },
            "launch_status": "video_uploaded",
            "updated_at": datetime.utcnow().isoformat(),
        },
    )
    append_material_event(material_id, "meta_video_uploaded", {"video_id": video_id})
    return material


def create_ad_creative_for_material(material_id: str) -> dict[str, Any]:
    material = load_material_record(material_id)
    video_id = str((material.get("meta_mapping") or {}).get("video_id") or "").strip()
    if not video_id:
        material = upload_video_to_meta(material_id)
        video_id = str((material.get("meta_mapping") or {}).get("video_id") or "").strip()

    copy_block = material.get("copy") or {}
    object_story_spec = {
        "page_id": _page_id(material),
        "video_data": {
            "video_id": video_id,
            "message": str(copy_block.get("primary_text") or "").strip(),
            "title": str(copy_block.get("headline") or "").strip(),
            "description": str(copy_block.get("description") or "").strip(),
            "call_to_action": {
                "type": str(copy_block.get("cta") or META_ADS_CONFIG.get("default_call_to_action") or "LEARN_MORE").strip(),
                "value": {
                    "link": _landing_page_url(material),
                },
            },
        },
    }
    if _dry_run_enabled():
        response = {"id": f"dry_creative_{uuid.uuid4().hex[:10]}"}
    else:
        response = _request(
            "POST",
            f"{_ad_account_id()}/adcreatives",
            data={
                "name": f"{META_ADS_CONFIG.get('creative_name_prefix', '[Auto-Creative]')} {material_id}",
                "object_story_spec": json.dumps(object_story_spec, ensure_ascii=False),
            },
        )
    creative_id = str(response.get("id") or "").strip()
    if not creative_id:
        raise RuntimeError(f"Meta 创意创建成功但未返回 creative_id: {response}")

    material = update_material_record(
        material_id,
        {
            "meta_mapping": {
                **(material.get("meta_mapping") or {}),
                "creative_id": creative_id,
                "video_id": video_id,
            },
            "launch_status": "creative_created",
        },
    )
    append_material_event(material_id, "meta_creative_created", {"creative_id": creative_id})
    return material


def create_paused_ad_for_material(material_id: str) -> dict[str, Any]:
    material = load_material_record(material_id)
    creative_id = str((material.get("meta_mapping") or {}).get("creative_id") or "").strip()
    if not creative_id:
        material = create_ad_creative_for_material(material_id)
        creative_id = str((material.get("meta_mapping") or {}).get("creative_id") or "").strip()

    ad_name_prefix = str(META_ADS_CONFIG.get("ad_name_prefix") or "[Auto-Gen]").strip()
    target_adset_id = _target_adset_id(material)
    if _dry_run_enabled():
        response = {"id": f"dry_ad_{uuid.uuid4().hex[:10]}"}
    else:
        response = _request(
            "POST",
            f"{_ad_account_id()}/ads",
            data={
                "name": f"{ad_name_prefix} {material_id}",
                "adset_id": target_adset_id,
                "creative": json.dumps({"creative_id": creative_id}, ensure_ascii=False),
                "status": _default_initial_status(),
            },
        )
    ad_id = str(response.get("id") or "").strip()
    if not ad_id:
        raise RuntimeError(f"Meta 广告创建成功但未返回 ad_id: {response}")

    launch_status = "prelaunched_paused" if _default_initial_status() == "PAUSED" else "prelaunched_active"
    material = update_material_record(
        material_id,
        {
            "target_adset_id": target_adset_id,
            "meta_mapping": {
                **(material.get("meta_mapping") or {}),
                "creative_id": creative_id,
                "ad_id": ad_id,
            },
            "launch_status": launch_status,
            "ad_enable_status": "paused" if _default_initial_status() == "PAUSED" else "active",
            "meta_runtime": {
                "dry_run": _dry_run_enabled(),
                "status": "PAUSED" if _default_initial_status() == "PAUSED" else "ACTIVE",
            },
        },
    )
    append_material_event(
        material_id,
        "meta_ad_created",
        {
            "ad_id": ad_id,
            "target_adset_id": target_adset_id,
            "status": _default_initial_status(),
        },
    )
    return material


def change_meta_ad_status(ad_id: str, new_status: str) -> dict[str, Any]:
    if _dry_run_enabled():
        return {"success": True, "id": ad_id, "status": str(new_status or "").strip().upper()}
    return _request(
        "POST",
        ad_id,
        data={"status": str(new_status or "").strip().upper()},
    )


def activate_prelaunched_material(material_id: str) -> dict[str, Any]:
    material = load_material_record(material_id)
    ad_id = str((material.get("meta_mapping") or {}).get("ad_id") or "").strip()
    if not ad_id:
        raise RuntimeError(f"素材 {material_id} 还没有预上架广告 ad_id。")
    change_meta_ad_status(ad_id, "ACTIVE")
    material = update_material_record(
        material_id,
        {
            "launch_status": "active",
            "ad_enable_status": "active",
            "meta_runtime": {
                **(material.get("meta_runtime") or {}),
                "dry_run": _dry_run_enabled(),
                "status": "ACTIVE",
            },
        },
    )
    append_material_event(material_id, "meta_ad_activated", {"ad_id": ad_id})
    return material


def pause_material_ad(material_id: str, reason: str = "") -> dict[str, Any]:
    material = load_material_record(material_id)
    ad_id = str((material.get("meta_mapping") or {}).get("ad_id") or "").strip()
    if not ad_id:
        raise RuntimeError(f"素材 {material_id} 没有关联 ad_id。")
    change_meta_ad_status(ad_id, "PAUSED")
    material = update_material_record(
        material_id,
        {
            "launch_status": "paused_by_rule",
            "ad_enable_status": "paused",
            "pause_reason": reason,
            "meta_runtime": {
                **(material.get("meta_runtime") or {}),
                "dry_run": _dry_run_enabled(),
                "status": "PAUSED",
            },
        },
    )
    append_material_event(material_id, "meta_ad_paused", {"ad_id": ad_id, "reason": reason})
    return material
