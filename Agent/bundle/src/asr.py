import os
import re
import uuid
from http import HTTPStatus
from typing import Any
import textwrap
import subprocess
import unicodedata

import requests
from agent_bundle_env import load_agent_bundle_env

from media_pipeline import (
    build_scene_audio_duration_map,
    ensure_dir,
    find_binary,
    normalize_local_path,
    probe_audio_duration,
    safe_file_uri,
)
from rustfs_util import upload_file_to_rustfs
from workspace_paths import ensure_active_run

try:
    import dashscope
    from dashscope.audio.asr import Transcription
except ImportError:  # pragma: no cover - optional dependency
    dashscope = None
    Transcription = None


load_agent_bundle_env()
if dashscope is not None:
    dashscope.api_key = os.getenv("DASHSCOPE_API_KEY")


CJK_CHAR_RE = re.compile(r"[\u3400-\u9FFF]")
SILENCE_START_RE = re.compile(r"silence_start:\s*([0-9.]+)")
SILENCE_END_RE = re.compile(r"silence_end:\s*([0-9.]+)")
MOJIBAKE_MARKERS = set("ÃÂÅÆÇÐÑÒÓÔÕÖØÙÚÛÜÝÞßàáâãäåæçèéêëìíîïðñòóôõöøùúûüýþÿ銆鈥鍥鍙锛锟�")


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
    output_dir = ensure_dir(ensure_active_run().subtitles)
    srt_name = f"{stem or uuid.uuid4().hex}.srt"
    srt_path = output_dir / srt_name
    srt_path.write_text(content, encoding="utf-8")
    return str(srt_path)


def _format_subtitle_text(text: str, max_line_length: int = 34) -> str:
    cleaned = _clean_subtitle_text(text)
    if not cleaned:
        return ""

    if CJK_CHAR_RE.search(cleaned):
        return cleaned

    wrapped = textwrap.wrap(
        cleaned,
        width=max_line_length,
        break_long_words=False,
        break_on_hyphens=False,
    )
    if len(wrapped) <= 2:
        return "\n".join(wrapped)

    first_line_words: list[str] = []
    second_line_words: list[str] = []
    words = cleaned.split()
    half_index = max(1, len(words) // 2)
    for word in words[:half_index]:
        first_line_words.append(word)
    for word in words[half_index:]:
        second_line_words.append(word)
    first_line = " ".join(first_line_words).strip()
    second_line = " ".join(second_line_words).strip()
    if len(first_line) > max_line_length:
        wrapped = textwrap.wrap(first_line, width=max_line_length, break_long_words=False, break_on_hyphens=False)
        first_line = " ".join(wrapped[:-1]).strip() if len(wrapped) > 1 else wrapped[0]
        second_line = " ".join([wrapped[-1], second_line]).strip()
    return "\n".join(line for line in [first_line, second_line] if line)


def _split_subtitle_units(text: str) -> list[str]:
    cleaned = _clean_subtitle_text(text)
    if not cleaned:
        return []
    if CJK_CHAR_RE.search(cleaned):
        parts = re.split(r"(?<=[。！？；])\s*", cleaned)
    else:
        parts = re.split(r"(?<=[.!?;:])\s+", cleaned)
    units = [part.strip() for part in parts if part.strip()]
    return units or [cleaned]


def _collect_subtitle_units(script: dict) -> list[dict]:
    scenes = _extract_scenes(script)
    units: list[dict] = []
    for scene in scenes:
        for part in _scene_subtitle_units(scene):
            units.append(
                {
                    "scene_number": int(scene.get("scene_number", 0) or 0),
                    "text": part,
                }
            )
    return units


def _scene_subtitle_units(scene: dict) -> list[str]:
    audio = scene.get("audio", {}) if isinstance(scene, dict) else {}
    explicit_subtitle = _clean_subtitle_text(
        (audio.get("subtitle_text") or scene.get("subtitle_text") or scene.get("subtitle") or "")
    )
    if explicit_subtitle:
        return [explicit_subtitle]

    text = _scene_subtitle_text(scene)
    return _split_subtitle_units(text)


def _scene_subtitle_text(scene: dict) -> str:
    audio = scene.get("audio", {}) if isinstance(scene, dict) else {}
    scene_voiceover = (
        scene.get("voiceover")
        or scene.get("voice_over")
        or scene.get("voiceover_en")
        or scene.get("narration")
        or scene.get("subtitle_text")
        or scene.get("subtitle")
        or ""
    ).strip()
    preferred = (
        (audio.get("subtitle_text") or "").strip()
        or scene_voiceover
        or (audio.get("voice_over") or "").strip()
        or (audio.get("text") or "").strip()
        or (audio.get("subtitle") or "").strip()
        or (scene.get("key_message") or "").strip()
    )
    english_fallback = (
        (audio.get("text") or "").strip()
        or (audio.get("voice_over") or "").strip()
        or scene_voiceover
        or (scene.get("key_message") or "").strip()
    )
    if _looks_like_mojibake(preferred):
        preferred = english_fallback
    return _clean_subtitle_text(preferred)


def _clean_subtitle_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text or "")
    normalized = normalized.replace("\ufeff", " ").replace("\u200b", " ").replace("\ufffd", " ")
    return " ".join(normalized.replace("\r", "\n").split())


def _looks_like_mojibake(text: str) -> bool:
    candidate = _clean_subtitle_text(text)
    if not candidate:
        return False
    marker_hits = sum(1 for ch in candidate if ch in MOJIBAKE_MARKERS)
    return marker_hits >= 3 and marker_hits / max(1, len(candidate)) >= 0.08


def _should_force_script_subtitles(script: dict | None) -> bool:
    if not isinstance(script, dict):
        return False
    meta = script.get("meta", {})
    if not isinstance(meta, dict):
        meta = {}
    subtitle_mode = str(meta.get("subtitle_mode", "") or "").strip().lower()
    if subtitle_mode in {"english_only", "script", "script_only"}:
        return True
    if bool(meta.get("force_english_subtitles", False)):
        return True
    language = str(meta.get("language", "") or "").strip().lower()
    return language in {"english", "en", "en-us", "en_us"}


def _merge_subtitle_units_to_target(units: list[dict], target_count: int) -> list[dict]:
    merged = [dict(unit) for unit in units]
    while len(merged) > target_count and len(merged) >= 2:
        merge_index = min(
            range(len(merged) - 1),
            key=lambda index: _estimate_text_weight(merged[index]["text"]) + _estimate_text_weight(merged[index + 1]["text"]),
        )
        merged[merge_index]["text"] = f"{merged[merge_index]['text']} {merged[merge_index + 1]['text']}".strip()
        merged.pop(merge_index + 1)
    return merged


def _detect_nonsilent_segments(
    audio_path: str,
    total_duration: float | None = None,
    noise_threshold: str = "-35dB",
    min_silence_seconds: float = 0.18,
) -> list[tuple[float, float]]:
    resolved_audio = normalize_local_path(audio_path)
    if not resolved_audio or not os.path.exists(resolved_audio):
        return []

    ffmpeg = find_binary("ffmpeg")
    proc = subprocess.run(
        [
            ffmpeg,
            "-i",
            resolved_audio,
            "-af",
            f"silencedetect=noise={noise_threshold}:d={min_silence_seconds:.2f}",
            "-f",
            "null",
            "-",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    stderr = proc.stderr or ""
    silence_events: list[tuple[str, float]] = []
    for line in stderr.splitlines():
        start_match = SILENCE_START_RE.search(line)
        if start_match:
            silence_events.append(("start", float(start_match.group(1))))
        end_match = SILENCE_END_RE.search(line)
        if end_match:
            silence_events.append(("end", float(end_match.group(1))))

    if total_duration is None or total_duration <= 0:
        total_duration = probe_audio_duration(resolved_audio)
    if total_duration <= 0:
        return []

    segments: list[tuple[float, float]] = []
    cursor = 0.0
    pending_silence_start: float | None = None

    for event_type, value in silence_events:
        if event_type == "start":
            pending_silence_start = value
            if value - cursor >= 0.12:
                segments.append((max(0.0, cursor), max(0.0, value)))
        elif event_type == "end":
            cursor = value
            pending_silence_start = None

    if total_duration - cursor >= 0.12 and pending_silence_start is None:
        segments.append((max(0.0, cursor), max(0.0, total_duration)))

    return [(start, end) for start, end in segments if end - start >= 0.12]


def _estimate_text_weight(text: str) -> float:
    words = len(re.findall(r"[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)*", text or ""))
    chars = len((text or "").strip())
    punctuation = len(re.findall(r"[,.!?;:]", text or ""))
    return max(0.5, words + chars * 0.02 + punctuation * 0.15)


def _partition_segments_to_units(
    segments: list[tuple[float, float]],
    unit_weights: list[float],
) -> list[tuple[int, int]] | None:
    seg_count = len(segments)
    unit_count = len(unit_weights)
    if unit_count == 0 or seg_count < unit_count:
        return None

    segment_durations = [end - start for start, end in segments]
    total_duration = sum(segment_durations)
    total_weight = sum(unit_weights) or float(unit_count)
    target_durations = [total_duration * (weight / total_weight) for weight in unit_weights]
    prefix = [0.0]
    for duration in segment_durations:
        prefix.append(prefix[-1] + duration)

    dp = [[float("inf")] * (seg_count + 1) for _ in range(unit_count + 1)]
    prev: list[list[int | None]] = [[None] * (seg_count + 1) for _ in range(unit_count + 1)]
    dp[0][0] = 0.0

    for unit_index in range(1, unit_count + 1):
        for seg_index in range(unit_index, seg_count + 1):
            for split_index in range(unit_index - 1, seg_index):
                group_duration = prefix[seg_index] - prefix[split_index]
                cost = (group_duration - target_durations[unit_index - 1]) ** 2
                candidate = dp[unit_index - 1][split_index] + cost
                if candidate < dp[unit_index][seg_index]:
                    dp[unit_index][seg_index] = candidate
                    prev[unit_index][seg_index] = split_index

    if prev[unit_count][seg_count] is None:
        return None

    groups: list[tuple[int, int]] = []
    unit_index = unit_count
    seg_index = seg_count
    while unit_index > 0:
        split_index = prev[unit_index][seg_index]
        if split_index is None:
            return None
        groups.append((split_index, seg_index))
        seg_index = split_index
        unit_index -= 1
    groups.reverse()
    return groups


def generate_srt_from_script(
    script: dict,
    duration_seconds: float | None = None,
    scene_duration_map: dict[int, float] | None = None,
    audio_path: str | None = None,
) -> tuple[str, str]:
    scenes = _extract_scenes(script)
    if not scenes:
        raise ValueError("Script does not contain any scenes for subtitle generation.")

    subtitle_units = _collect_subtitle_units(script)
    resolved_audio_path = normalize_local_path(audio_path) if audio_path else ""
    if subtitle_units and resolved_audio_path and os.path.exists(resolved_audio_path):
        detected_segments = _detect_nonsilent_segments(
            resolved_audio_path,
            total_duration=duration_seconds,
        )
        if detected_segments and len(subtitle_units) > len(detected_segments):
            subtitle_units = _merge_subtitle_units_to_target(subtitle_units, len(detected_segments))
        if len(detected_segments) >= len(subtitle_units):
            partition = _partition_segments_to_units(
                detected_segments,
                [_estimate_text_weight(unit["text"]) for unit in subtitle_units],
            )
            if partition:
                srt_blocks = []
                for idx, (unit, (seg_start_index, seg_end_index)) in enumerate(zip(subtitle_units, partition), start=1):
                    start_seconds = detected_segments[seg_start_index][0]
                    end_seconds = detected_segments[seg_end_index - 1][1]
                    start = seconds_to_srt_time(start_seconds)
                    end = seconds_to_srt_time(end_seconds)
                    text = _format_subtitle_text(unit["text"])
                    srt_blocks.append(f"{idx}\n{start} --> {end}\n{text}\n")
                srt_path = _write_srt("\n".join(srt_blocks))
                return safe_file_uri(srt_path), srt_path

    duration_lookup = build_scene_audio_duration_map(
        script,
        duration_seconds=duration_seconds,
        scene_duration_map=scene_duration_map,
    )
    srt_blocks = []
    cursor = 0.0

    for idx, scene in enumerate(scenes, start=1):
        text = _scene_subtitle_text(scene)
        if not text:
            continue

        duration = max(
            1.0,
            float(duration_lookup.get(int(scene.get("scene_number", 0)), scene.get("duration_seconds", 1) or 1)),
        )
        text = _format_subtitle_text(text)
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
    audio_path: str | None = None,
) -> tuple[str, str]:
    if _should_force_script_subtitles(script):
        return generate_srt_from_script(
            script or {},
            duration_seconds=duration_seconds,
            scene_duration_map=scene_duration_map,
            audio_path=audio_path,
        )
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
            audio_path=audio_path,
        )


def generate_srt_from_audio(
    audio_url: str,
    script: dict | None = None,
    duration_seconds: float | None = None,
    scene_duration_map: dict[int, float] | None = None,
    audio_path: str | None = None,
) -> str:
    srt_url, _ = generate_srt_asset_from_audio(
        audio_url,
        script=script,
        duration_seconds=duration_seconds,
        scene_duration_map=scene_duration_map,
        audio_path=audio_path,
    )
    return srt_url
