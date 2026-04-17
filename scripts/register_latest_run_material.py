from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ad_material_pipeline import register_and_prelaunch_run_output, register_run_output_to_material_library
from workspace_paths import runs_root


def _read_json(path: Path):
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _latest_run_id() -> str:
    candidates = [path for path in runs_root().iterdir() if path.is_dir()]
    if not candidates:
        raise RuntimeError("没有可用的 run。")
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates[0].name


def main() -> None:
    parser = argparse.ArgumentParser(description="把最新或指定 run 的成片注册进素材库，并可选预上架到 Meta。")
    parser.add_argument("--run-id", default="", help="指定 run_id，不传则使用最近一个 run。")
    parser.add_argument("--prelaunch", action="store_true", help="注册后立即预上架到 Meta，广告默认保持 PAUSED。")
    args = parser.parse_args()

    run_id = args.run_id.strip() or _latest_run_id()
    meta_dir = runs_root() / run_id / "meta"
    final_video_result = _read_json(meta_dir / "final_video_result.json")
    script = _read_json(meta_dir / "script.json")
    ti_intro = _read_json(meta_dir / "ti_intro.json")
    brief = _read_json(meta_dir / "brief.json") or {}
    inputs = brief.get("inputs", {}) if isinstance(brief, dict) else {}

    if args.prelaunch:
        material = register_and_prelaunch_run_output(
            run_id=run_id,
            final_video_result=final_video_result,
            script=script,
            ti_intro=ti_intro,
            source_inputs=inputs,
        )
    else:
        material = register_run_output_to_material_library(
            run_id=run_id,
            final_video_result=final_video_result,
            script=script,
            ti_intro=ti_intro,
            source_inputs=inputs,
        )
    print(json.dumps(material, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
