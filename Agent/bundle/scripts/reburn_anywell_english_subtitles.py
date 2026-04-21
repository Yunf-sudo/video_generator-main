from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import _bootstrap  # noqa: F401

from asr import generate_srt_from_script
from media_pipeline import assemble_final_video, probe_audio_duration


def _normalize_script_to_english(script: dict) -> dict:
    scenes_root = script.get("scenes", {})
    scenes = scenes_root.get("scenes", []) if isinstance(scenes_root, dict) else []
    for scene in scenes:
        audio = scene.setdefault("audio", {})
        english_text = (audio.get("text") or audio.get("voice_over") or "").strip()
        audio["subtitle_text"] = english_text
    return script


def _concept_dirs(output_root: Path) -> list[Path]:
    return sorted(path for path in output_root.iterdir() if path.is_dir() and path.name.startswith("concept_"))


def reburn_concept(concept_dir: Path) -> None:
    script_path = concept_dir / "script.json"
    audio_path = concept_dir / "voiceover.mp3"
    clips_dir = concept_dir / "clips"
    final_video_path = concept_dir / "final_video.mp4"
    srt_path = concept_dir / "subtitles.srt"

    script = json.loads(script_path.read_text(encoding="utf-8"))
    script = _normalize_script_to_english(script)
    script_path.write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")

    duration_seconds = probe_audio_duration(str(audio_path))
    _, new_srt_path = generate_srt_from_script(
        script,
        duration_seconds=duration_seconds,
        audio_path=str(audio_path),
    )
    if srt_path.exists() and not (concept_dir / "subtitles_bilingual_backup.srt").exists():
        shutil.copy2(srt_path, concept_dir / "subtitles_bilingual_backup.srt")
    shutil.copy2(new_srt_path, srt_path)

    clip_paths = [str(path) for path in sorted(clips_dir.glob("scene_*.mp4"))]
    if final_video_path.exists() and not (concept_dir / "final_video_bilingual_backup.mp4").exists():
        shutil.copy2(final_video_path, concept_dir / "final_video_bilingual_backup.mp4")

    exported = assemble_final_video(
        clip_paths,
        audio_path=str(audio_path),
        srt_path=str(srt_path),
        output_dir=str(concept_dir),
        filename="final_video_refreshed.mp4",
        transition_name="fade",
        transition_duration=0.35,
        aspect_ratio="9:16",
    )
    shutil.copy2(exported["video_path"], final_video_path)
    for temp_path in concept_dir.glob("aligned_*.mp4"):
        temp_path.unlink(missing_ok=True)
    for temp_path in concept_dir.glob("merged_*.mp4"):
        temp_path.unlink(missing_ok=True)
    for temp_path in concept_dir.glob("with_audio_*.mp4"):
        temp_path.unlink(missing_ok=True)
    (concept_dir / "final_video_refreshed.mp4").unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Reburn AnyWell live videos with English-only styled subtitles.")
    parser.add_argument("--output-root", default="outputs/anywell_campaign_live", help="AnyWell live output root.")
    args = parser.parse_args()

    output_root = Path(args.output_root)
    for concept_dir in _concept_dirs(output_root):
        reburn_concept(concept_dir)
        print(concept_dir)


if __name__ == "__main__":
    main()
