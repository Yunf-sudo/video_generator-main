from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ad_ops_config import load_ad_ops_config
from workspace_paths import PROJECT_ROOT, ensure_dir


AD_OPS_CONFIG = load_ad_ops_config()
META_POOL_STATE_CONFIG = AD_OPS_CONFIG["meta_pool_state"]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _state_root() -> Path:
    configured = str(
        META_POOL_STATE_CONFIG.get("state_root")
        or META_POOL_STATE_CONFIG.get("library_root")
        or "generated/ad_ops_state"
    ).strip()
    root = Path(configured)
    if not root.is_absolute():
        root = (PROJECT_ROOT / root).resolve()
    return ensure_dir(root)


@dataclass(frozen=True)
class MetaPoolStatePaths:
    root: Path
    materials: Path
    assets: Path
    archives: Path
    alerts: Path
    reports: Path


def meta_pool_state_paths() -> MetaPoolStatePaths:
    root = _state_root()
    materials = ensure_dir(root / "materials")
    assets = root / "assets"
    if bool(META_POOL_STATE_CONFIG.get("copy_assets_to_workspace", False)):
        assets = ensure_dir(assets)
    archives = ensure_dir(root / "archives")
    alerts = ensure_dir(root / str(META_POOL_STATE_CONFIG.get("alerts_bucket") or "alerts"))
    reports = ensure_dir(root / "reports")
    ensure_dir(archives / str(META_POOL_STATE_CONFIG.get("success_archive_bucket") or "success_ads"))
    ensure_dir(archives / str(META_POOL_STATE_CONFIG.get("failed_archive_bucket") or "failed_ads"))
    return MetaPoolStatePaths(
        root=root,
        materials=materials,
        assets=assets,
        archives=archives,
        alerts=alerts,
        reports=reports,
    )


def _material_record_path(material_id: str) -> Path:
    return meta_pool_state_paths().materials / f"{material_id}.json"


def _copy_asset_to_library(source_path: str, material_id: str, suffix_hint: str = "") -> str:
    source = Path(source_path).resolve()
    if not source.exists():
        return ""
    if not bool(META_POOL_STATE_CONFIG.get("copy_assets_to_workspace", False)):
        return str(source)
    ext = source.suffix or suffix_hint or ".bin"
    target = meta_pool_state_paths().assets / f"{material_id}{ext}"
    if source.resolve() != target.resolve():
        shutil.copy2(source, target)
    return str(target)


def save_material_record(record: dict[str, Any]) -> Path:
    material_id = str(record.get("material_id") or "").strip()
    if not material_id:
        raise ValueError("material record 缺少 material_id")
    target = _material_record_path(material_id)
    target.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def delete_material_record(material_id: str) -> None:
    path = _material_record_path(material_id)
    if path.exists():
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            record = {}
        asset_path = str(record.get("storage_uri") or "").strip()
        if bool(record.get("managed_asset")) and asset_path and Path(asset_path).exists():
            Path(asset_path).unlink(missing_ok=True)
        path.unlink(missing_ok=True)

        for archive_path in meta_pool_state_paths().archives.rglob(f"{material_id}.json"):
            archive_path.unlink(missing_ok=True)


def load_material_record(material_id: str) -> dict[str, Any]:
    path = _material_record_path(material_id)
    if not path.exists():
        raise FileNotFoundError(f"未找到素材记录：{material_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def list_material_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(meta_pool_state_paths().materials.glob("*.json")):
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return records


def list_recent_material_records(limit: int = 10) -> list[dict[str, Any]]:
    records = list_material_records()
    records.sort(key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""), reverse=True)
    return records[:limit]


def update_material_record(material_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    record = load_material_record(material_id)
    record.update(patch)
    record["updated_at"] = _utc_now_iso()
    save_material_record(record)
    return record


def append_material_event(material_id: str, event_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    record = load_material_record(material_id)
    history = record.get("history", [])
    if not isinstance(history, list):
        history = []
    history.append(
        {
            "time": _utc_now_iso(),
            "type": event_type,
            "payload": payload or {},
        }
    )
    record["history"] = history
    record["updated_at"] = _utc_now_iso()
    save_material_record(record)
    return record


def inventory_snapshot() -> dict[str, Any]:
    records = list_material_records()
    ready_records = [
        item
        for item in records
        if str(item.get("launch_status") or "") in {"ready_for_launch", "prelaunched_paused"}
    ]
    min_ready = int(META_POOL_STATE_CONFIG.get("min_ready_materials") or 3)
    target_ready = int(META_POOL_STATE_CONFIG.get("target_ready_materials") or 8)
    shortage = max(0, target_ready - len(ready_records))
    return {
        "total_materials": len(records),
        "ready_materials": len(ready_records),
        "min_ready_materials": min_ready,
        "target_ready_materials": target_ready,
        "needs_generation": len(ready_records) < min_ready,
        "recommended_generation_count": shortage if len(ready_records) < target_ready else 0,
    }


def material_status_summary() -> dict[str, Any]:
    records = list_material_records()
    summary = {
        "total_materials": len(records),
        "pending_review": 0,
        "approved": 0,
        "rejected": 0,
        "ready_for_launch": 0,
        "prelaunched_paused": 0,
        "active": 0,
        "paused_by_rule": 0,
        "archived_success": 0,
        "archived_failed": 0,
    }
    success_bucket = str(META_POOL_STATE_CONFIG.get("success_archive_bucket") or "success_ads")
    failed_bucket = str(META_POOL_STATE_CONFIG.get("failed_archive_bucket") or "failed_ads")
    for item in records:
        review_status = str(item.get("review_status") or "")
        launch_status = str(item.get("launch_status") or "")
        archive_bucket = str(item.get("archive_bucket") or "")

        if review_status == "pending_review":
            summary["pending_review"] += 1
        elif review_status in {"approved", "auto_approved"}:
            summary["approved"] += 1
        elif review_status == "rejected":
            summary["rejected"] += 1

        if launch_status == "ready_for_launch":
            summary["ready_for_launch"] += 1
        elif launch_status == "prelaunched_paused":
            summary["prelaunched_paused"] += 1
        elif launch_status in {"active", "winner_running"}:
            summary["active"] += 1
        elif launch_status == "paused_by_rule":
            summary["paused_by_rule"] += 1

        if archive_bucket == success_bucket:
            summary["archived_success"] += 1
        elif archive_bucket == failed_bucket:
            summary["archived_failed"] += 1
    return summary


def create_alert(alert_type: str, message: str, payload: dict[str, Any] | None = None) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = meta_pool_state_paths().alerts / f"{timestamp}_{alert_type}.json"
    target.write_text(
        json.dumps(
            {
                "created_at": _utc_now_iso(),
                "alert_type": alert_type,
                "message": message,
                "payload": payload or {},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return target


def list_recent_alerts(limit: int = 10) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    for path in sorted(meta_pool_state_paths().alerts.glob("*.json"), reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["_path"] = str(path)
            alerts.append(payload)
        except Exception:
            continue
    return alerts[:limit]


def archive_material(
    material_id: str,
    archive_bucket: str,
    reason: str,
    extra_patch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record = load_material_record(material_id)
    patch = {
        "archive_bucket": archive_bucket,
        "archive_reason": reason,
        "archive_time": _utc_now_iso(),
        "launch_status": "archived",
    }
    if extra_patch:
        patch.update(extra_patch)
    record.update(patch)
    record["updated_at"] = _utc_now_iso()
    save_material_record(record)
    target = meta_pool_state_paths().archives / archive_bucket / f"{material_id}.json"
    target.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return record


def _derive_primary_text(ti_intro: dict[str, Any] | None, script: dict[str, Any] | None) -> str:
    if isinstance(ti_intro, dict):
        description = str(ti_intro.get("description") or "").strip()
        if description:
            return description
    scenes_root = script.get("scenes", {}) if isinstance(script, dict) else {}
    scenes = scenes_root.get("scenes", []) if isinstance(scenes_root, dict) else []
    lines: list[str] = []
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        audio = scene.get("audio", {})
        if isinstance(audio, dict):
            candidate = str(audio.get("text") or audio.get("voice_over") or "").strip()
            if candidate:
                lines.append(candidate)
    return " ".join(lines[:3]).strip()


def register_generated_material(
    *,
    run_id: str,
    final_video_path: str,
    script: dict[str, Any] | None,
    ti_intro: dict[str, Any] | None,
    source_inputs: dict[str, Any] | None,
    final_video_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    final_video_path = str(final_video_path or "").strip()
    if not final_video_path:
        raise ValueError("缺少 final_video_path，无法写入 Meta 暂存池状态。")
    source_inputs = source_inputs or {}

    material_id = f"mat_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    copied_video_path = _copy_asset_to_library(final_video_path, material_id, ".mp4")
    thumbnail_path = ""

    title = str((ti_intro or {}).get("title") or "").strip()
    description = str((ti_intro or {}).get("description") or "").strip()
    tags = (ti_intro or {}).get("tags") if isinstance(ti_intro, dict) else []
    if not isinstance(tags, list):
        tags = []

    meta = script.get("meta", {}) if isinstance(script, dict) else {}
    source_meta = script.get("source_meta", {}) if isinstance(script, dict) else {}
    primary_text = _derive_primary_text(ti_intro, script)
    headline = title or str(meta.get("product_name") or source_meta.get("product_name") or "Auto Generated Ad").strip()
    review_status = str(META_POOL_STATE_CONFIG.get("default_review_status") or "pending_review")

    record = {
        "material_id": material_id,
        "created_at": _utc_now_iso(),
        "updated_at": _utc_now_iso(),
        "source_type": "generated",
        "asset_type": "video",
        "run_id": run_id,
        "storage_uri": copied_video_path,
        "managed_asset": bool(META_POOL_STATE_CONFIG.get("copy_assets_to_workspace", False)),
        "thumbnail_uri": thumbnail_path,
        "review_status": review_status,
        "launch_status": "ready_for_launch",
        "material_status": "ready",
        "ad_enable_status": "not_enabled",
        "copy": {
            "primary_text": primary_text,
            "headline": headline,
            "description": description,
            "cta": "LEARN_MORE",
            "tags": tags,
        },
        "landing_page_url": str(source_meta.get("landing_page_url") or source_inputs.get("landing_page_url") or "").strip(),
        "page_id": str(source_meta.get("page_id") or source_inputs.get("page_id") or "").strip(),
        "target_adset_id": str(source_meta.get("target_adset_id") or source_inputs.get("target_adset_id") or "").strip(),
        "desired_video_name": str(source_inputs.get("desired_video_name") or "").strip(),
        "desired_creative_name": str(source_inputs.get("desired_creative_name") or "").strip(),
        "desired_ad_name": str(source_inputs.get("desired_ad_name") or "").strip(),
        "meta_mapping": {
            "video_id": "",
            "creative_id": "",
            "ad_id": "",
        },
        "performance_snapshot": {
            "spend": 0.0,
            "impressions": 0,
            "ctr": 0.0,
            "add_to_cart": 0.0,
            "purchases": 0.0,
            "roas": 0.0,
        },
        "source_inputs": source_inputs or {},
        "source_script_meta": meta,
        "source_script_input_meta": source_meta,
        "final_video_result": final_video_result or {},
        "history": [
            {
                "time": _utc_now_iso(),
                "type": "meta_pool_record_registered",
                "payload": {
                    "run_id": run_id,
                    "video_path": copied_video_path,
                },
            }
        ],
        "is_dry_run": False,
    }
    save_material_record(record)
    return record


def register_backup_material(
    *,
    video_path: str,
    primary_text: str,
    headline: str,
    description: str = "",
    landing_page_url: str = "",
    page_id: str = "",
    target_adset_id: str = "",
    cta: str = "LEARN_MORE",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    source = str(video_path or "").strip()
    if not source:
        raise ValueError("缺少备用素材视频路径。")
    material_id = f"bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    copied_video_path = _copy_asset_to_library(source, material_id, ".mp4")
    review_status = str(META_POOL_STATE_CONFIG.get("default_review_status") or "pending_review")
    record = {
        "material_id": material_id,
        "created_at": _utc_now_iso(),
        "updated_at": _utc_now_iso(),
        "source_type": "backup_manual",
        "asset_type": "video",
        "run_id": "",
        "storage_uri": copied_video_path,
        "managed_asset": bool(META_POOL_STATE_CONFIG.get("copy_assets_to_workspace", False)),
        "thumbnail_uri": "",
        "review_status": review_status,
        "launch_status": "ready_for_launch",
        "material_status": "ready",
        "ad_enable_status": "not_enabled",
        "copy": {
            "primary_text": str(primary_text or "").strip(),
            "headline": str(headline or "").strip(),
            "description": str(description or "").strip(),
            "cta": str(cta or "LEARN_MORE").strip(),
            "tags": tags or [],
        },
        "landing_page_url": str(landing_page_url or "").strip(),
        "page_id": str(page_id or "").strip(),
        "target_adset_id": str(target_adset_id or "").strip(),
        "meta_mapping": {
            "video_id": "",
            "creative_id": "",
            "ad_id": "",
        },
        "performance_snapshot": {
            "spend": 0.0,
            "impressions": 0,
            "ctr": 0.0,
            "add_to_cart": 0.0,
            "purchases": 0.0,
            "roas": 0.0,
        },
        "source_inputs": {},
        "source_script_meta": {},
        "source_script_input_meta": {},
        "final_video_result": {},
        "history": [
            {
                "time": _utc_now_iso(),
                "type": "meta_pool_backup_registered",
                "payload": {
                    "video_path": copied_video_path,
                },
            }
        ],
        "is_dry_run": False,
    }
    save_material_record(record)
    return record


def pending_prelaunch_materials(limit: int = 20) -> list[dict[str, Any]]:
    allow_before_review = bool(META_POOL_STATE_CONFIG.get("allow_prelaunch_before_manual_review", True))
    records = list_material_records()
    pending: list[dict[str, Any]] = []
    for item in records:
        if str(item.get("launch_status") or "") != "ready_for_launch":
            continue
        review_status = str(item.get("review_status") or "")
        if not allow_before_review and review_status != "approved":
            continue
        pending.append(item)
    pending.sort(key=lambda item: str(item.get("created_at") or ""))
    return pending[:limit]


def paused_material_candidates_for_activation(adset_id: str, limit: int = 20) -> list[dict[str, Any]]:
    records = list_material_records()
    candidates: list[dict[str, Any]] = []
    for item in records:
        if str(item.get("launch_status") or "") != "prelaunched_paused":
            continue
        if str(item.get("review_status") or "") not in {"approved", "auto_approved"}:
            continue
        if adset_id and str(item.get("target_adset_id") or "") != str(adset_id):
            continue
        if not str(item.get("meta_mapping", {}).get("ad_id") or "").strip():
            continue
        candidates.append(item)
    candidates.sort(key=lambda item: str(item.get("created_at") or ""))
    return candidates[:limit]


def build_archive_feature_summary() -> dict[str, Any]:
    records = list_material_records()
    success = [item for item in records if str(item.get("archive_bucket") or "") == str(META_POOL_STATE_CONFIG.get("success_archive_bucket") or "success_ads")]
    failed = [item for item in records if str(item.get("archive_bucket") or "") == str(META_POOL_STATE_CONFIG.get("failed_archive_bucket") or "failed_ads")]

    def _top_values(items: list[dict[str, Any]], key: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in items:
            value = str(item.get("source_script_input_meta", {}).get(key) or item.get("source_inputs", {}).get(key) or "").strip()
            if not value:
                continue
            counts[value] = counts.get(value, 0) + 1
        return dict(sorted(counts.items(), key=lambda pair: pair[1], reverse=True)[:10])

    summary = {
        "generated_at": _utc_now_iso(),
        "success_count": len(success),
        "failed_count": len(failed),
        "success_style_presets": _top_values(success, "style_preset"),
        "failed_style_presets": _top_values(failed, "style_preset"),
        "success_markets": _top_values(success, "target_market"),
        "failed_markets": _top_values(failed, "target_market"),
    }
    target = meta_pool_state_paths().reports / "archive_feature_summary.json"
    target.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary
