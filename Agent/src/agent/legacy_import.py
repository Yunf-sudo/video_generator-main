from __future__ import annotations

import json
import shutil
from glob import glob
from pathlib import Path
from typing import Any

from agent.config import nested_get, resolve_path
from agent.history import append_history


def _set_nested(payload: dict[str, Any], dotted_key: str, value: str) -> None:
    parts = dotted_key.split(".")
    current: dict[str, Any] = payload
    for part in parts[:-1]:
        node = current.get(part)
        if not isinstance(node, dict):
            node = {}
            current[part] = node
        current = node
    current[parts[-1]] = value


def _copy_file(source: str, target_dir: Path, material_id: str, alias: str) -> str:
    source_path = Path(source).resolve()
    if not source_path.exists():
        return ""
    target_dir.mkdir(parents=True, exist_ok=True)
    suffix = source_path.suffix or ""
    target_path = target_dir / f"{material_id}_{alias}{suffix}"
    shutil.copy2(source_path, target_path)
    return str(target_path.resolve())


def import_legacy_materials(settings: dict[str, Any]) -> dict[str, Any]:
    legacy = settings.get("legacy_import", {}) if isinstance(settings.get("legacy_import"), dict) else {}
    source_glob = str(legacy.get("source_material_glob") or "").strip()
    target_material_dir = resolve_path(str(legacy.get("target_material_dir") or "bundle/generated/ad_ops_state/materials"))
    target_asset_dir = resolve_path(str(legacy.get("target_asset_dir") or "bundle/generated/imported_assets"))
    copy_paths = list(legacy.get("copy_paths") or [])

    target_material_dir.mkdir(parents=True, exist_ok=True)
    target_asset_dir.mkdir(parents=True, exist_ok=True)

    copied = 0
    failed = 0
    imported_materials: list[dict[str, Any]] = []
    errors: list[str] = []

    for raw_path in sorted(glob(str(resolve_path(source_glob))), reverse=True):
        source_path = Path(raw_path)
        try:
            payload = json.loads(source_path.read_text(encoding="utf-8"))
        except Exception as exc:
            failed += 1
            errors.append(f"{source_path}: {exc}")
            continue

        material_id = str(payload.get("material_id") or source_path.stem)
        working = json.loads(json.dumps(payload, ensure_ascii=False))
        asset_dir = target_asset_dir / material_id
        copied_paths: dict[str, str] = {}

        for dotted_key in copy_paths:
            source_value = str(nested_get(payload, dotted_key, "") or "").strip()
            if not source_value:
                continue
            alias = dotted_key.replace(".", "_")
            copied_value = _copy_file(source_value, asset_dir, material_id, alias)
            if copied_value:
                _set_nested(working, dotted_key, copied_value)
                copied_paths[dotted_key] = copied_value

        target_record_path = target_material_dir / f"{material_id}.json"
        target_record_path.write_text(json.dumps(working, ensure_ascii=False, indent=2), encoding="utf-8")
        copied += 1
        imported_materials.append(
            {
                "material_id": material_id,
                "target_record_path": str(target_record_path.resolve()),
                "copied_paths": copied_paths,
            }
        )

    result = {
        "copied": copied,
        "failed": failed,
        "imported_materials": imported_materials,
        "errors": errors,
        "target_material_dir": str(target_material_dir.resolve()),
        "target_asset_dir": str(target_asset_dir.resolve()),
    }
    append_history(
        settings,
        event_type="legacy_import",
        status="failed" if failed else "success",
        title="导入旧项目素材到 Agent",
        payload={
            "copied": copied,
            "failed": failed,
            "target_material_dir": result["target_material_dir"],
            "target_asset_dir": result["target_asset_dir"],
            "errors": errors[:10],
        },
    )
    return result
