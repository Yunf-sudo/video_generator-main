from __future__ import annotations

import json
import sys
from pathlib import Path


AGENT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = AGENT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from agent.config import ensure_workspace_dirs, load_settings
from agent.env import load_agent_env
from agent.frontend_validation import run_frontend_validation


def main() -> int:
    load_agent_env()
    settings = load_settings()
    ensure_workspace_dirs(settings)
    result = run_frontend_validation(settings)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if str(result.get("status") or "").lower() == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
