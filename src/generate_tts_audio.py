from __future__ import annotations

import base64
import os
import subprocess
import uuid
from pathlib import Path

from dotenv import load_dotenv

from media_pipeline import find_binary, probe_audio_duration, safe_file_uri
from rustfs_util import upload_file_to_rustfs
from workspace_paths import ensure_active_run


load_dotenv()

DEFAULT_TTS_BUCKET = os.getenv("RUSTFS_BUCKET_NAME_AUDIO") or "audio-clips"


def _extract_scenes(script: dict) -> list[dict]:
    scenes_root = script.get("scenes", {})
    if isinstance(scenes_root, dict):
        return scenes_root.get("scenes", [])
    if isinstance(scenes_root, list):
        return scenes_root
    return []


def collect_voiceover_lines(script: dict) -> list[str]:
    lines: list[str] = []
    for scene in _extract_scenes(script):
        scene_voiceover = (
            scene.get("voiceover")
            or scene.get("voice_over")
            or scene.get("voiceover_en")
            or scene.get("narration")
            or ""
        ).strip()
        text = (
            scene.get("audio", {}).get("subtitle_text")
            or scene_voiceover
            or scene.get("audio", {}).get("voice_over")
            or scene.get("audio", {}).get("text")
            or scene.get("audio", {}).get("subtitle")
            or scene.get("key_message")
            or ""
        ).strip()
        if text:
            lines.append(text)
    return lines


def build_voiceover_text(script: dict) -> str:
    return " ".join(collect_voiceover_lines(script)).strip()


def _ensure_voiceover_text(script: dict) -> str:
    text = build_voiceover_text(script)
    if not text:
        raise ValueError("Script does not contain any usable voiceover text for TTS.")
    return text


def _estimate_duration_seconds(text: str) -> float:
    words = max(1, len((text or "").split()))
    return max(2.0, round(words / 2.5, 2))


def _upload_or_file_url(file_path: str, bucket_name: str, object_name: str) -> str:
    url = upload_file_to_rustfs(file_path, bucket_name or DEFAULT_TTS_BUCKET, object_name=object_name)
    return url or safe_file_uri(file_path)


def _generate_local_tts_windows(text: str, output_dir: str, filename: str) -> tuple[str, str, float]:
    output_path = Path(output_dir) / filename.replace(".mp3", ".wav")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    encoded_text = base64.b64encode(text.encode("utf-8")).decode("ascii")
    escaped_output_path = str(output_path).replace("'", "''")
    command = (
        "$ErrorActionPreference='Stop'; "
        "Add-Type -AssemblyName System.Speech; "
        f"$encoded='{encoded_text}'; "
        "$text=[System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($encoded)); "
        "$speaker=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$speaker.SetOutputToWaveFile('{escaped_output_path}'); "
        "$speaker.Speak($text); "
        "$speaker.Dispose();"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        check=True,
        capture_output=True,
        text=True,
    )
    duration_seconds = probe_audio_duration(str(output_path))
    url = _upload_or_file_url(str(output_path), DEFAULT_TTS_BUCKET, output_path.name)
    return url, str(output_path), duration_seconds


def _generate_silent_audio(text: str, output_dir: str, filename: str) -> tuple[str, str, float]:
    duration_seconds = _estimate_duration_seconds(text)
    output_path = Path(output_dir) / filename
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = find_binary("ffmpeg")
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-t",
            f"{duration_seconds:.2f}",
            "-q:a",
            "9",
            "-acodec",
            "libmp3lame",
            str(output_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    url = _upload_or_file_url(str(output_path), DEFAULT_TTS_BUCKET, output_path.name)
    return url, str(output_path), duration_seconds


def _generate_local_tts(text: str, output_dir: str, filename: str) -> tuple[str, str, float]:
    last_error: Exception | None = None
    if os.name == "nt":
        try:
            return _generate_local_tts_windows(text, output_dir, filename)
        except Exception as exc:
            last_error = exc
    try:
        return _generate_silent_audio(text, output_dir, filename)
    except Exception:
        if last_error is not None:
            raise last_error
        raise


def generate_and_upload_tts(
    text: str,
    output_dir: str | None = None,
    bucket_name: str = DEFAULT_TTS_BUCKET,
    voice: str = "alloy",
    model: str = "",
    allow_local_fallback: bool = True,
) -> tuple[str, str, float]:
    del voice, model
    output_dir = output_dir or str(ensure_active_run().audio)
    os.makedirs(output_dir, exist_ok=True)
    filename = f"tts_{uuid.uuid4()}.mp3"
    if not allow_local_fallback:
        return "", "", 0.0
    return _generate_local_tts(text, output_dir, filename)


def generate_tts_audio(script: dict, voice: str = "alloy"):
    del voice
    return generate_and_upload_tts(_ensure_voiceover_text(script))
