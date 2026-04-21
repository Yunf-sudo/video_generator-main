from __future__ import annotations

import json
from glob import glob
from pathlib import Path
from typing import Any

from agent.config import nested_get, resolve_path


def _alert(level: str, title: str, message: str, source: str = "") -> dict[str, str]:
    return {
        "level": level,
        "title": title,
        "message": message,
        "source": source,
    }


def _resolve_first_existing(payload: dict[str, Any], candidates: list[str]) -> str:
    for dotted_key in candidates:
        value = str(nested_get(payload, dotted_key, "") or "").strip()
        if value:
            return value
    return ""


def _expand_paths(pattern: str) -> list[Path]:
    return [Path(item) for item in glob(str(resolve_path(pattern)), recursive=True)]


def _scan_material_records(settings: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    materials = settings.get("materials", {}) if isinstance(settings.get("materials"), dict) else {}
    pattern = str(materials.get("material_record_glob") or "").strip()
    max_records = int(materials.get("max_records") or 200)
    video_candidates = list(materials.get("video_path_candidates") or [])
    thumbnail_candidates = list(materials.get("thumbnail_path_candidates") or [])

    records: list[dict[str, Any]] = []
    alerts: list[dict[str, str]] = []
    material_paths = sorted(_expand_paths(pattern), key=lambda item: item.stat().st_mtime, reverse=True)

    for path in material_paths[:max_records]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            alerts.append(_alert("error", "素材记录读取失败", str(exc), str(path.resolve())))
            records.append(
                {
                    "kind": "material_record",
                    "material_id": path.stem,
                    "record_path": str(path.resolve()),
                    "load_status": "failed",
                    "message": f"JSON 读取失败: {exc}",
                }
            )
            continue

        video_path = _resolve_first_existing(payload, video_candidates)
        thumbnail_path = _resolve_first_existing(payload, thumbnail_candidates)
        resolved_video = resolve_path(video_path) if video_path else None
        resolved_thumbnail = resolve_path(thumbnail_path) if thumbnail_path else None
        video_exists = bool(resolved_video and resolved_video.exists())
        thumbnail_exists = bool(resolved_thumbnail and resolved_thumbnail.exists())

        load_status = "loaded" if video_exists else "failed"
        message = "视频可加载" if video_exists else "缺少可播放视频文件"
        if video_exists:
            alerts.append(_alert("success", "素材加载成功", f"{payload.get('material_id') or path.stem} 已可加载", str(path.resolve())))
        else:
            alerts.append(_alert("error", "素材加载失败", f"{payload.get('material_id') or path.stem} 缺少视频文件", str(path.resolve())))
        if video_exists and not thumbnail_exists:
            alerts.append(_alert("warning", "缩略图缺失", f"{payload.get('material_id') or path.stem} 没有可用缩略图", str(path.resolve())))

        records.append(
            {
                "kind": "material_record",
                "material_id": str(payload.get("material_id") or path.stem),
                "run_id": str(payload.get("run_id") or ""),
                "source_type": str(payload.get("source_type") or ""),
                "review_status": str(payload.get("review_status") or ""),
                "launch_status": str(payload.get("launch_status") or ""),
                "updated_at": str(payload.get("updated_at") or payload.get("created_at") or ""),
                "record_path": str(path.resolve()),
                "video_path": str(resolved_video) if resolved_video else "",
                "thumbnail_path": str(resolved_thumbnail) if resolved_thumbnail else "",
                "video_exists": video_exists,
                "thumbnail_exists": thumbnail_exists,
                "landing_page_url": str(payload.get("landing_page_url") or ""),
                "video_id": str((payload.get("meta_mapping") or {}).get("video_id") or ""),
                "creative_id": str((payload.get("meta_mapping") or {}).get("creative_id") or ""),
                "ad_id": str((payload.get("meta_mapping") or {}).get("ad_id") or ""),
                "load_status": load_status,
                "message": message,
            }
        )
    return records, alerts


def _scan_orphan_videos(settings: dict[str, Any], known_video_paths: set[str]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    materials = settings.get("materials", {}) if isinstance(settings.get("materials"), dict) else {}
    globs = list(materials.get("deliverable_video_globs") or [])
    records: list[dict[str, Any]] = []
    alerts: list[dict[str, str]] = []
    for pattern in globs:
        for path in sorted(_expand_paths(pattern), key=lambda item: item.stat().st_mtime, reverse=True):
            resolved = str(path.resolve())
            if resolved in known_video_paths:
                continue
            records.append(
                {
                    "kind": "orphan_video",
                    "material_id": "",
                    "run_id": path.parent.name,
                    "source_type": "orphan_video",
                    "review_status": "",
                    "launch_status": "",
                    "updated_at": "",
                    "record_path": "",
                    "video_path": resolved,
                    "thumbnail_path": "",
                    "video_exists": True,
                    "thumbnail_exists": False,
                    "landing_page_url": "",
                    "video_id": "",
                    "creative_id": "",
                    "ad_id": "",
                    "load_status": "loaded",
                    "message": "视频存在，但未挂到素材记录中",
                }
            )
            alerts.append(_alert("warning", "发现未登记素材", f"{path.name} 可播放，但未写入素材记录", resolved))
    return records, alerts


def scan_materials(settings: dict[str, Any]) -> dict[str, Any]:
    records, alerts = _scan_material_records(settings)
    known_video_paths = {str(item.get("video_path") or "") for item in records if str(item.get("video_path") or "").strip()}
    orphan_records, orphan_alerts = _scan_orphan_videos(settings, known_video_paths)
    records.extend(orphan_records)
    alerts.extend(orphan_alerts)

    loaded_count = sum(1 for item in records if item.get("load_status") == "loaded")
    failed_count = sum(1 for item in records if item.get("load_status") == "failed")
    warning_count = sum(1 for item in alerts if item.get("level") == "warning")
    success_count = sum(1 for item in alerts if item.get("level") == "success")
    error_count = sum(1 for item in alerts if item.get("level") == "error")

    records.sort(key=lambda item: (str(item.get("updated_at") or ""), str(item.get("video_path") or "")), reverse=True)
    return {
        "summary": {
            "total_records": len(records),
            "loaded_count": loaded_count,
            "failed_count": failed_count,
            "success_alerts": success_count,
            "warning_alerts": warning_count,
            "error_alerts": error_count,
        },
        "alerts": alerts,
        "records": records,
    }
