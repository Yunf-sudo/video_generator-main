from __future__ import annotations

import _bootstrap  # noqa: F401
import json
import time
from pathlib import Path

from asr import generate_srt_asset_from_audio
from generate_scenes_pics_tools import generate_storyboard
from generate_tts_audio import generate_tts_audio
from generate_video_tools import generate_video_from_image_path
from media_pipeline import assemble_final_video, build_scene_audio_duration_map
from workspace_paths import ensure_active_run


def build_outdoor_promo_script() -> dict:
    params = {
        "product_name": "Song electric wheelchair",
        "product_category": "electric wheelchair / mobility device",
        "campaign_goal": (
            "Create a polished vertical brand-promo film with English narration and English subtitles, "
            "showing companionship, outdoor lifestyle, and confident movement across varied real-world terrain."
        ),
        "target_market": "Global",
        "target_audience": "elderly families, active seniors, caregivers, rehab centers, distributors",
        "core_selling_points": (
            "- smooth electric control\n"
            "- stable movement across varied daily terrain\n"
            "- comfortable outdoor mobility with family companionship\n"
            "- confident everyday lifestyle positioning"
        ),
        "use_scenarios": (
            "- residential outdoor entry path\n"
            "- curb ramp and textured paving\n"
            "- park trail with family jogging nearby\n"
            "- lakeside boardwalk and promenade finish"
        ),
        "style_preset": "brand promo",
        "custom_style_notes": (
            "Premium outdoor product promo. Vertical mobile composition. Same elderly rider, same family companion, "
            "same wheelchair, same route progression. Emotional but realistic. Natural transitions. English narration. "
            "English subtitles. Show the wheelchair handling different terrain types smoothly."
        ),
        "style_tone": "warm, cinematic, premium, reassuring, lifestyle-oriented",
        "consistency_anchor": (
            "Exactly one dark powered Song wheelchair with the same frame geometry, powered rear wheel design, joystick, "
            "armrests, seat, and footplate in every scene."
        ),
        "additional_info": (
            "Keep the same rider and companion across all scenes. Rider: a dignified 70-year-old East Asian man with "
            "silver-gray hair, light blue shirt, navy cardigan, dark trousers, black walking shoes. Companion: his adult "
            "daughter, about 38, East Asian, dark ponytail, cream running jacket, black leggings, white running shoes. "
            "They should look like the same two people in every scene. The daughter may jog beside him in some shots. "
            "No hospital vibe. No random identity swap. No wheelchair type swap."
        ),
        "language": "English",
        "video_orientation": "9:16",
        "desired_scene_count": 4,
        "preferred_runtime_seconds": 22,
        "reference_style": "",
    }

    return {
        "id": f"outdoor-promo-{int(time.time())}",
        "version": 1,
        "meta": params,
        "history": [],
        "scenes": {
            "main_theme": "Outdoor freedom with family by your side",
            "scenes": [
                {
                    "scene_number": 1,
                    "theme": "Start together",
                    "duration_seconds": 5,
                    "scene_description": (
                        "A dignified 70-year-old East Asian man with silver-gray hair rides the same dark powered Song "
                        "wheelchair along the smooth outdoor entry path just outside a modern residential building. He wears "
                        "a light blue shirt, navy cardigan, dark trousers, and black walking shoes. Beside him, his adult "
                        "daughter in a cream running jacket, black leggings, and white running shoes jogs lightly and smiles "
                        "at him. The camera tracks from a front three-quarter angle in a polished promo-film style. The mood "
                        "is warm, active, and companionable, with natural outdoor light and realistic motion."
                    ),
                    "visuals": {
                        "camera_movement": (
                            "stable front three-quarter tracking shot, gentle forward glide, polished promo-film pacing"
                        ),
                        "lighting": "soft bright morning sunlight with realistic outdoor contrast",
                        "composition_and_set_dressing": (
                            "vertical composition, rider and wheelchair hero in the foreground, daughter jogging beside him, "
                            "modern residential facade and greenery in the background"
                        ),
                        "transition_anchor": (
                            "end with both moving screen-right toward a curb-ramp connection so the next shot continues the same outing"
                        ),
                    },
                    "audio": {
                        "voice_over": "Every ride begins with comfort, confidence, and someone by your side.",
                        "text": "Every ride begins with comfort, confidence, and someone by your side.",
                        "music": "warm modern brand-film music",
                        "sfx": "soft wheel roll, light footsteps, outdoor ambience",
                    },
                    "key_message": "companionship from the first move",
                },
                {
                    "scene_number": 2,
                    "theme": "Real terrain confidence",
                    "duration_seconds": 5,
                    "scene_description": (
                        "Continue with the same elderly rider, the same daughter, and the same dark powered Song wheelchair. "
                        "They move from the smooth path across a curb ramp and over textured tactile paving into a brick plaza. "
                        "The daughter keeps pace just off his shoulder, still lightly jogging. Show the same route logic and "
                        "screen direction as scene one. Emphasize stable wheel movement, controlled turning, and the wheelchair "
                        "handling the terrain change naturally."
                    ),
                    "visuals": {
                        "camera_movement": (
                            "side-follow shot with a subtle push-in as the chair crosses the ramp and textured paving"
                        ),
                        "lighting": "same natural daylight family, slightly brighter open-air plaza feel",
                        "composition_and_set_dressing": (
                            "vertical mid shot to near-detail move, clear curb ramp, tactile paving, brick ground texture, "
                            "same rider and daughter wardrobe continuity"
                        ),
                        "transition_anchor": (
                            "finish the turn into the plaza while still moving toward the park path, preserving route continuity"
                        ),
                    },
                    "audio": {
                        "voice_over": "From curb ramps to textured paths, stable control keeps every move easy.",
                        "text": "From curb ramps to textured paths, stable control keeps every move easy.",
                        "music": "same warm modern brand-film music with slightly more momentum",
                        "sfx": "wheel contact over paving, subtle footsteps, plaza ambience",
                    },
                    "key_message": "confidence across real terrain",
                },
                {
                    "scene_number": 3,
                    "theme": "Active moments outdoors",
                    "duration_seconds": 6,
                    "scene_description": (
                        "The same rider and daughter continue into a green park path with compact gravel and a gentle incline. "
                        "The daughter now runs a little more freely beside him, matching his pace and glancing toward him with "
                        "encouragement. The same dark powered Song wheelchair moves smoothly and steadily up the slight incline. "
                        "Keep the same rider identity, same wardrobe, and same outing progression. This should feel like a premium "
                        "lifestyle promo, not a medical ad."
                    ),
                    "visuals": {
                        "camera_movement": (
                            "low side tracking shot that rises slightly as they climb the gentle incline, smooth and natural"
                        ),
                        "lighting": "bright park daylight with soft foliage highlights",
                        "composition_and_set_dressing": (
                            "vertical composition showing compact gravel path, trees, light breeze, daughter jogging naturally nearby"
                        ),
                        "transition_anchor": (
                            "end with them cresting the incline and moving toward a wooden boardwalk entrance"
                        ),
                    },
                    "audio": {
                        "voice_over": "Outdoors feels easier when smooth power meets steady support from family.",
                        "text": "Outdoors feels easier when smooth power meets steady support from family.",
                        "music": "uplifting premium lifestyle music",
                        "sfx": "soft gravel wheel sound, footsteps, light breeze, park ambience",
                    },
                    "key_message": "mobility that keeps life moving",
                },
                {
                    "scene_number": 4,
                    "theme": "Freedom to keep going",
                    "duration_seconds": 6,
                    "scene_description": (
                        "The same elderly rider and the same daughter arrive on a lakeside wooden boardwalk that connects into a "
                        "smooth promenade. He rides calmly while she slows from a jog to an easy supportive run beside him. The "
                        "camera settles into a polished front three-quarter hero angle as they continue together. Show the same dark "
                        "powered Song wheelchair, the same rider, the same daughter, and the same outing flow. Finish with a warm, "
                        "premium promotional-film feeling of freedom, companionship, and confident everyday mobility."
                    ),
                    "visuals": {
                        "camera_movement": (
                            "follow-through into a gentle settle at a front three-quarter hero angle, elegant promo-film finish"
                        ),
                        "lighting": "clean late-morning lakeside light with soft reflections",
                        "composition_and_set_dressing": (
                            "vertical hero framing on the wooden boardwalk and promenade, water and trees softly behind, "
                            "wheelchair dominant, daughter visible nearby"
                        ),
                        "transition_anchor": (
                            "close on a smooth forward glide and confident smile as the final brand moment"
                        ),
                    },
                    "audio": {
                        "voice_over": "With comfort, control, and connection, every day opens up a little more.",
                        "text": "With comfort, control, and connection, every day opens up a little more.",
                        "music": "warm reassuring premium brand ending",
                        "sfx": "soft boardwalk wheel roll, footsteps, breeze, distant water ambience",
                    },
                    "key_message": "freedom with family",
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
    script = build_outdoor_promo_script()
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
        filename=f"song_wheelchair_outdoor_promo_{stamp}.mp4",
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
    report_path = ensure_active_run().exports / f"song_wheelchair_outdoor_promo_{stamp}_report.json"
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
