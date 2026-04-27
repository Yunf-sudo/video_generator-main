from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from agent.config import resolve_path
from agent.env import load_agent_env, meta_access_token_source, resolve_meta_access_token
from agent.history import append_history

load_agent_env()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _token(settings: dict[str, Any]) -> str:
    meta = settings.get("meta", {}) if isinstance(settings.get("meta"), dict) else {}
    env_keys = list(meta.get("access_token_env_keys") or [])
    for key in env_keys:
        value = (os.getenv(str(key)) or "").strip()
        if value:
            return value
    return resolve_meta_access_token()


def _state_path(settings: dict[str, Any]) -> Path:
    runtime = settings.get("runtime", {}) if isinstance(settings.get("runtime"), dict) else {}
    path = resolve_path(str(runtime.get("monitor_state_path") or "runtime/monitor_state.json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_state(settings: dict[str, Any]) -> dict[str, Any]:
    path = _state_path(settings)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"zombie_tracker": {}, "purchase_tracker": {}, "blacklist": []}


def save_state(settings: dict[str, Any], state: dict[str, Any]) -> None:
    _state_path(settings).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _graph_url(settings: dict[str, Any], path: str) -> str:
    meta = settings.get("meta", {}) if isinstance(settings.get("meta"), dict) else {}
    version = str(meta.get("api_version") or "v19.0").strip()
    return f"https://graph.facebook.com/{version}/{path.lstrip('/')}"


def _request_get(settings: dict[str, Any], path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
    access_token = _token(settings)
    if not access_token:
        raise RuntimeError("缺少 META_ACCESS_TOKEN 或 FACEBOOK_ACCESS_TOKEN。")
    query = dict(params or {})
    query["access_token"] = access_token
    response = requests.get(_graph_url(settings, path), params=query, timeout=120)
    body = response.json()
    if not response.ok:
        raise RuntimeError(f"Meta GET 失败: {json.dumps(body, ensure_ascii=False)}")
    return body if isinstance(body, dict) else {}


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


def get_adset_daily_budget(settings: dict[str, Any], adset_id: str) -> float:
    meta = settings.get("meta", {}) if isinstance(settings.get("meta"), dict) else {}
    body = _request_get(settings, adset_id, params={"fields": "daily_budget,lifetime_budget"})
    if "daily_budget" in body:
        return float(body["daily_budget"]) / 100.0
    if "lifetime_budget" in body:
        return float(body["lifetime_budget"]) / 100.0 / 7.0
    return float(meta.get("daily_budget_fallback") or 50.0)


def fetch_adset_insights(settings: dict[str, Any], adset_id: str) -> list[dict[str, Any]]:
    body = _request_get(
        settings,
        f"{adset_id}/ads",
        params={
            "fields": "id,name,status,effective_status,insights.date_preset(maximum){spend,impressions,ctr,actions,action_values}",
        },
    )
    data = body.get("data", [])
    return data if isinstance(data, list) else []


def _rules(settings: dict[str, Any]) -> dict[str, Any]:
    return settings.get("monitor_rules", {}) if isinstance(settings.get("monitor_rules"), dict) else {}


def process_single_adset(settings: dict[str, Any], adset_id: str, state: dict[str, Any]) -> dict[str, Any]:
    rules = _rules(settings)
    daily_budget = get_adset_daily_budget(settings, adset_id)
    sg1 = daily_budget * float(rules.get("gate_ratio_1") or 0.3)
    sg2 = daily_budget * float(rules.get("gate_ratio_2") or 0.8)
    sg3 = daily_budget * float(rules.get("gate_ratio_3") or 1.6)
    ads_data = fetch_adset_insights(settings, adset_id)

    active_ads: list[str] = []
    paused_backup_ads: list[dict[str, str]] = []
    ad_reports: list[dict[str, Any]] = []
    planned_actions: list[dict[str, Any]] = []
    now_ts = time.time()
    blacklist = state.setdefault("blacklist", [])
    zombie_tracker = state.setdefault("zombie_tracker", {})
    purchase_tracker = state.setdefault("purchase_tracker", {})

    for ad in ads_data:
        ad_id = str(ad.get("id") or "").strip()
        ad_name = str(ad.get("name") or ad_id)
        status = str(ad.get("status") or "").strip().upper()
        insights_data = ad.get("insights", {}).get("data", [])

        if status == "PAUSED":
            spend = float((insights_data[0] if insights_data else {}).get("spend", 0.0) or 0.0)
            if ad_id not in blacklist and (not insights_data or spend < float(rules.get("paused_backup_max_spend") or 2.0)):
                paused_backup_ads.append({"id": ad_id, "name": ad_name})
            ad_reports.append(
                {
                    "ad_id": ad_id,
                    "ad_name": ad_name,
                    "status": status,
                    "decision": "paused_backup_candidate" if ad_id not in blacklist else "paused_blacklisted",
                    "spend": spend,
                }
            )
            continue

        if status != "ACTIVE":
            ad_reports.append({"ad_id": ad_id, "ad_name": ad_name, "status": status, "decision": "ignored"})
            continue

        if not insights_data:
            active_ads.append(ad_id)
            ad_reports.append({"ad_id": ad_id, "ad_name": ad_name, "status": status, "decision": "keep_new_no_data"})
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

        is_zombie = False
        if ad_id not in zombie_tracker:
            zombie_tracker[ad_id] = {"spend": spend, "time": now_ts}
        else:
            hours_passed = (now_ts - float(zombie_tracker[ad_id]["time"])) / 3600.0
            if spend - float(zombie_tracker[ad_id]["spend"]) > 0.5:
                zombie_tracker[ad_id] = {"spend": spend, "time": now_ts}
            elif hours_passed >= float(rules.get("zombie_freeze_hours") or 3.0) and spend >= sg1 and atc < float(rules.get("min_atc") or 1):
                is_zombie = True

        if ad_id not in purchase_tracker:
            purchase_tracker[ad_id] = {"count": purchases, "last_time": now_ts}
        elif purchases > float(purchase_tracker[ad_id]["count"]):
            purchase_tracker[ad_id] = {"count": purchases, "last_time": now_ts}
        days_since_last_purchase = (now_ts - float(purchase_tracker[ad_id]["last_time"])) / 86400.0

        kill_reason = ""
        decision = "keep"
        if purchases >= float(rules.get("winner_purchase_count") or 3) and roas >= float(rules.get("min_roas") or 1.5):
            decision = "winner_keep"
        elif purchases == 2 and roas >= float(rules.get("min_roas") or 1.5):
            if days_since_last_purchase > float(rules.get("expire_days_2_purchase") or 7.0):
                kill_reason = f"出2单后已 {days_since_last_purchase:.1f} 天未出第3单"
        elif purchases == 1 and roas >= float(rules.get("min_roas") or 1.5):
            if days_since_last_purchase > float(rules.get("expire_days_1_purchase") or 4.0):
                kill_reason = f"首单后已 {days_since_last_purchase:.1f} 天未出第2单"

        if not kill_reason and decision == "keep":
            if spend >= sg3 and (purchases == 0 or roas < float(rules.get("min_roas") or 1.5)):
                kill_reason = f"消耗达到三阶线 ${sg3:.1f} 且 ROAS={roas:.2f}"
            elif spend >= sg2 and atc < float(rules.get("min_atc") or 1):
                kill_reason = f"消耗达到二阶线 ${sg2:.1f} 但无加购"
            elif is_zombie:
                kill_reason = f"僵尸广告，占坑 {spend:.2f} 美元无推进"
            elif spend >= sg1 and impressions >= int(rules.get("min_impressions") or 800):
                if ctr < float(rules.get("min_ctr") or 5.0):
                    kill_reason = f"CTR 过低 ({ctr:.2f}%)"
                elif play_rate_3s < float(rules.get("min_3s_play_rate") or 30.0):
                    kill_reason = f"3 秒播放率过低 ({play_rate_3s:.2f}%)"

        if kill_reason:
            decision = "plan_pause"
            planned_actions.append(
                {
                    "action": "pause_ad",
                    "ad_id": ad_id,
                    "ad_name": ad_name,
                    "reason": kill_reason,
                }
            )
        else:
            active_ads.append(ad_id)

        ad_reports.append(
            {
                "ad_id": ad_id,
                "ad_name": ad_name,
                "status": status,
                "decision": decision,
                "spend": spend,
                "impressions": impressions,
                "ctr": ctr,
                "add_to_cart": atc,
                "purchases": purchases,
                "roas": roas,
                "play_rate_3s": play_rate_3s,
                "reason": kill_reason,
            }
        )

    target_active = int(rules.get("target_active_ads_per_adset") or 3)
    if len(active_ads) < target_active:
        needed = target_active - len(active_ads)
        for backup in paused_backup_ads[:needed]:
            planned_actions.append(
                {
                    "action": "activate_backup_ad",
                    "ad_id": str(backup.get("id") or ""),
                    "ad_name": str(backup.get("name") or ""),
                    "reason": "active_ad_count_below_target",
                }
            )

    return {
        "adset_id": adset_id,
        "daily_budget": daily_budget,
        "thresholds": {"sg1": sg1, "sg2": sg2, "sg3": sg3},
        "active_ads": len(active_ads),
        "paused_backup_ads": len(paused_backup_ads),
        "planned_actions": planned_actions,
        "ad_reports": ad_reports,
    }


def run_meta_monitor(settings: dict[str, Any], adset_ids: list[str] | None = None) -> dict[str, Any]:
    meta = settings.get("meta", {}) if isinstance(settings.get("meta"), dict) else {}
    target_ids = adset_ids or [str(item).strip() for item in meta.get("default_target_adset_ids") or [] if str(item).strip()]
    token_available = bool(_token(settings))
    result: dict[str, Any] = {
        "run_time": _utc_now_iso(),
        "read_only_mode": bool(meta.get("read_only", True)),
        "token_available": token_available,
        "token_source": meta_access_token_source(),
        "results": [],
    }
    if not token_available:
        result["status"] = "blocked"
        result["message"] = "缺少 META_ACCESS_TOKEN 或 FACEBOOK_ACCESS_TOKEN。"
        append_history(
            settings,
            event_type="meta_monitor",
            status="blocked",
            title="执行 Meta 只读扫描",
            payload={"message": result["message"]},
        )
        return result

    state = load_state(settings)
    try:
        for adset_id in target_ids:
            result["results"].append(process_single_adset(settings, adset_id, state))
        save_state(settings, state)
        result["status"] = "success"
        append_history(
            settings,
            event_type="meta_monitor",
            status="success",
            title="执行 Meta 只读扫描",
            payload={
                "target_ids": target_ids,
                "result_count": len(result["results"]),
                "planned_actions": sum(len(item.get("planned_actions", [])) for item in result["results"]),
            },
        )
        return result
    except Exception as exc:
        save_state(settings, state)
        result["status"] = "failed"
        result["message"] = str(exc)
        append_history(
            settings,
            event_type="meta_monitor",
            status="failed",
            title="执行 Meta 只读扫描",
            payload={"message": result["message"], "target_ids": target_ids},
        )
        return result
