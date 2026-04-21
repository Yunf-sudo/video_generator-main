from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from ad_ops_config import load_ad_ops_config
from meta_pool_state import (
    append_material_event,
    archive_material,
    build_archive_feature_summary,
    create_alert,
    inventory_snapshot,
    list_material_records,
    load_material_record,
    paused_material_candidates_for_activation,
    save_material_record,
    update_material_record,
)
from meta_ads_service import activate_prelaunched_material, is_meta_read_only_mode, pause_material_ad
from workspace_paths import PROJECT_ROOT, ensure_dir

load_dotenv()


AD_OPS_CONFIG = load_ad_ops_config()
META_ADS_CONFIG = AD_OPS_CONFIG["meta_ads"]
MONITOR_RULES = AD_OPS_CONFIG["monitor_rules"]
META_POOL_STATE_CONFIG = AD_OPS_CONFIG["meta_pool_state"]


def _dry_run_enabled() -> bool:
    return str(
        os.getenv(
            "META_ADS_DRY_RUN",
            str(META_ADS_CONFIG.get("dry_run_mode", False)),
        )
    ).strip().lower() in {"1", "true", "yes", "on"}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _state_path() -> Path:
    return ensure_dir(PROJECT_ROOT / "generated" / "ad_ops_state") / "agent_state.json"


def load_agent_state() -> dict[str, Any]:
    path = _state_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"zombie_tracker": {}, "purchase_tracker": {}, "pause_events": []}


def save_agent_state(state: dict[str, Any]) -> None:
    _state_path().write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _meta_access_token() -> str:
    token = (os.getenv("META_ACCESS_TOKEN") or os.getenv("FACEBOOK_ACCESS_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("缺少 META_ACCESS_TOKEN 或 FACEBOOK_ACCESS_TOKEN。")
    return token


def _api_version() -> str:
    return str(META_ADS_CONFIG.get("api_version") or "v19.0").strip()


def _graph_url(path: str) -> str:
    return f"https://graph.facebook.com/{_api_version()}/{path.lstrip('/')}"


def _extract_action(actions_list: Any, action_type: str, key: str = "value") -> float:
    if not isinstance(actions_list, list):
        return 0.0
    for action in actions_list:
        if isinstance(action, dict) and action.get("action_type") == action_type:
            try:
                return float(action.get(key, 0.0))
            except Exception:
                return 0.0
    return 0.0


def _request_get(path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
    query = dict(params or {})
    query["access_token"] = _meta_access_token()
    response = requests.get(_graph_url(path), params=query, timeout=120)
    body = response.json()
    if not response.ok:
        raise RuntimeError(f"Meta GET 失败: {json.dumps(body, ensure_ascii=False)}")
    return body if isinstance(body, dict) else {}


def get_adset_daily_budget(adset_id: str) -> float:
    if _dry_run_enabled():
        return float(META_ADS_CONFIG.get("dry_run_daily_budget") or 50.0)
    body = _request_get(adset_id, params={"fields": "daily_budget,lifetime_budget"})
    if "daily_budget" in body:
        return float(body["daily_budget"]) / 100.0
    if "lifetime_budget" in body:
        return float(body["lifetime_budget"]) / 100.0 / 7.0
    return 50.0


def fetch_adset_insights(adset_id: str) -> list[dict[str, Any]]:
    if _dry_run_enabled():
        records = list_material_records()
        ads: list[dict[str, Any]] = []
        for item in records:
            if str(item.get("target_adset_id") or "").strip() != str(adset_id).strip():
                continue
            meta_mapping = item.get("meta_mapping") or {}
            ad_id = str(meta_mapping.get("ad_id") or "").strip()
            if not ad_id:
                continue
            status = (
                str((item.get("meta_runtime") or {}).get("status") or "")
                or ("ACTIVE" if str(item.get("ad_enable_status") or "") == "active" else "PAUSED")
            ).upper()
            perf = item.get("performance_snapshot") or {}
            spend = float(perf.get("spend", 0.0) or 0.0)
            impressions = int(perf.get("impressions", 0) or 0)
            ctr = float(perf.get("ctr", 0.0) or 0.0)
            atc = float(perf.get("add_to_cart", 0.0) or 0.0)
            purchases = float(perf.get("purchases", 0.0) or 0.0)
            roas = float(perf.get("roas", 0.0) or 0.0)
            purchase_value = round(spend * roas, 2) if spend > 0 else 0.0
            actions = []
            if atc > 0:
                actions.append({"action_type": "add_to_cart", "value": atc})
            if purchases > 0:
                actions.append({"action_type": "purchase", "value": purchases})
            if impressions > 0:
                actions.append({"action_type": "video_view", "value": max(0.0, impressions * 0.35)})
            action_values = []
            if purchase_value > 0:
                action_values.append({"action_type": "purchase", "value": purchase_value})
            insights_data = []
            if spend > 0 or impressions > 0 or atc > 0 or purchases > 0:
                insights_data = [
                    {
                        "spend": spend,
                        "impressions": impressions,
                        "ctr": ctr,
                        "actions": actions,
                        "action_values": action_values,
                    }
                ]
            ads.append(
                {
                    "id": ad_id,
                    "name": f"{item.get('material_id', ad_id)}",
                    "status": status,
                    "effective_status": status,
                    "insights": {"data": insights_data},
                }
            )
        return ads
    body = _request_get(
        f"{adset_id}/ads",
        params={
            "fields": "id,name,status,effective_status,insights.date_preset(maximum){spend,impressions,ctr,actions,action_values}",
        },
    )
    data = body.get("data", [])
    return data if isinstance(data, list) else []


def _find_material_by_ad_id(ad_id: str) -> dict[str, Any] | None:
    for record in list_material_records():
        if str((record.get("meta_mapping") or {}).get("ad_id") or "").strip() == str(ad_id):
            return record
    return None


def _record_pause_event(state: dict[str, Any], material_id: str, ad_id: str, reason: str) -> None:
    pause_events = state.setdefault("pause_events", [])
    pause_events.append(
        {
            "time": time.time(),
            "material_id": material_id,
            "ad_id": ad_id,
            "reason": reason,
        }
    )
    window_seconds = float(MONITOR_RULES.get("frequent_pause_warning_window_hours") or 24.0) * 3600.0
    now_ts = time.time()
    state["pause_events"] = [item for item in pause_events if now_ts - float(item.get("time") or 0) <= window_seconds]


def _check_frequent_pause_warning(state: dict[str, Any]) -> None:
    threshold = int(MONITOR_RULES.get("frequent_pause_warning_count") or 5)
    pause_events = state.get("pause_events", [])
    if len(pause_events) < threshold:
        return
    create_alert(
        "frequent_pause_warning",
        "最近窗口期内广告下架过于频繁，建议人工介入调整生成方向。",
        {
            "pause_event_count": len(pause_events),
            "window_hours": float(MONITOR_RULES.get("frequent_pause_warning_window_hours") or 24.0),
            "recent_events": pause_events[-threshold:],
        },
    )


def _maybe_archive_material(record: dict[str, Any], archive_kind: str, reason: str, performance: dict[str, Any]) -> None:
    bucket = (
        str(META_POOL_STATE_CONFIG.get("failed_archive_bucket") or "failed_ads")
        if archive_kind == "failed"
        else str(META_POOL_STATE_CONFIG.get("success_archive_bucket") or "success_ads")
    )
    archive_material(
        str(record.get("material_id") or ""),
        bucket,
        reason,
        extra_patch={
            "performance_snapshot": performance,
        },
    )


def process_single_adset(adset_id: str, state: dict[str, Any]) -> dict[str, Any]:
    daily_budget = get_adset_daily_budget(adset_id)
    sg1 = daily_budget * float(MONITOR_RULES.get("gate_ratio_1") or 0.3)
    sg2 = daily_budget * float(MONITOR_RULES.get("gate_ratio_2") or 0.8)
    sg3 = daily_budget * float(MONITOR_RULES.get("gate_ratio_3") or 1.6)
    read_only_mode = is_meta_read_only_mode()

    ads_data = fetch_adset_insights(adset_id)
    if not ads_data:
        return {
            "adset_id": adset_id,
            "read_only_mode": read_only_mode,
            "active_ads": 0,
            "observed_active_ads": 0,
            "paused_ads": 0,
            "killed_ads": 0,
            "planned_pauses": 0,
            "planned_activations": 0,
            "planned_actions": [],
        }

    active_ads = 0
    observed_active_ads = 0
    paused_ads = 0
    killed_ads = 0
    planned_pauses = 0
    planned_activations = 0
    planned_actions: list[dict[str, Any]] = []
    now_ts = time.time()
    zombie_tracker = state.setdefault("zombie_tracker", {})
    purchase_tracker = state.setdefault("purchase_tracker", {})

    for ad in ads_data:
        ad_id = str(ad.get("id") or "").strip()
        ad_name = str(ad.get("name") or ad_id)
        status = str(ad.get("status") or "").strip().upper()
        insights_data = ad.get("insights", {}).get("data", [])
        material = _find_material_by_ad_id(ad_id)

        if status == "PAUSED":
            paused_ads += 1
            continue
        if status != "ACTIVE":
            continue
        observed_active_ads += 1
        active_ads += 1

        if not insights_data:
            continue

        insights = insights_data[0] if isinstance(insights_data, list) and insights_data else {}
        spend = float(insights.get("spend", 0.0))
        impressions = int(insights.get("impressions", 0) or 0)
        ctr = float(insights.get("ctr", 0.0) or 0.0)
        actions = insights.get("actions", [])
        action_values = insights.get("action_values", [])
        atc = _extract_action(actions, "add_to_cart")
        purchases = _extract_action(actions, "purchase")
        purchase_value = _extract_action(action_values, "purchase")
        roas = purchase_value / spend if spend > 0 else 0.0
        play_rate_3s = (_extract_action(actions, "video_view") / impressions * 100.0) if impressions > 0 else 0.0

        if material:
            update_material_record(
                str(material.get("material_id")),
                {
                    "launch_status": "active",
                    "ad_enable_status": "active",
                    "performance_snapshot": {
                        "spend": spend,
                        "impressions": impressions,
                        "ctr": ctr,
                        "add_to_cart": atc,
                        "purchases": purchases,
                        "roas": roas,
                    },
                },
            )

        is_zombie = False
        if ad_id not in zombie_tracker:
            zombie_tracker[ad_id] = {"spend": spend, "time": now_ts}
        else:
            hours_passed = (now_ts - float(zombie_tracker[ad_id]["time"])) / 3600.0
            if spend - float(zombie_tracker[ad_id]["spend"]) > 0.5:
                zombie_tracker[ad_id] = {"spend": spend, "time": now_ts}
            elif hours_passed >= float(MONITOR_RULES.get("zombie_freeze_hours") or 3.0) and spend >= sg1 and atc < float(MONITOR_RULES.get("min_atc") or 1):
                is_zombie = True

        if ad_id not in purchase_tracker:
            purchase_tracker[ad_id] = {"count": purchases, "last_time": now_ts}
        elif purchases > float(purchase_tracker[ad_id]["count"]):
            purchase_tracker[ad_id] = {"count": purchases, "last_time": now_ts}

        days_since_last_purchase = (now_ts - float(purchase_tracker[ad_id]["last_time"])) / 86400.0

        kill_reason = ""
        winner_purchase_count = float(MONITOR_RULES.get("winner_purchase_count") or 3)
        if purchases >= winner_purchase_count and roas >= float(MONITOR_RULES.get("min_roas") or 1.5):
            if material:
                update_material_record(
                    str(material.get("material_id")),
                    {
                        "winner_level": "winner",
                        "launch_status": "winner_running",
                    },
                )
                append_material_event(str(material.get("material_id")), "winner_detected", {"ad_id": ad_id, "purchases": purchases, "roas": roas})
            continue

        if purchases == 2 and roas >= float(MONITOR_RULES.get("min_roas") or 1.5):
            if days_since_last_purchase > float(MONITOR_RULES.get("expire_days_2_purchase") or 7.0):
                kill_reason = f"出2单后已 {days_since_last_purchase:.1f} 天未出第3单"
        elif purchases == 1 and roas >= float(MONITOR_RULES.get("min_roas") or 1.5):
            if days_since_last_purchase > float(MONITOR_RULES.get("expire_days_1_purchase") or 4.0):
                kill_reason = f"首单后已 {days_since_last_purchase:.1f} 天未出第2单"

        if not kill_reason:
            if spend >= sg3 and (purchases == 0 or roas < float(MONITOR_RULES.get("min_roas") or 1.5)):
                kill_reason = f"消耗达到三阶线 ${sg3:.1f} 且 ROAS={roas:.2f}"
            elif spend >= sg2 and atc < float(MONITOR_RULES.get("min_atc") or 1):
                kill_reason = f"消耗达到二阶线 ${sg2:.1f} 但无加购"
            elif is_zombie:
                kill_reason = f"僵尸广告，占坑 {spend:.2f} 美元无推进"
            elif spend >= sg1 and impressions >= int(MONITOR_RULES.get("min_impressions") or 800):
                if ctr < float(MONITOR_RULES.get("min_ctr") or 5.0):
                    kill_reason = f"CTR 过低 ({ctr:.2f}%)"
                elif play_rate_3s < float(MONITOR_RULES.get("min_3s_play_rate") or 30.0):
                    kill_reason = f"3 秒播放率过低 ({play_rate_3s:.2f}%)"

        if kill_reason:
            action_payload = {
                "action": "pause_ad",
                "ad_id": ad_id,
                "ad_name": ad_name,
                "reason": kill_reason,
                "material_id": str((material or {}).get("material_id") or ""),
                "performance": {
                    "spend": spend,
                    "impressions": impressions,
                    "ctr": ctr,
                    "add_to_cart": atc,
                    "purchases": purchases,
                    "roas": roas,
                    "play_rate_3s": play_rate_3s,
                },
            }
            if read_only_mode:
                planned_pauses += 1
                planned_actions.append(action_payload)
            else:
                if material:
                    pause_material_ad(str(material.get("material_id")), kill_reason)
                    _record_pause_event(state, str(material.get("material_id")), ad_id, kill_reason)
                    _maybe_archive_material(
                        material,
                        "failed",
                        kill_reason,
                        {
                            "spend": spend,
                            "impressions": impressions,
                            "ctr": ctr,
                            "add_to_cart": atc,
                            "purchases": purchases,
                            "roas": roas,
                        },
                    )
                killed_ads += 1
            active_ads = max(0, active_ads - 1)

    target_active = int(MONITOR_RULES.get("target_active_ads_per_adset") or 3)
    if active_ads < target_active:
        needed = target_active - active_ads
        for candidate in paused_material_candidates_for_activation(adset_id, limit=needed):
            if read_only_mode:
                planned_activations += 1
                planned_actions.append(
                    {
                        "action": "activate_prelaunched_material",
                        "material_id": str(candidate.get("material_id") or ""),
                        "ad_id": str((candidate.get("meta_mapping") or {}).get("ad_id") or ""),
                        "adset_id": adset_id,
                        "reason": "active_ad_count_below_target",
                    }
                )
            else:
                activate_prelaunched_material(str(candidate.get("material_id")))
            active_ads += 1

    inventory = inventory_snapshot()
    if inventory.get("needs_generation"):
        create_alert(
            "low_material_inventory",
            "Meta 暂存池可用库存不足，建议自动补量生成。",
            inventory,
        )

    _check_frequent_pause_warning(state)
    build_archive_feature_summary()

    return {
        "adset_id": adset_id,
        "read_only_mode": read_only_mode,
        "active_ads": active_ads,
        "observed_active_ads": observed_active_ads,
        "paused_ads": paused_ads,
        "killed_ads": killed_ads,
        "planned_pauses": planned_pauses,
        "planned_activations": planned_activations,
        "planned_actions": planned_actions,
        "inventory": inventory,
    }


def run_agent_once(adset_ids: list[str] | None = None) -> dict[str, Any]:
    state = load_agent_state()
    target_ids = adset_ids or [str(item).strip() for item in META_ADS_CONFIG.get("default_target_adset_ids") or [] if str(item).strip()]
    results = []
    for adset_id in target_ids:
        results.append(process_single_adset(adset_id, state))
    save_agent_state(state)
    return {
        "run_time": _utc_now_iso(),
        "read_only_mode": is_meta_read_only_mode(),
        "results": results,
    }


def run_agent_forever(interval_minutes: int | None = None) -> None:
    interval = int(interval_minutes or MONITOR_RULES.get("monitor_interval_minutes") or 60)
    while True:
        run_agent_once()
        time.sleep(max(1, interval) * 60)
