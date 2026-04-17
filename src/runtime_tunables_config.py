from __future__ import annotations

import copy
import importlib.util
import os
from pathlib import Path
from types import ModuleType

from workspace_paths import PROJECT_ROOT


DEFAULT_RUNTIME_TUNABLES_PATH = PROJECT_ROOT / "configs" / "runtime_tunables" / "runtime_settings.py"


def _resolve_config_path() -> Path:
    configured = (os.getenv("RUNTIME_TUNABLES_CONFIG_PATH") or "").strip()
    if not configured:
        return DEFAULT_RUNTIME_TUNABLES_PATH
    candidate = Path(configured)
    if not candidate.is_absolute():
        candidate = (PROJECT_ROOT / candidate).resolve()
    return candidate


def _load_module_from_path(path: Path) -> ModuleType:
    if not path.exists():
        raise FileNotFoundError(f"未找到运行时调参配置文件：{path}")
    spec = importlib.util.spec_from_file_location("runtime_tunables_config_module", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载运行时调参配置文件：{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _module_value(module: ModuleType, name: str, default):
    return copy.deepcopy(getattr(module, name, default))


def load_runtime_tunables() -> dict:
    config_path = _resolve_config_path()
    module = _load_module_from_path(config_path)

    model_config = _module_value(module, "MODEL_CONFIG", {})
    app_runtime_flags = _module_value(module, "APP_RUNTIME_FLAGS", {})
    google_api_runtime = _module_value(module, "GOOGLE_API_RUNTIME", {})
    video_runtime = _module_value(module, "VIDEO_RUNTIME", {})
    subtitle_runtime = _module_value(module, "SUBTITLE_RUNTIME", {})

    return {
        "config_path": str(config_path),
        "model_config": model_config,
        "app_runtime_flags": app_runtime_flags,
        "google_api_runtime": google_api_runtime,
        "video_runtime": video_runtime,
        "subtitle_runtime": subtitle_runtime,
    }
