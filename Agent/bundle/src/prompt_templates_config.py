from __future__ import annotations

import copy
import importlib.util
import os
from pathlib import Path
from types import ModuleType

from workspace_paths import PROJECT_ROOT


AGENT_ROOT = PROJECT_ROOT.parent
PRIMARY_PROMPT_TEMPLATES_PATH = AGENT_ROOT / "config" / "prompt_inputs" / "prompt_templates.py"
FALLBACK_PROMPT_TEMPLATES_PATH = PROJECT_ROOT / "configs" / "prompt_inputs" / "prompt_templates.py"
DEFAULT_PROMPT_TEMPLATES_PATH = (
    PRIMARY_PROMPT_TEMPLATES_PATH if PRIMARY_PROMPT_TEMPLATES_PATH.exists() else FALLBACK_PROMPT_TEMPLATES_PATH
)


def _resolve_config_path() -> Path:
    configured = (os.getenv("PROMPT_TEMPLATES_CONFIG_PATH") or "").strip()
    if not configured:
        return DEFAULT_PROMPT_TEMPLATES_PATH
    candidate = Path(configured)
    if not candidate.is_absolute():
        agent_candidate = (AGENT_ROOT / candidate).resolve()
        candidate = agent_candidate if agent_candidate.exists() else (PROJECT_ROOT / candidate).resolve()
    return candidate


def _load_module_from_path(path: Path) -> ModuleType:
    if not path.exists():
        raise FileNotFoundError(f"未找到提示词模板配置文件：{path}")
    spec = importlib.util.spec_from_file_location("prompt_templates_config_module", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载提示词模板配置文件：{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _module_value(module: ModuleType, name: str, default: str = "") -> str:
    return copy.deepcopy(getattr(module, name, default))


def load_prompt_templates() -> dict[str, str]:
    config_path = _resolve_config_path()
    module = _load_module_from_path(config_path)
    return {
        "config_path": str(config_path),
        "generate_script_system_prompt": _module_value(module, "GENERATE_SCRIPT_SYSTEM_PROMPT"),
        "generate_script_user_prompt": _module_value(module, "GENERATE_SCRIPT_USER_PROMPT"),
        "generate_scene_pic_system_prompt": _module_value(module, "GENERATE_SCENE_PIC_SYSTEM_PROMPT"),
        "generate_scene_pic_user_prompt": _module_value(module, "GENERATE_SCENE_PIC_USER_PROMPT"),
        "video_generate_prompt": _module_value(module, "VIDEO_GENERATE_PROMPT"),
        "ti_intro_generator_prompt": _module_value(module, "TI_INTRO_GENERATOR_PROMPT"),
        "ti_intro_generator_prompt_with_ref": _module_value(module, "TI_INTRO_GENERATOR_PROMPT_WITH_REF"),
        "prompt_composer_system_prompt": _module_value(module, "PROMPT_COMPOSER_SYSTEM_PROMPT"),
        "translation_system_prompt": _module_value(module, "TRANSLATION_SYSTEM_PROMPT"),
    }
