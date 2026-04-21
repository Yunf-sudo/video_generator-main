from __future__ import annotations

import copy
import importlib.util
import os
from pathlib import Path
from types import ModuleType

from workspace_paths import PROJECT_ROOT


DEFAULT_APP_CONFIG_PATH = PROJECT_ROOT / "configs" / "streamlit_app_defaults.py"


def _resolve_config_path() -> Path:
    configured = (os.getenv("STREAMLIT_APP_DEFAULTS_PATH") or "").strip()
    if not configured:
        return DEFAULT_APP_CONFIG_PATH
    candidate = Path(configured)
    if not candidate.is_absolute():
        candidate = (PROJECT_ROOT / candidate).resolve()
    return candidate


def _load_module_from_path(path: Path) -> ModuleType:
    if not path.exists():
        raise FileNotFoundError(f"未找到工作台默认配置文件：{path}")
    spec = importlib.util.spec_from_file_location("streamlit_app_defaults_config", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载工作台默认配置文件：{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _module_value(module: ModuleType, name: str, default):
    value = getattr(module, name, default)
    return copy.deepcopy(value)


def load_app_defaults() -> dict:
    config_path = _resolve_config_path()
    module = _load_module_from_path(config_path)

    style_presets = _module_value(module, "STYLE_PRESETS", {})
    default_inputs = _module_value(module, "DEFAULT_INPUTS", {})
    language_options = _module_value(module, "LANGUAGE_OPTIONS", ["Chinese", "English"])
    video_orientation_options = _module_value(module, "VIDEO_ORIENTATION_OPTIONS", ["9:16", "16:9", "1:1"])

    if not isinstance(style_presets, dict) or not style_presets:
        raise ValueError(f"配置文件中的 STYLE_PRESETS 无效：{config_path}")
    if not isinstance(default_inputs, dict) or not default_inputs:
        raise ValueError(f"配置文件中的 DEFAULT_INPUTS 无效：{config_path}")
    if not isinstance(language_options, list) or not language_options:
        raise ValueError(f"配置文件中的 LANGUAGE_OPTIONS 无效：{config_path}")
    if not isinstance(video_orientation_options, list) or not video_orientation_options:
        raise ValueError(f"配置文件中的 VIDEO_ORIENTATION_OPTIONS 无效：{config_path}")

    return {
        "config_path": str(config_path),
        "style_presets": style_presets,
        "default_inputs": default_inputs,
        "language_options": language_options,
        "video_orientation_options": video_orientation_options,
    }
