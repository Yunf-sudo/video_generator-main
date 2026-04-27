from __future__ import annotations

from pathlib import Path
from typing import Any

from dotenv import load_dotenv


BUNDLE_SRC_DIR = Path(__file__).resolve().parent
AGENT_ROOT = BUNDLE_SRC_DIR.parent.parent
AGENT_ENV_PATH = AGENT_ROOT / ".env"


def load_agent_bundle_env(*, override: bool = False) -> dict[str, Any]:
    loaded = {
        "agent_env_path": str(AGENT_ENV_PATH),
        "agent_env_exists": AGENT_ENV_PATH.exists(),
    }
    if AGENT_ENV_PATH.exists():
        load_dotenv(dotenv_path=AGENT_ENV_PATH, override=override)
    return loaded
