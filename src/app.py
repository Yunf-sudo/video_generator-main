from __future__ import annotations

import copy
import json
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import streamlit as st

from asr import generate_srt_asset_from_audio
from generate_scenes_pics_tools import generate_storyboard, repair_single_pic
from generate_script_tools import generate_scripts, repair_script
from generate_tts_audio import generate_tts_audio
from generate_video_tools import generate_video_from_image_path, get_video_path_from_video_id
from media_pipeline import assemble_final_video, build_scene_audio_duration_map
from quick_cut import capcut_service_status, get_capcut_api_url, quick_cut_video, upload_all_videos_to_rustfs
from ti_intro_generate_tools import generate_ti_intro
from workspace_paths import activate_run, run_paths, runs_root, start_new_run, write_run_json
from youtube_fetch.youtube_video_analysis import analyze_video


STYLE_PRESETS = {
    "产品演示型": "真实、高级、产品中心构图，突出电动操控、稳定和舒适，适合商务演示与客户沟通。",
    "渠道招商型": "镜头更偏成交导向，强调产品卖点、采购场景和合作价值，节奏更利落。",
    "家庭关怀型": "画面更温暖，突出日常代步、省力和陪伴感，但仍保持真实可信。",
    "机构采购型": "突出稳重、专业、耐看，适合康复机构、医院和养老场景展示。",
}

DEFAULT_INPUTS = {
    "product_name": "AnyWell 电动轮椅",
    "product_category": "电动轮椅 / mobility chair",
    "campaign_goal": "生成一条面向欧美市场的竖版情感广告视频，突出明显肥胖/大体重老年人重新安全走向户外的自由感和尊严感",
    "target_market": "美国、加拿大、英国和西欧",
    "target_audience": "欧美市场明显肥胖、heavyset、plus-size 老年人、配偶、35-55 岁成年子女，以及正在为家人评估户外出行辅助产品的家庭",
    "core_selling_points": "- 平顺双动力系统\n- 稳定的户外通行支持\n- 温和起步和可控转向\n- 支持明显肥胖/大体重长者安心回到户外",
    "use_scenarios": "- 家庭门口和坡道\n- 后院小路\n- 林地边缘或安静社区道路\n- 与伴侣一起外出看风景",
    "style_preset": "家庭关怀型",
    "custom_style_notes": STYLE_PRESETS["家庭关怀型"],
    "style_tone": "温暖、克制、真实、电影感，避免煽情和医疗化表达",
    "consistency_anchor": "Match the same AnyWell electric wheelchair across all scenes: consistent frame, armrest, footrest, wheel size, right-side joystick, seat cushion, and side housing. Keep the rear/top-back structure compact and proportional to the real product. Do not invent extra rods, poles, antenna-like parts, cane-like extensions, or exaggerated push bars behind the backrest. Do not show a rear/lower battery pack, exposed cable, folded state, or storage configuration.",
    "additional_info": "The rider should be the same dignified heavyset or plus-size Western senior across all scenes, clearly broader than an average or slightly stocky build. Show a broad torso and shoulders, rounded belly under normal clothing, thicker arms and legs, and a seated posture that naturally fills the wheelchair seat. Keep body type, wardrobe, posture, and identity consistent. During self-operated motion, the right hand should remain on the right-side joystick. Do not present the chair as autonomous hands-free motion. If short integrated rear handles are naturally visible, keep them subtle, short, close to the backrest, and never the visual focus. White-background product photos are identity references only and must never appear as ad frames or flash cuts.",
    "language": "English",
    "video_orientation": "9:16",
    "desired_scene_count": 5,
    "preferred_runtime_seconds": 28,
    "reference_style": "",
}

MODEL_SUMMARY = {
    "脚本": os.getenv("SCRIPT_MODEL", "gemini-2.5-flash"),
    "分镜图": os.getenv("IMAGE_MODEL", "gemini-2.5-flash-image"),
    "视频": os.getenv("VIDEO_MODEL", "veo-3.1-generate-preview"),
    "TTS": os.getenv("TTS_MODEL", "native-video-audio"),
    "竞品分析": os.getenv("YOUTUBE_ANALYSIS_MODEL", "gemini-2.5-flash"),
}

USE_GENERATED_VIDEO_AUDIO = os.getenv("USE_GENERATED_VIDEO_AUDIO", "true").strip().lower() in {"1", "true", "yes", "on"}

STEP_OPTIONS = ["产品简报", "广告脚本", "分镜图", "视频片段", "配音字幕", "导出成片"]
RECOVERABLE_META_FILES = (
    "script.json",
    "storyboard.json",
    "video_result.json",
    "video_result_partial.json",
    "tts_result.json",
    "final_video_result.json",
    "capcut_result.json",
)


st.set_page_config(page_title="电动轮椅广告工作台", layout="wide")


def _coerce_dict(value):
    return value if isinstance(value, dict) else {}


def _coerce_list(value):
    return value if isinstance(value, list) else []


def _get_query_run_id() -> str:
    try:
        value = st.query_params.get("run_id", "")
    except Exception:
        try:
            value = st.experimental_get_query_params().get("run_id", [""])[0]
        except Exception:
            return ""
    if isinstance(value, list):
        value = value[0] if value else ""
    return str(value or "").strip()


def _set_query_run_id(run_id: str) -> None:
    run_id = str(run_id or "").strip()
    if not run_id or _get_query_run_id() == run_id:
        return
    try:
        st.query_params["run_id"] = run_id
    except Exception:
        try:
            st.experimental_set_query_params(run_id=run_id)
        except Exception:
            pass


def _read_run_json(run_id: str, filename: str, default=None):
    path = runs_root() / run_id / "meta" / filename
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _infer_final_video_result_from_exports(run_id: str, tts_result: dict | None = None) -> dict | None:
    export_dir = runs_root() / run_id / "exports"
    if not export_dir.exists():
        return None
    candidates = [
        path
        for path in export_dir.glob("*.mp4")
        if path.is_file() and not path.name.startswith(("merged_", "aligned_", "with_audio_"))
    ]
    if not candidates:
        return None
    latest = max(candidates, key=lambda path: path.stat().st_mtime)
    tts_result = _coerce_dict(tts_result)
    subtitle_path = tts_result.get("srt_path") or ""
    audio_path = tts_result.get("file_path") or ""
    return {
        "video_path": str(latest),
        "video_url": latest.resolve().as_uri(),
        "subtitle_path": subtitle_path,
        "audio_path": audio_path,
        "subtitles_burned": bool(subtitle_path and Path(subtitle_path).exists()),
        "scene_duration_map": {},
        "transition_name": "",
        "transition_duration": 0.0,
    }


def list_recent_runs(limit: int = 20) -> list[Path]:
    root = runs_root()
    if not root.exists():
        return []
    run_dirs = [path for path in root.iterdir() if path.is_dir()]
    run_dirs.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return run_dirs[:limit]


def run_has_recoverable_state(path: Path) -> bool:
    meta_dir = path / "meta"
    return any((meta_dir / filename).exists() for filename in RECOVERABLE_META_FILES)


def list_recoverable_runs(limit: int = 20) -> list[Path]:
    return [path for path in list_recent_runs(limit * 3) if run_has_recoverable_state(path)][:limit]


def latest_recoverable_run_id(limit: int = 50) -> str:
    for path in list_recoverable_runs(limit):
        return path.name
    return ""


def _run_label(path: Path) -> str:
    meta_dir = path / "meta"
    marks = []
    if (meta_dir / "script.json").exists():
        marks.append("脚本")
    if (meta_dir / "storyboard.json").exists():
        marks.append("分镜")
    if (meta_dir / "video_result.json").exists() or (meta_dir / "video_result_partial.json").exists():
        marks.append("片段")
    if (meta_dir / "final_video_result.json").exists():
        marks.append("成片")
    try:
        updated = datetime.fromtimestamp(path.stat().st_mtime).strftime("%m-%d %H:%M")
    except Exception:
        updated = "未知时间"
    status = " / ".join(marks) if marks else "空记录"
    return f"{path.name} | {updated} | {status}"


def load_run_state(run_id: str) -> bool:
    run_id = str(run_id or "").strip()
    run_root = runs_root() / run_id
    if not run_id or not run_root.exists() or not run_root.is_dir():
        return False
    if not run_has_recoverable_state(run_root):
        return False

    activate_run(run_id)
    st.session_state["run_id"] = run_id
    _set_query_run_id(run_id)

    brief = _coerce_dict(_read_run_json(run_id, "brief.json", {}))
    brief_inputs = brief.get("inputs")
    if isinstance(brief_inputs, dict):
        st.session_state["inputs"] = {**DEFAULT_INPUTS, **brief_inputs}
    else:
        st.session_state["inputs"] = copy.deepcopy(DEFAULT_INPUTS)
    st.session_state["reference_style"] = st.session_state["inputs"].get("reference_style", "")
    st.session_state["reference_image_paths"] = _coerce_list(brief.get("reference_image_paths"))

    st.session_state["script"] = _read_run_json(run_id, "script.json")
    st.session_state["script_chat_messages"] = _coerce_list(
        _read_run_json(run_id, "script_chat_messages.json", [])
    )
    st.session_state["storyboard"] = _coerce_list(_read_run_json(run_id, "storyboard.json", []))
    video_result = _read_run_json(run_id, "video_result.json")
    if video_result is None:
        video_result = _read_run_json(run_id, "video_result_partial.json", {})
    st.session_state["video_result"] = _coerce_dict(video_result)
    st.session_state["ti_intro"] = _read_run_json(run_id, "ti_intro.json")
    st.session_state["tts_result"] = _coerce_dict(_read_run_json(run_id, "tts_result.json", {}))
    final_video_result = _read_run_json(run_id, "final_video_result.json")
    if not isinstance(final_video_result, dict) or not final_video_result.get("video_path"):
        final_video_result = _infer_final_video_result_from_exports(run_id, st.session_state["tts_result"])
        if final_video_result:
            write_run_json("final_video_result.json", final_video_result)
    st.session_state["final_video_result"] = final_video_result
    st.session_state["capcut_result"] = _read_run_json(run_id, "capcut_result.json")
    st.session_state["active_step"] = infer_active_step()
    return True


def current_run_paths():
    run_id = st.session_state.get("run_id")
    if run_id:
        _set_query_run_id(run_id)
        return activate_run(run_id)
    created = start_new_run(prefix="ad")
    st.session_state["run_id"] = created.run_id
    _set_query_run_id(created.run_id)
    return created


def create_new_run() -> str:
    created = start_new_run(prefix="ad")
    st.session_state["run_id"] = created.run_id
    _set_query_run_id(created.run_id)
    return created.run_id


def persist_run_json(filename: str, payload) -> None:
    current_run_paths()
    write_run_json(filename, payload)


def persist_current_brief() -> None:
    active_run = current_run_paths()
    persist_run_json(
        "brief.json",
        {
            "run_id": active_run.run_id,
            "inputs": st.session_state.get("inputs", {}),
            "reference_image_paths": st.session_state.get("reference_image_paths", []),
        },
    )


def reset_generated_state() -> None:
    st.session_state["script"] = None
    st.session_state["script_chat_messages"] = []
    st.session_state["storyboard"] = []
    st.session_state["video_result"] = {}
    st.session_state["ti_intro"] = None
    st.session_state["tts_result"] = {}
    st.session_state["final_video_result"] = None
    st.session_state["capcut_result"] = None


def init_state() -> None:
    defaults = {
        "run_id": None,
        "inputs": copy.deepcopy(DEFAULT_INPUTS),
        "reference_style": "",
        "competitor_video_id": "",
        "reference_image_paths": [],
        "active_step": "产品简报",
        "active_step_nav": "产品简报",
        "active_step_nav_synced": "产品简报",
        "script": None,
        "script_chat_messages": [],
        "storyboard": [],
        "video_result": {},
        "ti_intro": None,
        "tts_result": {},
        "final_video_result": None,
        "capcut_result": None,
    }

    for key, value in defaults.items():
        if key not in st.session_state or st.session_state[key] is None:
            st.session_state[key] = copy.deepcopy(value)

    st.session_state["inputs"] = {**DEFAULT_INPUTS, **_coerce_dict(st.session_state.get("inputs"))}
    st.session_state["video_result"] = _coerce_dict(st.session_state.get("video_result"))
    st.session_state["tts_result"] = _coerce_dict(st.session_state.get("tts_result"))

    query_run_id = _get_query_run_id()
    if query_run_id and not st.session_state.get("run_id"):
        load_run_state(query_run_id)
    if not st.session_state.get("run_id"):
        latest_run_id = latest_recoverable_run_id()
        if latest_run_id:
            load_run_state(latest_run_id)


def extract_youtube_video_id(value: str) -> str:
    if not value:
        return ""
    parsed = urlparse(value.strip())
    if parsed.scheme and parsed.netloc:
        if parsed.netloc.endswith("youtu.be"):
            return parsed.path.strip("/")
        query_video_id = parse_qs(parsed.query).get("v", [""])[0]
        if query_video_id:
            return query_video_id
    return value.strip()


def persist_uploaded_files(upload_files) -> list[str]:
    upload_dir = current_run_paths().uploads
    upload_dir.mkdir(parents=True, exist_ok=True)
    saved_paths = []
    for file in upload_files or []:
        unique_name = f"ref_{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.name}"
        out_path = upload_dir / unique_name
        out_path.write_bytes(file.read())
        saved_paths.append(str(out_path))
    return saved_paths


def _safe_int(value, default: int = 999999) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def scene_list(script: dict | None) -> list[dict]:
    if not isinstance(script, dict):
        return []
    scenes_root = script.get("scenes")
    if isinstance(scenes_root, list):
        return [scene for scene in scenes_root if isinstance(scene, dict)]
    if isinstance(scenes_root, dict):
        nested = scenes_root.get("scenes")
        if isinstance(nested, list):
            return [scene for scene in nested if isinstance(scene, dict)]
    for key in ("scene_list", "script", "shots"):
        value = script.get(key)
        if isinstance(value, list):
            return [scene for scene in value if isinstance(scene, dict)]
    return []


def ordered_storyboard() -> list[dict]:
    frames = [item for item in st.session_state.get("storyboard", []) if isinstance(item, dict)]
    return sorted(frames, key=lambda item: _safe_int(item.get("scene_number") or item.get("scene_id")))


def ordered_video_results() -> list[tuple[str, dict]]:
    results = st.session_state.get("video_result", {})
    if isinstance(results, list):
        pairs = [(str(index + 1), item) for index, item in enumerate(results) if isinstance(item, dict)]
    elif isinstance(results, dict):
        pairs = [(str(key), value) for key, value in results.items() if isinstance(value, dict)]
    else:
        pairs = []
    return sorted(pairs, key=lambda item: _safe_int(item[0]))


def ordered_clip_paths() -> list[str]:
    return [item["video_path"] for _, item in ordered_video_results() if item.get("video_path")]


def ready_clip_count() -> int:
    return sum(1 for _, item in ordered_video_results() if item.get("video_path"))


def remote_clip_count() -> int:
    return sum(1 for _, item in ordered_video_results() if item.get("generation_mode") == "remote")


def local_preview_clip_count() -> int:
    return sum(1 for _, item in ordered_video_results() if item.get("generation_mode") == "local")


def infer_active_step() -> str:
    final_result = st.session_state.get("final_video_result")
    if isinstance(final_result, dict) and final_result.get("video_path"):
        return "导出成片"
    if st.session_state.get("capcut_result"):
        return "导出成片"
    tts_result = _coerce_dict(st.session_state.get("tts_result"))
    if tts_result.get("audio_url") or tts_result.get("file_path") or tts_result.get("srt_path"):
        return "配音字幕"
    if ordered_video_results():
        return "视频片段"
    if ordered_storyboard():
        return "视频片段"
    if scene_list(st.session_state.get("script")):
        return "广告脚本"
    return "产品简报"


def build_scene_duration_map() -> dict[int, float]:
    scene_duration_map = {}
    for key, value in ordered_video_results():
        duration = float(value.get("duration_seconds") or value.get("planned_duration_seconds") or 0)
        if duration > 0:
            scene_duration_map[int(key)] = duration
    return scene_duration_map


def build_target_scene_duration_map() -> dict[int, float]:
    tts_result = _coerce_dict(st.session_state.get("tts_result"))
    audio_duration = float(tts_result.get("duration_seconds") or tts_result.get("duration") or 0)
    return build_scene_audio_duration_map(
        st.session_state.get("script"),
        duration_seconds=audio_duration or None,
        scene_duration_map=build_scene_duration_map() or None,
    )


def all_clips_remote_ready() -> bool:
    frames = ordered_storyboard()
    if not frames:
        return False
    results = st.session_state.get("video_result", {})
    if len(results) < len(frames):
        return False
    for frame in frames:
        current = results.get(str(frame["scene_number"]), {})
        if not current.get("video_path") or current.get("generation_mode") != "remote":
            return False
    return True


def all_storyboard_clips_ready() -> bool:
    frames = ordered_storyboard()
    if not frames:
        return False
    results = st.session_state.get("video_result", {})
    if len(results) < len(frames):
        return False
    for frame in frames:
        current = results.get(str(frame["scene_number"]), {})
        if not current.get("video_path"):
            return False
    return True


def reset_downstream(from_stage: str) -> None:
    if from_stage == "script":
        st.session_state["storyboard"] = []
        st.session_state["video_result"] = {}
        st.session_state["ti_intro"] = None
        st.session_state["tts_result"] = {}
        st.session_state["final_video_result"] = None
        st.session_state["capcut_result"] = None
    elif from_stage == "storyboard":
        st.session_state["video_result"] = {}
        st.session_state["tts_result"] = {}
        st.session_state["final_video_result"] = None
        st.session_state["capcut_result"] = None
    elif from_stage == "clips":
        st.session_state["tts_result"] = {}
        st.session_state["final_video_result"] = None
        st.session_state["capcut_result"] = None
    else:
        return

    if not st.session_state.get("run_id"):
        return
    if from_stage == "script":
        persist_run_json("storyboard.json", [])
        persist_run_json("video_result.json", {})
        persist_run_json("ti_intro.json", None)
        persist_run_json("tts_result.json", {})
        persist_run_json("final_video_result.json", None)
        persist_run_json("capcut_result.json", None)
    elif from_stage == "storyboard":
        persist_run_json("video_result.json", {})
        persist_run_json("tts_result.json", {})
        persist_run_json("final_video_result.json", None)
        persist_run_json("capcut_result.json", None)
    elif from_stage == "clips":
        persist_run_json("tts_result.json", {})
        persist_run_json("final_video_result.json", None)
        persist_run_json("capcut_result.json", None)


def generate_script_step() -> None:
    current_run_paths()
    persist_current_brief()
    script, messages = generate_scripts(st.session_state["inputs"])
    st.session_state["script"] = script
    st.session_state["script_chat_messages"] = messages
    st.session_state["active_step"] = "广告脚本"
    persist_run_json("script.json", script)
    persist_run_json("script_chat_messages.json", messages)
    reset_downstream("script")


def generate_storyboard_step() -> None:
    current_run_paths()
    storyboard = generate_storyboard(
        st.session_state["script"],
        reference_image_paths=st.session_state.get("reference_image_paths", []),
        aspect_ratio=st.session_state["inputs"]["video_orientation"],
    )
    st.session_state["storyboard"] = storyboard
    st.session_state["active_step"] = "视频片段"
    persist_run_json("storyboard.json", storyboard)
    reset_downstream("storyboard")


def submit_all_missing_clips() -> None:
    current_run_paths()
    frames = ordered_storyboard()
    current_results = copy.deepcopy(st.session_state.get("video_result", {}))
    last_reference_frame = None

    for frame in frames:
        scene_key = str(frame["scene_number"])
        existing = current_results.get(scene_key, {})
        if existing.get("video_path") or existing.get("video_id"):
            last_reference_frame = existing.get("last_frame_path") or frame["saved_path"]
            continue

        clip_result = generate_video_from_image_path(
            frame["saved_path"],
            frame.get("scene_description", ""),
            frame.get("visuals", {}),
            scene_audio=frame.get("audio", {}),
            continuity=frame.get("continuity"),
            last_frame=last_reference_frame,
            until_finish=False,
            aspect_ratio=st.session_state["inputs"]["video_orientation"],
            duration_seconds=frame.get("duration_seconds", 8),
            force_local=False,
        )
        current_results[scene_key] = clip_result
        last_reference_frame = frame["saved_path"]

    st.session_state["video_result"] = current_results
    st.session_state["active_step"] = "视频片段"
    persist_run_json("video_result.json", current_results)
    reset_downstream("clips")


def resolve_all_pending_clips() -> None:
    current_run_paths()
    current_results = copy.deepcopy(st.session_state.get("video_result", {}))
    last_reference_frame = None
    for frame in ordered_storyboard():
        scene_key = str(frame["scene_number"])
        current = current_results.get(scene_key, {})
        if current.get("video_path"):
            last_reference_frame = current.get("last_frame_path") or last_reference_frame or frame["saved_path"]
            continue
        if not current.get("video_id"):
            continue
        try:
            refreshed = get_video_path_from_video_id(current["video_id"])
        except Exception:
            refreshed = generate_video_from_image_path(
                frame["saved_path"],
                frame.get("scene_description", ""),
                frame.get("visuals", {}),
                scene_audio=frame.get("audio", {}),
                continuity=frame.get("continuity"),
                last_frame=current.get("last_frame_path") or last_reference_frame,
                until_finish=True,
                aspect_ratio=st.session_state["inputs"]["video_orientation"],
                duration_seconds=frame.get("duration_seconds", 8),
                force_local=False,
            )
        refreshed["planned_duration_seconds"] = current.get("planned_duration_seconds", frame.get("duration_seconds", 8))
        current_results[scene_key] = refreshed
        last_reference_frame = refreshed.get("last_frame_path") or last_reference_frame or frame["saved_path"]
    st.session_state["video_result"] = current_results
    st.session_state["active_step"] = "视频片段"
    persist_run_json("video_result.json", current_results)


def generate_metadata_step() -> None:
    current_run_paths()
    ti_intro, _ = generate_ti_intro(st.session_state["script"])
    st.session_state["ti_intro"] = ti_intro
    st.session_state["active_step"] = "配音字幕"
    persist_run_json("ti_intro.json", ti_intro)


def generate_tts_step() -> None:
    current_run_paths()
    audio_url, file_path, duration = generate_tts_audio(st.session_state["script"])
    if not file_path:
        raise RuntimeError("没有拿到配音文件。")
    st.session_state["tts_result"] = {
        "audio_url": audio_url,
        "url": audio_url,
        "file_path": file_path,
        "duration_seconds": duration,
        "duration": duration,
    }
    st.session_state["active_step"] = "配音字幕"
    persist_run_json("tts_result.json", st.session_state["tts_result"])


def generate_subtitles_step() -> None:
    current_run_paths()
    tts_result = _coerce_dict(st.session_state.get("tts_result"))
    if not tts_result.get("audio_url"):
        raise RuntimeError("请先生成配音。")
    scene_duration_map = build_target_scene_duration_map()
    srt_url, srt_path = generate_srt_asset_from_audio(
        tts_result["audio_url"],
        script=st.session_state["script"],
        duration_seconds=tts_result.get("duration_seconds") or tts_result.get("duration"),
        scene_duration_map=scene_duration_map or None,
        audio_path=tts_result.get("file_path"),
    )
    st.session_state["tts_result"] = {
        **tts_result,
        "srt_url": srt_url,
        "srt_path": srt_path,
    }
    st.session_state["active_step"] = "配音字幕"
    persist_run_json("tts_result.json", st.session_state["tts_result"])


def ensure_audio_and_subtitles_ready() -> None:
    if USE_GENERATED_VIDEO_AUDIO:
        return
    if not st.session_state.get("script"):
        raise RuntimeError("请先生成脚本，才能自动补齐配音和字幕。")

    tts_result = _coerce_dict(st.session_state.get("tts_result"))
    if not (tts_result.get("file_path") or tts_result.get("audio_url")):
        generate_tts_step()
        tts_result = _coerce_dict(st.session_state.get("tts_result"))

    if not tts_result.get("srt_path"):
        generate_subtitles_step()


def export_formal_video_step() -> None:
    active_run = current_run_paths()
    if not all_storyboard_clips_ready():
        raise RuntimeError("当前还有片段未完成，无法拼接完整视频。")
    output_name = f"wheelchair-{datetime.now().strftime('%m%d-%H%M')}.mp4"
    if USE_GENERATED_VIDEO_AUDIO:
        st.session_state["final_video_result"] = assemble_final_video(
            ordered_clip_paths(),
            audio_path=None,
            srt_path=None,
            output_dir=active_run.exports,
            filename=output_name,
            scene_duration_map=None,
            transition_name=None,
            transition_duration=0.0,
            aspect_ratio=st.session_state.get("inputs", {}).get("video_orientation", "9:16"),
            preserve_clip_audio=True,
        )
    else:
        ensure_audio_and_subtitles_ready()
        scene_duration_map = build_target_scene_duration_map()
        tts_result = _coerce_dict(st.session_state.get("tts_result"))
        st.session_state["final_video_result"] = assemble_final_video(
            ordered_clip_paths(),
            audio_path=tts_result.get("file_path"),
            srt_path=tts_result.get("srt_path"),
            output_dir=active_run.exports,
            filename=output_name,
            scene_duration_map=scene_duration_map or None,
            transition_name=st.session_state.get("inputs", {}).get("transition_name", "fade"),
            transition_duration=float(st.session_state.get("inputs", {}).get("transition_duration_seconds", 0.35) or 0.0),
            aspect_ratio=st.session_state.get("inputs", {}).get("video_orientation", "9:16"),
        )
    st.session_state["active_step"] = "导出成片"
    persist_run_json("final_video_result.json", st.session_state["final_video_result"])


def run_full_pipeline() -> None:
    if not st.session_state.get("script"):
        generate_script_step()
    if not ordered_storyboard():
        generate_storyboard_step()
    submit_all_missing_clips()
    resolve_all_pending_clips()
    generate_metadata_step()
    if not USE_GENERATED_VIDEO_AUDIO:
        generate_tts_step()
        generate_subtitles_step()
    export_formal_video_step()


def render_sidebar() -> None:
    with st.sidebar:
        st.markdown("## 历史记录")
        st.caption("只显示已经生成过脚本、分镜、片段或成片的 Run；空白简报 Run 不会列出。")
        recent_runs = list_recoverable_runs()
        if recent_runs:
            run_labels = {path.name: _run_label(path) for path in recent_runs}
            run_names = [path.name for path in recent_runs]
            if st.session_state.get("restore_run_id") not in run_names:
                st.session_state["restore_run_id"] = run_names[0]
            selected_run = st.selectbox(
                "加载历史 Run",
                run_names,
                format_func=lambda value: run_labels.get(value, value),
                key="restore_run_id",
            )
            restore_col, new_col = st.columns(2)
            if restore_col.button("加载", use_container_width=True):
                if load_run_state(selected_run):
                    st.success(f"已加载 Run：{selected_run}")
                    st.rerun()
                else:
                    st.error("这个 Run 没有可恢复的脚本、分镜、片段或成片数据。")
            if new_col.button("新建", use_container_width=True):
                create_new_run()
                st.session_state["inputs"] = copy.deepcopy(DEFAULT_INPUTS)
                st.session_state["reference_image_paths"] = []
                st.session_state["active_step"] = "产品简报"
                reset_generated_state()
                persist_current_brief()
                st.rerun()
        else:
            st.caption("还没有可恢复的历史 Run。")

        run_id = st.session_state.get("run_id")
        if run_id:
            active_run = run_paths(run_id)
            st.caption(f"当前 Run：{run_id}")
            st.caption(f"输出目录：{active_run.root}")

        st.markdown("## 快捷操作")
        if st.button("一键生成正式版", use_container_width=True):
            with st.spinner("正在从简报一路跑到正式成片，这会持续几分钟到十几分钟不等..."):
                try:
                    run_full_pipeline()
                    st.success("正式版流程已跑完。")
                except Exception as exc:
                    st.error(f"一键流程失败：{exc}")

        st.markdown("## 当前状态")
        st.metric("脚本场景数", len(scene_list(st.session_state.get("script"))))
        st.metric("分镜数量", len(ordered_storyboard()))
        st.metric("已完成片段", ready_clip_count())
        st.metric("远端动态片段", remote_clip_count())
        st.metric("本地预览片段", local_preview_clip_count())

        st.markdown("## 当前模型")
        for label, model_name in MODEL_SUMMARY.items():
            st.caption(f"{label}: {model_name}")


def render_header() -> None:
    st.title("电动轮椅广告工作台")
    st.caption("围绕同一台电动轮椅生成脚本、分镜、远端动态片段、配音字幕和最终成片。")

    cols = st.columns(5)
    cols[0].metric("脚本场景数", len(scene_list(st.session_state.get("script"))))
    cols[1].metric("分镜数量", len(ordered_storyboard()))
    cols[2].metric("已就绪片段", ready_clip_count())
    cols[3].metric("远端动态片段", remote_clip_count())
    cols[4].metric("本地预览片段", local_preview_clip_count())


def render_brief_tab() -> None:
    st.subheader("1. 产品简报")
    st.write("这里确定电动轮椅的广告目标、风格和产品一致性约束，后续模块都会沿用这份简报。")

    with st.expander("竞品视频风格参考", expanded=False):
        st.session_state["competitor_video_id"] = st.text_input(
            "可编辑 | YouTube 链接或视频 ID",
            value=st.session_state.get("competitor_video_id", ""),
            placeholder="例如 https://www.youtube.com/watch?v=... 或直接输入视频 ID",
        )
        parsed_video_id = extract_youtube_video_id(st.session_state["competitor_video_id"])
        if parsed_video_id:
            st.caption(f"识别到视频 ID：{parsed_video_id}")
        if st.button("分析竞品视频"):
            if not parsed_video_id:
                st.warning("请先输入有效的 YouTube 链接或视频 ID。")
            else:
                with st.spinner("正在分析竞品视频风格..."):
                    try:
                        st.session_state["reference_style"] = analyze_video(parsed_video_id)
                        st.session_state["inputs"]["reference_style"] = st.session_state["reference_style"]
                        st.success("竞品分析已写入提示词参考。")
                    except Exception as exc:
                        st.error(f"YouTube 分析失败：{exc}")
        if st.session_state.get("reference_style"):
            st.text_area("当前风格参考", value=st.session_state["reference_style"], height=220)

    with st.form("brief_form"):
        left, right = st.columns(2)
        with left:
            product_name = st.text_input("可编辑 | 产品名称", value=st.session_state["inputs"]["product_name"])
            product_category = st.text_input("可编辑 | 产品品类", value=st.session_state["inputs"]["product_category"])
            campaign_goal = st.text_area("可编辑 | 投放目标", value=st.session_state["inputs"]["campaign_goal"], height=90)
            target_market = st.text_input("可编辑 | 目标市场", value=st.session_state["inputs"]["target_market"])
            target_audience = st.text_area("可编辑 | 目标受众", value=st.session_state["inputs"]["target_audience"], height=110)
            language = st.selectbox(
                "可编辑 | 输出语言",
                options=["Chinese", "English"],
                index=["Chinese", "English"].index(st.session_state["inputs"]["language"]),
            )
            desired_scene_count = st.slider(
                "可编辑 | 目标场景数",
                min_value=4,
                max_value=6,
                value=int(st.session_state["inputs"]["desired_scene_count"]),
            )
            preferred_runtime_seconds = st.slider(
                "可编辑 | 目标总时长（秒）",
                min_value=20,
                max_value=36,
                value=int(st.session_state["inputs"]["preferred_runtime_seconds"]),
            )
        with right:
            core_selling_points = st.text_area("可编辑 | 核心卖点", value=st.session_state["inputs"]["core_selling_points"], height=120)
            use_scenarios = st.text_area("可编辑 | 使用场景", value=st.session_state["inputs"]["use_scenarios"], height=120)
            style_preset = st.selectbox(
                "可编辑 | 风格模板",
                options=list(STYLE_PRESETS.keys()),
                index=list(STYLE_PRESETS.keys()).index(st.session_state["inputs"]["style_preset"]),
            )
            custom_style_notes = st.text_area(
                "可编辑 | 自定义风格说明",
                value=st.session_state["inputs"]["custom_style_notes"],
                height=100,
            )
            style_tone = st.text_input("可编辑 | 风格语气", value=st.session_state["inputs"]["style_tone"])
            consistency_anchor = st.text_area("可编辑 | 产品一致性锚点", value=st.session_state["inputs"]["consistency_anchor"], height=110)
            additional_info = st.text_area("可编辑 | 补充说明", value=st.session_state["inputs"]["additional_info"], height=110)
            video_orientation = st.selectbox(
                "可编辑 | 画幅比例",
                options=["9:16", "16:9", "1:1"],
                index=["9:16", "16:9", "1:1"].index(st.session_state["inputs"]["video_orientation"]),
            )

        upload_files = st.file_uploader(
            "可编辑 | 上传轮椅参考图，可多张",
            type=["png", "jpg", "jpeg", "webp"],
            accept_multiple_files=True,
        )
        submitted = st.form_submit_button("保存简报")

    if submitted:
        run_id = create_new_run()
        st.session_state["inputs"] = {
            "product_name": product_name,
            "product_category": product_category,
            "campaign_goal": campaign_goal,
            "target_market": target_market,
            "target_audience": target_audience,
            "core_selling_points": core_selling_points,
            "use_scenarios": use_scenarios,
            "style_preset": style_preset,
            "custom_style_notes": custom_style_notes or STYLE_PRESETS[style_preset],
            "style_tone": style_tone,
            "consistency_anchor": consistency_anchor,
            "additional_info": additional_info,
            "language": language,
            "video_orientation": video_orientation,
            "desired_scene_count": desired_scene_count,
            "preferred_runtime_seconds": preferred_runtime_seconds,
            "reference_style": st.session_state.get("reference_style", ""),
        }
        st.session_state["reference_image_paths"] = persist_uploaded_files(upload_files) if upload_files else []
        st.session_state["active_step"] = "广告脚本"
        reset_generated_state()
        persist_run_json(
            "brief.json",
            {
                "run_id": run_id,
                "inputs": st.session_state["inputs"],
                "reference_image_paths": st.session_state["reference_image_paths"],
            },
        )
        st.success(f"产品简报已保存，新建 Run：{run_id}")

    if st.session_state.get("reference_image_paths"):
        st.caption("当前参考图")
        preview_cols = st.columns(min(3, len(st.session_state["reference_image_paths"])))
        for idx, path in enumerate(st.session_state["reference_image_paths"]):
            with preview_cols[idx % len(preview_cols)]:
                st.image(path, use_container_width=True)
                st.caption(Path(path).name)


def render_script_tab() -> None:
    st.subheader("2. 广告脚本")
    top_cols = st.columns([1, 1.2])
    if top_cols[0].button("生成广告脚本", use_container_width=True):
        with st.spinner("正在生成电动轮椅广告脚本..."):
            try:
                generate_script_step()
                st.success("脚本已生成。")
            except Exception as exc:
                st.error(f"脚本生成失败：{exc}")

    script = st.session_state.get("script")
    scenes = scene_list(script)
    if not scenes:
        st.info("请先生成脚本。")
        return

    scenes_root = script.get("scenes", {}) if isinstance(script, dict) else {}
    main_theme = scenes_root.get("main_theme", "") if isinstance(scenes_root, dict) else ""
    st.markdown(f"### {main_theme or '广告脚本'}")
    for scene in scenes:
        visuals = scene.get("visuals", {}) if isinstance(scene.get("visuals", {}), dict) else {}
        audio = scene.get("audio", {}) if isinstance(scene.get("audio", {}), dict) else {}
        scene_number = scene.get("scene_number", "")
        duration_seconds = scene.get("duration_seconds", "")
        theme = scene.get("theme", "")
        scene_description = scene.get("scene_description", "")
        camera_movement = visuals.get("camera_movement", "未提供")
        lighting = visuals.get("lighting", "未提供")
        composition = visuals.get("composition_and_set_dressing", "未提供")
        voice_text = audio.get("text") or audio.get("voice_over") or "未提供"
        key_message = scene.get("key_message", "")
        with st.container(border=True):
            st.markdown(f"**场景 {scene_number} | {duration_seconds}s | {theme}**")
            st.write(scene_description)
            st.caption(f"镜头：{camera_movement}")
            st.caption(f"灯光：{lighting}")
            st.caption(f"构图：{composition}")
            st.write(f"旁白：{voice_text}")
            st.caption(f"关键信息：{key_message}")

    with st.expander("脚本 JSON", expanded=False):
        st.json(script)

    with st.form("repair_script_form"):
        feedback = st.text_area(
            "可编辑 | 脚本修改意见",
            placeholder="例如：第二个镜头更突出操控稳定，结尾 CTA 更像成交引导。",
        )
        submitted = st.form_submit_button("应用脚本修改")
    if submitted and feedback.strip():
        with st.spinner("正在修改脚本..."):
            try:
                updated_script, updated_messages = repair_script(st.session_state["script_chat_messages"], feedback.strip())
                updated_script["meta"] = copy.deepcopy(st.session_state["script"].get("meta", {}))
                updated_script["history"] = copy.deepcopy(st.session_state["script"].get("history", []))
                updated_script["history"].append(feedback.strip())
                st.session_state["script"] = updated_script
                st.session_state["script_chat_messages"] = updated_messages
                persist_run_json("script.json", updated_script)
                persist_run_json("script_chat_messages.json", updated_messages)
                reset_downstream("script")
                st.success("脚本已更新。")
                st.rerun()
            except Exception as exc:
                st.error(f"脚本修改失败：{exc}")


def render_storyboard_tab() -> None:
    st.subheader("3. 分镜图")
    if not st.session_state.get("script"):
        st.info("请先生成脚本。")
        return

    if st.button("生成全部分镜图", use_container_width=True):
        with st.spinner("正在生成分镜图..."):
            try:
                generate_storyboard_step()
                st.success("分镜图已生成。")
            except Exception as exc:
                st.error(f"分镜图生成失败：{exc}")

    frames = ordered_storyboard()
    if not frames:
        st.info("先生成分镜图。")
        return

    for frame in frames:
        with st.container(border=True):
            left, right = st.columns([1, 1.2])
            with left:
                st.image(frame["saved_path"], use_container_width=True)
            with right:
                st.markdown(f"**场景 {frame['scene_number']} | 计划 {frame['duration_seconds']}s**")
                st.write(frame["scene_description"])
                st.caption(frame["key_message"])
                with st.expander("修改这个分镜"):
                    feedback = st.text_area(
                        "可编辑 | 分镜修改意见",
                        key=f"frame_feedback_{frame['scene_number']}",
                        placeholder="例如：轮椅更居中，背景更真实，保持同一台车。",
                    )
                    if st.button("应用分镜修改", key=f"frame_repair_{frame['scene_number']}"):
                        try:
                            new_path = repair_single_pic(
                                frame["saved_path"],
                                feedback,
                                aspect_ratio=st.session_state["inputs"]["video_orientation"],
                            )
                            frame["saved_path"] = new_path
                            persist_run_json("storyboard.json", st.session_state["storyboard"])
                            reset_downstream("storyboard")
                            st.success("分镜已更新。")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"分镜修改失败：{exc}")


def render_clips_tab() -> None:
    st.subheader("4. 视频片段")
    if not ordered_storyboard():
        st.info("请先生成分镜图。")
        return

    top_cols = st.columns(3)
    if top_cols[0].button("批量提交远端任务", use_container_width=True):
        with st.spinner("正在提交远端视频任务..."):
            try:
                submit_all_missing_clips()
                st.success("远端任务已提交。")
            except Exception as exc:
                st.error(f"视频任务提交失败：{exc}")

    if top_cols[1].button("刷新远端状态", use_container_width=True):
        with st.spinner("正在刷新远端状态..."):
            try:
                resolve_all_pending_clips()
                st.success("远端状态已刷新。")
            except Exception as exc:
                st.error(f"远端状态刷新失败：{exc}")

    if top_cols[2].button("提交并等待全部完成", use_container_width=True):
        with st.spinner("正在提交并等待所有片段完成，这会比较久..."):
            try:
                submit_all_missing_clips()
                resolve_all_pending_clips()
                st.success("全部片段已生成。")
            except Exception as exc:
                st.error(f"视频片段生成失败：{exc}")

    st.caption("正式成片建议全部场景都使用远端动态片段。若显示为本地预览，则说明该场景回退到了本地占位片段。")

    for frame in ordered_storyboard():
        scene_key = str(frame["scene_number"])
        scene_result = st.session_state.get("video_result", {}).get(scene_key, {})
        with st.container(border=True):
            st.markdown(f"**场景 {scene_key}**")
            if scene_result.get("video_path"):
                st.video(scene_result["video_path"])
                actual_duration = scene_result.get("duration_seconds") or scene_result.get("planned_duration_seconds")
                st.caption(f"时长：{actual_duration}s")
                if scene_result.get("generation_mode") == "remote":
                    st.success("远端动态片段已就绪。")
                else:
                    st.warning("这是本地预览片段，不是正式远端动态视频。")
                    if scene_result.get("fallback_reason"):
                        st.caption(scene_result["fallback_reason"])
            elif scene_result.get("video_id"):
                st.info(f"远端任务 ID：{scene_result['video_id']}")
            else:
                st.info("这个场景还没开始生成视频。")


def render_audio_tab() -> None:
    st.subheader("5. 配音、字幕、标题")
    if not st.session_state.get("script"):
        st.info("请先生成脚本。")
        return

    top_cols = st.columns(3)
    if top_cols[0].button("生成标题描述", use_container_width=True):
        with st.spinner("正在生成标题与描述..."):
            try:
                generate_metadata_step()
                st.success("标题描述已生成。")
            except Exception as exc:
                st.error(f"标题描述生成失败：{exc}")

    if top_cols[1].button("生成配音", use_container_width=True):
        with st.spinner("正在生成配音..."):
            try:
                generate_tts_step()
                st.success("配音已生成。")
            except Exception as exc:
                st.error(f"配音生成失败：{exc}")

    if top_cols[2].button("生成字幕", use_container_width=True):
        with st.spinner("正在生成字幕..."):
            try:
                generate_subtitles_step()
                st.success("字幕已生成。")
            except Exception as exc:
                st.error(f"字幕生成失败：{exc}")

    if st.session_state.get("ti_intro"):
        st.markdown("### 标题与描述")
        st.write(st.session_state["ti_intro"]["title"])
        st.write(st.session_state["ti_intro"]["description"])
        st.caption("，".join(st.session_state["ti_intro"]["tags"]))

    tts_result = _coerce_dict(st.session_state.get("tts_result"))
    if tts_result:
        st.markdown("### 配音与字幕结果")
        if tts_result.get("file_path"):
            st.audio(tts_result["file_path"])
        st.caption(f"配音地址：{tts_result.get('audio_url', '')}")
        if tts_result.get("srt_path"):
            st.caption(f"字幕文件：{tts_result['srt_path']}")


def render_export_tab() -> None:
    st.subheader("6. 导出成片")
    ready_paths = ordered_clip_paths()
    if not ready_paths:
        st.info("请先生成视频片段。")
        return

    st.write("这里会直接把前面已经完成的片段按顺序拼接成完整视频。导出时如果发现还没有配音或字幕，会先自动补齐，再一起合成进最终成片。")

    capcut_ready, capcut_message = capcut_service_status()
    if not all_storyboard_clips_ready():
        st.warning("当前还有片段未完成。先把所有分镜对应的片段生成出来，才能拼接完整视频。")
    else:
        if local_preview_clip_count():
            st.info("当前片段里包含本地预览片段，导出后的视频可以用于检查流程，但不是最终远端画质。")
        if st.button("拼接并导出完整视频", use_container_width=True):
            with st.spinner("正在补齐配音/字幕并导出正式成片..."):
                try:
                    export_formal_video_step()
                    st.success("正式成片已导出。")
                except Exception as exc:
                    st.error(f"正式成片导出失败：{exc}")

    final_result = st.session_state.get("final_video_result")
    if isinstance(final_result, dict) and final_result.get("video_path"):
        st.video(final_result["video_path"])
        st.caption(final_result["video_path"])

    with st.expander("可选：导入剪映草稿", expanded=False):
        st.caption("这一步不是主流程。只有在你确实需要继续进剪映微调时才用。")
        if capcut_ready:
            st.caption(f"剪映桥接服务：{get_capcut_api_url()}")
        else:
            st.warning(capcut_message)

        if st.button("上传片段并导入剪映", use_container_width=True, disabled=not capcut_ready):
            try:
                uploaded_video_result = upload_all_videos_to_rustfs(st.session_state.get("video_result", {}))
                draft_id, draft_url = quick_cut_video(uploaded_video_result, _coerce_dict(st.session_state.get("tts_result")), bgm_result=None)
                st.session_state["capcut_result"] = {"draft_id": draft_id, "draft_url": draft_url}
                st.session_state["active_step"] = "导出成片"
                persist_run_json("capcut_result.json", st.session_state["capcut_result"])
                st.success("已导入剪映。")
            except Exception as exc:
                st.error(f"剪映导入失败：{exc}")

        capcut_result = st.session_state.get("capcut_result")
        if isinstance(capcut_result, dict):
            st.caption(f"剪映草稿 ID：{capcut_result.get('draft_id')}")
            st.caption(f"剪映草稿地址：{capcut_result.get('draft_url')}")


def main() -> None:
    init_state()
    if st.session_state.get("run_id"):
        current_run_paths()
    render_header()
    if st.session_state.get("active_step") not in STEP_OPTIONS:
        st.session_state["active_step"] = infer_active_step()
    if st.session_state.get("active_step_nav_synced") != st.session_state.get("active_step"):
        st.session_state["active_step_nav"] = st.session_state.get("active_step")
        st.session_state["active_step_nav_synced"] = st.session_state.get("active_step")
    active_step = st.radio(
        "工作步骤",
        STEP_OPTIONS,
        key="active_step_nav",
        horizontal=True,
    )
    if active_step != st.session_state.get("active_step"):
        st.session_state["active_step"] = active_step
        st.session_state["active_step_nav_synced"] = active_step
    st.caption(f"当前进度建议：{infer_active_step()}。加载历史 Run 后会自动跳到对应步骤。")

    if active_step == "产品简报":
        render_brief_tab()
    elif active_step == "广告脚本":
        render_script_tab()
    elif active_step == "分镜图":
        render_storyboard_tab()
    elif active_step == "视频片段":
        render_clips_tab()
    elif active_step == "配音字幕":
        render_audio_tab()
    elif active_step == "导出成片":
        render_export_tab()
    render_sidebar()


if __name__ == "__main__":
    main()
