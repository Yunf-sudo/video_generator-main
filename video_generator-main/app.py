from __future__ import annotations

import copy
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
from quick_cut import quick_cut_video, upload_all_videos_to_rustfs
from ti_intro_generate_tools import generate_ti_intro
from youtube_fetch.youtube_video_analysis import analyze_video


BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"

STYLE_PRESETS = {
    "产品演示型": "真实、高级、产品中心构图，突出电动操控、稳定和舒适，适合商务演示与客户沟通。",
    "渠道招商型": "镜头更偏成交导向，强调产品卖点、采购场景和合作价值，节奏更利落。",
    "家庭关怀型": "画面更温暖，突出日常代步、省力和陪伴感，但仍保持真实可信。",
    "机构采购型": "突出稳重、专业、耐看，适合康复机构、医院和养老场景展示。",
}

DEFAULT_INPUTS = {
    "product_name": "电动轮椅",
    "product_category": "电动轮椅 / 出行辅助设备",
    "campaign_goal": "生成一条适合产品演示、短视频传播、客户沟通和成交辅助的完整广告视频",
    "target_market": "中国",
    "target_audience": "行动不便长者家庭、康复机构、医院、养老场景采购方、经销与代理渠道",
    "core_selling_points": "- 电动驱动更省力\n- 座椅与靠背舒适性更好\n- 通行和转向更稳定\n- 适合演示、沟通和成交转化",
    "use_scenarios": "- 小区与园区通行\n- 医院和康复中心\n- 商场与室内场景\n- 家庭日常出行与接送",
    "style_preset": "产品演示型",
    "custom_style_notes": STYLE_PRESETS["产品演示型"],
    "style_tone": "真实可信、专业克制、产品演示导向、带一点温度",
    "consistency_anchor": "同一台深色电动轮椅，保持一致的车架、扶手、脚踏、轮胎尺寸、操控杆、靠背与坐垫细节，不能在不同镜头里变成别的轮椅。",
    "additional_info": "必须保持同一台轮椅的产品一致性。优先做真实产品演示和使用场景说明，避免夸张医疗承诺。",
    "language": "Chinese",
    "video_orientation": "9:16",
    "desired_scene_count": 5,
    "preferred_runtime_seconds": 28,
    "reference_style": "",
}

MODEL_SUMMARY = {
    "脚本": os.getenv("SCRIPT_MODEL", "gpt-5-mini"),
    "分镜图": os.getenv("IMAGE_MODEL", "gpt-image-1-all"),
    "视频": os.getenv("VIDEO_MODEL", "veo_3_1-lite"),
    "TTS": os.getenv("TTS_MODEL", "gpt-4o-mini-tts"),
    "竞品分析": os.getenv("YOUTUBE_ANALYSIS_MODEL", "gpt-5-mini"),
}


st.set_page_config(page_title="电动轮椅广告工作台", layout="wide")


def _coerce_dict(value):
    return value if isinstance(value, dict) else {}


def init_state() -> None:
    defaults = {
        "inputs": copy.deepcopy(DEFAULT_INPUTS),
        "reference_style": "",
        "competitor_video_id": "",
        "reference_image_paths": [],
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
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    saved_paths = []
    for file in upload_files or []:
        unique_name = f"ref_{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.name}"
        out_path = UPLOAD_DIR / unique_name
        out_path.write_bytes(file.read())
        saved_paths.append(str(out_path))
    return saved_paths


def scene_list(script: dict | None) -> list[dict]:
    if not script:
        return []
    scenes_root = script.get("scenes")
    if isinstance(scenes_root, dict):
        return scenes_root.get("scenes", [])
    return []


def ordered_storyboard() -> list[dict]:
    return sorted(st.session_state.get("storyboard", []), key=lambda item: int(item["scene_number"]))


def ordered_video_results() -> list[tuple[str, dict]]:
    return sorted(st.session_state.get("video_result", {}).items(), key=lambda item: int(item[0]))


def ordered_clip_paths() -> list[str]:
    return [item["video_path"] for _, item in ordered_video_results() if item.get("video_path")]


def ready_clip_count() -> int:
    return sum(1 for _, item in ordered_video_results() if item.get("video_path"))


def remote_clip_count() -> int:
    return sum(1 for _, item in ordered_video_results() if item.get("generation_mode") == "remote")


def local_preview_clip_count() -> int:
    return sum(1 for _, item in ordered_video_results() if item.get("generation_mode") == "local")


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


def generate_script_step() -> None:
    script, messages = generate_scripts(st.session_state["inputs"])
    st.session_state["script"] = script
    st.session_state["script_chat_messages"] = messages
    reset_downstream("script")


def generate_storyboard_step() -> None:
    storyboard = generate_storyboard(
        st.session_state["script"],
        reference_image_paths=st.session_state.get("reference_image_paths", []),
        aspect_ratio=st.session_state["inputs"]["video_orientation"],
    )
    st.session_state["storyboard"] = storyboard
    reset_downstream("storyboard")


def submit_all_missing_clips() -> None:
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
            continuity=frame.get("continuity"),
            last_frame=last_reference_frame,
            until_finish=False,
            aspect_ratio=st.session_state["inputs"]["video_orientation"],
            duration_seconds=frame.get("duration_seconds", 5),
            force_local=False,
        )
        current_results[scene_key] = clip_result
        last_reference_frame = frame["saved_path"]

    st.session_state["video_result"] = current_results
    reset_downstream("clips")


def resolve_all_pending_clips() -> None:
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
                continuity=frame.get("continuity"),
                last_frame=current.get("last_frame_path") or last_reference_frame,
                until_finish=True,
                aspect_ratio=st.session_state["inputs"]["video_orientation"],
                duration_seconds=frame.get("duration_seconds", 5),
                force_local=False,
            )
        refreshed["planned_duration_seconds"] = current.get("planned_duration_seconds", frame.get("duration_seconds", 5))
        current_results[scene_key] = refreshed
        last_reference_frame = refreshed.get("last_frame_path") or last_reference_frame or frame["saved_path"]
    st.session_state["video_result"] = current_results


def generate_metadata_step() -> None:
    ti_intro, _ = generate_ti_intro(st.session_state["script"])
    st.session_state["ti_intro"] = ti_intro


def generate_tts_step() -> None:
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


def generate_subtitles_step() -> None:
    tts_result = _coerce_dict(st.session_state.get("tts_result"))
    if not tts_result.get("audio_url"):
        raise RuntimeError("请先生成配音。")
    scene_duration_map = build_target_scene_duration_map()
    srt_url, srt_path = generate_srt_asset_from_audio(
        tts_result["audio_url"],
        script=st.session_state["script"],
        duration_seconds=tts_result.get("duration_seconds") or tts_result.get("duration"),
        scene_duration_map=scene_duration_map or None,
    )
    st.session_state["tts_result"] = {
        **tts_result,
        "srt_url": srt_url,
        "srt_path": srt_path,
    }


def export_formal_video_step() -> None:
    if not all_clips_remote_ready():
        raise RuntimeError("还有场景不是远端动态片段，正式成片暂时不能导出。")
    output_name = f"song-wheelchair-{datetime.now().strftime('%m%d-%H%M')}.mp4"
    scene_duration_map = build_target_scene_duration_map()
    st.session_state["final_video_result"] = assemble_final_video(
        ordered_clip_paths(),
        audio_path=st.session_state.get("tts_result", {}).get("file_path"),
        srt_path=st.session_state.get("tts_result", {}).get("srt_path"),
        filename=output_name,
        scene_duration_map=scene_duration_map or None,
    )


def run_full_pipeline() -> None:
    if not st.session_state.get("script"):
        generate_script_step()
    if not ordered_storyboard():
        generate_storyboard_step()
    submit_all_missing_clips()
    resolve_all_pending_clips()
    generate_metadata_step()
    generate_tts_step()
    generate_subtitles_step()
    export_formal_video_step()


def render_sidebar() -> None:
    with st.sidebar:
        st.markdown("## 当前状态")
        st.metric("脚本场景数", len(scene_list(st.session_state.get("script"))))
        st.metric("分镜数量", len(st.session_state.get("storyboard", [])))
        st.metric("已完成片段", ready_clip_count())
        st.metric("远端动态片段", remote_clip_count())
        st.metric("本地预览片段", local_preview_clip_count())

        st.markdown("## 当前模型")
        for label, model_name in MODEL_SUMMARY.items():
            st.caption(f"{label}: {model_name}")

        st.markdown("## 快捷操作")
        if st.button("一键生成正式版", use_container_width=True):
            with st.spinner("正在从简报一路跑到正式成片，这会持续几分钟到十几分钟不等..."):
                try:
                    run_full_pipeline()
                    st.success("正式版流程已跑完。")
                except Exception as exc:
                    st.error(f"一键流程失败：{exc}")


def render_header() -> None:
    st.title("电动轮椅广告工作台")
    st.caption("围绕同一台电动轮椅生成脚本、分镜、远端动态片段、配音字幕和最终成片。")

    cols = st.columns(5)
    cols[0].metric("脚本场景数", len(scene_list(st.session_state.get("script"))))
    cols[1].metric("分镜数量", len(st.session_state.get("storyboard", [])))
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
        if upload_files:
            st.session_state["reference_image_paths"] = persist_uploaded_files(upload_files)
        st.success("产品简报已保存。")

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

    st.markdown(f"### {script['scenes']['main_theme']}")
    for scene in scenes:
        with st.container(border=True):
            st.markdown(f"**场景 {scene['scene_number']} | {scene['duration_seconds']}s | {scene['theme']}**")
            st.write(scene["scene_description"])
            st.caption(f"镜头：{scene['visuals']['camera_movement']}")
            st.caption(f"灯光：{scene['visuals']['lighting']}")
            st.caption(f"构图：{scene['visuals']['composition_and_set_dressing']}")
            st.write(f"旁白：{scene['audio']['text']}")
            st.caption(f"关键信息：{scene['key_message']}")

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
    st.subheader("6. 导出与剪映")
    ready_paths = ordered_clip_paths()
    if not ready_paths:
        st.info("请先生成视频片段。")
        return

    if not all_clips_remote_ready():
        st.warning("当前还不是全远端动态片段，正式成片暂时锁定。请继续刷新远端状态，直到全部场景都显示为远端动态片段。")
    else:
        if st.button("导出正式成片", use_container_width=True):
            with st.spinner("正在导出正式成片..."):
                try:
                    export_formal_video_step()
                    st.success("正式成片已导出。")
                except Exception as exc:
                    st.error(f"正式成片导出失败：{exc}")

    if st.button("上传片段并导入剪映", use_container_width=True):
        try:
            uploaded_video_result = upload_all_videos_to_rustfs(st.session_state.get("video_result", {}))
            draft_id, draft_url = quick_cut_video(uploaded_video_result, _coerce_dict(st.session_state.get("tts_result")), bgm_result=None)
            st.session_state["capcut_result"] = {"draft_id": draft_id, "draft_url": draft_url}
            st.success("已导入剪映。")
        except Exception as exc:
            st.error(f"剪映导入失败：{exc}")

    final_result = st.session_state.get("final_video_result")
    if isinstance(final_result, dict) and final_result.get("video_path"):
        st.video(final_result["video_path"])
        st.caption(final_result["video_path"])

    capcut_result = st.session_state.get("capcut_result")
    if isinstance(capcut_result, dict):
        st.caption(f"剪映草稿 ID：{capcut_result.get('draft_id')}")
        st.caption(f"剪映草稿地址：{capcut_result.get('draft_url')}")


def main() -> None:
    init_state()
    render_sidebar()
    render_header()
    tabs = st.tabs(["产品简报", "广告脚本", "分镜图", "视频片段", "配音字幕", "导出与剪映"])
    with tabs[0]:
        render_brief_tab()
    with tabs[1]:
        render_script_tab()
    with tabs[2]:
        render_storyboard_tab()
    with tabs[3]:
        render_clips_tab()
    with tabs[4]:
        render_audio_tab()
    with tabs[5]:
        render_export_tab()


if __name__ == "__main__":
    main()
