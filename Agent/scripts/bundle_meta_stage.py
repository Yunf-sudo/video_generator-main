from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
AGENT_ROOT = SCRIPT_DIR.parent
BUNDLE_SRC = AGENT_ROOT / "bundle" / "src"

if str(BUNDLE_SRC) not in sys.path:
    sys.path.insert(0, str(BUNDLE_SRC))

from meta_ads_service import (  # type: ignore  # noqa: E402
    create_ad_creative_for_material,
    create_paused_ad_for_material,
    upload_thumbnail_to_meta,
    upload_video_to_meta,
)
from meta_pool_state import (  # type: ignore  # noqa: E402
    load_material_record,
    register_generated_material,
    update_material_record,
)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _apply_overrides(material_id: str, args: argparse.Namespace) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    if str(args.page_id or "").strip():
        patch["page_id"] = str(args.page_id).strip()
    if str(args.target_adset_id or "").strip():
        patch["target_adset_id"] = str(args.target_adset_id).strip()
    if str(args.landing_page_url or "").strip():
        patch["landing_page_url"] = str(args.landing_page_url).strip()
    if str(args.ad_name or "").strip():
        patch["desired_ad_name"] = str(args.ad_name).strip()
    if str(args.creative_name or "").strip():
        patch["desired_creative_name"] = str(args.creative_name).strip()
    if not patch:
        return load_material_record(material_id)
    return update_material_record(material_id, patch)


def _stage_existing_material(material_id: str, *, direct_adset: bool) -> dict[str, Any]:
    material = load_material_record(material_id)
    mapping = material.get("meta_mapping") or {}
    steps: list[dict[str, Any]] = []

    if not direct_adset:
        return {
            "status": "success",
            "material_id": material_id,
            "steps": steps,
            "material": material,
            "meta_mapping": mapping,
        }

    pipeline = [
        ("video_id", "upload_video", "上传视频到 Meta", upload_video_to_meta),
        ("image_hash", "upload_thumbnail", "上传缩略图到 Meta", upload_thumbnail_to_meta),
        ("creative_id", "create_creative", "创建广告创意", create_ad_creative_for_material),
        ("ad_id", "create_ad", "创建 PAUSED 广告", create_paused_ad_for_material),
    ]

    latest = material
    for mapping_key, step_key, label, fn in pipeline:
        latest_mapping = latest.get("meta_mapping") or {}
        existing_value = str(latest_mapping.get(mapping_key) or "").strip()
        if existing_value and not existing_value.startswith("dry_"):
            steps.append(
                {
                    "step": step_key,
                    "label": label,
                    "status": "skipped",
                    "message": f"{label}已存在，跳过。",
                    "value": existing_value,
                }
            )
            continue
        latest = fn(material_id)
        latest_mapping = latest.get("meta_mapping") or {}
        steps.append(
            {
                "step": step_key,
                "label": label,
                "status": "success",
                "message": f"{label}成功。",
                "value": str(latest_mapping.get(mapping_key) or "").strip(),
            }
        )

    return {
        "status": "success",
        "material_id": material_id,
        "steps": steps,
        "material": latest,
        "meta_mapping": latest.get("meta_mapping") or {},
    }


def _register_concept(args: argparse.Namespace) -> dict[str, Any]:
    report_path = Path(str(args.concept_report_path or "")).resolve()
    if not report_path.exists():
        raise FileNotFoundError(f"未找到 concept_report.json：{report_path}")

    report = _read_json(report_path)
    concept_dir = report_path.parent
    script = _read_json(concept_dir / "script.json")
    ti_intro = _read_json(concept_dir / "ti_intro.json")
    final_video_path = str(report.get("final_video_path") or (concept_dir / "final_video.mp4")).strip()
    if not Path(final_video_path).exists():
        raise FileNotFoundError(f"未找到成片：{final_video_path}")

    run_root = str(report.get("run_root") or "").strip()
    run_id = Path(run_root).name if run_root else f"agent-{concept_dir.name}"
    source_inputs = {
        "page_id": str(args.page_id or "").strip(),
        "target_adset_id": str(args.target_adset_id or "").strip(),
        "landing_page_url": str(args.landing_page_url or "").strip(),
        "desired_ad_name": str(args.ad_name or "").strip(),
        "desired_creative_name": str(args.creative_name or "").strip(),
    }
    material = register_generated_material(
        run_id=run_id,
        final_video_path=final_video_path,
        script=script,
        ti_intro=ti_intro,
        source_inputs=source_inputs,
        final_video_result=report.get("final_video_result") if isinstance(report.get("final_video_result"), dict) else {"video_path": final_video_path},
    )
    material_id = str(material.get("material_id") or "").strip()
    material = _apply_overrides(material_id, args)
    return {
        "status": "success",
        "material_id": material_id,
        "registered_material": material,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stage Agent bundle output into Meta via bundled ad pipeline.")
    parser.add_argument("--mode", choices=["concept", "material"], required=True)
    parser.add_argument("--action", choices=["material_only", "direct_adset"], default="direct_adset")
    parser.add_argument("--concept-report-path", default="")
    parser.add_argument("--material-id", default="")
    parser.add_argument("--page-id", default="")
    parser.add_argument("--target-adset-id", default="")
    parser.add_argument("--landing-page-url", default="")
    parser.add_argument("--ad-name", default="")
    parser.add_argument("--creative-name", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.mode == "concept":
        result = _register_concept(args)
        material_id = str(result.get("material_id") or "").strip()
    else:
        material_id = str(args.material_id or "").strip()
        if not material_id:
            raise ValueError("material 模式下必须提供 --material-id")
        material = _apply_overrides(material_id, args)
        result = {
            "status": "success",
            "material_id": material_id,
            "registered_material": material,
        }

    if args.action == "direct_adset":
        staged = _stage_existing_material(material_id, direct_adset=True)
        result.update(staged)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
