from __future__ import annotations

import copy
import json
import logging
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from asr import generate_srt_asset_from_audio
from generate_scenes_pics_tools import generate_storyboard
from generate_tts_audio import build_voiceover_text, generate_tts_audio
from generate_video_tools import build_video_prompt, generate_video_from_image_path
from media_pipeline import assemble_final_video, build_scene_audio_duration_map
from product_reference_images import (
    get_product_reference_images,
    get_product_reference_signature,
    get_product_visual_structure,
)
from ti_intro_generate_tools import generate_ti_intro
from workspace_paths import RunPaths, start_new_run, write_run_json


DEFAULT_CONFIG_PATH = Path("configs") / "anywell_freedom_campaign.json"
DEFAULT_PROMPT_PATH = Path("prompts") / "anywell_freedom_campaign.md"
DEFAULT_OUTPUT_ROOT = Path("generated") / "deliverables" / "anywell_campaign"
DEFAULT_LOG_PATH = Path("logs") / "anywell_campaign_run.log"
DEFAULT_SUMMARY_PATH = Path("reports") / "anywell_campaign_summary.md"


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _safe_copy(src: str | Path | None, dst: Path) -> str:
    if not src:
        return ""
    source_path = Path(src)
    if not source_path.exists():
        return ""
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, dst)
    return str(dst)


def load_campaign_config(config_path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    return json.loads(Path(config_path).read_text(encoding="utf-8"))


def load_creative_guardrails(prompt_path: str | Path = DEFAULT_PROMPT_PATH) -> str:
    path = Path(prompt_path)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def build_anywell_script(campaign: dict[str, Any], concept: dict[str, Any], creative_guardrails: str) -> dict[str, Any]:
    scenes = []
    for shot in concept.get("shots", []):
        subtitle_text = shot.get("voiceover_en", "").strip()
        subtitle_zh = shot.get("subtitle_zh", "").strip()

        scenes.append(
            {
                "scene_number": int(shot["scene_number"]),
                "theme": shot["theme"],
                "duration_seconds": int(shot["duration_seconds"]),
                "scene_description": shot["scene_description"],
                "visuals": {
                    "camera_movement": shot["camera_movement"],
                    "lighting": shot["lighting"],
                    "composition_and_set_dressing": shot["composition_and_set_dressing"],
                    "transition_anchor": shot["transition_anchor"],
                },
                "audio": {
                    "voice_over": shot["voiceover_en"],
                    "text": shot["voiceover_en"],
                    "subtitle_text": subtitle_text,
                    "subtitle_translation": subtitle_zh,
                    "music": shot.get("music", concept.get("music", campaign.get("music", "Warm restrained cinematic underscore"))),
                    "sfx": shot.get("sfx", ""),
                },
                "key_message": shot["key_message"],
            }
        )

    use_product_reference_images = bool(campaign.get("use_product_reference_images", False))
    explicit_signature = (campaign.get("product_reference_signature") or "").strip()
    explicit_structure = campaign.get("product_visual_structure")
    meta = {
        "brand_name": campaign.get("brand_name", "AnyWell"),
        "product_brand_name": campaign.get("brand_name", "AnyWell"),
        "product_name": campaign.get("product_name", "AnyWell emotional campaign prototype"),
        "marketing_product_name": campaign.get("marketing_product_name", campaign.get("brand_name", "AnyWell")),
        "hero_product_name": campaign.get("hero_product_name", "the featured powered wheelchair"),
        "product_category": campaign.get("product_category", "powered wheelchair / mobility chair"),
        "campaign_goal": campaign.get("campaign_goal", ""),
        "target_market": campaign.get("target_market", "United States"),
        "target_audience": campaign.get("target_audience", ""),
        "core_selling_points": campaign.get("core_selling_points", ""),
        "use_scenarios": concept.get("use_scenarios", campaign.get("use_scenarios", "")),
        "style_preset": campaign.get("style_preset", "emotional brand film"),
        "custom_style_notes": concept.get("visual_style", campaign.get("visual_style", "")),
        "style_tone": campaign.get("style_tone", ""),
        "consistency_anchor": concept.get("consistency_anchor", campaign.get("consistency_anchor", "")),
        "additional_info": "\n".join(
            item
            for item in [
                campaign.get("additional_info", "").strip(),
                concept.get("additional_info", "").strip(),
                creative_guardrails,
            ]
            if item
        ),
        "language": campaign.get("language", "English"),
        "video_orientation": campaign.get("video_orientation", "9:16"),
        "desired_scene_count": len(scenes),
        "preferred_runtime_seconds": sum(int(scene["duration_seconds"]) for scene in scenes),
        "reference_style": concept.get("reference_style", ""),
        "use_product_reference_images": use_product_reference_images,
        "product_reference_image_limit": int(campaign.get("product_reference_image_limit", 5) or 5),
        "product_reference_signature": explicit_signature if explicit_signature else None,
        "product_visual_structure": explicit_structure if explicit_structure else None,
        "continuity_rider_anchor": concept.get(
            "continuity_rider_anchor",
            "Keep the same anonymous silver-haired older adult and the same partner across connected scenes. "
            "Faces should remain natural and not hyper-detailed. Wardrobe should stay consistent.",
        ),
        "concept_id": concept["id"],
        "concept_title": concept["title"],
        "concept_theme": concept["core_theme"],
        "concept_cta": concept["cta"],
        "video_generation_mode": concept.get("video_generation_mode", campaign.get("video_generation_mode", "local")),
        "require_remote_video": bool(concept.get("require_remote_video", campaign.get("require_remote_video", False))),
        "transition_name": concept.get("transition_name", campaign.get("transition_name", "")),
        "transition_duration_seconds": float(
            concept.get("transition_duration_seconds", campaign.get("transition_duration_seconds", 0.0)) or 0.0
        ),
        "tts_voice": concept.get("voice", campaign.get("voice", "alloy")),
        "video_reference_strategy": concept.get(
            "video_reference_strategy",
            campaign.get("video_reference_strategy", "full"),
        ),
        "allow_product_reference_images_in_video": bool(
            concept.get(
                "allow_product_reference_images_in_video",
                campaign.get("allow_product_reference_images_in_video", False),
            )
        ),
        "video_strict_reference_only": bool(
            concept.get(
                "video_strict_reference_only",
                campaign.get("video_strict_reference_only", False),
            )
        ),
        "reuse_storyboard_json": concept.get(
            "reuse_storyboard_json",
            campaign.get("reuse_storyboard_json", ""),
        ),
        "remote_scene_retry_count": int(
            concept.get(
                "remote_scene_retry_count",
                campaign.get("remote_scene_retry_count", 1),
            )
            or 1
        ),
        "use_last_frame_reference": bool(
            concept.get(
                "use_last_frame_reference",
                campaign.get("use_last_frame_reference", True),
            )
        ),
        "reuse_video_result_json": concept.get(
            "reuse_video_result_json",
            campaign.get("reuse_video_result_json", ""),
        ),
        "skip_storyboard_crop_for_video": bool(
            concept.get(
                "skip_storyboard_crop_for_video",
                campaign.get("skip_storyboard_crop_for_video", False),
            )
        ),
    }

    return {
        "id": f"{concept['id']}-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "version": 1,
        "meta": meta,
        "history": [],
        "scenes": {
            "main_theme": concept["main_theme"],
            "scenes": scenes,
        },
    }


def _script_markdown(campaign: dict[str, Any], concept: dict[str, Any], script: dict[str, Any], ti_intro: dict[str, Any]) -> str:
    lines = [
        f"# {concept['title']}",
        "",
        f"Brand: {campaign.get('brand_name', 'AnyWell')}",
        f"Tagline: {campaign.get('tagline', '')}",
        f"Core theme: {concept['core_theme']}",
        f"Runtime: {script['meta']['preferred_runtime_seconds']} seconds",
        f"Orientation: {script['meta']['video_orientation']}",
        "",
        "## Ad Copy",
        f"Hook: {concept.get('hook', '')}",
        f"Cover copy: {concept.get('cover_copy', '')}",
        f"CTA: {concept.get('cta', '')}",
        "",
        "## Title Suggestion",
        ti_intro.get("title", ""),
        "",
        "## Description Suggestion",
        ti_intro.get("description", ""),
        "",
        "## Scenes",
    ]
    for scene in script["scenes"]["scenes"]:
        subtitle_text = scene["audio"].get("subtitle_text", "").strip()
        lines.extend(
            [
                "",
                f"### Scene {scene['scene_number']} | {scene['duration_seconds']}s | {scene['theme']}",
                scene["scene_description"],
                f"Voiceover: {scene['audio']['text']}",
                f"Subtitle: {subtitle_text}",
                f"Key message: {scene['key_message']}",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def _prompts_text(storyboard: list[dict[str, Any]], video_prompts: dict[str, str]) -> str:
    blocks: list[str] = []
    for frame in storyboard:
        scene_key = str(frame["scene_number"])
        blocks.extend(
            [
                f"Scene {scene_key}",
                "Image prompt:",
                frame.get("image_prompt", "").strip(),
                "",
                "Video prompt:",
                video_prompts.get(scene_key, "").strip(),
                "",
                f"Image generation mode: {frame.get('image_generation_mode', 'unknown')}",
            ]
        )
        if frame.get("image_generation_error"):
            blocks.append(f"Image generation error: {frame['image_generation_error']}")
        blocks.append("")
    return "\n".join(blocks).strip() + "\n"


def _cover_copy_text(concept: dict[str, Any], ti_intro: dict[str, Any]) -> str:
    lines = [
        f"Cover copy: {concept.get('cover_copy', '')}",
        f"Short title: {ti_intro.get('title', '')}",
        f"CTA: {concept.get('cta', '')}",
    ]
    return "\n".join(lines).strip() + "\n"


def _summary_markdown(results: list[dict[str, Any]], output_root: Path) -> str:
    lines = [
        "# AnyWell Campaign Summary",
        "",
        f"Generated at: {datetime.now().isoformat(timespec='seconds')}",
        f"Output root: {output_root.resolve()}",
        "",
    ]
    for result in results:
        lines.extend(
            [
                f"## {result['concept_id']}",
                f"Status: {result['status']}",
                f"Title: {result['title']}",
                f"Concept dir: {result['concept_dir']}",
                f"Run root: {result.get('run_root', '')}",
                f"Storyboard mode(s): {', '.join(result.get('storyboard_modes', [])) or 'n/a'}",
                f"Video mode(s): {', '.join(result.get('video_modes', [])) or 'n/a'}",
                f"Video model(s): {', '.join(result.get('video_models', [])) or 'n/a'}",
                f"Audio path: {result.get('audio_path', '')}",
                f"Subtitle path: {result.get('subtitle_path', '')}",
                f"Final video: {result.get('final_video_path', '')}",
            ]
        )
        if result.get("error"):
            lines.append(f"Error: {result['error']}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _copy_storyboard_assets(storyboard: list[dict[str, Any]], storyboard_dir: Path) -> list[str]:
    copied = []
    for frame in storyboard:
        suffix = Path(frame["saved_path"]).suffix or ".png"
        target = storyboard_dir / f"scene_{int(frame['scene_number']):02d}{suffix}"
        copied.append(_safe_copy(frame["saved_path"], target))
    return copied


def _copy_clip_assets(video_result: dict[str, dict[str, Any]], clips_dir: Path) -> list[str]:
    copied = []
    for scene_key, result in sorted(video_result.items(), key=lambda item: int(item[0])):
        video_path = result.get("video_path")
        if not video_path:
            continue
        suffix = Path(video_path).suffix or ".mp4"
        target = clips_dir / f"scene_{int(scene_key):02d}{suffix}"
        copied.append(_safe_copy(video_path, target))
    return copied


def _load_reused_storyboard(storyboard_json_path: str | Path) -> list[dict[str, Any]]:
    storyboard_path = Path(storyboard_json_path)
    if not storyboard_path.exists():
        raise FileNotFoundError(f"Storyboard JSON not found: {storyboard_path}")

    storyboard = json.loads(storyboard_path.read_text(encoding="utf-8"))
    if not isinstance(storyboard, list) or not storyboard:
        raise ValueError(f"Storyboard JSON is empty or malformed: {storyboard_path}")

    for frame in storyboard:
        saved_path = Path(str(frame.get("saved_path", "")))
        if not saved_path.exists():
            raise FileNotFoundError(f"Storyboard frame image not found: {saved_path}")
    return storyboard


def _load_reused_video_results(video_result_json_path: str | Path) -> dict[str, dict[str, Any]]:
    video_result_path = Path(video_result_json_path)
    if not video_result_path.exists():
        raise FileNotFoundError(f"Video result JSON not found: {video_result_path}")

    video_result = json.loads(video_result_path.read_text(encoding="utf-8"))
    if not isinstance(video_result, dict):
        raise ValueError(f"Video result JSON is malformed: {video_result_path}")

    normalized: dict[str, dict[str, Any]] = {}
    for scene_key, result in video_result.items():
        if not isinstance(result, dict):
            continue
        video_path = Path(str(result.get("video_path", "")))
        if not video_path.exists():
            raise FileNotFoundError(f"Reused video clip not found: {video_path}")
        last_frame_path_raw = str(result.get("last_frame_path", "") or "").strip()
        if last_frame_path_raw and not Path(last_frame_path_raw).exists():
            raise FileNotFoundError(f"Reused last frame not found: {last_frame_path_raw}")
        normalized[str(scene_key)] = result
    return normalized


def _run_single_concept(
    campaign: dict[str, Any],
    concept: dict[str, Any],
    creative_guardrails: str,
    output_root: Path,
    logger: logging.Logger,
) -> dict[str, Any]:
    run_paths: RunPaths = start_new_run(prefix=f"anywell-{concept['id']}")
    concept_dir = _ensure_dir(output_root / concept["id"])
    storyboard_dir = _ensure_dir(concept_dir / "storyboard")
    clips_dir = _ensure_dir(concept_dir / "clips")

    script = build_anywell_script(campaign, concept, creative_guardrails)
    product_reference_paths = get_product_reference_images(limit=int(campaign.get("product_reference_image_limit", 5) or 5))
    if script["meta"].get("use_product_reference_images"):
        if not script["meta"].get("product_reference_signature"):
            script["meta"]["product_reference_signature"] = get_product_reference_signature()
        if not script["meta"].get("product_visual_structure"):
            script["meta"]["product_visual_structure"] = get_product_visual_structure()
    write_run_json("brief.json", {"campaign": campaign, "concept": concept})
    write_run_json("script.json", script)
    _write_json(concept_dir / "script.json", script)
    _write_json(concept_dir / "product_reference_images.json", product_reference_paths)
    if script["meta"].get("product_visual_structure"):
        _write_json(concept_dir / "product_visual_structure.json", script["meta"]["product_visual_structure"])
    if script["meta"].get("product_reference_signature"):
        _write_text(concept_dir / "product_reference_signature.txt", str(script["meta"]["product_reference_signature"]).strip() + "\n")

    ti_intro, ti_messages = generate_ti_intro(script)
    write_run_json("ti_intro.json", ti_intro)
    _write_json(concept_dir / "ti_intro.json", ti_intro)
    if ti_messages:
        _write_json(concept_dir / "ti_intro_messages.json", ti_messages)

    reuse_storyboard_json = str(script["meta"].get("reuse_storyboard_json", "") or "").strip()
    if reuse_storyboard_json:
        logger.info("Reusing storyboard for %s from %s", concept["id"], reuse_storyboard_json)
        storyboard = _load_reused_storyboard(reuse_storyboard_json)
    else:
        storyboard = generate_storyboard(script, aspect_ratio=script["meta"]["video_orientation"])
    write_run_json("storyboard.json", storyboard)
    _write_json(concept_dir / "storyboard.json", storyboard)
    _copy_storyboard_assets(storyboard, storyboard_dir)

    video_prompts: dict[str, str] = {}
    for frame in storyboard:
        scene_key = str(frame["scene_number"])
        video_prompts[scene_key] = build_video_prompt(
            scene_info=frame.get("scene_description", ""),
            visuals=frame.get("visuals", {}),
            aspect_ratio=script["meta"]["video_orientation"],
            duration_seconds=int(frame.get("duration_seconds", 5)),
            continuity=frame.get("continuity"),
            meta=script["meta"],
            hero_product_name=script["meta"].get("hero_product_name"),
            product_reference_signature=script["meta"].get("product_reference_signature"),
            product_visual_structure=script["meta"].get("product_visual_structure"),
        )
    _write_text(concept_dir / "prompts.txt", _prompts_text(storyboard, video_prompts))

    resolved: dict[str, dict[str, Any]] = {}
    last_frame = None
    force_local_video = script["meta"].get("video_generation_mode", "local") != "remote"
    require_remote_video = bool(script["meta"].get("require_remote_video", False))
    video_reference_strategy = str(script["meta"].get("video_reference_strategy", "full") or "full").strip().lower()
    strict_reference_only = bool(script["meta"].get("video_strict_reference_only", False))
    include_product_reference_images = bool(script["meta"].get("use_product_reference_images", False))
    remote_scene_retry_count = max(1, int(script["meta"].get("remote_scene_retry_count", 1) or 1))
    use_last_frame_reference = bool(script["meta"].get("use_last_frame_reference", True))
    reuse_video_result_json = str(script["meta"].get("reuse_video_result_json", "") or "").strip()
    if reuse_video_result_json:
        logger.info("Reusing resolved clips for %s from %s", concept["id"], reuse_video_result_json)
        resolved = _load_reused_video_results(reuse_video_result_json)
        if resolved:
            last_scene_key = sorted(resolved.keys(), key=int)[-1]
            last_frame = resolved[last_scene_key].get("last_frame_path") or resolved[last_scene_key].get("video_path")
            write_run_json("video_result_partial.json", resolved)
            _write_json(concept_dir / "video_result_partial.json", resolved)
    if video_reference_strategy == "storyboard_only":
        include_product_reference_images = False
        strict_reference_only = True
    for frame in storyboard:
        scene_key = str(frame["scene_number"])
        if scene_key in resolved and resolved[scene_key].get("video_path"):
            logger.info("Skipping %s scene %s because an existing clip is being reused.", concept["id"], scene_key)
            last_frame = resolved[scene_key].get("last_frame_path") or resolved[scene_key].get("video_path")
            continue
        logger.info("Generating clip for %s scene %s", concept["id"], scene_key)
        result: dict[str, Any] | None = None
        last_scene_error = ""
        for attempt in range(1, remote_scene_retry_count + 1):
            logger.info("Submitting scene %s attempt %s/%s", scene_key, attempt, remote_scene_retry_count)
            result = generate_video_from_image_path(
                frame["saved_path"],
                frame.get("scene_description", ""),
                frame.get("visuals", {}),
                continuity=frame.get("continuity"),
                last_frame=last_frame if use_last_frame_reference else None,
                until_finish=True,
                aspect_ratio=script["meta"]["video_orientation"],
                duration_seconds=int(frame.get("duration_seconds", 5)),
                force_local=force_local_video,
                strict_reference_only=strict_reference_only,
                include_product_reference_images=include_product_reference_images,
                product_reference_paths=product_reference_paths if include_product_reference_images else None,
                meta=script["meta"],
                hero_product_name=script["meta"].get("hero_product_name"),
                product_reference_signature=script["meta"].get("product_reference_signature"),
                product_visual_structure=script["meta"].get("product_visual_structure"),
            )
            if not require_remote_video or result.get("generation_mode") == "remote":
                break

            last_scene_error = (
                f"Scene {scene_key} did not return a remote video clip. Result mode: {result.get('generation_mode')}. "
                f"Fallback reason: {result.get('fallback_reason', '')}"
            )
            logger.warning(last_scene_error)
            if attempt < remote_scene_retry_count:
                time.sleep(min(20, 5 * attempt))
        if require_remote_video and (result is None or result.get("generation_mode") != "remote"):
            raise RuntimeError(last_scene_error or f"Scene {scene_key} failed to produce a remote clip.")
        result["planned_duration_seconds"] = int(frame.get("duration_seconds", 5))
        resolved[scene_key] = result
        last_frame = result.get("last_frame_path") or frame["saved_path"]
        write_run_json("video_result_partial.json", resolved)
        _write_json(concept_dir / "video_result_partial.json", resolved)
    write_run_json("video_result.json", resolved)
    _write_json(concept_dir / "video_result.json", resolved)
    _copy_clip_assets(resolved, clips_dir)

    audio_url, audio_path, audio_duration = generate_tts_audio(script, voice=script["meta"].get("tts_voice", "alloy"))
    if not audio_path:
        raise RuntimeError("TTS generation failed and no local fallback audio was produced.")
    copied_audio_path = _safe_copy(audio_path, concept_dir / f"voiceover{Path(audio_path).suffix}")

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
        audio_path=audio_path,
    )
    copied_srt_path = _safe_copy(srt_path, concept_dir / "subtitles.srt")

    final_video = assemble_final_video(
        [resolved[key]["video_path"] for key in sorted(resolved.keys(), key=int) if resolved[key].get("video_path")],
        audio_path=audio_path,
        srt_path=srt_path,
        scene_duration_map=scene_duration_map,
        filename=f"{concept['id']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4",
        transition_name=script["meta"].get("transition_name") or None,
        transition_duration=float(script["meta"].get("transition_duration_seconds") or 0.0),
        aspect_ratio=script["meta"].get("video_orientation", "9:16"),
    )
    copied_final_video = _safe_copy(final_video.get("video_path"), concept_dir / "final_video.mp4")

    _write_text(concept_dir / "script.txt", _script_markdown(campaign, concept, script, ti_intro))
    _write_text(concept_dir / "voiceover.txt", build_voiceover_text(script) + "\n")
    _write_text(concept_dir / "cover_copy.txt", _cover_copy_text(concept, ti_intro))
    _write_text(concept_dir / "cta.txt", (concept.get("cta", "").strip() + "\n"))

    report = {
        "concept_id": concept["id"],
        "title": concept["title"],
        "status": "success",
        "concept_dir": str(concept_dir.resolve()),
        "run_root": str(run_paths.root.resolve()),
        "storyboard_modes": sorted({frame.get("image_generation_mode", "unknown") for frame in storyboard}),
        "video_modes": sorted({result.get("generation_mode", "unknown") for result in resolved.values()}),
        "video_models": sorted({result.get("video_model", "") for result in resolved.values() if result.get("video_model")}),
        "audio_url": audio_url,
        "audio_path": copied_audio_path,
        "audio_duration_seconds": audio_duration,
        "subtitle_url": srt_url,
        "subtitle_path": copied_srt_path,
        "final_video_path": copied_final_video,
        "scene_duration_map": scene_duration_map,
        "transition_name": script["meta"].get("transition_name", ""),
        "transition_duration_seconds": float(script["meta"].get("transition_duration_seconds") or 0.0),
        "product_reference_images": product_reference_paths,
        "used_product_reference_images": bool(script["meta"].get("use_product_reference_images")),
        "video_reference_strategy": video_reference_strategy,
        "allow_product_reference_images_in_video": bool(script["meta"].get("allow_product_reference_images_in_video", False)),
        "strict_reference_only": strict_reference_only,
        "reused_storyboard_json": reuse_storyboard_json,
        "use_last_frame_reference": use_last_frame_reference,
        "reuse_video_result_json": reuse_video_result_json,
    }
    _write_json(concept_dir / "concept_report.json", report)
    return report


def run_anywell_campaign(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    prompt_path: str | Path = DEFAULT_PROMPT_PATH,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    log_path: str | Path = DEFAULT_LOG_PATH,
    summary_path: str | Path = DEFAULT_SUMMARY_PATH,
    max_concepts: int | None = None,
    max_scenes_per_concept: int | None = None,
    skip_storyboard_crop_for_video: bool = False,
) -> dict[str, Any]:
    campaign = load_campaign_config(config_path)
    if skip_storyboard_crop_for_video:
        campaign["skip_storyboard_crop_for_video"] = True
    creative_guardrails = load_creative_guardrails(prompt_path)
    output_root = _ensure_dir(Path(output_root))
    log_path = Path(log_path)
    summary_path = Path(summary_path)
    _ensure_dir(log_path.parent)
    _ensure_dir(summary_path.parent)

    logger = logging.getLogger("anywell_campaign")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)

    results: list[dict[str, Any]] = []
    concepts = copy.deepcopy(campaign.get("concepts", []))
    if max_concepts is not None:
        concepts = concepts[:max_concepts]
    if max_scenes_per_concept is not None:
        for concept in concepts:
            shots = concept.get("shots", [])
            if isinstance(shots, list):
                concept["shots"] = shots[:max_scenes_per_concept]

    for concept in concepts:
        logger.info("Starting concept %s", concept["id"])
        try:
            result = _run_single_concept(campaign, concept, creative_guardrails, output_root, logger)
            results.append(result)
            logger.info("Completed concept %s", concept["id"])
        except Exception as exc:
            logger.exception("Concept %s failed", concept["id"])
            concept_dir = _ensure_dir(output_root / concept["id"])
            failure = {
                "concept_id": concept["id"],
                "title": concept["title"],
                "status": "failed",
                "concept_dir": str(concept_dir.resolve()),
                "error": str(exc),
            }
            _write_json(concept_dir / "concept_report.json", failure)
            results.append(failure)

    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "config_path": str(Path(config_path).resolve()),
        "prompt_path": str(Path(prompt_path).resolve()),
        "output_root": str(output_root.resolve()),
        "log_path": str(log_path.resolve()),
        "results": results,
    }
    _write_json(output_root / "campaign_report.json", summary)
    _write_text(summary_path, _summary_markdown(results, output_root))
    return summary
