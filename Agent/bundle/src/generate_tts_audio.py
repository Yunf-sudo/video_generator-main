from __future__ import annotations

import asyncio
import base64
import os
import subprocess
import sys
import threading
import uuid
from pathlib import Path

from dotenv import load_dotenv

from media_pipeline import find_binary, probe_audio_duration, safe_file_uri
from runtime_tunables_config import load_runtime_tunables
from rustfs_util import upload_file_to_rustfs
from workspace_paths import PROJECT_ROOT, ensure_active_run


load_dotenv()

DEFAULT_TTS_BUCKET = os.getenv("RUSTFS_BUCKET_NAME_AUDIO") or "audio-clips"
LOCAL_VENDOR_SITE_PACKAGES = PROJECT_ROOT / "generated" / "cache" / "python_vendor"
OPENAI_PLACEHOLDER_VOICES = {
    "alloy",
    "ash",
    "ballad",
    "coral",
    "echo",
    "fable",
    "nova",
    "onyx",
    "sage",
    "shimmer",
    "verse",
}


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
            scene_voiceover
            or scene.get("audio", {}).get("voice_over")
            or scene.get("audio", {}).get("text")
            or scene.get("audio", {}).get("subtitle_text")
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


def _load_tts_runtime_settings() -> dict:
    return dict(load_runtime_tunables().get("tts_runtime") or {})


def _resolve_str_setting(runtime: dict, config_key: str, env_name: str, default: str) -> str:
    env_value = (os.getenv(env_name) or "").strip()
    if env_value:
        return env_value
    config_value = runtime.get(config_key, default)
    return str(config_value).strip() or default


def _resolve_int_setting(runtime: dict, config_key: str, env_name: str, default: int) -> int:
    raw_value = os.getenv(env_name)
    if raw_value is None or not str(raw_value).strip():
        raw_value = runtime.get(config_key, default)
    try:
        return int(float(raw_value))
    except (TypeError, ValueError):
        return default


def _resolve_bool_setting(runtime: dict, config_key: str, env_name: str, default: bool) -> bool:
    raw_value = os.getenv(env_name)
    if raw_value is None or not str(raw_value).strip():
        raw_value = runtime.get(config_key, default)
    if isinstance(raw_value, bool):
        return raw_value
    normalized = str(raw_value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _normalize_voice_override(voice: str) -> str:
    candidate = (voice or "").strip()
    if not candidate:
        return ""
    if candidate.lower() in OPENAI_PLACEHOLDER_VOICES:
        return ""
    return candidate


def _resolve_tts_settings(voice: str = "") -> dict:
    runtime = _load_tts_runtime_settings()
    voice_override = _normalize_voice_override(voice)
    return {
        "provider": _resolve_str_setting(runtime, "provider", "TTS_PROVIDER", "auto").lower(),
        "edge_voice": voice_override or _resolve_str_setting(
            runtime,
            "edge_voice",
            "EDGE_TTS_VOICE",
            "en-US-AvaNeural",
        ),
        "edge_rate": _resolve_str_setting(runtime, "edge_rate", "EDGE_TTS_RATE", "+0%"),
        "edge_pitch": _resolve_str_setting(runtime, "edge_pitch", "EDGE_TTS_PITCH", "+0Hz"),
        "macos_voice": voice_override or _resolve_str_setting(
            runtime,
            "macos_voice",
            "MACOS_TTS_VOICE",
            "Ava",
        ),
        "macos_rate": _resolve_int_setting(runtime, "macos_rate", "MACOS_TTS_RATE", 175),
        "windows_voice": voice_override or _resolve_str_setting(
            runtime,
            "windows_voice",
            "WINDOWS_TTS_VOICE",
            "",
        ),
        "windows_rate": _resolve_int_setting(runtime, "windows_rate", "WINDOWS_TTS_RATE", 3),
        "allow_silent_fallback": _resolve_bool_setting(
            runtime,
            "allow_silent_fallback",
            "TTS_ALLOW_SILENT_FALLBACK",
            True,
        ),
    }


def _run_async(coroutine):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)

    result: dict[str, object] = {"value": None, "error": None}

    def _worker():
        try:
            result["value"] = asyncio.run(coroutine)
        except Exception as exc:  # pragma: no cover - defensive fallback
            result["error"] = exc

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    thread.join()
    if result["error"] is not None:
        raise result["error"]  # type: ignore[misc]
    return result["value"]


def _import_edge_tts_module():
    try:
        import edge_tts
        return edge_tts
    except ImportError as first_error:  # pragma: no cover - optional dependency
        vendor_path = str(LOCAL_VENDOR_SITE_PACKAGES)
        if LOCAL_VENDOR_SITE_PACKAGES.exists() and vendor_path not in sys.path:
            sys.path.insert(0, vendor_path)
        try:
            import edge_tts
            return edge_tts
        except ImportError as second_error:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "edge-tts 未安装，无法使用 edge_tts provider。请先执行 pip install -r requirements.txt，"
                "或安装到 generated/cache/python_vendor。"
            ) from second_error


def _generate_edge_tts(
    text: str,
    output_dir: str,
    filename: str,
    bucket_name: str,
    voice: str = "",
) -> tuple[str, str, float]:
    settings = _resolve_tts_settings(voice)
    output_path = Path(output_dir) / filename.replace(".wav", ".mp3").replace(".aiff", ".mp3")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    edge_tts = _import_edge_tts_module()

    communicate = edge_tts.Communicate(
        text=text,
        voice=settings["edge_voice"],
        rate=settings["edge_rate"],
        pitch=settings["edge_pitch"],
    )
    _run_async(communicate.save(str(output_path)))
    duration_seconds = probe_audio_duration(str(output_path))
    url = _upload_or_file_url(str(output_path), bucket_name, output_path.name)
    return url, str(output_path), duration_seconds


def _generate_local_tts_windows(
    text: str,
    output_dir: str,
    filename: str,
    bucket_name: str,
    voice: str = "",
) -> tuple[str, str, float]:
    settings = _resolve_tts_settings(voice)
    output_path = Path(output_dir) / filename.replace(".mp3", ".wav")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    encoded_text = base64.b64encode(text.encode("utf-8")).decode("ascii")
    escaped_output_path = str(output_path).replace("'", "''")
    escaped_voice = settings["windows_voice"].replace("'", "''")
    command = (
        "$ErrorActionPreference='Stop'; "
        "Add-Type -AssemblyName System.Speech; "
        f"$encoded='{encoded_text}'; "
        "$text=[System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($encoded)); "
        "$speaker=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$voiceName='{escaped_voice}'; "
        "if ($voiceName) { $speaker.SelectVoice($voiceName); } "
        f"$speaker.Rate = {settings['windows_rate']}; "
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
    url = _upload_or_file_url(str(output_path), bucket_name, output_path.name)
    return url, str(output_path), duration_seconds


def _generate_local_tts_macos(
    text: str,
    output_dir: str,
    filename: str,
    bucket_name: str,
    voice: str = "",
) -> tuple[str, str, float]:
    settings = _resolve_tts_settings(voice)
    output_path = Path(output_dir) / filename.replace(".mp3", ".aiff")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "say",
            "-v",
            settings["macos_voice"],
            "-r",
            str(settings["macos_rate"]),
            "-o",
            str(output_path),
            text,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    duration_seconds = probe_audio_duration(str(output_path))
    url = _upload_or_file_url(str(output_path), bucket_name, output_path.name)
    return url, str(output_path), duration_seconds


def _generate_silent_audio(
    text: str,
    output_dir: str,
    filename: str,
    bucket_name: str,
) -> tuple[str, str, float]:
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
    url = _upload_or_file_url(str(output_path), bucket_name, output_path.name)
    return url, str(output_path), duration_seconds


def _build_provider_attempts(provider: str) -> list[str]:
    normalized = (provider or "auto").strip().lower()
    if normalized == "edge_tts":
        attempts = ["edge_tts"]
    elif normalized == "macos_say":
        attempts = ["macos_say"]
    elif normalized == "windows_sapi":
        attempts = ["windows_sapi"]
    elif normalized == "silent":
        attempts = ["silent"]
    else:
        attempts = ["edge_tts"]
        if sys.platform == "darwin":
            attempts.append("macos_say")
        elif os.name == "nt":
            attempts.append("windows_sapi")
        attempts.append("silent")
        return attempts

    if normalized != "silent" and "silent" not in attempts:
        attempts.append("silent")
    return attempts


def _generate_local_tts(
    text: str,
    output_dir: str,
    filename: str,
    bucket_name: str,
    voice: str = "",
) -> tuple[str, str, float]:
    settings = _resolve_tts_settings(voice)
    last_error: Exception | None = None
    for provider in _build_provider_attempts(settings["provider"]):
        if provider == "silent" and not settings["allow_silent_fallback"] and settings["provider"] != "silent":
            continue
        try:
            if provider == "edge_tts":
                return _generate_edge_tts(text, output_dir, filename, bucket_name, voice=voice)
            if provider == "macos_say" and sys.platform == "darwin":
                return _generate_local_tts_macos(text, output_dir, filename, bucket_name, voice=voice)
            if provider == "windows_sapi" and os.name == "nt":
                return _generate_local_tts_windows(text, output_dir, filename, bucket_name, voice=voice)
            if provider == "silent":
                return _generate_silent_audio(text, output_dir, filename, bucket_name)
        except Exception as exc:
            last_error = exc

    if last_error is not None:
        raise last_error
    raise RuntimeError("No usable TTS provider is available for the current environment.")


def generate_and_upload_tts(
    text: str,
    output_dir: str | None = None,
    bucket_name: str = DEFAULT_TTS_BUCKET,
    voice: str = "alloy",
    model: str = "",
    allow_local_fallback: bool = True,
) -> tuple[str, str, float]:
    del model
    output_dir = output_dir or str(ensure_active_run().audio)
    os.makedirs(output_dir, exist_ok=True)
    filename = f"tts_{uuid.uuid4()}.mp3"
    if not allow_local_fallback:
        return "", "", 0.0
    return _generate_local_tts(text, output_dir, filename, bucket_name, voice=voice)


def generate_tts_audio(script: dict, voice: str = "alloy"):
    return generate_and_upload_tts(_ensure_voiceover_text(script), voice=voice)
