from __future__ import annotations

import copy
import json
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import streamlit as st

from ad_material_pipeline import stage_run_output_to_meta
from ad_flow_dry_run import run_full_dry_run_test
from ad_management_agent import run_agent_once
from ad_ops_config import load_ad_ops_config
from app_defaults_config import load_app_defaults
from asr import generate_srt_asset_from_audio
from generate_scenes_pics_tools import generate_storyboard, repair_single_pic
from generate_script_tools import generate_scripts, repair_script
from generate_tts_audio import generate_tts_audio
from generate_video_tools import generate_video_from_image_path, get_video_path_from_video_id
from meta_pool_state import (
    build_archive_feature_summary,
    inventory_snapshot,
    list_recent_alerts,
    list_material_records,
    load_material_record,
    material_status_summary,
    update_material_record,
)
from media_pipeline import assemble_final_video, build_scene_audio_duration_map
from prompt_strategy_playbook import (
    compose_prompt_editor_fields,
    error_example_labels,
    optimization_labels,
    selected_error_examples,
    selected_optimization_directions,
)
from quick_cut import capcut_service_status, get_capcut_api_url, quick_cut_video, upload_all_videos_to_rustfs
from prompt_templates_config import load_prompt_templates
from runtime_tunables_config import load_runtime_tunables
from ti_intro_generate_tools import generate_ti_intro
from workspace_paths import activate_run, run_paths, runs_root, start_new_run, write_run_json
from youtube_fetch.youtube_video_analysis import analyze_video


APP_DEFAULTS = load_app_defaults()
RUNTIME_TUNABLES = load_runtime_tunables()
PROMPT_TEMPLATES = load_prompt_templates()
AD_OPS_CONFIG = load_ad_ops_config()
APP_DEFAULTS_CONFIG_PATH = APP_DEFAULTS["config_path"]
RUNTIME_TUNABLES_CONFIG_PATH = RUNTIME_TUNABLES["config_path"]
PROMPT_TEMPLATES_CONFIG_PATH = PROMPT_TEMPLATES["config_path"]
AD_OPS_CONFIG_PATH = AD_OPS_CONFIG["config_path"]
STYLE_PRESETS = APP_DEFAULTS["style_presets"]
DEFAULT_INPUTS = APP_DEFAULTS["default_inputs"]
LANGUAGE_OPTIONS = APP_DEFAULTS["language_options"]
VIDEO_ORIENTATION_OPTIONS = APP_DEFAULTS["video_orientation_options"]

MODEL_SUMMARY = {
    "脚本": os.getenv("SCRIPT_MODEL", str(RUNTIME_TUNABLES["model_config"].get("script_model") or "")),
    "分镜图": os.getenv("IMAGE_MODEL", str(RUNTIME_TUNABLES["model_config"].get("image_model") or "")),
    "视频": os.getenv("VIDEO_MODEL", str(RUNTIME_TUNABLES["model_config"].get("video_model") or "")),
    "TTS": os.getenv("TTS_MODEL", str(RUNTIME_TUNABLES["model_config"].get("tts_model") or "")),
    "竞品分析": os.getenv(
        "YOUTUBE_ANALYSIS_MODEL",
        str(RUNTIME_TUNABLES["model_config"].get("youtube_analysis_model") or ""),
    ),
    "翻译": os.getenv("TRANSLATION_MODEL", str(RUNTIME_TUNABLES["model_config"].get("translation_model") or "")),
}

USE_GENERATED_VIDEO_AUDIO = str(
    os.getenv(
        "USE_GENERATED_VIDEO_AUDIO",
        str(RUNTIME_TUNABLES["app_runtime_flags"].get("use_generated_video_audio", True)),
    )
).strip().lower() in {"1", "true", "yes", "on"}

STEP_OPTIONS = ["产品简报", "广告脚本", "分镜图", "视频片段", "配音字幕", "导出成片", "广告运营"]
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


PROMPT_MANUAL_FALLBACKS = {
    "prompt_scene_description_manual": "prompt_scene_description_notes",
    "prompt_special_emphasis_manual": "prompt_special_emphasis",
    "prompt_error_notes_manual": "prompt_error_notes",
}


def _coerce_dict(value):
    return value if isinstance(value, dict) else {}


def _coerce_list(value):
    return value if isinstance(value, list) else []


def _brief_widget_key(name: str) -> str:
    run_id = str(st.session_state.get("run_id") or "draft").strip() or "draft"
    return f"brief_{run_id}_{name}"


def _prompt_manual_default(field_name: str) -> str:
    inputs = _coerce_dict(st.session_state.get("inputs"))
    fallback_key = PROMPT_MANUAL_FALLBACKS.get(field_name, "")
    if isinstance(inputs.get(field_name), str) and str(inputs.get(field_name) or "").strip():
        return str(inputs.get(field_name) or "")
    if fallback_key:
        return str(inputs.get(fallback_key) or "")
    return ""


def _build_prompt_editor_preview(
    optimization_selection: list[str] | None,
    error_selection: list[str] | None,
    manual_scene_notes: str,
    manual_special_emphasis: str,
    manual_error_notes: str,
) -> dict[str, str]:
    return compose_prompt_editor_fields(
        optimization_labels_selected=optimization_selection or [],
        error_labels_selected=error_selection or [],
        manual_scene_notes=manual_scene_notes,
        manual_special_emphasis=manual_special_emphasis,
        manual_error_notes=manual_error_notes,
    )


def _render_meta_stage_report(report: dict | None) -> None:
    payload = _coerce_dict(report)
    if not payload:
        return

    material_id = str(payload.get("material_id") or "")
    status = str(payload.get("status") or "")
    failed_step = str(payload.get("failed_step") or "")
    meta_mapping = _coerce_dict(payload.get("meta_mapping"))
    steps = [item for item in _coerce_list(payload.get("steps")) if isinstance(item, dict)]

    if status == "success":
        st.success(f"Meta 链路已跑通：素材 {material_id} 已创建到广告层。")
    elif status == "partial_failure":
        st.warning(f"Meta 链路在 {failed_step or '未知步骤'} 卡住，但前置成功步骤已经保留。")

    for item in steps:
        step_status = str(item.get("status") or "")
        label = str(item.get("label") or item.get("step") or "步骤")
        message = str(item.get("message") or "")
        value = str(item.get("value") or "").strip()
        prefix = "[成功]" if step_status == "success" else "[失败]"
        st.write(f"{prefix} {label}")
        if message:
            st.caption(message)
        if value:
            st.code(value, language="text")

    if meta_mapping:
        st.markdown("**当前 Meta 映射**")
        st.json(meta_mapping)


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
    st.session_state["last_meta_stage_result"] = None
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
    st.session_state["last_meta_stage_result"] = None

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
        "last_meta_stage_result": None,
        "last_agent_run_result": None,
        "last_dry_run_result": None,
        "archive_feature_summary": None,
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


def _material_time_label(item: dict) -> str:
    return str(item.get("updated_at") or item.get("created_at") or "").replace("T", " ")[:19]


def _material_option_label(item: dict) -> str:
    material_id = str(item.get("material_id") or "")
    review_status = str(item.get("review_status") or "-")
    launch_status = str(item.get("launch_status") or "-")
    source_type = str(item.get("source_type") or "-")
    return f"{material_id} | {review_status} | {launch_status} | {source_type}"

def _build_material_table_rows(records: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for item in records:
        copy_block = item.get("copy", {}) if isinstance(item.get("copy"), dict) else {}
        performance = item.get("performance_snapshot", {}) if isinstance(item.get("performance_snapshot"), dict) else {}
        rows.append(
            {
                "素材ID": str(item.get("material_id") or ""),
                "来源": str(item.get("source_type") or ""),
                "审核": str(item.get("review_status") or ""),
                "投放状态": str(item.get("launch_status") or ""),
                "启用状态": str(item.get("ad_enable_status") or ""),
                "标题": str(copy_block.get("headline") or "")[:36],
                "花费": performance.get("spend", 0.0),
                "CTR": performance.get("ctr", 0.0),
                "加购": performance.get("add_to_cart", 0.0),
                "出单": performance.get("purchases", 0.0),
                "最近更新时间": _material_time_label(item),
            }
        )
    return rows

def _filter_material_records(
    records: list[dict],
    *,
    keyword: str = "",
    review_status: str = "全部",
    launch_status: str = "全部",
    source_type: str = "全部",
    only_current_run: bool = False,
    current_run_id: str = "",
) -> list[dict]:
    filtered: list[dict] = []
    keyword = keyword.strip().lower()
    for item in records:
        if review_status != "全部" and str(item.get("review_status") or "") != review_status:
            continue
        if launch_status != "全部" and str(item.get("launch_status") or "") != launch_status:
            continue
        if source_type != "全部" and str(item.get("source_type") or "") != source_type:
            continue
        if only_current_run and str(item.get("run_id") or "") != current_run_id:
            continue

        if keyword:
            text_parts = [
                str(item.get("material_id") or ""),
                str(item.get("run_id") or ""),
                str(item.get("review_status") or ""),
                str(item.get("launch_status") or ""),
                str(item.get("source_type") or ""),
                str((item.get("copy") or {}).get("headline") or ""),
                str((item.get("copy") or {}).get("primary_text") or ""),
                str(item.get("landing_page_url") or ""),
            ]
            haystack = " ".join(text_parts).lower()
            if keyword not in haystack:
                continue
        filtered.append(item)
    filtered.sort(key=lambda record: str(record.get("updated_at") or record.get("created_at") or ""), reverse=True)
    return filtered

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
    output_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
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
        st.caption(f"默认配置文件：{APP_DEFAULTS_CONFIG_PATH}")
        st.caption(f"运行调参文件：{RUNTIME_TUNABLES_CONFIG_PATH}")
        st.caption(f"提示词模板文件：{PROMPT_TEMPLATES_CONFIG_PATH}")
        st.caption(f"广告业务配置：{AD_OPS_CONFIG_PATH}")
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

        ad_summary = material_status_summary()
        ad_inventory = inventory_snapshot()
        st.markdown("## 广告库存")
        st.metric("可用素材", ad_inventory["ready_materials"])
        st.metric("待审核素材", ad_summary["pending_review"])


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
    st.caption(f"当前默认参数配置文件：{APP_DEFAULTS_CONFIG_PATH}")
    st.caption("当前交互输入建议使用中文；系统会在调用模型前自动翻译成英文，再进入脚本/分镜/视频生成链路。")

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

    input_left, input_right = st.columns(2)
    with input_left:
        product_name = st.text_input(
            "可编辑 | 产品名称",
            value=st.session_state["inputs"]["product_name"],
            key=_brief_widget_key("product_name"),
        )
        product_category = st.text_input(
            "可编辑 | 产品品类",
            value=st.session_state["inputs"]["product_category"],
            key=_brief_widget_key("product_category"),
        )
        campaign_goal = st.text_area(
            "可编辑 | 投放目标",
            value=st.session_state["inputs"]["campaign_goal"],
            height=90,
            key=_brief_widget_key("campaign_goal"),
        )
        target_market = st.text_input(
            "可编辑 | 目标市场",
            value=st.session_state["inputs"]["target_market"],
            key=_brief_widget_key("target_market"),
        )
        target_audience = st.text_area(
            "可编辑 | 目标受众",
            value=st.session_state["inputs"]["target_audience"],
            height=110,
            key=_brief_widget_key("target_audience"),
        )
        language = st.selectbox(
            "可编辑 | 输出语言",
            options=LANGUAGE_OPTIONS,
            index=LANGUAGE_OPTIONS.index(st.session_state["inputs"]["language"])
            if st.session_state["inputs"]["language"] in LANGUAGE_OPTIONS
            else 0,
            key=_brief_widget_key("language"),
        )
        desired_scene_count = st.slider(
            "可编辑 | 目标场景数",
            min_value=4,
            max_value=6,
            value=int(st.session_state["inputs"]["desired_scene_count"]),
            key=_brief_widget_key("desired_scene_count"),
        )
        preferred_runtime_seconds = st.slider(
            "可编辑 | 目标总时长（秒）",
            min_value=20,
            max_value=36,
            value=int(st.session_state["inputs"]["preferred_runtime_seconds"]),
            key=_brief_widget_key("preferred_runtime_seconds"),
        )
    with input_right:
        core_selling_points = st.text_area(
            "可编辑 | 核心卖点",
            value=st.session_state["inputs"]["core_selling_points"],
            height=120,
            key=_brief_widget_key("core_selling_points"),
        )
        use_scenarios = st.text_area(
            "可编辑 | 使用场景",
            value=st.session_state["inputs"]["use_scenarios"],
            height=120,
            key=_brief_widget_key("use_scenarios"),
        )
        style_preset = st.selectbox(
            "可编辑 | 风格模板",
            options=list(STYLE_PRESETS.keys()),
            index=list(STYLE_PRESETS.keys()).index(st.session_state["inputs"]["style_preset"]),
            key=_brief_widget_key("style_preset"),
        )
        custom_style_notes = st.text_area(
            "可编辑 | 自定义风格说明",
            value=st.session_state["inputs"]["custom_style_notes"],
            height=100,
            key=_brief_widget_key("custom_style_notes"),
        )
        style_tone = st.text_input(
            "可编辑 | 风格语气",
            value=st.session_state["inputs"]["style_tone"],
            key=_brief_widget_key("style_tone"),
        )
        consistency_anchor = st.text_area(
            "可编辑 | 产品一致性锚点",
            value=st.session_state["inputs"]["consistency_anchor"],
            height=110,
            key=_brief_widget_key("consistency_anchor"),
        )
        additional_info = st.text_area(
            "可编辑 | 补充说明",
            value=st.session_state["inputs"]["additional_info"],
            height=110,
            key=_brief_widget_key("additional_info"),
        )
        video_orientation = st.selectbox(
            "可编辑 | 画幅比例",
            options=VIDEO_ORIENTATION_OPTIONS,
            index=VIDEO_ORIENTATION_OPTIONS.index(st.session_state["inputs"]["video_orientation"])
            if st.session_state["inputs"]["video_orientation"] in VIDEO_ORIENTATION_OPTIONS
            else 0,
            key=_brief_widget_key("video_orientation"),
        )

    upload_files = st.file_uploader(
        "可编辑 | 上传轮椅参考图，可多张",
        type=["png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True,
        key=_brief_widget_key("reference_images"),
    )

    st.markdown("### 提示词策略台")
    st.write("先选策略，再补一句人话。系统会自动整理成后续脚本、分镜和视频共用的提示词字段。")
    strategy_cols = st.columns([1, 1])
    with strategy_cols[0]:
        optimization_selection = st.multiselect(
            "优化方向",
            options=optimization_labels(),
            default=_coerce_list(st.session_state["inputs"].get("prompt_optimization_directions")),
            key=_brief_widget_key("prompt_optimization_directions"),
            help="用于快速确定这条视频更偏冷启动测试、真实性、卖点展示还是情绪转化。",
        )
        if optimization_selection:
            for item in selected_optimization_directions(optimization_selection):
                with st.container(border=True):
                    st.markdown(f"**{item['label']}**")
                    st.caption(item["description"])
        else:
            st.info("至少选 1 个优化方向，后面的建议会更明确。")

    with strategy_cols[1]:
        error_selection = st.multiselect(
            "错误实例",
            options=error_example_labels(),
            default=_coerce_list(st.session_state["inputs"].get("prompt_error_examples")),
            key=_brief_widget_key("prompt_error_examples"),
            help="把你最怕出现的问题显式写进去，系统会自动转成错误约束。",
        )
        if error_selection:
            for item in selected_error_examples(error_selection):
                with st.container(border=True):
                    st.markdown(f"**{item['label']}**")
                    st.caption(f"常见问题：{item['symptom']}")
                    st.code(item["prompt_fix"], language="text")
        else:
            st.info("如果模型常在某些地方翻车，直接在这里勾出来。")

    manual_cols = st.columns(3)
    with manual_cols[0]:
        prompt_scene_description_manual = st.text_area(
            "手动补充 | 场景路线和世界观",
            value=_prompt_manual_default("prompt_scene_description_manual"),
            height=140,
            key=_brief_widget_key("prompt_scene_description_manual"),
            help="这里补你想强塞给所有场景的路线感、空间关系和整体叙事。",
        )
    with manual_cols[1]:
        prompt_special_emphasis_manual = st.text_area(
            "手动补充 | 重点卖点和镜头关注点",
            value=_prompt_manual_default("prompt_special_emphasis_manual"),
            height=140,
            key=_brief_widget_key("prompt_special_emphasis_manual"),
            help="这里补最想让模型重视的产品可见度、人物状态和转化重点。",
        )
    with manual_cols[2]:
        prompt_error_notes_manual = st.text_area(
            "手动补充 | 易出错点",
            value=_prompt_manual_default("prompt_error_notes_manual"),
            height=140,
            key=_brief_widget_key("prompt_error_notes_manual"),
            help="这里补项目特有的翻车点。系统还会叠加代码里的默认错误约束。",
        )

    prompt_preview = _build_prompt_editor_preview(
        optimization_selection=optimization_selection,
        error_selection=error_selection,
        manual_scene_notes=prompt_scene_description_manual,
        manual_special_emphasis=prompt_special_emphasis_manual,
        manual_error_notes=prompt_error_notes_manual,
    )
    preview_cols = st.columns(3)
    with preview_cols[0]:
        st.markdown("**系统最终写入 | 场景描述补充**")
        st.code(prompt_preview["prompt_scene_description_notes"] or "未补充", language="text")
    with preview_cols[1]:
        st.markdown("**系统最终写入 | 特殊点强调**")
        st.code(prompt_preview["prompt_special_emphasis"] or "未补充", language="text")
    with preview_cols[2]:
        st.markdown("**系统最终写入 | 错误约束补充**")
        st.code(prompt_preview["prompt_error_notes"] or "未补充", language="text")
    st.caption("保存后会把上面三块最终文本写入正式简报字段，生成脚本、分镜和视频时统一复用。")

    submitted = st.button("保存简报", use_container_width=True, key=_brief_widget_key("save"))

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
            "prompt_scene_description_notes": prompt_preview["prompt_scene_description_notes"],
            "prompt_special_emphasis": prompt_preview["prompt_special_emphasis"],
            "prompt_error_notes": prompt_preview["prompt_error_notes"],
            "prompt_scene_description_manual": prompt_scene_description_manual,
            "prompt_special_emphasis_manual": prompt_special_emphasis_manual,
            "prompt_error_notes_manual": prompt_error_notes_manual,
            "prompt_optimization_directions": optimization_selection,
            "prompt_error_examples": error_selection,
            "language": language,
            "video_orientation": video_orientation,
            "desired_scene_count": desired_scene_count,
            "preferred_runtime_seconds": preferred_runtime_seconds,
            "reference_style": st.session_state.get("reference_style", ""),
        }
        st.session_state["reference_image_paths"] = (
            persist_uploaded_files(upload_files)
            if upload_files
            else _coerce_list(st.session_state.get("reference_image_paths"))
        )
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
                with st.expander("查看本场景最终图片提示词", expanded=False):
                    if frame.get("image_prompt"):
                        st.code(frame["image_prompt"], language="text")
                    if frame.get("image_prompt_mode"):
                        st.caption(f"组装方式：{frame['image_prompt_mode']} | 模型：{frame.get('image_prompt_model', '')}")
                    if frame.get("image_prompt_composer_bundle"):
                        st.json(frame["image_prompt_composer_bundle"])
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
            with st.expander("查看本场景最终视频提示词", expanded=False):
                if scene_result.get("video_prompt"):
                    st.code(scene_result["video_prompt"], language="text")


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
        st.markdown("### 下一步")
        st.write("正式成片已经准备好。这里可以直接把当前 Run 一键接入 Meta；如果中途被平台限制拦住，也会明确告诉你卡在哪一步。")
        next_cols = st.columns(2)
        if next_cols[0].button("当前 Run 一键上传到 Meta", use_container_width=True):
            with st.spinner("正在把当前成片接入 Meta 链路..."):
                try:
                    upload_report = stage_run_output_to_meta(
                        run_id=str(st.session_state.get("run_id") or ""),
                        final_video_result=final_result,
                        script=st.session_state.get("script"),
                        ti_intro=st.session_state.get("ti_intro"),
                        source_inputs=st.session_state.get("inputs"),
                    )
                    st.session_state["last_meta_stage_result"] = upload_report
                except Exception as exc:
                    st.session_state["last_meta_stage_result"] = {
                        "status": "partial_failure",
                        "material_id": "",
                        "failed_step": "register",
                        "steps": [
                            {
                                "step": "register",
                                "label": "写入 Meta 暂存池",
                                "status": "failed",
                                "message": str(exc),
                            }
                        ],
                        "meta_mapping": {},
                    }
        if next_cols[1].button("进入广告运营", use_container_width=True):
            st.session_state["active_step"] = "广告运营"
            st.session_state["active_step_nav"] = "广告运营"
            st.session_state["active_step_nav_synced"] = "广告运营"
            st.rerun()

        _render_meta_stage_report(st.session_state.get("last_meta_stage_result"))

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


def render_ad_ops_tab() -> None:
    st.subheader("7. 广告运营")
    st.write("这里统一处理 Meta 暂存池入库、关停预上架、审核、Agent 扫描和 Dry Run 测试。生成完成的视频会直接进入 Meta，PAUSED 状态即视为库存。")
    st.caption(f"广告业务配置文件：{AD_OPS_CONFIG_PATH}")

    meta_ads_config = _coerce_dict(AD_OPS_CONFIG.get("meta_ads"))
    monitor_rules = _coerce_dict(AD_OPS_CONFIG.get("monitor_rules"))
    inventory = inventory_snapshot()
    status_summary = material_status_summary()
    all_materials = list_material_records()
    recent_alerts = list_recent_alerts(limit=5)

    if bool(meta_ads_config.get("dry_run_mode")):
        st.warning("当前 Meta 处于 Dry Run 模式：可以完整演练素材入库、预上架和 Agent 监控流程，但不会真的创建线上广告。")
    else:
        st.success("当前 Meta 为真实请求模式。执行预上架前，请确认账号、广告组、主页和落地页都已经配置正确。")

    metric_cols = st.columns(6)
    metric_cols[0].metric("素材总数", status_summary["total_materials"])
    metric_cols[1].metric("可用库存", inventory["ready_materials"])
    metric_cols[2].metric("待审核", status_summary["pending_review"])
    metric_cols[3].metric("已预上架", status_summary["prelaunched_paused"])
    metric_cols[4].metric("运行中广告", status_summary["active"])
    metric_cols[5].metric("失败归档", status_summary["archived_failed"])

    if inventory["needs_generation"]:
        st.warning(
            f"当前库存低于安全线，建议至少补量生成 {inventory['recommended_generation_count']} 条素材，"
            f"把可用库存拉回到目标值 {inventory['target_ready_materials']}。"
        )
    else:
        st.info(
            f"当前可用库存 {inventory['ready_materials']} 条，已接近或达到目标库存 {inventory['target_ready_materials']} 条，可以优先推进审核、预上架和复盘。"
        )

    current_run_result = st.session_state.get("final_video_result")
    if isinstance(current_run_result, dict) and current_run_result.get("video_path"):
        with st.container(border=True):
            st.markdown("#### 当前 Run 快捷操作")
            st.caption(
                f"当前 Run 已有正式成片：{st.session_state.get('run_id', '')}。如果要把这一条内容接入广告链路，直接上传到 Meta 并保持关停即可。"
            )
            if st.button("当前 Run 上传到 Meta 暂存池（关停）", use_container_width=True):
                try:
                    st.session_state["last_meta_stage_result"] = stage_run_output_to_meta(
                        run_id=str(st.session_state.get("run_id") or ""),
                        final_video_result=current_run_result,
                        script=st.session_state.get("script"),
                        ti_intro=st.session_state.get("ti_intro"),
                        source_inputs=st.session_state.get("inputs"),
                    )
                except Exception as exc:
                    st.session_state["last_meta_stage_result"] = {
                        "status": "partial_failure",
                        "material_id": "",
                        "failed_step": "register",
                        "steps": [
                            {
                                "step": "register",
                                "label": "写入 Meta 暂存池",
                                "status": "failed",
                                "message": str(exc),
                            }
                        ],
                        "meta_mapping": {},
                    }
            _render_meta_stage_report(st.session_state.get("last_meta_stage_result"))
    else:
        st.info("当前 Run 还没有正式成片。你仍然可以在这个页签查看 Meta 暂存池状态、审核素材、运行 Agent 和执行 Dry Run 测试。")

    library_tab, ops_tab, archive_tab = st.tabs(["Meta 暂存池", "运营操作", "归档复盘"])

    with library_tab:
        st.markdown("#### Meta 暂存池筛选")
        filter_cols = st.columns([1.6, 1, 1, 1, 0.9])
        keyword = filter_cols[0].text_input(
            "搜索",
            value="",
            placeholder="按素材ID / Run ID / 标题 / 文案关键词搜索",
            key="material_filter_keyword",
        )
        review_options = ["全部"] + sorted({str(item.get("review_status") or "") for item in all_materials if item.get("review_status")})
        review_filter = filter_cols[1].selectbox("审核状态", review_options, key="material_review_filter")
        launch_options = ["全部"] + sorted({str(item.get("launch_status") or "") for item in all_materials if item.get("launch_status")})
        launch_filter = filter_cols[2].selectbox("投放状态", launch_options, key="material_launch_filter")
        source_options = ["全部"] + sorted({str(item.get("source_type") or "") for item in all_materials if item.get("source_type")})
        source_filter = filter_cols[3].selectbox("素材来源", source_options, key="material_source_filter")
        only_current_run = filter_cols[4].checkbox(
            "仅当前 Run",
            value=False,
            key="material_filter_current_run_only",
            disabled=not bool(st.session_state.get("run_id")),
        )

        filtered_materials = _filter_material_records(
            all_materials,
            keyword=keyword,
            review_status=review_filter,
            launch_status=launch_filter,
            source_type=source_filter,
            only_current_run=only_current_run,
            current_run_id=str(st.session_state.get("run_id") or ""),
        )

        st.caption(f"筛选结果：{len(filtered_materials)} 条。默认按最近更新时间倒序展示。")
        if filtered_materials:
            st.dataframe(_build_material_table_rows(filtered_materials[:20]), use_container_width=True, hide_index=True)

            material_options = {
                item["material_id"]: item
                for item in filtered_materials
                if isinstance(item, dict) and item.get("material_id")
            }
            selected_material_id = st.selectbox(
                "选择 Meta 暂存素材查看详情",
                list(material_options.keys()),
                format_func=lambda value: _material_option_label(material_options[value]),
                key="selected_material_id_for_ops",
            )
            selected_material = load_material_record(selected_material_id)
            copy_block = _coerce_dict(selected_material.get("copy"))
            performance = _coerce_dict(selected_material.get("performance_snapshot"))
            meta_mapping = _coerce_dict(selected_material.get("meta_mapping"))
            history = _coerce_list(selected_material.get("history"))

            detail_left, detail_right = st.columns([1.1, 0.9])
            with detail_left:
                st.markdown("#### 暂存素材详情")
                info_cols = st.columns(3)
                info_cols[0].metric("审核状态", str(selected_material.get("review_status") or "-"))
                info_cols[1].metric("投放状态", str(selected_material.get("launch_status") or "-"))
                info_cols[2].metric("来源", str(selected_material.get("source_type") or "-"))
                st.caption(f"素材 ID：{selected_material_id}")
                st.caption(f"所属 Run：{selected_material.get('run_id') or '无'}")
                st.caption(f"最近更新时间：{_material_time_label(selected_material)}")
                if selected_material.get("landing_page_url"):
                    st.caption(f"落地页：{selected_material.get('landing_page_url')}")
                if selected_material.get("pause_reason"):
                    st.warning(f"暂停原因：{selected_material.get('pause_reason')}")
                if selected_material.get("archive_bucket"):
                    st.info(
                        f"归档桶：{selected_material.get('archive_bucket')} | 原因：{selected_material.get('archive_reason') or '未记录'}"
                    )

            with detail_right:
                st.markdown("#### 视频预览")
                storage_uri = str(selected_material.get("storage_uri") or "").strip()
                if storage_uri and Path(storage_uri).exists():
                    st.video(storage_uri)
                    st.caption(storage_uri)
                else:
                    st.info("当前素材没有可播放的视频文件。")

            detail_tabs = st.tabs(["文案信息", "表现快照", "事件历史"])
            with detail_tabs[0]:
                st.text_area("标题", value=str(copy_block.get("headline") or ""), height=80, disabled=True)
                st.text_area("主文案", value=str(copy_block.get("primary_text") or ""), height=120, disabled=True)
                st.text_area("补充描述", value=str(copy_block.get("description") or ""), height=80, disabled=True)
                st.caption(f"CTA：{copy_block.get('cta') or ''}")
                if copy_block.get("tags"):
                    st.caption(f"标签：{', '.join([str(tag) for tag in copy_block.get('tags', [])])}")
            with detail_tabs[1]:
                perf_cols = st.columns(5)
                perf_cols[0].metric("花费", performance.get("spend", 0.0))
                perf_cols[1].metric("CTR", performance.get("ctr", 0.0))
                perf_cols[2].metric("加购", performance.get("add_to_cart", 0.0))
                perf_cols[3].metric("出单", performance.get("purchases", 0.0))
                perf_cols[4].metric("ROAS", performance.get("roas", 0.0))
                st.json(
                    {
                        "meta_mapping": meta_mapping,
                        "performance_snapshot": performance,
                        "ad_enable_status": selected_material.get("ad_enable_status"),
                        "target_adset_id": selected_material.get("target_adset_id"),
                        "page_id": selected_material.get("page_id"),
                    }
                )
            with detail_tabs[2]:
                if history:
                    for event in reversed(history[-12:]):
                        st.caption(f"{event.get('time', '')} | {event.get('type', '')}")
                        if event.get("payload"):
                            st.json(event.get("payload"))
                else:
                    st.caption("这条素材还没有事件历史。")

            review_note = st.text_input(
                "审核备注",
                value=str(selected_material.get("review_note") or ""),
                key=f"review_note_input_{selected_material_id}",
            )
            review_cols = st.columns(3)
            if review_cols[0].button("审核通过", use_container_width=True, key=f"approve_{selected_material_id}"):
                update_material_record(
                    selected_material_id,
                    {"review_status": "approved", "review_note": review_note or "approved in streamlit"},
                )
                st.success(f"{selected_material_id} 已标记为 approved")
                st.rerun()
            if review_cols[1].button("驳回素材", use_container_width=True, key=f"reject_{selected_material_id}"):
                update_material_record(
                    selected_material_id,
                    {"review_status": "rejected", "review_note": review_note or "rejected in streamlit"},
                )
                st.warning(f"{selected_material_id} 已标记为 rejected")
                st.rerun()
            if review_cols[2].button("恢复待审核", use_container_width=True, key=f"reset_{selected_material_id}"):
                update_material_record(
                    selected_material_id,
                    {"review_status": "pending_review", "review_note": review_note or "reset in streamlit"},
                )
                st.info(f"{selected_material_id} 已恢复为 pending_review")
                st.rerun()
        else:
            st.info("当前筛选条件下没有素材。可以先放宽筛选，或者先把当前 Run 上传到 Meta 暂存池。")

    with ops_tab:
        st.markdown("#### 运营操作台")
        summary_cols = st.columns(3)
        summary_cols[0].metric("库存目标", inventory["target_ready_materials"])
        summary_cols[1].metric("建议补量", inventory["recommended_generation_count"])
        summary_cols[2].metric("轮询频率", f"{monitor_rules.get('monitor_interval_minutes', 60)} 分钟")

        st.caption(
            f"默认广告账户：{meta_ads_config.get('ad_account_id', '')} | "
            f"默认广告组：{', '.join([str(item) for item in meta_ads_config.get('default_target_adset_ids', [])])} | "
            f"默认落地页：{meta_ads_config.get('default_landing_page_url', '')}"
        )

        action_cols = st.columns(2)
        if action_cols[0].button("广告 Agent 扫描一次", use_container_width=True):
            try:
                result = run_agent_once()
                st.session_state["last_agent_run_result"] = result
                st.success("Agent 扫描完成。")
            except Exception as exc:
                st.error(f"Agent 扫描失败：{exc}")

        if action_cols[1].button("执行 Dry Run 全链路测试", use_container_width=True):
            try:
                result = run_full_dry_run_test()
                st.session_state["last_dry_run_result"] = result
                st.success("Dry Run 测试完成。")
            except Exception as exc:
                st.error(f"Dry Run 测试失败：{exc}")

        config_cols = st.columns(2)
        with config_cols[0]:
            with st.expander("查看运营规则摘要", expanded=False):
                st.json(
                    {
                        "target_active_ads_per_adset": monitor_rules.get("target_active_ads_per_adset"),
                        "min_impressions": monitor_rules.get("min_impressions"),
                        "min_ctr": monitor_rules.get("min_ctr"),
                        "min_atc": monitor_rules.get("min_atc"),
                        "min_roas": monitor_rules.get("min_roas"),
                        "winner_purchase_count": monitor_rules.get("winner_purchase_count"),
                    }
                )
        with config_cols[1]:
            with st.expander("最近告警", expanded=False):
                if recent_alerts:
                    for alert in recent_alerts:
                        st.caption(f"{alert.get('created_at', '')} | {alert.get('alert_type', '')}")
                        st.write(alert.get("message", ""))
                else:
                    st.caption("最近没有告警。")

        if st.session_state.get("last_agent_run_result"):
            with st.expander("最近一次 Agent 扫描结果", expanded=False):
                st.json(st.session_state["last_agent_run_result"])

        if st.session_state.get("last_dry_run_result"):
            with st.expander("最近一次 Dry Run 结果", expanded=False):
                st.json(st.session_state["last_dry_run_result"])

    with archive_tab:
        st.markdown("#### 成功 / 失败素材复盘")
        st.caption("这里把归档结果按成功与失败做简单特征聚合，帮助你们调整下一轮生成方向。")

        archive_summary = st.session_state.get("archive_feature_summary")
        if archive_summary is None and (status_summary["archived_success"] or status_summary["archived_failed"]):
            try:
                archive_summary = build_archive_feature_summary()
                st.session_state["archive_feature_summary"] = archive_summary
            except Exception:
                archive_summary = None

        if st.button("刷新归档特征总结", use_container_width=True):
            try:
                archive_summary = build_archive_feature_summary()
                st.session_state["archive_feature_summary"] = archive_summary
                st.success("归档总结已刷新。")
            except Exception as exc:
                st.error(f"刷新归档总结失败：{exc}")

        archive_metric_cols = st.columns(2)
        archive_metric_cols[0].metric("成功归档", status_summary["archived_success"])
        archive_metric_cols[1].metric("失败归档", status_summary["archived_failed"])

        if archive_summary:
            insight_cols = st.columns(2)
            with insight_cols[0]:
                st.markdown("**成功素材特征**")
                st.json(
                    {
                        "success_style_presets": archive_summary.get("success_style_presets", {}),
                        "success_markets": archive_summary.get("success_markets", {}),
                    }
                )
            with insight_cols[1]:
                st.markdown("**失败素材特征**")
                st.json(
                    {
                        "failed_style_presets": archive_summary.get("failed_style_presets", {}),
                        "failed_markets": archive_summary.get("failed_markets", {}),
                    }
                )
            with st.expander("查看完整归档总结 JSON", expanded=False):
                st.json(archive_summary)
        else:
            st.info("当前还没有可用于复盘的归档数据。等广告进入 success / failed 归档后，这里会自动开始形成总结。")


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
    elif active_step == "广告运营":
        render_ad_ops_tab()
    render_sidebar()


if __name__ == "__main__":
    main()
