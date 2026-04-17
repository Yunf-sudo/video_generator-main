from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ad_management_agent import run_agent_forever, run_agent_once


def main() -> None:
    parser = argparse.ArgumentParser(description="运行广告管理 Agent，执行监控、补位、归档和告警。")
    parser.add_argument("--once", action="store_true", help="只执行一次，不进入守护循环。")
    parser.add_argument("--interval-minutes", type=int, default=0, help="守护模式下的轮询频率，默认读取配置。")
    args = parser.parse_args()

    if args.once:
        result = run_agent_once()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    run_agent_forever(interval_minutes=args.interval_minutes or None)


if __name__ == "__main__":
    main()
