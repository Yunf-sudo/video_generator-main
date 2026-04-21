from __future__ import annotations

import _bootstrap  # noqa: F401
import json
import os
import time
from pathlib import Path

from asr import generate_srt_asset_from_audio
from generate_scenes_pics_tools import generate_storyboard
from generate_script_tools import generate_scripts
from generate_tts_audio import generate_tts_audio
from generate_video_tools import generate_video_from_image_path, get_video_path_from_video_id
from media_pipeline import assemble_final_video, build_scene_audio_duration_map
from ti_intro_generate_tools import generate_ti_intro
from workspace_paths import ensure_active_run


DEFAULT_INPUTS = {
    "product_name": "电动轮椅",
    "product_category": "电动轮椅 / 出行辅助设备",
    "campaign_goal": "生成一条适合产品演示、客户沟通和短视频传播的完整广告视频",
    "target_market": "中国",
    "target_audience": "行动不便长者家庭、康复机构、经销渠道、医院与养老场景采购方",
    "core_selling_points": "- 电动驱动更省力\n- 座椅与靠背更注重舒适性\n- 日常通行和转向更稳定\n- 便于展示、沟通和成交",
    "use_scenarios": "- 小区通行\n- 医院和康复中心\n- 商场与室内场景\n- 家庭出行和接送",
    "style_preset": "产品演示型",
    "custom_style_notes": "镜头高级但真实，突出操控、舒适与稳定，不要夸张影视感。",
    "style_tone": "真实可信、专业克制、产品演示导向、带一点温度",
    "consistency_anchor": "同一台深色电动轮椅，保持一致的车架、扶手、脚踏、轮胎、操控杆、靠背与坐垫细节，不能在不同镜头里变成别的轮椅。",
    "additional_info": "必须保持同一台轮椅的产品一致性。优先做真实产品演示和使用场景说明，避免夸张医疗承诺。",
    "language": "Chinese",
    "video_orientation": "9:16",
    "desired_scene_count": 5,
    "preferred_runtime_seconds": 28,
    "reference_style": "",
}


def _build_scene_duration_map(video_result: dict[str, dict]) -> dict[int, float]:
    result = {}
    for key, value in video_result.items():
        duration = float(value.get("duration_seconds") or value.get("planned_duration_seconds") or 0)
        if duration > 0:
            result[int(key)] = duration
    return result


def _submit_all_remote_clips(storyboard: list[dict], aspect_ratio: str) -> dict[str, dict]:
    video_result: dict[str, dict] = {}
    last_frame_path = None
    for frame in storyboard:
        result = generate_video_from_image_path(
            frame["saved_path"],
            frame["scene_description"],
            frame["visuals"],
            continuity=frame.get("continuity"),
            last_frame=last_frame_path,
            until_finish=False,
            aspect_ratio=aspect_ratio,
            duration_seconds=frame["duration_seconds"],
            force_local=False,
        )
        video_result[str(frame["scene_number"])] = result
        last_frame_path = frame["saved_path"]
    return video_result


def _resolve_scene_clip(
    frame: dict,
    current: dict,
    aspect_ratio: str,
    last_frame_path: str | None,
    max_retries: int = 3,
) -> dict:
    last_error: Exception | None = None
    attempt = 0
    active = dict(current)

    while attempt < max_retries:
        attempt += 1
        try:
            if active.get("video_path"):
                return active
            if not active.get("video_id"):
                raise RuntimeError(f"Scene {frame['scene_number']} did not return a video task id.")
            refreshed = get_video_path_from_video_id(active["video_id"])
            refreshed["planned_duration_seconds"] = active.get("planned_duration_seconds", frame.get("duration_seconds", 5))
            return refreshed
        except Exception as exc:
            last_error = exc
            active = generate_video_from_image_path(
                frame["saved_path"],
                frame["scene_description"],
                frame["visuals"],
                continuity=frame.get("continuity"),
                last_frame=last_frame_path,
                until_finish=True,
                aspect_ratio=aspect_ratio,
                duration_seconds=frame["duration_seconds"],
                force_local=False,
            )
            if active.get("video_path"):
                return active

    raise RuntimeError(f"Scene {frame['scene_number']} failed after {max_retries} attempts: {last_error}")


def _wait_for_all_remote_clips(
    storyboard: list[dict],
    video_result: dict[str, dict],
    aspect_ratio: str,
) -> dict[str, dict]:
    resolved: dict[str, dict] = {}
    last_frame_path = None

    for frame in storyboard:
        key = str(frame["scene_number"])
        current = dict(video_result.get(key, {}))
        refreshed = _resolve_scene_clip(frame, current, aspect_ratio, last_frame_path)
        resolved[key] = refreshed
        last_frame_path = refreshed.get("last_frame_path") or last_frame_path

    return resolved


def main() -> None:
    started_at = time.time()
    scene_limit = int(os.getenv("DEMO_SCENE_LIMIT", "0") or 0)

    script, _ = generate_scripts(DEFAULT_INPUTS)
    if scene_limit > 0:
        script["scenes"]["scenes"] = script["scenes"]["scenes"][:scene_limit]

    storyboard = generate_storyboard(script, aspect_ratio=DEFAULT_INPUTS["video_orientation"])
    video_result = _submit_all_remote_clips(storyboard, DEFAULT_INPUTS["video_orientation"])
    video_result = _wait_for_all_remote_clips(storyboard, video_result, DEFAULT_INPUTS["video_orientation"])

    audio_url, file_path, duration = generate_tts_audio(script)
    if not file_path:
        raise RuntimeError("TTS generation failed.")

    scene_duration_map = build_scene_audio_duration_map(
        script,
        duration_seconds=duration,
        scene_duration_map=_build_scene_duration_map(video_result),
    )
    srt_url, srt_path = generate_srt_asset_from_audio(
        audio_url,
        script=script,
        duration_seconds=duration,
        scene_duration_map=scene_duration_map,
    )
    ti_intro, _ = generate_ti_intro(script)

    final_video = assemble_final_video(
        [video_result[key]["video_path"] for key in sorted(video_result.keys(), key=int)],
        audio_path=file_path,
        srt_path=srt_path,
        filename="song_wheelchair_formal_demo.mp4",
        scene_duration_map=scene_duration_map,
    )

    report = {
        "elapsed_seconds": round(time.time() - started_at, 2),
        "scene_count": len(storyboard),
        "script_main_theme": script["scenes"]["main_theme"],
        "storyboard": storyboard,
        "video_result": video_result,
        "audio_url": audio_url,
        "audio_path": file_path,
        "audio_duration_seconds": duration,
        "scene_duration_map": scene_duration_map,
        "srt_url": srt_url,
        "srt_path": srt_path,
        "metadata": ti_intro,
        "final_video": final_video,
    }
    report_path = ensure_active_run().exports / "song_wheelchair_formal_demo_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
