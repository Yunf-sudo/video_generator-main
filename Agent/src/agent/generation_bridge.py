from __future__ import annotations

import os
import shlex
import subprocess
import sys
import json
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


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _concept_report_summary(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    concept_dir = path.parent
    final_video_result = payload.get("final_video_result") if isinstance(payload.get("final_video_result"), dict) else {}
    final_video_path = str(
        payload.get("final_video_path")
        or final_video_result.get("video_path")
        or ((concept_dir / "final_video.mp4") if (concept_dir / "final_video.mp4").exists() else "")
        or ""
    ).strip()
    subtitle_path = str(
        payload.get("subtitle_path")
        or final_video_result.get("subtitle_path")
        or ((concept_dir / "subtitles.srt") if (concept_dir / "subtitles.srt").exists() else "")
        or ""
    ).strip()
    return {
        "concept_report_path": str(path.resolve()),
        "concept_id": str(payload.get("concept_id") or concept_dir.name),
        "title": str(payload.get("title") or concept_dir.name),
        "status": str(payload.get("status") or ""),
        "concept_dir": str(concept_dir.resolve()),
        "run_root": str(payload.get("run_root") or ""),
        "final_video_path": final_video_path,
        "final_video_exists": bool(final_video_path and Path(final_video_path).exists()),
        "subtitle_path": subtitle_path,
        "subtitle_exists": bool(subtitle_path and Path(subtitle_path).exists()),
        "subtitles_burned": bool(payload.get("subtitles_burned") or final_video_result.get("subtitles_burned")),
        "audio_path": str(payload.get("audio_path") or final_video_result.get("audio_path") or ""),
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
    concept_report_paths = sorted(glob(str(output_root / "**" / "concept_report.json"), recursive=True))
    concept_reports = [_concept_report_summary(Path(item)) for item in concept_report_paths][-10:]
    final_videos = [item["final_video_path"] for item in concept_reports if item.get("final_video_exists")]
    if not final_videos:
        final_videos = sorted(glob(str(output_root / "**" / "final_video.mp4"), recursive=True))[-10:]
    return {
        "output_root": str(output_root),
        "log_path": str(log_path),
        "log_exists": log_path.exists(),
        "summary_path": str(summary_path),
        "summary_exists": summary_path.exists(),
        "final_videos": final_videos[-10:],
        "concept_reports": [item["concept_report_path"] for item in concept_reports],
        "recent_concepts": concept_reports,
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
