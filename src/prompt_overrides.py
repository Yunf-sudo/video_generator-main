from __future__ import annotations

import json
from functools import lru_cache
from workspace_paths import PROJECT_ROOT

OVERRIDES_PATH = PROJECT_ROOT / "prompt_overrides.json"


@lru_cache(maxsize=1)
def load_prompt_overrides() -> dict[str, str]:
    if not OVERRIDES_PATH.exists():
        return {}
    try:
        data = json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
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
