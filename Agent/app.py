from __future__ import annotations

import sys
from pathlib import Path


AGENT_ROOT = Path(__file__).resolve().parent
SRC_DIR = AGENT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from agent.config import ensure_workspace_dirs, load_settings
from agent.dashboard import main
from agent.env import load_agent_env


if __name__ == "__main__":
    load_agent_env()
    settings = load_settings()
    ensure_workspace_dirs(settings)
    main(settings)
