from __future__ import annotations

import json
import time
from pathlib import Path

from asr import generate_srt_asset_from_audio
from generate_scenes_pics_tools import generate_storyboard
from generate_tts_audio import generate_tts_audio
from generate_video_tools import generate_video_from_image_path
from media_pipeline import assemble_final_video, build_scene_audio_duration_map


def build_elderly_script() -> dict:
    params = {
        "product_name": "Song electric wheelchair",
        "product_category": "electric wheelchair / mobility device",
        "campaign_goal": (
            "Create a vertical short-form product ad featuring an elderly rider, with realistic continuity, "
            "natural scene transitions, and a strong product-demo feel."
        ),
        "target_market": "China",
        "target_audience": "elderly families, caregivers, rehabilitation centers, distributors",
        "core_selling_points": (
            "- effortless electric control\n"
            "- stable movement through daily routes\n"
            "- comfortable seating for short everyday trips"
        ),
        "use_scenarios": (
            "- residential building lobby\n"
            "- corridor and ramp connection\n"
            "- outdoor walkway just outside the building"
        ),
        "style_preset": "product demo",
        "custom_style_notes": (
            "Real short-form ad look. Vertical mobile composition. Same elderly rider, same outfit, same wheelchair, "
            "same route progression. Natural movement. No random age swap or wheelchair swap."
        ),
        "style_tone": "realistic, warm, trustworthy, product-forward",
        "consistency_anchor": (
            "Exactly one dark powered Song wheelchair with the same frame geometry, powered rear wheel design, "
            "joystick, armrests, seat, and footplate in every scene."
        ),
        "additional_info": (
            "Same rider across all scenes: a calm 68-year-old East Asian man with short silver-gray hair, "
            "light blue shirt, navy cardigan, dark trousers, black walking shoes. He should look like the same "
            "person in every scene. Elderly but energetic, dignified, and independent. Not frail. No hospital styling."
        ),
        "language": "Chinese",
        "video_orientation": "9:16",
        "desired_scene_count": 3,
        "preferred_runtime_seconds": 15,
        "reference_style": "",
    }

    return {
        "id": f"elderly-{int(time.time())}",
        "version": 1,
        "meta": params,
        "history": [],
        "scenes": {
            "main_theme": "Song electric wheelchair for confident senior mobility",
            "scenes": [
                {
                    "scene_number": 1,
                    "theme": "Lobby start",
                    "duration_seconds": 5,
                    "scene_description": (
                        "A dignified 68-year-old East Asian man with short silver-gray hair wears a light blue shirt, "
                        "navy cardigan, dark trousers, and black walking shoes. He sits in the same dark powered Song "
                        "wheelchair inside a bright residential building lobby. The camera begins at a stable front "
                        "three-quarter angle and gently tracks as he smoothly starts forward toward the corridor. "
                        "He is clearly elderly, but independent and energetic, with no hospital or rehab styling."
                    ),
                    "visuals": {
                        "camera_movement": (
                            "stable front three-quarter tracking shot, calm forward motion, no whip, no abrupt framing change"
                        ),
                        "lighting": "bright realistic daytime lobby light with soft window spill",
                        "composition_and_set_dressing": (
                            "vertical composition, wheelchair hero in foreground, clean lobby doors and corridor entry visible"
                        ),
                        "transition_anchor": (
                            "end with the rider continuing screen-right toward the corridor so the next shot can follow naturally"
                        ),
                    },
                    "audio": {
                        "voice_over": "从大厅出发，轻轻操控，日常出行就更省力。",
                        "text": "从大厅出发，轻轻操控，日常出行就更省力。",
                        "music": "warm modern commercial music",
                        "sfx": "soft wheel roll, subtle room tone",
                    },
                    "key_message": "easy senior mobility",
                },
                {
                    "scene_number": 2,
                    "theme": "Stable turn",
                    "duration_seconds": 5,
                    "scene_description": (
                        "Continue with the same elderly East Asian man, the same silver-gray hair, the same outfit, and the "
                        "same dark powered Song wheelchair. He moves along the corridor connection and passes a gentle ramp, "
                        "then makes a smooth controlled turn. Keep the same route and screen direction as scene one. Show stable "
                        "powered movement, clear joystick control, and the same product details without redesign."
                    ),
                    "visuals": {
                        "camera_movement": (
                            "side-follow shot that gently pushes closer during the turn, preserving the same route direction"
                        ),
                        "lighting": "same daytime lighting family with believable indoor transition",
                        "composition_and_set_dressing": (
                            "vertical mid shot to near-detail move, same rider, same outfit, same corridor materials"
                        ),
                        "transition_anchor": (
                            "open with the same route momentum from scene one and finish aimed toward the outdoor exit"
                        ),
                    },
                    "audio": {
                        "voice_over": "遇到坡道和转弯，车身依然稳，老人也能更从容。",
                        "text": "遇到坡道和转弯，车身依然稳，老人也能更从容。",
                        "music": "same warm modern commercial music",
                        "sfx": "subtle wheel and corridor ambience",
                    },
                    "key_message": "stable confident handling",
                },
                {
                    "scene_number": 3,
                    "theme": "Outdoor finish",
                    "duration_seconds": 5,
                    "scene_description": (
                        "The same 68-year-old man exits to the outdoor walkway right outside the same building and slows to a "
                        "confident stop. Keep the same silver-gray hair, same light blue shirt and navy cardigan, same dark "
                        "powered Song wheelchair, and the same rider identity. Use a polished but realistic final angle that "
                        "shows comfort, dignity, and product presence. No identity swap, no age change, no wheelchair type change."
                    ),
                    "visuals": {
                        "camera_movement": (
                            "follow-through into a gentle settle at a front three-quarter hero angle, smooth realistic finish"
                        ),
                        "lighting": "natural daytime exterior light matching the route progression",
                        "composition_and_set_dressing": (
                            "vertical hero framing on the walkway outside the same building, clean background, product dominant"
                        ),
                        "transition_anchor": (
                            "continue the motion from the corridor exit and end on a stable confident stop for the final beat"
                        ),
                    },
                    "audio": {
                        "voice_over": "坐得舒适，老人日常短途出行，也能更轻松。",
                        "text": "坐得舒适，老人日常短途出行，也能更轻松。",
                        "music": "warm reassuring commercial ending music",
                        "sfx": "soft exterior ambience and gentle stop",
                    },
                    "key_message": "comfortable senior everyday use",
                },
            ],
        },
    }


def require_remote(result: dict, scene_number: int) -> None:
    if result.get("generation_mode") != "remote":
        raise RuntimeError(
            f"Scene {scene_number} did not finish as a remote veo clip. Result: {json.dumps(result, ensure_ascii=False)}"
        )


def main() -> None:
    script = build_elderly_script()
    params = script["meta"]
    started = time.time()

    print("[1/5] Generating storyboard...", flush=True)
    storyboard = generate_storyboard(script, aspect_ratio=params["video_orientation"])
    print(json.dumps({"storyboard_frames": len(storyboard)}, ensure_ascii=False), flush=True)

    print("[2/5] Generating remote veo clips...", flush=True)
    resolved: dict[str, dict] = {}
    last_frame_path = None
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
                    last_frame=last_frame_path,
                    until_finish=True,
                    aspect_ratio=params["video_orientation"],
                    duration_seconds=frame["duration_seconds"],
                    force_local=False,
                )
                require_remote(result, scene_number)
                result["planned_duration_seconds"] = frame["duration_seconds"]
                resolved[str(scene_number)] = result
                last_frame_path = result.get("last_frame_path") or last_frame_path
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

    print("[3/5] Generating TTS and subtitles...", flush=True)
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
        filename=f"song_wheelchair_elderly_vertical_{stamp}.mp4",
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
    report_path = Path("exports") / f"song_wheelchair_elderly_vertical_{stamp}_report.json"
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
