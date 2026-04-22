from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.config import resolve_path
from agent.env import load_agent_env
from agent.generation_bridge import validate_generation_bridge
from agent.history import append_history
from agent.material_loader import scan_materials
from agent.meta_monitor import run_meta_monitor
from agent.meta_upload import validate_meta_upload_bridge
from agent.tts_settings import validate_tts_runtime_bridge


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def run_healthcheck(settings: dict[str, Any], *, include_meta: bool = False) -> dict[str, Any]:
    env_info = load_agent_env()
    workspace = settings.get("workspace", {}) if isinstance(settings.get("workspace"), dict) else {}
    path_checks = {}
    for key, raw in workspace.items():
        path = resolve_path(str(raw or ""))
        path_checks[key] = {"path": str(path), "exists": path.exists()}

    generation = validate_generation_bridge(settings)
    materials = scan_materials(settings)

    result: dict[str, Any] = {
        "run_time": _utc_now_iso(),
        "config_path": str(settings.get("config_path") or ""),
        "path_checks": path_checks,
        "generation_bridge": generation,
        "tts_runtime": validate_tts_runtime_bridge(settings),
        "meta_upload_bridge": validate_meta_upload_bridge(settings),
        "materials": materials["summary"],
        "token_present": bool((os.getenv("META_ACCESS_TOKEN") or os.getenv("FACEBOOK_ACCESS_TOKEN") or "").strip()),
        "environment": env_info,
    }

    if include_meta:
        result["meta_monitor"] = run_meta_monitor(settings)

    runtime = settings.get("runtime", {}) if isinstance(settings.get("runtime"), dict) else {}
    report_path = resolve_path(str(runtime.get("healthcheck_report_path") or "runtime/healthcheck_report.json"))
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    result["report_path"] = str(report_path)
    append_history(
        settings,
        event_type="healthcheck",
        status="success",
        title="执行健康检查",
        payload={
            "report_path": result["report_path"],
            "token_present": result["token_present"],
            "materials": result["materials"],
            "include_meta": include_meta,
        },
    )
    return result
