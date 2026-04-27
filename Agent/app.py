from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


AGENT_ROOT = Path(__file__).resolve().parent
AGENT_SRC_DIR = AGENT_ROOT / "src"
BUNDLE_SRC_DIR = AGENT_ROOT / "bundle" / "src"

for path in (AGENT_SRC_DIR, BUNDLE_SRC_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from agent.env import load_agent_env


def _load_bundle_app():
    bundle_app_path = BUNDLE_SRC_DIR / "app.py"
    spec = importlib.util.spec_from_file_location("agent_bundle_app", bundle_app_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 Agent bundle 前端入口: {bundle_app_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    load_agent_env()
    bundle_app = _load_bundle_app()
    bundle_app.main()


if __name__ == "__main__":
    main()
