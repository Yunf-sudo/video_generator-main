import os
import uuid
from http import HTTPStatus
from typing import Any

import requests
from dotenv import load_dotenv

from media_pipeline import SUBTITLES_DIR, build_scene_audio_duration_map, ensure_dir, safe_file_uri
from rustfs_util import upload_file_to_rustfs

try:
    import dashscope
    from dashscope.audio.asr import Transcription
except ImportError:  # pragma: no cover - optional dependency
    dashscope = None
    Transcription = None


load_dotenv()
if dashscope is not None:
    dashscope.api_key = os.getenv("DASHSCOPE_API_KEY")


def ms_to_srt_time(ms: int) -> str:
    seconds, milliseconds = divmod(ms, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def seconds_to_srt_time(seconds: float) -> str:
    ms = int(round(max(0.0, seconds) * 1000))
    return ms_to_srt_time(ms)


def _extract_scenes(script: dict | None) -> list[dict]:
    if not script:
        return []
    if isinstance(script.get("scenes"), dict):
        return script["scenes"].get("scenes", [])
    if isinstance(script.get("scenes"), list):
        return script["scenes"]
    return []


def _write_srt(content: str, stem: str | None = None) -> str:
    output_dir = ensure_dir(SUBTITLES_DIR)
    srt_name = f"{stem or uuid.uuid4().hex}.srt"
    srt_path = output_dir / srt_name
    srt_path.write_text(content, encoding="utf-8")
    return str(srt_path)


def generate_srt_from_script(
    script: dict,
    duration_seconds: float | None = None,
    scene_duration_map: dict[int, float] | None = None,
) -> tuple[str, str]:
    scenes = _extract_scenes(script)
    if not scenes:
        raise ValueError("Script does not contain any scenes for subtitle generation.")

    duration_lookup = build_scene_audio_duration_map(
        script,
        duration_seconds=duration_seconds,
        scene_duration_map=scene_duration_map,
    )
    srt_blocks = []
    cursor = 0.0

    for idx, scene in enumerate(scenes, start=1):
        text = (
            scene.get("audio", {}).get("text")
            or scene.get("audio", {}).get("voice_over")
            or scene.get("key_message")
            or ""
        ).strip()
        if not text:
            continue

        duration = max(
            1.0,
            float(duration_lookup.get(int(scene.get("scene_number", 0)), scene.get("duration_seconds", 1) or 1)),
        )
        start = seconds_to_srt_time(cursor)
        cursor += duration
        end = seconds_to_srt_time(cursor)
        srt_blocks.append(f"{idx}\n{start} --> {end}\n{text}\n")

    if not srt_blocks:
        raise ValueError("No subtitle text could be derived from the script.")

    srt_path = _write_srt("\n".join(srt_blocks))
    return safe_file_uri(srt_path), srt_path


def _transcription_to_srt_content(data: dict[str, Any]) -> str:
    srt_content = []
    for transcript in data.get("transcripts", []):
        for sentence in transcript.get("sentences", []):
            idx = sentence["sentence_id"]
            start = ms_to_srt_time(sentence["begin_time"])
            end = ms_to_srt_time(sentence["end_time"])
            text = sentence["text"]
            srt_content.append(f"{idx}\n{start} --> {end}\n{text}\n")
    return "\n".join(srt_content)


def _maybe_remote_asr(audio_url: str) -> tuple[str, str]:
    if not audio_url.startswith("http"):
        raise ValueError("Remote ASR only supports HTTP(S) audio URLs.")
    if dashscope is None or Transcription is None:
        raise ValueError("dashscope SDK is not installed for remote ASR.")
    if not dashscope.api_key:
        raise ValueError("Missing DASHSCOPE_API_KEY for remote ASR.")

    task_response = Transcription.async_call(model="fun-asr-mtl", file_urls=[audio_url])
    transcribe_response = Transcription.wait(task=task_response.output.task_id)

    if transcribe_response.status_code != HTTPStatus.OK:
        raise RuntimeError(f"ASR task failed: {transcribe_response.output}")

    results = transcribe_response.output.results
    if not results:
        raise RuntimeError("No transcription results found.")

    transcription_url = results[0]["transcription_url"]
    resp = requests.get(transcription_url, timeout=60)
    resp.raise_for_status()
    srt_content = _transcription_to_srt_content(resp.json())
    srt_path = _write_srt(srt_content, stem=task_response.output.task_id)

    bucket_name = os.getenv("RUSTFS_BUCKET_NAME_AUDIO", "audio-clips")
    rustfs_url = upload_file_to_rustfs(srt_path, bucket_name)
    return rustfs_url or safe_file_uri(srt_path), srt_path


def generate_srt_asset_from_audio(
    audio_url: str,
    script: dict | None = None,
    duration_seconds: float | None = None,
    scene_duration_map: dict[int, float] | None = None,
) -> tuple[str, str]:
    try:
        return _maybe_remote_asr(audio_url)
    except Exception as remote_err:
        print(f"Remote ASR unavailable, falling back to local subtitles: {remote_err}")
        if script is None:
            raise
        return generate_srt_from_script(
            script,
            duration_seconds=duration_seconds,
            scene_duration_map=scene_duration_map,
        )


def generate_srt_from_audio(
    audio_url: str,
    script: dict | None = None,
    duration_seconds: float | None = None,
    scene_duration_map: dict[int, float] | None = None,
) -> str:
    srt_url, _ = generate_srt_asset_from_audio(
        audio_url,
        script=script,
        duration_seconds=duration_seconds,
        scene_duration_map=scene_duration_map,
    )
    return srt_url
