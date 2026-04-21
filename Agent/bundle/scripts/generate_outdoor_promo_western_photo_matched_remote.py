from __future__ import annotations

import _bootstrap  # noqa: F401
import json
import time
from pathlib import Path

from asr import generate_srt_asset_from_audio
from generate_outdoor_promo_western_locked import (
    build_script_from_storyboard,
    normalize_storyboard,
    require_remote,
    scene_specs,
)
from generate_tts_audio import generate_tts_audio
from generate_video_tools import generate_video_from_image_path
from media_pipeline import assemble_final_video, build_scene_audio_duration_map
from workspace_paths import ensure_active_run


PHOTO_MATCHED_STORYBOARD_PATHS = [
    str(_bootstrap.LEGACY_ROOT / "pics" / "generated_bef2bea2.png"),
    str(_bootstrap.LEGACY_ROOT / "pics" / "generated_444a345d.png"),
    str(_bootstrap.LEGACY_ROOT / "pics" / "generated_54b9f629.png"),
    str(_bootstrap.LEGACY_ROOT / "pics" / "generated_603b1589.png"),
]


def build_photo_matched_storyboard() -> list[dict]:
    specs = scene_specs(PHOTO_MATCHED_STORYBOARD_PATHS[0])
    storyboard = []
    for spec, corrected_path in zip(specs, PHOTO_MATCHED_STORYBOARD_PATHS):
        frame = dict(spec)
        frame["saved_path"] = corrected_path
        storyboard.append(frame)
    return normalize_storyboard(storyboard)


def main() -> None:
    started = time.time()

    print("[1/5] Loading photo-matched storyboard...", flush=True)
    storyboard = build_photo_matched_storyboard()
    script = build_script_from_storyboard(storyboard)
    print(json.dumps({"storyboard_frames": len(storyboard)}, ensure_ascii=False), flush=True)

    print("[2/5] Generating strict-reference remote veo clips...", flush=True)
    resolved: dict[str, dict] = {}
    for frame in storyboard:
        scene_number = int(frame["scene_number"])
        last_error = None
        for attempt in range(1, 4):
            try:
                print(
                    json.dumps({"scene": scene_number, "attempt": attempt, "status": "submitting"}, ensure_ascii=False),
                    flush=True,
                )
                result = generate_video_from_image_path(
                    frame["saved_path"],
                    frame["scene_description"],
                    frame["visuals"],
                    continuity=frame.get("continuity"),
                    last_frame=None,
                    until_finish=True,
                    aspect_ratio="9:16",
                    duration_seconds=frame["duration_seconds"],
                    force_local=False,
                    strict_reference_only=True,
                    include_product_reference_images=False,
                )
                require_remote(result, scene_number)
                result["planned_duration_seconds"] = frame["duration_seconds"]
                resolved[str(scene_number)] = result
                print(
                    json.dumps(
                        {
                            "scene": scene_number,
                            "status": "completed",
                            "video_path": result.get("video_path"),
                            "duration_seconds": result.get("duration_seconds"),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                last_error = None
                break
            except Exception as exc:
                last_error = str(exc)
                print(
                    json.dumps(
                        {"scene": scene_number, "attempt": attempt, "status": "retry", "reason": last_error[:500]},
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                time.sleep(min(20, 5 * attempt))
        if last_error is not None:
            raise RuntimeError(f"Scene {scene_number} failed after retries: {last_error}")

    print("[3/5] Generating English TTS and subtitles...", flush=True)
    audio_url, audio_path, audio_duration = generate_tts_audio(script)
    if not audio_path:
        raise RuntimeError("TTS generation failed.")

    scene_duration_map = build_scene_audio_duration_map(
        script,
        duration_seconds=audio_duration,
        scene_duration_map={
            int(key): float(value.get("duration_seconds") or value.get("planned_duration_seconds") or 0)
            for key, value in resolved.items()
        },
    )
    srt_url, srt_path = generate_srt_asset_from_audio(
        audio_url,
        script=script,
        duration_seconds=audio_duration,
        scene_duration_map=scene_duration_map,
    )

    print("[4/5] Assembling final video...", flush=True)
    stamp = time.strftime("%m%d_%H%M%S")
    final_video = assemble_final_video(
        [resolved[key]["video_path"] for key in sorted(resolved.keys(), key=int)],
        audio_path=audio_path,
        srt_path=srt_path,
        filename=f"song_wheelchair_outdoor_promo_western_photo_matched_remote_{stamp}.mp4",
        scene_duration_map=scene_duration_map,
    )

    report = {
        "elapsed_seconds": round(time.time() - started, 2),
        "script": script,
        "storyboard": storyboard,
        "video_result": resolved,
        "audio_url": audio_url,
        "audio_path": audio_path,
        "audio_duration_seconds": audio_duration,
        "scene_duration_map": scene_duration_map,
        "srt_url": srt_url,
        "srt_path": srt_path,
        "final_video": final_video,
    }
    report_path = ensure_active_run().exports / f"song_wheelchair_outdoor_promo_western_photo_matched_remote_{stamp}_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("[5/5] Done", flush=True)
    print(
        json.dumps(
            {
                "final_video": final_video,
                "report_path": str(report_path),
                "elapsed_seconds": report["elapsed_seconds"],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
