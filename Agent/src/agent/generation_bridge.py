from __future__ import annotations

import os
import shlex
import subprocess
import sys
from glob import glob
from pathlib import Path
from typing import Any

from agent.config import resolve_path
from agent.env import load_agent_env
from agent.history import append_history
from agent.tts_settings import materialize_runtime_tunables, validate_tts_runtime_bridge


def build_generation_command(settings: dict[str, Any]) -> list[str]:
    generation = settings.get("generation", {}) if isinstance(settings.get("generation"), dict) else {}
    runner_script = resolve_path(str(generation.get("runner_script") or ""))
    pythonpath = resolve_path(str(generation.get("pythonpath") or ""))
    default_campaign_config = resolve_path(str(generation.get("default_campaign_config") or ""))
    default_prompt = resolve_path(str(generation.get("default_prompt") or ""))
    default_output_root = resolve_path(str(generation.get("default_output_root") or ""))
    default_log_path = resolve_path(str(generation.get("default_log_path") or ""))
    default_summary_path = resolve_path(str(generation.get("default_summary_path") or ""))
    max_concepts = int(generation.get("max_concepts") or 1)
    max_scenes = int(generation.get("max_scenes") or 3)

    return [
        sys.executable,
        str(runner_script),
        "--config",
        str(default_campaign_config),
        "--prompt",
        str(default_prompt),
        "--output-root",
        str(default_output_root),
        "--log-path",
        str(default_log_path),
        "--summary-path",
        str(default_summary_path),
        "--max-concepts",
        str(max_concepts),
        "--max-scenes",
        str(max_scenes),
    ]


def generation_paths(settings: dict[str, Any]) -> dict[str, Path]:
    generation = settings.get("generation", {}) if isinstance(settings.get("generation"), dict) else {}
    return {
        "runner_script": resolve_path(str(generation.get("runner_script") or "")),
        "pythonpath": resolve_path(str(generation.get("pythonpath") or "")),
        "default_campaign_config": resolve_path(str(generation.get("default_campaign_config") or "")),
        "default_prompt": resolve_path(str(generation.get("default_prompt") or "")),
        "default_output_root": resolve_path(str(generation.get("default_output_root") or "")),
        "default_log_path": resolve_path(str(generation.get("default_log_path") or "")),
        "default_summary_path": resolve_path(str(generation.get("default_summary_path") or "")),
    }


def build_generation_command_string(settings: dict[str, Any]) -> str:
    command = build_generation_command(settings)
    tts_validation = validate_tts_runtime_bridge(settings)
    return "PYTHONPATH={pythonpath} {command}".format(
        pythonpath=shlex.quote(str(resolve_path(str(settings.get("generation", {}).get("pythonpath") or "")))),
        command=" ".join(
            [
                f"RUNTIME_TUNABLES_CONFIG_PATH={shlex.quote(str(tts_validation['runtime_override_path']))}",
                *[shlex.quote(part) for part in command],
            ]
        ),
    )


def validate_generation_bridge(settings: dict[str, Any]) -> dict[str, Any]:
    paths = generation_paths(settings)
    checks = {
        "runner_script": paths["runner_script"],
        "pythonpath": paths["pythonpath"],
        "default_campaign_config": paths["default_campaign_config"],
        "default_prompt": paths["default_prompt"],
    }
    results: dict[str, Any] = {"ok": True, "checks": {}}
    for key, path in checks.items():
        exists = path.exists()
        results["checks"][key] = {"path": str(path), "exists": exists}
        if not exists:
            results["ok"] = False
    tts_validation = validate_tts_runtime_bridge(settings)
    results["tts_runtime"] = tts_validation
    if not tts_validation.get("ok"):
        results["ok"] = False
    results["paths"] = {key: str(path) for key, path in paths.items()}
    results["command"] = build_generation_command_string(settings)
    return results


def recent_generation_outputs(settings: dict[str, Any]) -> dict[str, Any]:
    paths = generation_paths(settings)
    output_root = paths["default_output_root"]
    log_path = paths["default_log_path"]
    summary_path = paths["default_summary_path"]
    final_videos = sorted(glob(str(output_root / "**" / "final_video.mp4"), recursive=True))
    concept_reports = sorted(glob(str(output_root / "**" / "concept_report.json"), recursive=True))
    return {
        "output_root": str(output_root),
        "log_path": str(log_path),
        "log_exists": log_path.exists(),
        "summary_path": str(summary_path),
        "summary_exists": summary_path.exists(),
        "final_videos": final_videos[-10:],
        "concept_reports": concept_reports[-10:],
    }


def run_generation(settings: dict[str, Any], *, execute: bool = False) -> dict[str, Any]:
    validation = validate_generation_bridge(settings)
    if not execute:
        result = {
            "executed": False,
            "validation": validation,
            "outputs": recent_generation_outputs(settings),
        }
        append_history(
            settings,
            event_type="generation_status_refresh",
            status="success",
            title="刷新生成状态",
            payload={"outputs": result["outputs"]},
        )
        return result
    if not validation.get("ok"):
        raise RuntimeError(f"生成桥接校验失败: {validation}")

    load_agent_env()
    env = dict(os.environ)
    paths = generation_paths(settings)
    runtime_override = materialize_runtime_tunables(settings)
    env["PYTHONPATH"] = str(paths["pythonpath"])
    env["PROMPT_OVERRIDES_PATH"] = str((paths["runner_script"].parents[1] / "prompt_overrides.json").resolve())
    env["RUNTIME_TUNABLES_CONFIG_PATH"] = str(runtime_override["path"])
    command = build_generation_command(settings)
    paths["default_output_root"].mkdir(parents=True, exist_ok=True)
    paths["default_log_path"].parent.mkdir(parents=True, exist_ok=True)
    paths["default_summary_path"].parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        command,
        env=env,
        cwd=str(paths["runner_script"].parents[1]),
        capture_output=True,
        text=True,
        check=False,
    )
    result = {
        "executed": True,
        "validation": validation,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "outputs": recent_generation_outputs(settings),
        "runtime_tunables_override": runtime_override,
    }
    append_history(
        settings,
        event_type="generation_execute",
        status="success" if int(completed.returncode or 1) == 0 else "failed",
        title="执行默认生成任务",
        payload={
            "returncode": completed.returncode,
            "outputs": result["outputs"],
            "runtime_tunables_override": runtime_override,
            "stdout_tail": (completed.stdout or "")[-2000:],
            "stderr_tail": (completed.stderr or "")[-2000:],
        },
    )
    return result
