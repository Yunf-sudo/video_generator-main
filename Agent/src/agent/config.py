from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


AGENT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SETTINGS_PATH = AGENT_ROOT / "config" / "agent_settings.json"


def agent_root() -> Path:
    return AGENT_ROOT


def load_settings(path: str | None = None) -> dict[str, Any]:
    configured = (path or os.getenv("AGENT_SETTINGS_PATH") or "").strip()
    settings_path = Path(configured) if configured else DEFAULT_SETTINGS_PATH
    if not settings_path.is_absolute():
        settings_path = (AGENT_ROOT / settings_path).resolve()
    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    payload["config_path"] = str(settings_path)
    payload["agent_root"] = str(AGENT_ROOT)
    return payload


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
