from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


SRC_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SRC_DIR.parent
GENERATED_ROOT = PROJECT_ROOT / "generated"
RUNS_ROOT = GENERATED_ROOT / "runs"
CACHE_ROOT = GENERATED_ROOT / "cache"
_ACTIVE_RUN_ID: str | None = os.getenv("VIDEO_GENERATOR_RUN_ID") or None


@dataclass(frozen=True)
class RunPaths:
    run_id: str
    root: Path
    uploads: Path
    pics: Path
    clips: Path
    audio: Path
    subtitles: Path
    exports: Path
    youtube_data: Path
    local_storage: Path
    meta: Path


def ensure_dir(path: Path | str) -> Path:
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    return target


def generated_root() -> Path:
    return ensure_dir(GENERATED_ROOT)


def cache_root() -> Path:
    return ensure_dir(CACHE_ROOT)


def runs_root() -> Path:
    return ensure_dir(RUNS_ROOT)


def _build_run_paths(run_id: str) -> RunPaths:
    root = runs_root() / run_id
    paths = RunPaths(
        run_id=run_id,
        root=root,
        uploads=root / "uploads",
        pics=root / "pics",
        clips=root / "clips",
        audio=root / "audio",
        subtitles=root / "subtitles",
        exports=root / "exports",
        youtube_data=root / "youtube_data",
        local_storage=root / "local_storage",
        meta=root / "meta",
    )
    for path in (
        paths.root,
        paths.uploads,
        paths.pics,
        paths.clips,
        paths.audio,
        paths.subtitles,
        paths.exports,
        paths.youtube_data,
        paths.local_storage,
        paths.meta,
    ):
        ensure_dir(path)
    return paths


def activate_run(run_id: str) -> RunPaths:
    global _ACTIVE_RUN_ID
    _ACTIVE_RUN_ID = run_id
    os.environ["VIDEO_GENERATOR_RUN_ID"] = run_id
    return _build_run_paths(run_id)


def _slugify_run_prefix(value: str, default: str = "run") -> str:
    text = str(value or "").strip().lower()
    if not text:
        return default
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text[:40] or default


def start_new_run(prefix: str = "run", project_name: str | None = None) -> RunPaths:
    resolved_prefix = _slugify_run_prefix(project_name or prefix, default=prefix)
    run_id = f"{resolved_prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    return activate_run(run_id)


def get_active_run_id() -> str | None:
    return _ACTIVE_RUN_ID


def ensure_active_run(prefix: str = "run") -> RunPaths:
    if _ACTIVE_RUN_ID:
        return _build_run_paths(_ACTIVE_RUN_ID)
    return start_new_run(prefix=prefix)


def run_paths(run_id: str | None = None) -> RunPaths:
    if run_id:
        return _build_run_paths(run_id)
    return ensure_active_run()


def write_run_json(filename: str, payload: Any) -> Path:
    target = ensure_active_run().meta / filename
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target
