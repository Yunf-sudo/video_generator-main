from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from streamlit.testing.v1 import AppTest

from agent.config import agent_root, resolve_path
from agent.env import load_agent_env
from agent.history import append_history, history_summary
from agent.material_loader import scan_materials
from agent.tts_settings import load_tts_preferences


def _meta_token() -> str:
    return (os.getenv("META_ACCESS_TOKEN") or os.getenv("FACEBOOK_ACCESS_TOKEN") or "").strip()


def frontend_validation_report_path(settings: dict[str, Any]) -> Path:
    runtime = settings.get("runtime", {}) if isinstance(settings.get("runtime"), dict) else {}
    path = resolve_path(str(runtime.get("frontend_validation_report_path") or "runtime/frontend_validation_report.json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _step(name: str, status: str, message: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "message": message,
        "payload": payload or {},
    }


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _app() -> AppTest:
    return AppTest.from_file(str((agent_root() / "app.py").resolve()), default_timeout=180)


def _check_no_exceptions(at: AppTest, context: str) -> None:
    _assert(len(at.exception) == 0, f"{context} 出现异常: {[str(item) for item in at.exception]}")


def _button(at: AppTest, label: str):
    for item in at.button:
        if getattr(item, "label", "") == label:
            return item
    raise AssertionError(f"未找到按钮: {label}")


def _checkbox(at: AppTest, label: str):
    for item in at.checkbox:
        if getattr(item, "label", "") == label:
            return item
    raise AssertionError(f"未找到复选框: {label}")


def _toggle(at: AppTest, label: str):
    for item in at.toggle:
        if getattr(item, "label", "") == label:
            return item
    raise AssertionError(f"未找到开关: {label}")


def _selectbox(at: AppTest, label: str):
    for item in at.selectbox:
        if getattr(item, "label", "") == label:
            return item
    raise AssertionError(f"未找到下拉框: {label}")


@contextmanager
def _temporary_env(overrides: dict[str, str]) -> Iterator[None]:
    sentinel = object()
    previous: dict[str, object] = {}
    for key, value in overrides.items():
        previous[key] = os.environ.get(key, sentinel)
        os.environ[key] = value
    try:
        yield
    finally:
        for key, previous_value in previous.items():
            if previous_value is sentinel:
                os.environ.pop(key, None)
            else:
                os.environ[key] = str(previous_value)


def _initial_render_step(settings: dict[str, Any]) -> dict[str, Any]:
    at = _app()
    at.run()
    _check_no_exceptions(at, "前端初始渲染")
    tab_labels = [getattr(item, "label", "") for item in at.tabs]
    button_labels = [getattr(item, "label", "") for item in at.button]
    required_top_tabs = ["概览", "素材监控", "Meta 监控", "生成桥接", "健康检查", "任务历史", "配置"]
    required_generation_subtabs = ["配音生成", "视频合成", "Meta 上传"]
    _assert(
        all(label in tab_labels for label in required_top_tabs),
        f"缺少顶层页签: {tab_labels}",
    )
    _assert(
        all(label in tab_labels for label in required_generation_subtabs),
        f"缺少生成区二级页签: {tab_labels}",
    )
    _assert("执行默认生成任务" in button_labels, "缺少生成任务按钮")
    _assert("保存 TTS 配置" in button_labels, "缺少 TTS 保存按钮")
    _assert(len(at.selectbox) >= 3, "下拉控件数量异常")
    _assert(len(at.toggle) >= 2, "预览开关数量异常")
    return _step(
        "initial_render",
        "success",
        "前端初始渲染成功，页签和基础控件完整。",
        {
            "tabs": tab_labels,
            "buttons": button_labels,
            "material_options": len(getattr(_selectbox(at, "选择素材预览"), "options", []) or []),
        },
    )


def _material_flow_step(settings: dict[str, Any]) -> dict[str, Any]:
    at = _app()
    at.run()
    _button(at, "导入旧项目素材到 Agent").click().run()
    _check_no_exceptions(at, "导入素材后")
    import_result = at.session_state["agent_import_result"]
    _assert("copied" in import_result, "导入结果缺少 copied 字段")

    _toggle(at, "加载选中素材视频预览").set_value(True).run()
    _check_no_exceptions(at, "素材预览开启后")
    materials = scan_materials(settings)
    _assert(int(materials["summary"]["total_records"]) > 0, "素材扫描结果为空")
    return _step(
        "material_flow",
        "success",
        "素材导入、扫描和预览开关联动正常。",
        {
            "import_copied": int(import_result.get("copied", 0) or 0),
            "import_failed": int(import_result.get("failed", 0) or 0),
            "material_summary": materials["summary"],
        },
    )


def _generation_flow_step() -> dict[str, Any]:
    at = _app()
    at.run()
    _button(at, "刷新生成状态").click().run()
    _check_no_exceptions(at, "刷新生成状态后")
    generation_result = at.session_state["agent_generation_result"]
    _assert(generation_result.get("executed") is False, "刷新生成状态不应触发真实生成")
    _assert(bool((generation_result.get("validation") or {}).get("ok")), "生成桥接校验失败")

    _toggle(at, "加载最近成片预览").set_value(True).run()
    _check_no_exceptions(at, "成片预览开启后")
    outputs = generation_result.get("outputs") or {}
    return _step(
        "generation_flow",
        "success",
        "生成桥接刷新正常，且未触发视频生成。",
        {
            "executed": generation_result.get("executed"),
            "final_videos": len(outputs.get("final_videos", []) or []),
            "log_exists": bool(outputs.get("log_exists")),
            "summary_exists": bool(outputs.get("summary_exists")),
        },
    )


def _tts_settings_step(settings: dict[str, Any]) -> dict[str, Any]:
    at = _app()
    at.run()
    preferences = load_tts_preferences(settings)
    _assert(len(at.selectbox) >= 3, "TTS 下拉控件未渲染")
    _button(at, "保存 TTS 配置").click().run()
    _check_no_exceptions(at, "保存 TTS 配置后")
    save_result = at.session_state["agent_tts_save_result"]
    override_path = Path(str(save_result.get("runtime_override_path") or ""))
    _assert(override_path.exists(), f"TTS 运行时覆盖文件不存在: {override_path}")
    resolved = save_result.get("resolved_tts_runtime", {})
    _assert(str(resolved.get("provider") or ""), "TTS provider 未保存")
    return _step(
        "tts_settings_flow",
        "success",
        "TTS 网页配置可保存，且运行时覆盖文件已生成。",
        {
            "runtime_override_path": str(override_path),
            "provider": resolved.get("provider"),
            "edge_voice": resolved.get("edge_voice"),
            "edge_rate_percent": preferences.get("edge_rate_percent"),
            "edge_pitch_hz": preferences.get("edge_pitch_hz"),
        },
    )


def _meta_upload_ui_step() -> dict[str, Any]:
    at = _app()
    at.run()
    _button(at, "保存上传默认值").click().run()
    _check_no_exceptions(at, "保存 Meta 上传默认值后")
    save_result = at.session_state["agent_meta_launch_save_result"]
    _assert("meta_launch" in save_result, "Meta 上传默认值缺少 meta_launch 字段")
    return _step(
        "meta_upload_ui_flow",
        "success",
        "Meta 上传默认值可在网页端保存。",
        {
            "default_upload_mode": save_result.get("meta_launch", {}).get("default_upload_mode"),
            "default_target_adset_id": save_result.get("meta_launch", {}).get("default_target_adset_id"),
        },
    )


def _healthcheck_step() -> dict[str, Any]:
    at = _app()
    at.run()
    _button(at, "执行健康检查").click().run()
    _check_no_exceptions(at, "执行健康检查后")
    result = at.session_state["agent_healthcheck_result"]
    report_path = Path(str(result.get("report_path") or ""))
    _assert(report_path.exists(), f"健康检查报告不存在: {report_path}")
    return _step(
        "healthcheck",
        "success",
        "健康检查可执行，且报告已落盘。",
        {
            "report_path": str(report_path),
            "token_present": bool(result.get("token_present")),
            "materials": result.get("materials", {}),
        },
    )


def _config_flow_step() -> dict[str, Any]:
    at = _app()
    at.run()
    _button(at, "刷新 bundle 清单").click().run()
    _check_no_exceptions(at, "刷新 bundle 清单后")
    manifest = at.session_state["agent_bundle_manifest"]
    _assert(int((manifest.get("counts") or {}).get("src_py", 0) or 0) > 0, "bundle 清单为空")

    _button(at, "审计 bundle 保留集").click().run()
    _check_no_exceptions(at, "审计 bundle 保留集后")
    audit = at.session_state["agent_bundle_audit"]
    _assert(int(audit.get("total_files", 0) or 0) >= int(audit.get("kept_files", 0) or 0), "bundle 审计计数异常")
    return _step(
        "config_flow",
        "success",
        "bundle 清单和裁剪审计可执行。",
        {
            "bundle_counts": manifest.get("counts", {}),
            "audit_total_files": int(audit.get("total_files", 0) or 0),
            "audit_review_candidate_files": int(audit.get("review_candidate_files", 0) or 0),
        },
    )


def _meta_blocked_step() -> dict[str, Any]:
    with _temporary_env({"META_ACCESS_TOKEN": "", "FACEBOOK_ACCESS_TOKEN": ""}):
        at = _app()
        at.run()
        _button(at, "执行 Meta 只读扫描").click().run()
        _check_no_exceptions(at, "Meta 阻塞路径扫描后")
        meta_result = at.session_state["agent_meta_result"]
        _assert(meta_result.get("status") == "blocked", f"Meta 阻塞路径状态异常: {meta_result}")

        at = _app()
        at.run()
        _checkbox(at, "包含 Meta 只读扫描").set_value(True).run()
        _button(at, "执行健康检查").click().run()
        _check_no_exceptions(at, "Meta 阻塞路径健康检查后")
        health_result = at.session_state["agent_healthcheck_result"]
        meta_health = health_result.get("meta_monitor", {})
        _assert(meta_health.get("status") == "blocked", f"健康检查中的 Meta 阻塞状态异常: {meta_health}")
    return _step(
        "meta_blocked_flow",
        "success",
        "Meta 无 token 阻塞提示正常。",
        {"status": "blocked"},
    )


def _meta_live_step() -> dict[str, Any]:
    token = _meta_token()
    if not token:
        return _step("meta_live_flow", "skipped", "当前环境没有 Meta token，跳过真实只读扫描验证。")

    at = _app()
    at.run()
    _button(at, "执行 Meta 只读扫描").click().run()
    _check_no_exceptions(at, "Meta 真实扫描后")
    meta_result = at.session_state["agent_meta_result"]
    _assert(meta_result.get("status") == "success", f"Meta 真实扫描失败: {meta_result}")
    _assert(len(meta_result.get("results", [])) > 0, "Meta 真实扫描结果为空")

    at = _app()
    at.run()
    _checkbox(at, "包含 Meta 只读扫描").set_value(True).run()
    _button(at, "执行健康检查").click().run()
    _check_no_exceptions(at, "包含 Meta 的健康检查后")
    health_result = at.session_state["agent_healthcheck_result"]
    meta_health = health_result.get("meta_monitor", {})
    _assert(meta_health.get("status") == "success", f"健康检查中的 Meta 扫描失败: {meta_health}")
    return _step(
        "meta_live_flow",
        "success",
        "Meta 真实只读扫描和健康检查联动正常。",
        {
            "result_count": len(meta_result.get("results", [])),
            "planned_actions": sum(len(item.get("planned_actions", [])) for item in meta_result.get("results", [])),
        },
    )


def _history_step(settings: dict[str, Any], *, baseline_total: int) -> dict[str, Any]:
    summary = history_summary(settings, limit=500)
    items = summary["items"]
    event_types = {str(item.get("event_type") or "") for item in items}
    required = {
        "legacy_import",
        "generation_status_refresh",
        "healthcheck",
        "bundle_manifest",
        "bundle_audit",
        "meta_monitor",
        "tts_settings_save",
        "meta_launch_settings_save",
    }
    missing = sorted(required - event_types)
    _assert(summary["summary"]["total"] > baseline_total, "任务历史没有新增记录")
    _assert(not missing, f"任务历史缺少事件类型: {missing}")
    return _step(
        "history_flow",
        "success",
        "任务历史已记录关键前端动作。",
        {
            "baseline_total": baseline_total,
            "current_total": summary["summary"]["total"],
            "event_types": sorted(event_types),
        },
    )


def run_frontend_validation(settings: dict[str, Any]) -> dict[str, Any]:
    load_agent_env()
    baseline_history = history_summary(settings, limit=500)
    baseline_total = baseline_history["summary"]["total"]
    steps: list[dict[str, Any]] = []

    try:
        steps.append(_initial_render_step(settings))
        steps.append(_material_flow_step(settings))
        steps.append(_tts_settings_step(settings))
        steps.append(_meta_upload_ui_step())
        steps.append(_generation_flow_step())
        steps.append(_healthcheck_step())
        steps.append(_config_flow_step())
        steps.append(_meta_blocked_step())
        steps.append(_meta_live_step())
        steps.append(_history_step(settings, baseline_total=baseline_total))
        status = "success"
        message = "Agent 前端非生成链路验证通过。"
    except Exception as exc:
        status = "failed"
        message = str(exc)
        steps.append(_step("validation_error", "failed", str(exc)))

    report = {
        "status": status,
        "message": message,
        "meta_token_present": bool(_meta_token()),
        "materials": scan_materials(settings)["summary"],
        "history": history_summary(settings, limit=200)["summary"],
        "steps": steps,
    }
    report_path = frontend_validation_report_path(settings)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["report_path"] = str(report_path)
    append_history(
        settings,
        event_type="frontend_validation",
        status=status,
        title="执行前端全功能验证",
        payload={
            "report_path": report["report_path"],
            "step_count": len(steps),
            "message": message,
        },
    )
    return report
