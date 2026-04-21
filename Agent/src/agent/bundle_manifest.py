from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.config import resolve_path
from agent.history import append_history


def bundle_manifest_path(settings: dict[str, Any]) -> Path:
    runtime = settings.get("runtime", {}) if isinstance(settings.get("runtime"), dict) else {}
    path = resolve_path(str(runtime.get("bundle_manifest_path") or "runtime/bundle_manifest.json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def build_bundle_manifest(settings: dict[str, Any]) -> dict[str, Any]:
    workspace = settings.get("workspace", {}) if isinstance(settings.get("workspace"), dict) else {}
    bundle_root = resolve_path(str(workspace.get("source_root") or "bundle/src")).parent

    categories = {
        "src_py": sorted(str(path.resolve()) for path in (bundle_root / "src").rglob("*.py")),
        "scripts_py": sorted(str(path.resolve()) for path in (bundle_root / "scripts").rglob("*.py")),
        "configs_json": sorted(str(path.resolve()) for path in (bundle_root / "configs").rglob("*.json")),
        "configs_py": sorted(str(path.resolve()) for path in (bundle_root / "configs").rglob("*.py")),
        "prompts_md": sorted(str(path.resolve()) for path in (bundle_root / "prompts").rglob("*.md")),
        "reference_images": sorted(str(path.resolve()) for path in (bundle_root / "白底图").glob("*.JPG")),
    }

    manifest = {
        "bundle_root": str(bundle_root.resolve()),
        "entrypoints": {
            "app": str((bundle_root.parent / "app.py").resolve()),
            "run_anywell_campaign": str((bundle_root / "scripts" / "run_anywell_campaign.py").resolve()),
        },
        "counts": {key: len(value) for key, value in categories.items()},
        "files": categories,
    }

    path = bundle_manifest_path(settings)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    append_history(
        settings,
        event_type="bundle_manifest",
        status="success",
        title="刷新 bundle 清单",
        payload={"manifest_path": str(path), "counts": manifest["counts"]},
    )
    manifest["manifest_path"] = str(path)
    return manifest
