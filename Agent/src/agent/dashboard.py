from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st

from agent.bundle_audit import audit_bundle_retain_set
from agent.bundle_manifest import build_bundle_manifest
from agent.generation_bridge import (
    build_generation_command_string,
    recent_generation_outputs,
    run_generation,
    validate_generation_bridge,
)
from agent.env import load_agent_env
from agent.healthcheck import run_healthcheck
from agent.history import history_summary
from agent.legacy_import import import_legacy_materials
from agent.material_loader import scan_materials
from agent.meta_monitor import run_meta_monitor


def _render_alerts(alerts: list[dict[str, str]], *, limit: int = 20) -> None:
    if not alerts:
        st.success("当前没有加载告警。")
        return
    for alert in alerts[:limit]:
        text = f"{alert.get('title', '')}: {alert.get('message', '')}"
        if alert.get("source"):
            text = f"{text}\n\n来源: {alert.get('source')}"
        level = str(alert.get("level") or "").lower()
        if level == "error":
            st.error(text)
        elif level == "warning":
            st.warning(text)
        else:
            st.success(text)


def _material_preview(records: list[dict[str, Any]]) -> None:
    if not records:
        st.info("没有可预览素材。")
        return
    options = {
        f"{item.get('material_id') or item.get('video_path') or 'unknown'} | {item.get('load_status') or ''}": item
        for item in records
    }
    selected = st.selectbox("选择素材预览", list(options.keys()))
    item = options[selected]
    video_path = str(item.get("video_path") or "").strip()
    if video_path and Path(video_path).exists():
        st.video(video_path)
        st.caption(video_path)
    else:
        st.info("当前素材没有可播放视频。")
    st.json(item)


def main(settings: dict[str, Any]) -> None:
    frontend = settings.get("frontend", {}) if isinstance(settings.get("frontend"), dict) else {}
    st.set_page_config(
        page_title=str(frontend.get("page_title") or "Anywell Agent"),
        layout=str(frontend.get("layout") or "wide"),
    )
    st.title(str(settings.get("project_name") or "Anywell Agent"))
    st.caption(f"统一配置文件：{settings.get('config_path', '')}")

    if st.session_state.get("agent_import_result"):
        st.info("历史素材已导入到 Agent 本地工作区。")
    material_result = scan_materials(settings)
    material_summary = material_result["summary"]
    env_info = load_agent_env()
    meta_result = st.session_state.get("agent_meta_result")
    health_result = st.session_state.get("agent_healthcheck_result")
    import_result = st.session_state.get("agent_import_result")
    generation_result = st.session_state.get("agent_generation_result")
    bundle_manifest = st.session_state.get("agent_bundle_manifest")
    bundle_audit = st.session_state.get("agent_bundle_audit")
    history_result = history_summary(settings)

    top_cols = st.columns(5)
    top_cols[0].metric("素材总数", material_summary["total_records"])
    top_cols[1].metric("加载成功", material_summary["loaded_count"])
    top_cols[2].metric("加载失败", material_summary["failed_count"])
    top_cols[3].metric("警告", material_summary["warning_alerts"])
    top_cols[4].metric("错误", material_summary["error_alerts"])

    overview_tab, material_tab, meta_tab, generation_tab, health_tab, history_tab, config_tab = st.tabs(
        ["概览", "素材监控", "Meta 监控", "生成桥接", "健康检查", "任务历史", "配置"]
    )

    with overview_tab:
        st.write("这个交接版目录只保留核心能力：统一配置、素材加载监控、只读 Meta 监控、生成命令桥接和健康检查。")
        env_cols = st.columns(3)
        env_cols[0].metric("Agent .env", "存在" if env_info.get("agent_env_exists") else "缺失")
        env_cols[1].metric("根目录 .env", "存在" if env_info.get("root_env_exists") else "缺失")
        env_cols[2].metric("Meta Token", "已加载" if env_info.get("meta_token_present") else "缺失")
        _render_alerts(material_result["alerts"], limit=10)

    with material_tab:
        st.subheader("素材加载监控")
        st.write("这里统一扫描 Agent 本地工作区里的素材记录和成片目录，自动判断视频是否可加载，并对缺文件、未登记素材和缩略图缺失做提醒。")
        if st.button("导入旧项目素材到 Agent", use_container_width=True):
            st.session_state["agent_import_result"] = import_legacy_materials(settings)
            import_result = st.session_state["agent_import_result"]
            material_result = scan_materials(settings)
        if import_result:
            if int(import_result.get("failed", 0) or 0) > 0:
                st.warning(f"导入完成，但有 {import_result.get('failed', 0)} 条失败。")
            else:
                st.success(f"导入完成，共导入 {import_result.get('copied', 0)} 条素材。")
            with st.expander("查看导入结果", expanded=False):
                st.json(import_result)
        _render_alerts(material_result["alerts"], limit=30)
        st.dataframe(material_result["records"], use_container_width=True, hide_index=True)
        _material_preview(material_result["records"])

    with meta_tab:
        st.subheader("Meta 只读监控")
        st.write("这里调用真实 Meta GET API 读取广告状态和表现，但不会上传素材、创建广告或修改广告状态。")
        if st.button("执行 Meta 只读扫描", use_container_width=True):
            st.session_state["agent_meta_result"] = run_meta_monitor(settings)
            meta_result = st.session_state["agent_meta_result"]
        if meta_result:
            if meta_result.get("status") == "success":
                st.success("Meta 扫描完成。")
            elif meta_result.get("status") == "blocked":
                st.warning(str(meta_result.get("message") or "Meta token 缺失。"))
            else:
                st.error(str(meta_result.get("message") or "Meta 扫描失败。"))
            for item in meta_result.get("results", []):
                cols = st.columns(4)
                cols[0].metric(f"广告组 {item.get('adset_id')}", item.get("active_ads", 0))
                cols[1].metric("备用暂停广告", item.get("paused_backup_ads", 0))
                cols[2].metric("计划动作", len(item.get("planned_actions", [])))
                cols[3].metric("日预算", f"${float(item.get('daily_budget', 0.0)):.2f}")
                if item.get("planned_actions"):
                    st.warning(f"建议动作: {item.get('planned_actions')}")
                st.dataframe(item.get("ad_reports", []), use_container_width=True, hide_index=True)
        else:
            st.info("尚未执行 Meta 扫描。")

    with generation_tab:
        st.subheader("生成桥接")
        validation = validate_generation_bridge(settings)
        outputs = recent_generation_outputs(settings)
        if validation.get("ok"):
            st.success("生成桥接校验通过。")
        else:
            st.error("生成桥接校验失败，请先修正路径。")
        st.code(build_generation_command_string(settings), language="bash")
        gen_cols = st.columns(2)
        if gen_cols[0].button("刷新生成状态", use_container_width=True):
            st.session_state["agent_generation_result"] = run_generation(settings, execute=False)
            generation_result = st.session_state["agent_generation_result"]
        if gen_cols[1].button("执行默认生成任务", use_container_width=True):
            with st.spinner("正在执行 Agent 独立生成任务..."):
                st.session_state["agent_generation_result"] = run_generation(settings, execute=True)
                generation_result = st.session_state["agent_generation_result"]

        if generation_result:
            if generation_result.get("executed"):
                if int(generation_result.get("returncode", 1) or 1) == 0:
                    st.success("生成任务执行完成。")
                else:
                    st.error(f"生成任务执行失败，returncode={generation_result.get('returncode')}")
                if generation_result.get("stdout"):
                    with st.expander("stdout", expanded=False):
                        st.code(str(generation_result.get("stdout") or ""), language="text")
                if generation_result.get("stderr"):
                    with st.expander("stderr", expanded=False):
                        st.code(str(generation_result.get("stderr") or ""), language="text")
            outputs = generation_result.get("outputs") or outputs

        st.json(validation)
        st.markdown("#### 最近生成产物")
        out_cols = st.columns(4)
        out_cols[0].metric("成片数", len(outputs.get("final_videos", [])))
        out_cols[1].metric("概念报告数", len(outputs.get("concept_reports", [])))
        out_cols[2].metric("日志文件", "存在" if outputs.get("log_exists") else "缺失")
        out_cols[3].metric("总结文件", "存在" if outputs.get("summary_exists") else "缺失")
        st.caption(f"输出目录：{outputs.get('output_root', '')}")
        if outputs.get("log_exists"):
            st.caption(f"日志：{outputs.get('log_path', '')}")
        if outputs.get("summary_exists"):
            st.caption(f"总结：{outputs.get('summary_path', '')}")
        if outputs.get("final_videos"):
            for video_path in outputs.get("final_videos", [])[-3:]:
                if Path(video_path).exists():
                    st.video(video_path)
                    st.caption(video_path)
        if outputs.get("concept_reports"):
            with st.expander("概念报告路径", expanded=False):
                st.json(outputs.get("concept_reports"))

    with health_tab:
        st.subheader("健康检查")
        st.write("健康检查会校验路径、生成桥接、素材加载，并可选执行一次 Meta 只读扫描。")
        include_meta = st.checkbox("包含 Meta 只读扫描", value=False)
        if st.button("执行健康检查", use_container_width=True):
            st.session_state["agent_healthcheck_result"] = run_healthcheck(settings, include_meta=include_meta)
            health_result = st.session_state["agent_healthcheck_result"]
        if health_result:
            st.json(health_result)
        else:
            st.info("尚未执行健康检查。")

    with history_tab:
        st.subheader("任务历史")
        summary = history_result["summary"]
        hist_cols = st.columns(4)
        hist_cols[0].metric("记录总数", summary["total"])
        hist_cols[1].metric("成功", summary["success"])
        hist_cols[2].metric("失败", summary["failed"])
        hist_cols[3].metric("阻塞", summary["blocked"])
        st.dataframe(history_result["items"], use_container_width=True, hide_index=True)

    with config_tab:
        st.subheader("当前配置")
        if st.button("刷新 bundle 清单", use_container_width=True):
            st.session_state["agent_bundle_manifest"] = build_bundle_manifest(settings)
            bundle_manifest = st.session_state["agent_bundle_manifest"]
        if st.button("审计 bundle 保留集", use_container_width=True):
            st.session_state["agent_bundle_audit"] = audit_bundle_retain_set(settings)
            bundle_audit = st.session_state["agent_bundle_audit"]
        if bundle_manifest:
            st.markdown("#### Bundle 清单")
            st.json(bundle_manifest.get("counts", {}))
            with st.expander("查看 bundle 清单详情", expanded=False):
                st.json(bundle_manifest)
        if bundle_audit:
            st.markdown("#### Bundle 裁剪审计")
            audit_cols = st.columns(3)
            audit_cols[0].metric("总文件数", int(bundle_audit.get("total_files", 0) or 0))
            audit_cols[1].metric("建议保留", int(bundle_audit.get("kept_files", 0) or 0))
            audit_cols[2].metric("建议复核", int(bundle_audit.get("review_candidate_files", 0) or 0))
            with st.expander("查看建议复核文件", expanded=False):
                st.json(bundle_audit.get("review_candidates", []))
        st.json(settings)
