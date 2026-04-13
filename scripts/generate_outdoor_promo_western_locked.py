from __future__ import annotations

import _bootstrap  # noqa: F401
import json
import os
import time
from pathlib import Path

os.environ.setdefault("JIANYI_ENDPOINT", "http://jeniya.cn/v1/chat/completions")

from asr import generate_srt_asset_from_audio
from generate_image_from_prompt import generate_image_from_prompt
from generate_tts_audio import generate_tts_audio
from generate_video_tools import generate_video_from_image_path
from media_pipeline import assemble_final_video, build_scene_audio_duration_map
from product_reference_images import (
    get_product_reference_images,
    get_product_reference_signature,
    merge_reference_images,
)
from workspace_paths import ensure_active_run


BASE_SYSTEM_PROMPT = (
    "Create a realistic live-action premium storyboard frame for the same commercial. "
    "The rider must be the same Western elderly man in every scene: about 70 years old, Caucasian, silver-gray hair, "
    "light blue shirt, navy cardigan, dark navy trousers, black walking shoes. "
    "If a family member appears, it must be the same clearly adult Western woman, about 38 years old, brunette ponytail, "
    "cream running jacket, black leggings, white running shoes. "
    "Keep the same dark powered Song wheelchair in every scene. "
    f"{get_product_reference_signature()} "
    "No minors. No ethnicity swap. No wardrobe swap. No manual wheelchair substitution. "
    "Keep a premium outdoor promo-film look."
)
STORYBOARD_PROBE_PATH = ensure_active_run().exports / "outdoor_promo_western_storyboard_probe.json"


def generate_base_reference_image() -> str:
    product_reference_paths = get_product_reference_images()
    prompt = (
        "Create the opening hero frame of a vertical 9:16 premium outdoor promo film. "
        "Show the same Western elderly man, about 70 years old, Caucasian, silver-gray hair, wearing a light blue shirt, "
        "navy cardigan, dark navy trousers, and black walking shoes, seated in the same dark powered Song wheelchair. "
        "Beside him is the same clearly adult Western woman, about 38 years old, brunette ponytail, wearing a cream running jacket, "
        "black leggings, and white running shoes, jogging supportively and smiling at him. "
        "They are on a clean residential outdoor path with modern homes and greenery behind them. "
        "The wheelchair must be fully visible, premium, realistic, and consistent. "
        "The frame should feel warm, companionable, and physically shootable."
    )
    return generate_image_from_prompt(
        prompt=prompt,
        system_prompt=BASE_SYSTEM_PROMPT,
        reference_pic_paths=product_reference_paths or None,
        aspect_ratio="9:16",
    )


def scene_specs(base_reference_image: str) -> list[dict]:
    return [
        {
            "scene_number": 1,
            "duration_seconds": 5,
            "saved_path": base_reference_image,
            "scene_description": (
                "The same Western elderly man in the same dark powered Song wheelchair rides along a clean residential outdoor path. "
                "His adult Western daughter jogs beside him. This is the opening shot of a premium outdoor promo film."
            ),
            "visuals": {
                "camera_movement": "stable front three-quarter tracking shot with gentle forward glide",
                "lighting": "soft bright morning outdoor light",
                "composition_and_set_dressing": (
                    "vertical composition, rider and wheelchair dominant, clearly adult daughter jogging beside him, modern homes and greenery behind"
                ),
                "transition_anchor": "end moving toward a curb-ramp transition while keeping the same route direction",
            },
            "key_message": "companionship at the start of the ride",
        },
        {
            "scene_number": 2,
            "duration_seconds": 5,
            "edit_prompt": (
                "Transform the supplied image into the next scene of the same ad. Keep the exact same Western elderly man, the same clearly adult "
                "Western daughter, the same wardrobe, the same dark powered Song wheelchair, and the same facial identity. "
                "Change only the route progression: show them crossing a curb ramp and moving over yellow tactile paving into a brick plaza. "
                "The daughter stays adult and supportive beside him. Preserve the same premium outdoor promo-film feel."
            ),
            "scene_description": (
                "The same Western elderly rider and the same adult Western daughter continue into a curb-ramp crossing with yellow tactile paving and brick ground. "
                "The same dark powered Song wheelchair moves smoothly across the terrain change while she keeps pace beside him."
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
                "Transform the supplied image into the next scene of the same ad. Keep the exact same Western elderly man, the same clearly adult "
                "Western daughter, the same wardrobe, the same dark powered Song wheelchair, and the same facial identity. "
                "Move the setting to a tree-lined park path with compact gravel and a gentle incline. The daughter is still clearly adult and jogging beside him. "
                "The wheelchair should look stable on the gravel incline. Preserve the same premium outdoor promo-film feel."
            ),
            "scene_description": (
                "The same Western elderly rider and the same adult Western daughter move along a tree-lined park path with compact gravel and a gentle incline. "
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
                "Transform the supplied image into the final scene of the same ad. Keep the exact same Western elderly man, the same clearly adult Western daughter, "
                "the same wardrobe, the same dark powered Song wheelchair, and the same facial identity. "
                "Move the setting to a lakeside wooden boardwalk connected to a smooth promenade. Keep the wheelchair fully visible and dominant. "
                "The daughter remains clearly adult and keeps pace beside him with a warm smile. Make this a premium promotional closing shot with the same people and same wheelchair."
            ),
            "scene_description": (
                "The same Western elderly rider and the same adult Western daughter continue onto a lakeside wooden boardwalk and smooth promenade. "
                "The same dark powered Song wheelchair stays fully visible in a polished closing shot."
            ),
            "visuals": {
                "camera_movement": "front three-quarter tracking shot settling into a polished hero glide",
                "lighting": "clean lakeside daylight with soft reflections",
                "composition_and_set_dressing": (
                    "vertical hero framing on the boardwalk with water and trees behind, wheelchair fully visible, adult daughter keeping pace beside him"
                ),
                "transition_anchor": "close on a smooth forward glide and warm shared smile",
            },
            "key_message": "freedom with family support",
        },
    ]


def build_storyboard() -> list[dict]:
    base_reference_image = generate_base_reference_image()
    specs = scene_specs(base_reference_image)

    storyboard = []
    product_reference_paths = get_product_reference_images()
    base_reference = str(Path(base_reference_image))
    previous_reference = base_reference

    for spec in specs:
        frame = dict(spec)
        if frame.get("saved_path"):
            saved_path = frame["saved_path"]
        else:
            saved_path = generate_image_from_prompt(
                prompt=frame["edit_prompt"],
                system_prompt=BASE_SYSTEM_PROMPT,
                reference_pic_paths=merge_reference_images(
                    product_reference_paths,
                    [base_reference, previous_reference],
                    limit=6,
                ),
                aspect_ratio="9:16",
            )
        frame["saved_path"] = saved_path
        frame["continuity"] = {
            "same_rider_default": (
                "Use the same Western elderly man and the same clearly adult Western daughter in every scene. "
                "Keep wardrobe and wheelchair identical."
            )
        }
        storyboard.append(frame)
        previous_reference = saved_path

    return storyboard


def load_storyboard(force_refresh: bool = False) -> list[dict]:
    if not force_refresh and STORYBOARD_PROBE_PATH.exists():
        return json.loads(STORYBOARD_PROBE_PATH.read_text(encoding="utf-8"))
    return build_storyboard()


def normalize_storyboard(storyboard: list[dict]) -> list[dict]:
    normalized = []
    for frame in storyboard:
        scene_number = int(frame["scene_number"])
        merged = dict(frame)
        continuity = dict(merged.get("continuity") or {})
        continuity["same_rider_default"] = (
            "Use the same Western elderly man and the same clearly adult Western daughter in every scene. "
            "Keep face, hair, age, ethnicity, wardrobe, posture, and wheelchair identical."
        )
        if scene_number == 4:
            merged["edit_prompt"] = (
                "Transform the supplied image into the final scene of the same ad. Keep the exact same Western elderly man, the same clearly adult "
                "Western daughter, the same wardrobe, the same dark powered Song wheelchair, and the same facial identity. "
                "Move the setting to a lakeside wooden boardwalk connected to a smooth promenade. Keep the wheelchair fully visible and dominant. "
                "The daughter remains clearly adult and keeps pace beside him with a warm smile. Make this a premium promotional closing shot with the same people and same wheelchair."
            )
            merged["scene_description"] = (
                "The same Western elderly rider and the same clearly adult Western daughter continue onto a lakeside wooden boardwalk and smooth promenade. "
                "The same dark powered Song wheelchair stays fully visible in a polished closing shot while she keeps pace beside him."
            )
            visuals = dict(merged.get("visuals") or {})
            visuals["composition_and_set_dressing"] = (
                "vertical hero framing on the boardwalk with water and trees behind, wheelchair fully visible, clearly adult daughter keeping pace beside him"
            )
            merged["visuals"] = visuals
        merged["continuity"] = continuity
        normalized.append(merged)
    return normalized


def build_script_from_storyboard(storyboard: list[dict]) -> dict:
    return {
        "id": f"outdoor-promo-western-{int(time.time())}",
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
    force_refresh = os.getenv("FORCE_REBUILD_STORYBOARD", "0").strip().lower() in {"1", "true", "yes"}

    print("[1/5] Building western-locked storyboard...", flush=True)
    storyboard = normalize_storyboard(load_storyboard(force_refresh=force_refresh))
    STORYBOARD_PROBE_PATH.write_text(json.dumps(storyboard, ensure_ascii=False, indent=2), encoding="utf-8")
    script = build_script_from_storyboard(storyboard)
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
                last_frame_for_scene = last_frame_path
                if scene_number >= 4:
                    last_frame_for_scene = None
                result = generate_video_from_image_path(
                    frame["saved_path"],
                    frame["scene_description"],
                    frame["visuals"],
                    continuity=frame.get("continuity"),
                    last_frame=last_frame_for_scene,
                    until_finish=True,
                    aspect_ratio="9:16",
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
        filename=f"song_wheelchair_outdoor_promo_western_{stamp}.mp4",
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
    report_path = ensure_active_run().exports / f"song_wheelchair_outdoor_promo_western_{stamp}_report.json"
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
