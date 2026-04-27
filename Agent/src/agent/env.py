from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv

from agent.config import agent_root


def resolve_google_api_key() -> str:
    return (
        os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
        or os.getenv("GOOGLE_GENAI_API_KEY")
        or ""
    ).strip()


def google_api_key_source() -> str:
    if (os.getenv("GEMINI_API_KEY") or "").strip():
        return "GEMINI_API_KEY"
    if (os.getenv("GOOGLE_API_KEY") or "").strip():
        return "GOOGLE_API_KEY"
    if (os.getenv("GOOGLE_GENAI_API_KEY") or "").strip():
        return "GOOGLE_GENAI_API_KEY"
    return ""


def resolve_meta_access_token() -> str:
    return (
        os.getenv("META_ACCESS_TOKEN")
        or os.getenv("FACEBOOK_ACCESS_TOKEN")
        or ""
    ).strip()


def meta_access_token_source() -> str:
    if (os.getenv("META_ACCESS_TOKEN") or "").strip():
        return "META_ACCESS_TOKEN"
    if (os.getenv("FACEBOOK_ACCESS_TOKEN") or "").strip():
        return "FACEBOOK_ACCESS_TOKEN"
    return ""


def load_agent_env(*, override: bool = False) -> dict[str, Any]:
    root = agent_root()
    agent_env = root / ".env"

    loaded = {
        "agent_env_path": str(agent_env),
        "agent_env_exists": agent_env.exists(),
    }

    if agent_env.exists():
        load_dotenv(dotenv_path=agent_env, override=override)

    loaded["google_key_present"] = bool(resolve_google_api_key())
    loaded["google_key_source"] = google_api_key_source()
    loaded["meta_token_present"] = bool(resolve_meta_access_token())
    loaded["meta_token_source"] = meta_access_token_source()
    return loaded
