from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from workspace_paths import PROJECT_ROOT

AGENT_ROOT = PROJECT_ROOT.parent
PRIMARY_OVERRIDES_PATH = AGENT_ROOT / "config" / "prompt_overrides.json"
FALLBACK_OVERRIDES_PATH = PROJECT_ROOT / "prompt_overrides.json"
DEFAULT_OVERRIDES_PATH = PRIMARY_OVERRIDES_PATH if PRIMARY_OVERRIDES_PATH.exists() else FALLBACK_OVERRIDES_PATH


def _resolve_overrides_path() -> str:
    custom_path = (os.getenv("PROMPT_OVERRIDES_PATH") or "").strip()
    if custom_path:
        if os.path.isabs(custom_path):
            return custom_path
        agent_candidate = (AGENT_ROOT / custom_path).resolve()
        if agent_candidate.exists():
            return str(agent_candidate)
        return str((PROJECT_ROOT / custom_path).resolve())
    return str(DEFAULT_OVERRIDES_PATH.resolve())


@lru_cache(maxsize=1)
def load_prompt_overrides() -> dict[str, str]:
    overrides_path = _resolve_overrides_path()
    path = Path(overrides_path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): str(value) for key, value in data.items() if value}


def apply_override(base_text: str, key: str) -> str:
    overrides = load_prompt_overrides()
    extra = (overrides.get(key) or "").strip()
    if not extra:
        return base_text
    return f"{base_text.rstrip()}\n\nAdditional local override:\n{extra}\n"
