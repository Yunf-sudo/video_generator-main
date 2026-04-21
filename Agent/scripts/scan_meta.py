from __future__ import annotations

import json
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
AGENT_ROOT = SCRIPT_DIR.parent
SRC_DIR = AGENT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from agent.config import ensure_workspace_dirs, load_settings
from agent.env import load_agent_env
from agent.meta_monitor import run_meta_monitor


def main() -> None:
    load_agent_env()
    settings = load_settings()
    ensure_workspace_dirs(settings)
    result = run_meta_monitor(settings)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
