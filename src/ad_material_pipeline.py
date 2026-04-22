from __future__ import annotations

from typing import Any

from meta_pool_state import register_generated_material
from meta_ads_service import (
    create_ad_creative_for_material,
    create_paused_ad_for_material,
    meta_write_override,
    upload_thumbnail_to_meta,
    upload_video_to_meta,
)


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


def stage_run_output_to_meta(
    *,
    run_id: str,
    final_video_result: dict[str, Any] | None,
    script: dict[str, Any] | None,
    ti_intro: dict[str, Any] | None,
    source_inputs: dict[str, Any] | None,
    perform_actual_upload: bool = False,
    allow_meta_write_override: bool = False,
) -> dict[str, Any]:
    material = _register_run_output_to_meta_pool_state(
        run_id=run_id,
        final_video_result=final_video_result,
        script=script,
        ti_intro=ti_intro,
        source_inputs=source_inputs,
    )
    material_id = str(material.get("material_id") or "").strip()
    if not material_id:
        raise RuntimeError("素材入库成功，但没有返回 material_id。")

    steps: list[dict[str, Any]] = [
        {
            "step": "register",
            "label": "写入 Meta 暂存池",
            "status": "success",
            "message": f"素材 {material_id} 已写入本地暂存池。",
        }
    ]

    if not perform_actual_upload:
        steps.append(
            {
                "step": "skip_remote_upload",
                "label": "跳过真实上传",
                "status": "success",
                "message": "本次只登记本地暂存池，未调用 Meta 上传、创意创建和广告创建。",
            }
        )
        return {
            "status": "registered_only",
            "material_id": material_id,
            "failed_step": "",
            "steps": steps,
            "material": material,
            "meta_mapping": material.get("meta_mapping") or {},
        }

    stage_calls = [
        ("upload_video", "上传视频到 Meta", upload_video_to_meta, "video_id"),
        ("upload_thumbnail", "上传缩略图到 Meta", upload_thumbnail_to_meta, "image_hash"),
        ("create_creative", "创建广告创意", create_ad_creative_for_material, "creative_id"),
        ("create_ad", "创建 PAUSED 广告", create_paused_ad_for_material, "ad_id"),
    ]

    latest_material = material
    with meta_write_override(allow_meta_write_override):
        for step_key, label, fn, mapping_key in stage_calls:
            try:
                latest_material = fn(material_id)
                value = str((latest_material.get("meta_mapping") or {}).get(mapping_key) or "").strip()
                steps.append(
                    {
                        "step": step_key,
                        "label": label,
                        "status": "success",
                        "message": f"{label}成功。",
                        "value": value,
                    }
                )
            except Exception as exc:
                latest_mapping = latest_material.get("meta_mapping") or {}
                steps.append(
                    {
                        "step": step_key,
                        "label": label,
                        "status": "failed",
                        "message": str(exc),
                        "value": str(latest_mapping.get(mapping_key) or "").strip(),
                    }
                )
                return {
                    "status": "partial_failure",
                    "material_id": material_id,
                    "failed_step": step_key,
                    "steps": steps,
                    "material": latest_material,
                    "meta_mapping": latest_mapping,
                }

    return {
        "status": "success",
        "material_id": material_id,
        "failed_step": "",
        "steps": steps,
        "material": latest_material,
        "meta_mapping": latest_material.get("meta_mapping") or {},
    }
