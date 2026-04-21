from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from agent.config import agent_root


def load_agent_env(*, override: bool = False) -> dict[str, Any]:
    root = agent_root()
    agent_env = root / ".env"
    root_env = root.parent / ".env"

    loaded = {
        "agent_env_path": str(agent_env),
        "agent_env_exists": agent_env.exists(),
        "root_env_path": str(root_env),
        "root_env_exists": root_env.exists(),
    }

    if root_env.exists():
        load_dotenv(dotenv_path=root_env, override=override)
    if agent_env.exists():
        load_dotenv(dotenv_path=agent_env, override=True)

    loaded["meta_token_present"] = bool(
        (os.getenv("META_ACCESS_TOKEN") or os.getenv("FACEBOOK_ACCESS_TOKEN") or "").strip()
    )
    return loaded
