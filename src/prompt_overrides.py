from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from workspace_paths import PROJECT_ROOT

DEFAULT_OVERRIDES_PATH = PROJECT_ROOT / "prompt_overrides.json"


def _resolve_overrides_path() -> str:
    custom_path = (os.getenv("PROMPT_OVERRIDES_PATH") or "").strip()
    if custom_path:
        return str((PROJECT_ROOT / custom_path).resolve()) if not os.path.isabs(custom_path) else custom_path
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
