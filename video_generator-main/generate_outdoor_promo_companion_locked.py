from __future__ import annotations

import json
import time
from pathlib import Path

from asr import generate_srt_asset_from_audio
from generate_image_from_prompt import generate_image_from_prompt
from generate_tts_audio import generate_tts_audio
from generate_video_tools import generate_video_from_image_path
from media_pipeline import assemble_final_video, build_scene_audio_duration_map


BASE_REFERENCE_IMAGE = "pics\\generated_4085aca1.png"


SCENES = [
    {
        "scene_number": 1,
        "duration_seconds": 5,
        "saved_path": BASE_REFERENCE_IMAGE,
        "scene_description": (
            "The same 70-year-old East Asian man with silver-gray hair rides the same dark powered Song wheelchair "
            "along a clean residential outdoor path. His adult daughter in a cream running jacket jogs beside him. "
            "This is the opening shot of a premium outdoor promo film."
        ),
        "visuals": {
            "camera_movement": "stable front three-quarter tracking shot with gentle forward glide",
            "lighting": "soft bright morning outdoor light",
            "composition_and_set_dressing": (
                "vertical composition, rider and wheelchair dominant, adult daughter jogging beside him, modern homes and greenery behind"
            ),
            "transition_anchor": "end moving toward a curb-ramp transition while keeping the same route direction",
        },
        "key_message": "companionship at the start of the ride",
    },
    {
        "scene_number": 2,
        "duration_seconds": 5,
        "edit_prompt": (
            "Transform the supplied image into the next scene of the same ad while keeping the exact same elderly East Asian man, "
            "the same adult daughter, the same wardrobe, the same dark powered Song wheelchair, and the same product details. "
            "Change only the location and route progression: show them crossing a curb ramp and moving over yellow tactile paving "
            "into a brick plaza. Keep the daughter clearly adult, still jogging beside him. Maintain the same general camera angle, "
            "same warm promo-film feel, and natural continuity from the previous scene. No minors. No identity changes."
        ),
        "scene_description": (
            "The same elderly rider and the same adult daughter continue into a curb-ramp crossing with yellow tactile paving and brick ground. "
            "The same dark powered Song wheelchair moves smoothly across the terrain change while the daughter keeps pace beside him."
        ),
        "visuals": {
            "camera_movement": "side-follow shot with a subtle push-in while crossing the curb ramp",
            "lighting": "same natural daylight with a slightly brighter open plaza feel",
            "composition_and_set_dressing": (
                "vertical composition, curb ramp and tactile paving clearly visible, daughter remains clearly adult and close to the rider"
            ),
            "transition_anchor": "finish the terrain crossing and continue toward a park path",
        },
        "key_message": "stable control over daily terrain",
    },
    {
        "scene_number": 3,
        "duration_seconds": 5,
        "edit_prompt": (
            "Transform the supplied image into the next scene of the same ad while keeping the exact same elderly East Asian man, "
            "the same adult daughter, the same wardrobe, the same dark powered Song wheelchair, and the same facial identity. "
            "Move the setting to a tree-lined park path with compact gravel and a gentle incline. The daughter is still clearly adult "
            "and jogging beside him. The wheelchair should look stable on the gravel incline. Keep a premium outdoor promo-film feel. "
            "No minors. No identity changes. No wheelchair changes."
        ),
        "scene_description": (
            "The same elderly rider and the same adult daughter move along a tree-lined park path with compact gravel and a gentle incline. "
            "The same dark powered Song wheelchair remains stable as she jogs beside him."
        ),
        "visuals": {
            "camera_movement": "low side tracking shot that rises slightly with the incline",
            "lighting": "bright natural park daylight with soft foliage highlights",
            "composition_and_set_dressing": (
                "vertical composition showing gravel texture, gentle incline, trees, and the adult daughter jogging supportively nearby"
            ),
            "transition_anchor": "crest the incline and continue toward a lakeside boardwalk",
        },
        "key_message": "smooth movement outdoors",
    },
    {
        "scene_number": 4,
        "duration_seconds": 6,
        "edit_prompt": (
            "Transform the supplied image into the final scene of the same ad while keeping the exact same elderly East Asian man, "
            "the same adult daughter, the same wardrobe, the same dark powered Song wheelchair, and the same overall identity. "
            "Move the setting to a lakeside wooden boardwalk connected to a smooth promenade. Keep the wheelchair fully visible and dominant. "
            "The daughter remains clearly adult and runs beside him with a warm smile. Make this a premium promotional closing shot, but keep "
            "the same people and same wheelchair. No minors. No new people. No hero close-up that crops out the chair."
        ),
        "scene_description": (
            "The same elderly rider and the same adult daughter continue onto a lakeside wooden boardwalk and smooth promenade. "
            "The same dark powered Song wheelchair stays fully visible in a polished closing shot."
        ),
        "visuals": {
            "camera_movement": "front three-quarter tracking shot settling into a polished hero glide",
            "lighting": "clean lakeside daylight with soft reflections",
            "composition_and_set_dressing": (
                "vertical hero framing on the boardwalk with water and trees behind, wheelchair fully visible, adult daughter running beside him"
            ),
            "transition_anchor": "close on a smooth forward glide and warm shared smile",
        },
        "key_message": "freedom with family support",
    },
]


def build_storyboard() -> list[dict]:
    base_path = Path(BASE_REFERENCE_IMAGE)
    if not base_path.exists():
        raise FileNotFoundError(f"Base reference image not found: {BASE_REFERENCE_IMAGE}")

    storyboard = []
    reference_paths = [str(base_path)]
    system_prompt = (
        "Edit the supplied image into the next storyboard frame of the same commercial. "
        "Keep the same elderly East Asian man, the same clearly adult daughter, the same wardrobe, "
        "the same dark powered Song wheelchair, and the same premium realistic promo-film look. "
        "No minors. No identity swaps. No wheelchair redesign."
    )

    for scene in SCENES:
        scene_data = dict(scene)
        if scene_data.get("saved_path"):
            saved_path = scene_data["saved_path"]
        else:
            saved_path = generate_image_from_prompt(
                prompt=scene_data["edit_prompt"],
                system_prompt=system_prompt,
                reference_pic_paths=reference_paths,
                aspect_ratio="9:16",
            )
        scene_data["saved_path"] = saved_path
        scene_data["continuity"] = {
            "same_rider_default": (
                "Use the same elderly East Asian man and the same clearly adult daughter in every scene. "
                "Keep wardrobe and wheelchair identical."
            )
        }
        storyboard.append(scene_data)
        reference_paths = [reference_paths[0], saved_path] if len(reference_paths) == 1 else [reference_paths[1], saved_path]

    return storyboard


def build_script_from_storyboard(storyboard: list[dict]) -> dict:
    return {
        "id": f"outdoor-promo-locked-{int(time.time())}",
        "version": 1,
        "meta": {
            "language": "English",
            "video_orientation": "9:16",
            "style_tone": "premium outdoor brand promo with companionship",
        },
        "history": [],
        "scenes": {
            "main_theme": "Outdoor freedom with family by your side",
            "scenes": [
                {
                    "scene_number": 1,
                    "theme": "Start together",
                    "duration_seconds": 5,
                    "scene_description": storyboard[0]["scene_description"],
                    "visuals": storyboard[0]["visuals"],
                    "audio": {
                        "voice_over": "Every ride begins with comfort, confidence, and someone by your side.",
                        "text": "Every ride begins with comfort, confidence, and someone by your side.",
                        "music": "warm modern brand-film music",
                        "sfx": "soft wheel roll, light footsteps, outdoor ambience",
                    },
                    "key_message": storyboard[0]["key_message"],
                },
                {
                    "scene_number": 2,
                    "theme": "Real terrain confidence",
                    "duration_seconds": 5,
                    "scene_description": storyboard[1]["scene_description"],
                    "visuals": storyboard[1]["visuals"],
                    "audio": {
                        "voice_over": "From curb ramps to textured paths, stable control keeps every move easy.",
                        "text": "From curb ramps to textured paths, stable control keeps every move easy.",
                        "music": "warm modern brand-film music",
                        "sfx": "wheel contact over paving, subtle footsteps, plaza ambience",
                    },
                    "key_message": storyboard[1]["key_message"],
                },
                {
                    "scene_number": 3,
                    "theme": "Active moments outdoors",
                    "duration_seconds": 5,
                    "scene_description": storyboard[2]["scene_description"],
                    "visuals": storyboard[2]["visuals"],
                    "audio": {
                        "voice_over": "Outdoors feels easier when smooth power meets steady support from family.",
                        "text": "Outdoors feels easier when smooth power meets steady support from family.",
                        "music": "uplifting premium lifestyle music",
                        "sfx": "soft gravel wheel sound, footsteps, light breeze, park ambience",
                    },
                    "key_message": storyboard[2]["key_message"],
                },
                {
                    "scene_number": 4,
                    "theme": "Freedom to keep going",
                    "duration_seconds": 6,
                    "scene_description": storyboard[3]["scene_description"],
                    "visuals": storyboard[3]["visuals"],
                    "audio": {
                        "voice_over": "With comfort, control, and connection, every day opens up a little more.",
                        "text": "With comfort, control, and connection, every day opens up a little more.",
                        "music": "warm reassuring premium brand ending",
                        "sfx": "soft boardwalk wheel roll, footsteps, breeze, distant water ambience",
                    },
                    "key_message": storyboard[3]["key_message"],
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
    started = time.time()

    print("[1/5] Building locked storyboard...", flush=True)
    storyboard = build_storyboard()
    script = build_script_from_storyboard(storyboard)
    print(json.dumps({"storyboard_frames": len(storyboard)}, ensure_ascii=False), flush=True)

    print("[2/5] Generating remote veo clips...", flush=True)
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
        filename=f"song_wheelchair_outdoor_promo_locked_{stamp}.mp4",
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
    report_path = Path("exports") / f"song_wheelchair_outdoor_promo_locked_{stamp}_report.json"
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
