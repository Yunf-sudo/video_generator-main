from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
from pprint import pformat
from types import ModuleType
from typing import Any

from agent.config import resolve_path, save_settings
from agent.history import append_history


COMMON_EDGE_VOICES = [
    "en-US-AvaNeural",
    "en-US-JennyNeural",
    "en-US-AriaNeural",
    "en-US-EmmaNeural",
    "en-US-GuyNeural",
    "en-US-AndrewNeural",
    "en-GB-SoniaNeural",
    "en-GB-RyanNeural",
]

VOICE_STYLE_PRESETS = {
    "gentle": {
        "label": "舒缓温柔",
        "provider": "edge_tts",
        "edge_voice": "en-US-AvaNeural",
        "edge_rate_percent": -22,
        "edge_pitch_hz": -10,
        "macos_voice": "Ava",
        "macos_rate": 138,
        "windows_rate": -1,
    },
    "balanced": {
        "label": "中性自然",
        "provider": "edge_tts",
        "edge_voice": "en-US-JennyNeural",
        "edge_rate_percent": -10,
        "edge_pitch_hz": -2,
        "macos_voice": "Ava",
        "macos_rate": 150,
        "windows_rate": 0,
    },
    "strong": {
        "label": "清晰有力",
        "provider": "edge_tts",
        "edge_voice": "en-US-AriaNeural",
        "edge_rate_percent": -4,
        "edge_pitch_hz": 2,
        "macos_voice": "Ava",
        "macos_rate": 165,
        "windows_rate": 1,
    },
}

_DEFAULT_TTS_SECTION = {
    "base_runtime_tunables_path": "config/runtime_tunables/runtime_settings.py",
    "runtime_override_path": "runtime/runtime_tunables.generated.py",
    "provider": "edge_tts",
    "edge_voice": "en-US-AvaNeural",
    "edge_rate_percent": -18,
    "edge_pitch_hz": -8,
    "macos_voice": "Ava",
    "macos_rate": 145,
    "windows_voice": "",
    "windows_rate": 0,
    "allow_silent_fallback": True,
}

_TOP_LEVEL_RUNTIME_KEYS = [
    "MODEL_CONFIG",
    "APP_RUNTIME_FLAGS",
    "GOOGLE_API_RUNTIME",
    "VIDEO_RUNTIME",
    "SUBTITLE_RUNTIME",
    "TTS_RUNTIME",
]


def _load_module_from_path(path: Path) -> ModuleType:
    if not path.exists():
        raise FileNotFoundError(f"未找到运行时调参配置文件：{path}")
    spec = importlib.util.spec_from_file_location("agent_runtime_tunables_source", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载运行时调参配置文件：{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _module_value(module: ModuleType, name: str, default: Any) -> Any:
    return copy.deepcopy(getattr(module, name, default))


def _parse_signed_int(raw: Any, suffix: str, default: int) -> int:
    text = str(raw or "").strip()
    if not text:
        return default
    normalized = text.replace(suffix, "").replace("+", "").strip()
    try:
        return int(float(normalized))
    except (TypeError, ValueError):
        return default


def _format_signed_value(value: int, suffix: str) -> str:
    number = int(value)
    prefix = "+" if number >= 0 else ""
    return f"{prefix}{number}{suffix}"


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def base_runtime_tunables_path(settings: dict[str, Any]) -> Path:
    tts = settings.get("tts", {}) if isinstance(settings.get("tts"), dict) else {}
    return resolve_path(str(tts.get("base_runtime_tunables_path") or _DEFAULT_TTS_SECTION["base_runtime_tunables_path"]))


def runtime_override_path(settings: dict[str, Any]) -> Path:
    tts = settings.get("tts", {}) if isinstance(settings.get("tts"), dict) else {}
    return resolve_path(str(tts.get("runtime_override_path") or _DEFAULT_TTS_SECTION["runtime_override_path"]))


def _load_base_runtime_payload(settings: dict[str, Any]) -> dict[str, Any]:
    module = _load_module_from_path(base_runtime_tunables_path(settings))
    return {key: _module_value(module, key, {}) for key in _TOP_LEVEL_RUNTIME_KEYS}


def load_tts_preferences(settings: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(_DEFAULT_TTS_SECTION)
    payload.update(settings.get("tts", {}) if isinstance(settings.get("tts"), dict) else {})
    try:
        base_runtime = _load_base_runtime_payload(settings).get("TTS_RUNTIME", {})
    except Exception:
        base_runtime = {}

    payload["provider"] = str(payload.get("provider") or base_runtime.get("provider") or _DEFAULT_TTS_SECTION["provider"]).strip().lower()
    payload["edge_voice"] = str(payload.get("edge_voice") or base_runtime.get("edge_voice") or _DEFAULT_TTS_SECTION["edge_voice"]).strip()
    payload["edge_rate_percent"] = _coerce_int(
        payload.get("edge_rate_percent", _parse_signed_int(base_runtime.get("edge_rate"), "%", _DEFAULT_TTS_SECTION["edge_rate_percent"])),
        _DEFAULT_TTS_SECTION["edge_rate_percent"],
    )
    payload["edge_pitch_hz"] = _coerce_int(
        payload.get("edge_pitch_hz", _parse_signed_int(base_runtime.get("edge_pitch"), "Hz", _DEFAULT_TTS_SECTION["edge_pitch_hz"])),
        _DEFAULT_TTS_SECTION["edge_pitch_hz"],
    )
    payload["macos_voice"] = str(payload.get("macos_voice") or base_runtime.get("macos_voice") or _DEFAULT_TTS_SECTION["macos_voice"]).strip()
    payload["macos_rate"] = _coerce_int(payload.get("macos_rate", base_runtime.get("macos_rate")), _DEFAULT_TTS_SECTION["macos_rate"])
    payload["windows_voice"] = str(payload.get("windows_voice") or base_runtime.get("windows_voice") or _DEFAULT_TTS_SECTION["windows_voice"]).strip()
    payload["windows_rate"] = _coerce_int(payload.get("windows_rate", base_runtime.get("windows_rate")), _DEFAULT_TTS_SECTION["windows_rate"])
    payload["allow_silent_fallback"] = _coerce_bool(
        payload.get("allow_silent_fallback", base_runtime.get("allow_silent_fallback")),
        _DEFAULT_TTS_SECTION["allow_silent_fallback"],
    )
    return payload


def build_tts_runtime_payload(settings: dict[str, Any]) -> dict[str, Any]:
    preferences = load_tts_preferences(settings)
    runtime = _load_base_runtime_payload(settings)
    tts_runtime = copy.deepcopy(runtime.get("TTS_RUNTIME", {}))
    tts_runtime.update(
        {
            "provider": preferences["provider"],
            "edge_voice": preferences["edge_voice"],
            "edge_rate": _format_signed_value(preferences["edge_rate_percent"], "%"),
            "edge_pitch": _format_signed_value(preferences["edge_pitch_hz"], "Hz"),
            "macos_voice": preferences["macos_voice"],
            "macos_rate": preferences["macos_rate"],
            "windows_voice": preferences["windows_voice"],
            "windows_rate": preferences["windows_rate"],
            "allow_silent_fallback": preferences["allow_silent_fallback"],
        }
    )
    runtime["TTS_RUNTIME"] = tts_runtime
    return runtime


def validate_tts_runtime_bridge(settings: dict[str, Any]) -> dict[str, Any]:
    base_path = base_runtime_tunables_path(settings)
    override_path = runtime_override_path(settings)
    preferences = load_tts_preferences(settings)
    resolved_runtime = build_tts_runtime_payload(settings)["TTS_RUNTIME"]
    return {
        "ok": base_path.exists(),
        "base_runtime_tunables_path": str(base_path),
        "base_exists": base_path.exists(),
        "runtime_override_path": str(override_path),
        "runtime_override_exists": override_path.exists(),
        "preferences": preferences,
        "resolved_tts_runtime": resolved_runtime,
    }


def materialize_runtime_tunables(settings: dict[str, Any]) -> dict[str, Any]:
    runtime_payload = build_tts_runtime_payload(settings)
    target_path = runtime_override_path(settings)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["from __future__ import annotations", "", "# Auto-generated by Agent TTS settings.", ""]
    for key in _TOP_LEVEL_RUNTIME_KEYS:
        lines.append(f"{key} = {pformat(runtime_payload.get(key, {}), width=100, sort_dicts=False)}")
        lines.append("")
    target_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return {
        "path": str(target_path),
        "exists": target_path.exists(),
        "tts_runtime": runtime_payload.get("TTS_RUNTIME", {}),
    }


def save_tts_preferences(settings: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    current = load_tts_preferences(settings)
    current.update(
        {
            "provider": str(payload.get("provider") or current["provider"]).strip().lower(),
            "edge_voice": str(payload.get("edge_voice") or current["edge_voice"]).strip(),
            "edge_rate_percent": _coerce_int(payload.get("edge_rate_percent"), current["edge_rate_percent"]),
            "edge_pitch_hz": _coerce_int(payload.get("edge_pitch_hz"), current["edge_pitch_hz"]),
            "macos_voice": str(payload.get("macos_voice") or current["macos_voice"]).strip(),
            "macos_rate": _coerce_int(payload.get("macos_rate"), current["macos_rate"]),
            "windows_voice": str(payload.get("windows_voice") or current["windows_voice"]).strip(),
            "windows_rate": _coerce_int(payload.get("windows_rate"), current["windows_rate"]),
            "allow_silent_fallback": _coerce_bool(payload.get("allow_silent_fallback"), current["allow_silent_fallback"]),
        }
    )
    settings["tts"] = {
        "base_runtime_tunables_path": current["base_runtime_tunables_path"],
        "runtime_override_path": current["runtime_override_path"],
        "provider": current["provider"],
        "edge_voice": current["edge_voice"],
        "edge_rate_percent": current["edge_rate_percent"],
        "edge_pitch_hz": current["edge_pitch_hz"],
        "macos_voice": current["macos_voice"],
        "macos_rate": current["macos_rate"],
        "windows_voice": current["windows_voice"],
        "windows_rate": current["windows_rate"],
        "allow_silent_fallback": current["allow_silent_fallback"],
    }
    config_path = save_settings(settings)
    override = materialize_runtime_tunables(settings)
    append_history(
        settings,
        event_type="tts_settings_save",
        status="success",
        title="保存 TTS 配音设置",
        payload={
            "config_path": str(config_path),
            "runtime_override_path": override["path"],
            "provider": current["provider"],
            "edge_voice": current["edge_voice"],
            "edge_rate_percent": current["edge_rate_percent"],
            "edge_pitch_hz": current["edge_pitch_hz"],
        },
    )
    return {
        "config_path": str(config_path),
        "runtime_override_path": override["path"],
        "tts": settings["tts"],
        "resolved_tts_runtime": override["tts_runtime"],
    }


def apply_tts_preset(settings: dict[str, Any], preset_name: str) -> dict[str, Any]:
    preset = VOICE_STYLE_PRESETS.get(preset_name)
    if not preset:
        raise KeyError(preset_name)
    payload = load_tts_preferences(settings)
    payload.update(
        {
            "provider": preset["provider"],
            "edge_voice": preset["edge_voice"],
            "edge_rate_percent": preset["edge_rate_percent"],
            "edge_pitch_hz": preset["edge_pitch_hz"],
            "macos_voice": preset["macos_voice"],
            "macos_rate": preset["macos_rate"],
            "windows_rate": preset["windows_rate"],
        }
    )
    return payload
