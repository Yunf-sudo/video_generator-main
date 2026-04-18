from __future__ import annotations

from typing import Any

from meta_pool_state import register_generated_material
from meta_ads_service import create_paused_ad_for_material


def _register_run_output_to_meta_pool_state(
    *,
    run_id: str,
    final_video_result: dict[str, Any] | None,
    script: dict[str, Any] | None,
    ti_intro: dict[str, Any] | None,
    source_inputs: dict[str, Any] | None,
) -> dict[str, Any]:
    final_video_path = str((final_video_result or {}).get("video_path") or "").strip()
    if not final_video_path:
        raise ValueError("当前 run 还没有正式成片，无法写入 Meta 暂存池状态。")
    return register_generated_material(
        run_id=run_id,
        final_video_path=final_video_path,
        script=script,
        ti_intro=ti_intro,
        source_inputs=source_inputs,
        final_video_result=final_video_result,
    )


def register_and_prelaunch_run_output(
    *,
    run_id: str,
    final_video_result: dict[str, Any] | None,
    script: dict[str, Any] | None,
    ti_intro: dict[str, Any] | None,
    source_inputs: dict[str, Any] | None,
) -> dict[str, Any]:
    material = _register_run_output_to_meta_pool_state(
        run_id=run_id,
        final_video_result=final_video_result,
        script=script,
        ti_intro=ti_intro,
        source_inputs=source_inputs,
    )
    return create_paused_ad_for_material(str(material.get("material_id") or ""))
