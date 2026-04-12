import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urlparse

try:
    import imageio_ffmpeg
except ImportError:  # pragma: no cover - optional dependency
    imageio_ffmpeg = None


BASE_DIR = Path(__file__).resolve().parent
LOCAL_STORAGE_DIR = BASE_DIR / "local_storage"
EXPORTS_DIR = BASE_DIR / "exports"
SUBTITLES_DIR = BASE_DIR / "subtitles"
CLIPS_DIR = BASE_DIR / "clips"
CJK_CHAR_RE = re.compile(r"[\u3400-\u9FFF]")
WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)*")
PAUSE_RE = re.compile(r"[\u3001\u3002\uff0c\uff01\uff1f\uff1b\uff1a,.!?;:]")


def ensure_dir(path: Path | str) -> Path:
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    return target


def safe_file_uri(path: Path | str) -> str:
    return Path(path).resolve().as_uri()


def normalize_local_path(path_or_uri: Optional[str]) -> str:
    if not path_or_uri:
        return ""
    parsed = urlparse(path_or_uri)
    if parsed.scheme == "file":
        netloc = parsed.netloc or ""
        prefix = f"//{netloc}" if netloc else ""
        return str(Path(f"{prefix}{parsed.path}"))
    return path_or_uri


def _candidate_binary_paths(binary_name: str) -> Iterable[Path]:
    exe_name = f"{binary_name}.exe" if os.name == "nt" else binary_name
    python_dir = Path(sys.executable).resolve().parent
    yield python_dir / exe_name
    yield python_dir / "Scripts" / exe_name
    yield BASE_DIR / exe_name


def find_binary(binary_name: str) -> str:
    found = shutil.which(binary_name)
    if found:
        return found
    if binary_name == "ffmpeg" and imageio_ffmpeg is not None:
        try:
            ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
            if ffmpeg_path and Path(ffmpeg_path).exists():
                return ffmpeg_path
        except Exception:
            pass
    for candidate in _candidate_binary_paths(binary_name):
        if candidate.exists():
            return str(candidate)
    raise FileNotFoundError(f"Unable to locate required binary: {binary_name}")


def probe_audio_duration(file_path: str) -> float:
    source = normalize_local_path(file_path)
    if not source or not Path(source).exists():
        return 0.0

    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        proc = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                source,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            try:
                return max(0.0, float(proc.stdout.strip()))
            except ValueError:
                pass

    ffmpeg = find_binary("ffmpeg")
    proc = subprocess.run(
        [ffmpeg, "-i", source, "-f", "null", "-"],
        capture_output=True,
        text=True,
        check=False,
    )
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", proc.stderr)
    if not match:
        return 0.0

    hours = int(match.group(1))
    minutes = int(match.group(2))
    seconds = float(match.group(3))
    return hours * 3600 + minutes * 60 + seconds


def probe_media_duration(file_path: str) -> float:
    return probe_audio_duration(file_path)


def copy_to_local_storage(file_path: str, bucket_name: str, object_name: Optional[str] = None) -> tuple[str, str]:
    source = Path(normalize_local_path(file_path)).resolve()
    if object_name is None:
        object_name = source.name
    target_dir = ensure_dir(LOCAL_STORAGE_DIR / bucket_name)
    target_path = target_dir / object_name
    if target_path.exists():
        target_path = target_dir / f"{target_path.stem}_{uuid.uuid4().hex[:8]}{target_path.suffix}"
    shutil.copy2(source, target_path)
    return safe_file_uri(target_path), str(target_path)


def _video_size_for_ratio(aspect_ratio: str) -> tuple[int, int]:
    mapping = {
        "16:9": (1280, 720),
        "9:16": (720, 1280),
        "1:1": (1080, 1080),
    }
    return mapping.get(aspect_ratio, (1280, 720))


def _extract_scenes(script: dict | None) -> list[dict]:
    if not script:
        return []
    scenes_root = script.get("scenes")
    if isinstance(scenes_root, dict):
        return scenes_root.get("scenes", [])
    if isinstance(scenes_root, list):
        return scenes_root
    return []


def _scene_voice_text(scene: dict) -> str:
    audio = scene.get("audio", {}) if isinstance(scene, dict) else {}
    return (
        (audio.get("text") or "").strip()
        or (audio.get("voice_over") or "").strip()
        or (scene.get("key_message") or "").strip()
    )


def _estimate_narration_seconds(text: str) -> float:
    cleaned = (text or "").strip()
    if not cleaned:
        return 0.0

    cjk_count = len(CJK_CHAR_RE.findall(cleaned))
    word_count = len(WORD_RE.findall(cleaned))
    pause_count = len(PAUSE_RE.findall(cleaned))

    seconds = 0.0
    if cjk_count:
        seconds += cjk_count / 4.0
    if word_count:
        seconds += word_count / 2.6
    seconds += pause_count * 0.12
    return max(0.8, seconds)


def _fit_scene_durations_to_total(raw_durations: list[float], target_total: float) -> list[float]:
    if not raw_durations:
        return []

    if target_total <= 0:
        return [round(max(0.8, value), 2) for value in raw_durations]

    minimum_duration = max(0.6, min(0.9, target_total / len(raw_durations)))
    raw_total = sum(max(0.1, value) for value in raw_durations)
    scale = (target_total / raw_total) if raw_total > 0 else 1.0
    scaled = [max(minimum_duration, value * scale) for value in raw_durations]
    remaining = target_total - sum(scaled)

    if remaining < 0:
        debt = -remaining
        for index in range(len(scaled) - 1, -1, -1):
            slack = max(0.0, scaled[index] - minimum_duration)
            reduction = min(slack, debt)
            scaled[index] -= reduction
            debt -= reduction
            if debt <= 1e-6:
                break
        remaining = -debt if debt > 1e-6 else 0.0

    if scaled:
        scaled[-1] += remaining

    rounded = [round(max(0.1, value), 2) for value in scaled]
    if rounded:
        rounded[-1] = round(max(0.1, rounded[-1] + target_total - sum(rounded)), 2)
    return rounded


def build_scene_audio_duration_map(
    script: dict | None,
    duration_seconds: float | None = None,
    scene_duration_map: dict[int, float] | None = None,
) -> dict[int, float]:
    fallback_map = {
        int(key): float(value)
        for key, value in (scene_duration_map or {}).items()
        if float(value or 0) > 0
    }
    scenes = _extract_scenes(script)
    if not scenes:
        return fallback_map

    scene_numbers: list[int] = []
    raw_durations: list[float] = []
    for index, scene in enumerate(scenes, start=1):
        scene_number = int(scene.get("scene_number") or index)
        planned_duration = float(
            fallback_map.get(scene_number, scene.get("duration_seconds", 0) or 0) or 0
        )
        narration_duration = _estimate_narration_seconds(_scene_voice_text(scene))
        raw_duration = max(0.8, narration_duration, planned_duration * 0.85 if planned_duration > 0 else 0.0)
        scene_numbers.append(scene_number)
        raw_durations.append(raw_duration)

    if duration_seconds and duration_seconds > 0:
        fitted_durations = _fit_scene_durations_to_total(raw_durations, float(duration_seconds))
    else:
        fitted_durations = [round(max(0.8, value), 2) for value in raw_durations]

    return {
        scene_number: fitted_durations[index]
        for index, scene_number in enumerate(scene_numbers)
    }


def generate_local_clip(
    image_path: str,
    duration_seconds: float = 8.0,
    aspect_ratio: str = "9:16",
    output_dir: str | Path = CLIPS_DIR,
) -> dict:
    output_root = ensure_dir(output_dir)
    ffmpeg = find_binary("ffmpeg")
    width, height = _video_size_for_ratio(aspect_ratio)
    clip_id = uuid.uuid4().hex
    video_path = output_root / f"{clip_id}.mp4"
    last_frame_path = output_root / f"{clip_id}_last_frame.jpg"

    zoom_width = max(width + 24, int(round(width * 1.08)))
    zoom_height = max(height + 24, int(round(height * 1.08)))
    safe_duration = max(1.0, float(duration_seconds))
    filter_chain = (
        f"scale={zoom_width}:{zoom_height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height}:"
        f"x='(in_w-out_w)*(0.5+0.08*sin(2*PI*t/{safe_duration:.2f}))':"
        f"y='(in_h-out_h)*(0.5-0.06*cos(2*PI*t/{safe_duration:.2f}))',"
        "fps=24,format=yuv420p"
    )
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-loop",
            "1",
            "-i",
            str(Path(image_path).resolve()),
            "-t",
            f"{max(1.0, float(duration_seconds)):.2f}",
            "-vf",
            filter_chain,
            "-r",
            "24",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(video_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    extract_proc = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-sseof",
            "-0.05",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            str(last_frame_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if extract_proc.returncode != 0:
        shutil.copy2(image_path, last_frame_path)

    return {
        "video_id": f"local:{clip_id}",
        "video_url": safe_file_uri(video_path),
        "video_path": str(video_path),
        "last_frame_path": str(last_frame_path),
        "generation_mode": "local",
        "duration_seconds": float(duration_seconds),
        "aspect_ratio": aspect_ratio,
    }


def _write_concat_manifest(video_paths: list[str], output_dir: Path) -> Path:
    manifest_path = output_dir / f"concat_{uuid.uuid4().hex}.txt"
    lines = []
    for video_path in video_paths:
        path_str = str(Path(video_path).resolve()).replace("'", "'\\''")
        lines.append(f"file '{path_str}'")
    manifest_path.write_text("\n".join(lines), encoding="utf-8")
    return manifest_path


def _subtitle_filter_path(subtitle_path: str) -> str:
    resolved = Path(subtitle_path).resolve().as_posix()
    escaped = resolved.replace(":", r"\:").replace("'", r"\'")
    font_name = os.getenv("SUBTITLE_FONT_NAME", "Microsoft YaHei")
    force_style = (
        f"FontName={font_name},"
        "Outline=1,"
        "Shadow=0,"
        "BorderStyle=1,"
        "MarginV=36"
    )
    return f"subtitles='{escaped}':charenc=UTF-8:force_style='{force_style}'"


def _retime_video_clip(
    video_path: str,
    target_duration: float,
    ffmpeg: str,
    output_dir: Path,
) -> str:
    source_duration = probe_media_duration(video_path)
    if source_duration <= 0 or target_duration <= 0:
        return video_path
    if abs(source_duration - target_duration) <= 0.12:
        return video_path

    output_path = output_dir / f"{Path(video_path).stem}_retimed_{uuid.uuid4().hex[:8]}.mp4"
    if source_duration > target_duration:
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(Path(video_path).resolve()),
                "-t",
                f"{max(0.1, target_duration):.2f}",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                str(output_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return str(output_path)

    setpts_factor = max(0.01, target_duration / source_duration)
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(Path(video_path).resolve()),
            "-vf",
            f"setpts={setpts_factor:.8f}*PTS,fps=24,format=yuv420p",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-t",
            f"{max(0.1, target_duration):.2f}",
            str(output_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return str(output_path)


def _prepare_clips_for_assembly(
    video_paths: list[str],
    scene_duration_map: dict[int, float] | None,
    ffmpeg: str,
    output_dir: Path,
) -> list[str]:
    if not scene_duration_map:
        return video_paths

    ordered_targets = [
        float(scene_duration_map[key])
        for key in sorted(scene_duration_map)
        if float(scene_duration_map[key] or 0) > 0
    ]
    if len(ordered_targets) != len(video_paths):
        return video_paths

    prepared_dir = ensure_dir(output_dir / "prepared_clips")
    prepared_paths = []
    for video_path, target_duration in zip(video_paths, ordered_targets):
        prepared_paths.append(_retime_video_clip(video_path, target_duration, ffmpeg, prepared_dir))
    return prepared_paths


def _align_video_duration(
    video_path: str,
    target_duration: float,
    ffmpeg: str,
    output_dir: Path,
) -> str:
    current_duration = probe_media_duration(video_path)
    if current_duration <= 0 or target_duration <= 0:
        return video_path
    if abs(current_duration - target_duration) <= 0.05:
        return video_path

    output_path = output_dir / f"aligned_{uuid.uuid4().hex}.mp4"
    if current_duration < target_duration:
        stop_duration = max(0.0, target_duration - current_duration)
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(Path(video_path).resolve()),
                "-vf",
                f"tpad=stop_mode=clone:stop_duration={stop_duration:.2f},format=yuv420p",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                str(output_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    else:
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(Path(video_path).resolve()),
                "-t",
                f"{max(0.1, target_duration):.2f}",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                str(output_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    return str(output_path)


def assemble_final_video(
    video_paths: list[str],
    audio_path: Optional[str] = None,
    srt_path: Optional[str] = None,
    output_dir: str | Path = EXPORTS_DIR,
    filename: Optional[str] = None,
    scene_duration_map: dict[int, float] | None = None,
) -> dict:
    if not video_paths:
        raise ValueError("No video clips provided for final assembly.")

    output_root = ensure_dir(output_dir)
    ffmpeg = find_binary("ffmpeg")
    prepared_video_paths = _prepare_clips_for_assembly(video_paths, scene_duration_map, ffmpeg, output_root)
    manifest_path = _write_concat_manifest(prepared_video_paths, output_root)
    merged_video_path = output_root / f"merged_{uuid.uuid4().hex}.mp4"

    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(manifest_path),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(merged_video_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    current_video_path = merged_video_path
    if audio_path:
        resolved_audio = normalize_local_path(audio_path)
        if resolved_audio and Path(resolved_audio).exists():
            audio_duration = probe_audio_duration(resolved_audio)
            if audio_duration > 0:
                current_video_path = Path(
                    _align_video_duration(str(current_video_path), audio_duration, ffmpeg, output_root)
                )
            with_audio_path = output_root / f"with_audio_{uuid.uuid4().hex}.mp4"
            subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-i",
                    str(current_video_path),
                    "-i",
                    resolved_audio,
                    "-map",
                    "0:v:0",
                    "-map",
                    "1:a:0",
                    "-c:v",
                    "copy",
                    "-c:a",
                    "aac",
                    "-shortest",
                    str(with_audio_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            current_video_path = with_audio_path

    final_name = filename or f"final_video_{uuid.uuid4().hex[:8]}.mp4"
    final_video_path = output_root / final_name
    subtitles_burned = False

    if srt_path:
        resolved_srt = normalize_local_path(srt_path)
        if resolved_srt and Path(resolved_srt).exists():
            burn_proc = subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-i",
                    str(current_video_path),
                    "-vf",
                    _subtitle_filter_path(resolved_srt),
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "20",
                    "-c:a",
                    "copy",
                    str(final_video_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            subtitles_burned = burn_proc.returncode == 0

    if not final_video_path.exists():
        shutil.copy2(current_video_path, final_video_path)

    return {
        "video_path": str(final_video_path),
        "video_url": safe_file_uri(final_video_path),
        "subtitle_path": normalize_local_path(srt_path) if srt_path else "",
        "audio_path": normalize_local_path(audio_path) if audio_path else "",
        "subtitles_burned": subtitles_burned,
        "scene_duration_map": scene_duration_map or {},
    }
