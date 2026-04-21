from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


AGENT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SETTINGS_PATH = AGENT_ROOT / "config" / "agent_settings.json"


def agent_root() -> Path:
    return AGENT_ROOT


def _resolve_settings_path(configured: str | None) -> Path:
    raw = (configured or "").strip()
    if not raw:
        return DEFAULT_SETTINGS_PATH
    candidate = Path(raw)
    if candidate.is_absolute():
        return candidate
    cwd_candidate = (Path.cwd() / candidate).resolve()
    if cwd_candidate.exists() or candidate.parts[:1] == ("Agent",):
        return cwd_candidate
    return (AGENT_ROOT / candidate).resolve()


def load_settings(path: str | None = None) -> dict[str, Any]:
    settings_path = _resolve_settings_path(path or os.getenv("AGENT_SETTINGS_PATH") or "")
    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    payload["config_path"] = str(settings_path)
    payload["agent_root"] = str(AGENT_ROOT)
    return payload


def save_settings(settings: dict[str, Any], path: str | None = None) -> Path:
    settings_path = _resolve_settings_path(path or str(settings.get("config_path") or "") or "")
    payload = json.loads(json.dumps(settings, ensure_ascii=False))
    payload.pop("config_path", None)
    payload.pop("agent_root", None)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    payload["config_path"] = str(settings_path)
    payload["agent_root"] = str(AGENT_ROOT)
    settings.clear()
    settings.update(payload)
    return settings_path


def resolve_path(value: str, *, base: Path | None = None) -> Path:
    raw = str(value or "").strip()
    if not raw:
        return (base or AGENT_ROOT).resolve()
    candidate = Path(raw)
    if candidate.is_absolute():
        return candidate
    return ((base or AGENT_ROOT) / candidate).resolve()


def resolve_setting_path(settings: dict[str, Any], dotted_key: str) -> Path:
    current: Any = settings
    for part in dotted_key.split("."):
        if not isinstance(current, dict):
            raise KeyError(dotted_key)
        current = current.get(part)
    return resolve_path(str(current or ""))


def nested_get(payload: dict[str, Any], dotted_key: str, default: Any = "") -> Any:
    current: Any = payload
    for part in dotted_key.split("."):
        if not isinstance(current, dict):
            return default
        current = current.get(part)
        if current is None:
            return default
    return current


def ensure_workspace_dirs(settings: dict[str, Any]) -> dict[str, str]:
    workspace = settings.get("workspace", {}) if isinstance(settings.get("workspace"), dict) else {}
    ensured: dict[str, str] = {}
    for key, value in workspace.items():
        if key == "legacy_root":
            continue
        path = resolve_path(str(value or ""))
        path.mkdir(parents=True, exist_ok=True)
        ensured[key] = str(path)
    return ensured
