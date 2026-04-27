from __future__ import annotations

import copy
import importlib.util
import os
from pathlib import Path
from types import ModuleType

from workspace_paths import PROJECT_ROOT


AGENT_ROOT = PROJECT_ROOT.parent
PRIMARY_AD_OPS_CONFIG_PATH = AGENT_ROOT / "config" / "ad_ops" / "material_flow_settings.py"
FALLBACK_AD_OPS_CONFIG_PATH = PROJECT_ROOT / "configs" / "ad_ops" / "material_flow_settings.py"
DEFAULT_AD_OPS_CONFIG_PATH = PRIMARY_AD_OPS_CONFIG_PATH if PRIMARY_AD_OPS_CONFIG_PATH.exists() else FALLBACK_AD_OPS_CONFIG_PATH


def _resolve_config_path() -> Path:
    configured = (os.getenv("AD_OPS_CONFIG_PATH") or "").strip()
    if not configured:
        return DEFAULT_AD_OPS_CONFIG_PATH
    candidate = Path(configured)
    if not candidate.is_absolute():
        agent_candidate = (AGENT_ROOT / candidate).resolve()
        candidate = agent_candidate if agent_candidate.exists() else (PROJECT_ROOT / candidate).resolve()
    return candidate


def _load_module_from_path(path: Path) -> ModuleType:
    if not path.exists():
        raise FileNotFoundError(f"未找到广告业务配置文件：{path}")
    spec = importlib.util.spec_from_file_location("ad_ops_config_module", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载广告业务配置文件：{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _module_value(module: ModuleType, name: str, default):
    return copy.deepcopy(getattr(module, name, default))


def load_ad_ops_config() -> dict:
    config_path = _resolve_config_path()
    module = _load_module_from_path(config_path)
    return {
        "config_path": str(config_path),
        "meta_pool_state": _module_value(module, "META_POOL_STATE", _module_value(module, "MATERIAL_LIBRARY", {})),
        "meta_ads": _module_value(module, "META_ADS", {}),
        "monitor_rules": _module_value(module, "MONITOR_RULES", {}),
    }
