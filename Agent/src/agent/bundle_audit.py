from __future__ import annotations

import json
from glob import glob
from pathlib import Path
from typing import Any

from agent.config import agent_root, resolve_path
from agent.history import append_history


def _retain_config_path() -> Path:
    return agent_root() / "config" / "bundle_retain.json"


def _bundle_root() -> Path:
    return agent_root() / "bundle"


def audit_bundle_retain_set(settings: dict[str, Any]) -> dict[str, Any]:
    retain_payload = json.loads(_retain_config_path().read_text(encoding="utf-8"))
    keep_globs = list(retain_payload.get("keep_globs") or [])
    bundle_root = _bundle_root()

    all_files = sorted(
        str(path.resolve())
        for path in bundle_root.rglob("*")
        if path.is_file() and "__pycache__" not in str(path)
    )
    kept: set[str] = set()
    for pattern in keep_globs:
        for item in glob(str((bundle_root / pattern).resolve()), recursive=True):
            path = Path(item)
            if path.is_file():
                kept.add(str(path.resolve()))

    review_candidates = [path for path in all_files if path not in kept]
    result = {
        "bundle_root": str(bundle_root.resolve()),
        "retain_config_path": str(_retain_config_path().resolve()),
        "total_files": len(all_files),
        "kept_files": len(kept),
        "review_candidate_files": len(review_candidates),
        "keep_globs": keep_globs,
        "review_candidates": review_candidates,
    }
    append_history(
        settings,
        event_type="bundle_audit",
        status="success",
        title="审计 bundle 保留清单",
        payload={
            "total_files": result["total_files"],
            "kept_files": result["kept_files"],
            "review_candidate_files": result["review_candidate_files"],
        },
    )
    return result
