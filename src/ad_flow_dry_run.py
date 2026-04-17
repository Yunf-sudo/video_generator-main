from __future__ import annotations

import os
from typing import Any

from ad_management_agent import run_agent_once
from ad_material_pipeline import register_and_prelaunch_run_output
from local_storyboard_placeholder import create_storyboard_placeholder
from material_library import delete_material_record, inventory_snapshot, list_material_records, load_material_record, update_material_record
from media_pipeline import assemble_final_video, generate_local_clip
from workspace_paths import start_new_run, write_run_json


def _build_minimal_run() -> tuple[str, dict, dict, dict]:
    run_paths = start_new_run(prefix="dryrun")
    placeholder = create_storyboard_placeholder(
        scene_number=1,
        scene_description="A calm product ad test scene for dry run validation.",
        key_message="Dry run validation clip",
        aspect_ratio="9:16",
        output_dir=run_paths.pics,
    )
    clip = generate_local_clip(
        placeholder,
        duration_seconds=2.0,
        aspect_ratio="9:16",
        output_dir=run_paths.clips,
    )
    final_video_result = assemble_final_video(
        [clip["video_path"]],
        audio_path=None,
        srt_path=None,
        output_dir=run_paths.exports,
        filename="dry_run_final.mp4",
        preserve_clip_audio=True,
        aspect_ratio="9:16",
    )
    inputs = {
        "product_name": "AnyWell Electric Wheelchair",
        "target_market": "United States",
        "style_preset": "家庭关怀型",
        "landing_page_url": "https://anywellshop.com/products/150kg-capacity-electric-wheelchair",
        "page_id": "325789213957232",
        "target_adset_id": "120244986089430635",
    }
    script = {
        "meta": {
            "product_name": "AnyWell Electric Wheelchair",
            "language": "English",
            "style_preset": "家庭关怀型",
        },
        "source_meta": inputs,
        "scenes": {
            "main_theme": "Dry run validation",
            "scenes": [
                {
                    "scene_number": 1,
                    "duration_seconds": 2,
                    "audio": {
                        "text": "A smooth dry run validation ad.",
                    },
                }
            ],
        },
    }
    ti_intro = {
        "title": "Dry Run Title",
        "description": "Dry run description for ad flow validation.",
        "tags": ["dry-run", "validation"],
    }
    write_run_json("final_video_result.json", final_video_result)
    write_run_json("script.json", script)
    write_run_json("ti_intro.json", ti_intro)
    write_run_json("brief.json", {"inputs": inputs})
    return run_paths.run_id, final_video_result, script, ti_intro


def run_full_dry_run_test() -> dict[str, Any]:
    os.environ["META_ADS_DRY_RUN"] = "true"

    for record in list_material_records():
        if bool(record.get("is_dry_run", False)):
            delete_material_record(str(record.get("material_id") or ""))

    run_id, final_video_result, script, ti_intro = _build_minimal_run()
    material = register_and_prelaunch_run_output(
        run_id=run_id,
        final_video_result=final_video_result,
        script=script,
        ti_intro=ti_intro,
        source_inputs=script["source_meta"],
    )
    material_id = str(material["material_id"])
    update_material_record(material_id, {"is_dry_run": True})

    approved = update_material_record(material_id, {"review_status": "approved", "review_note": "dry run auto approved"})
    first_agent_result = run_agent_once(adset_ids=[approved["target_adset_id"]])

    activated = load_material_record(material_id)
    update_material_record(
        material_id,
        {
            "performance_snapshot": {
                "spend": 45.0,
                "impressions": 1200,
                "ctr": 1.2,
                "add_to_cart": 0.0,
                "purchases": 0.0,
                "roas": 0.0,
            }
        },
    )
    second_agent_result = run_agent_once(adset_ids=[activated["target_adset_id"]])
    final_record = load_material_record(material_id)

    return {
        "run_id": run_id,
        "material_id": material_id,
        "inventory_snapshot": inventory_snapshot(),
        "first_agent_result": first_agent_result,
        "second_agent_result": second_agent_result,
        "final_launch_status": final_record.get("launch_status"),
        "final_archive_bucket": final_record.get("archive_bucket", ""),
        "meta_mapping": final_record.get("meta_mapping", {}),
        "history_count": len(final_record.get("history", [])),
    }
