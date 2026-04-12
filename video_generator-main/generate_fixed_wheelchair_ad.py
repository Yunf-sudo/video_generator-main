from __future__ import annotations

import json
import time
from pathlib import Path

from asr import generate_srt_asset_from_audio
from generate_scenes_pics_tools import generate_storyboard
from generate_tts_audio import generate_tts_audio
from generate_video_tools import generate_video_from_image_path
from media_pipeline import assemble_final_video, build_scene_audio_duration_map


def build_manual_script() -> dict:
    params = {
        "product_name": "Song electric wheelchair",
        "product_category": "electric wheelchair / mobility device",
        "campaign_goal": (
            "Create a vertical short-form product ad that feels like a real commercial shoot, "
            "with smooth continuity, believable motion, and conversion-oriented pacing."
        ),
        "target_market": "China",
        "target_audience": "buyers, family caregivers, rehab centers, distributors",
        "core_selling_points": (
            "- effortless electric control\n"
            "- stable turning and smooth passing on daily routes\n"
            "- comfortable seating for short everyday trips"
        ),
        "use_scenarios": (
            "- office or residential lobby\n"
            "- corridor ramp and hallway turn\n"
            "- outdoor walkway right outside the building"
        ),
        "style_preset": "product demo",
        "custom_style_notes": (
            "Real short-form ad look. Vertical mobile composition. Same rider, same outfit, same wheelchair, "
            "same route progression. No elderly default casting. No medical stereotype."
        ),
        "style_tone": "realistic, premium, restrained, product-forward",
        "consistency_anchor": (
            "Exactly one dark powered Song wheelchair with the same frame geometry, powered rear wheel design, "
            "joystick, armrests, seat, and footplate in every scene."
        ),
        "additional_info": (
            "Same rider across all scenes: a confident 42-year-old adult man, short black hair, navy overshirt, "
            "white T-shirt, khaki chinos, white sneakers. Not elderly. Not frail. Not a patient."
        ),
        "language": "Chinese",
        "video_orientation": "9:16",
        "desired_scene_count": 3,
        "preferred_runtime_seconds": 15,
        "reference_style": "",
    }

    return {
        "id": f"fixed-{int(time.time())}",
        "version": 1,
        "meta": params,
        "history": [],
        "scenes": {
            "main_theme": "Song electric wheelchair for smooth everyday movement",
            "scenes": [
                {
                    "scene_number": 1,
                    "theme": "Lobby exit",
                    "duration_seconds": 5,
                    "scene_description": (
                        "A confident 42-year-old adult man with short black hair, navy overshirt, white T-shirt, "
                        "khaki chinos, and white sneakers sits in the same dark powered Song wheelchair inside a bright "
                        "modern building lobby. The camera starts at a stable front three-quarter angle and gently tracks "
                        "with him as he smoothly exits the lobby toward the corridor. Real-world commercial lighting, "
                        "clean practical environment, no elderly styling, no medical vibe."
                    ),
                    "visuals": {
                        "camera_movement": (
                            "stable front three-quarter tracking shot, chest-height, calm forward motion, no sudden whip"
                        ),
                        "lighting": "bright realistic daytime lobby light with soft window spill",
                        "composition_and_set_dressing": (
                            "vertical composition, wheelchair hero in the foreground, lobby doors and corridor entrance "
                            "clearly visible, practical modern materials"
                        ),
                        "transition_anchor": (
                            "end with the rider moving screen-right toward the corridor so the next shot can continue the route"
                        ),
                    },
                    "audio": {
                        "voice_over": "\u4ece\u8fdb\u95e8\u5230\u51fa\u53d1\uff0c\u8f7b\u8f7b\u4e00\u63a8\u5c31\u66f4\u7701\u529b\u3002",
                        "text": "\u4ece\u8fdb\u95e8\u5230\u51fa\u53d1\uff0c\u8f7b\u8f7b\u4e00\u63a8\u5c31\u66f4\u7701\u529b\u3002",
                        "music": "clean modern commercial music",
                        "sfx": "soft wheel roll, subtle room tone",
                    },
                    "key_message": "easy everyday start",
                },
                {
                    "scene_number": 2,
                    "theme": "Ramp and turn",
                    "duration_seconds": 5,
                    "scene_description": (
                        "Continue with the same rider, same outfit, same dark powered Song wheelchair, and the same route "
                        "just outside the lobby. He moves along a corridor ramp and takes a smooth controlled turn without "
                        "changing speed. Keep screen direction consistent with the previous shot. Show the powered wheel, "
                        "joystick, footplate, and stable chassis clearly. The environment should feel like the same building, "
                        "not a new unrelated location."
                    ),
                    "visuals": {
                        "camera_movement": (
                            "side-follow shot that gently pushes closer during the turn, same motion direction as scene one"
                        ),
                        "lighting": "same daytime lighting family with believable indoor-outdoor transition",
                        "composition_and_set_dressing": (
                            "vertical mid shot to near-detail move, same rider and wardrobe, same building corridor materials"
                        ),
                        "transition_anchor": (
                            "open with the same route momentum from scene one and finish the turn aimed toward the outdoor exit"
                        ),
                    },
                    "audio": {
                        "voice_over": "\u9047\u5230\u5761\u9053\u548c\u8f6c\u5f2f\uff0c\u8f66\u8eab\u4f9d\u7136\u7a33\uff0c\u64cd\u63a7\u66f4\u4ece\u5bb9\u3002",
                        "text": "\u9047\u5230\u5761\u9053\u548c\u8f6c\u5f2f\uff0c\u8f66\u8eab\u4f9d\u7136\u7a33\uff0c\u64cd\u63a7\u66f4\u4ece\u5bb9\u3002",
                        "music": "same clean modern commercial music",
                        "sfx": "subtle wheel and interior ambience",
                    },
                    "key_message": "stable controlled movement",
                },
                {
                    "scene_number": 3,
                    "theme": "Outdoor finish",
                    "duration_seconds": 5,
                    "scene_description": (
                        "The same rider exits to the outdoor walkway right outside the same building and slows to a confident "
                        "hero stop. Keep the same dark powered Song wheelchair, the same wardrobe, and the same rider identity. "
                        "Use a polished but realistic ending angle that shows comfort and product presence without feeling like "
                        "a different commercial. No elderly casting, no hospital cues, no wheelchair redesign."
                    ),
                    "visuals": {
                        "camera_movement": (
                            "follow-through into a gentle settle at a front three-quarter hero angle, smooth commercial finish"
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
                        "voice_over": "\u5750\u611f\u8212\u9002\uff0c\u65e5\u5e38\u77ed\u9014\u51fa\u884c\u4e5f\u80fd\u66f4\u8f7b\u677e\u3002",
                        "text": "\u5750\u611f\u8212\u9002\uff0c\u65e5\u5e38\u77ed\u9014\u51fa\u884c\u4e5f\u80fd\u66f4\u8f7b\u677e\u3002",
                        "music": "warm reassuring commercial ending music",
                        "sfx": "soft exterior ambience and gentle stop",
                    },
                    "key_message": "comfortable everyday confidence",
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
    script = build_manual_script()
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
        filename=f"song_wheelchair_fixed_vertical_{stamp}.mp4",
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
    report_path = Path("exports") / f"song_wheelchair_fixed_vertical_{stamp}_report.json"
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
