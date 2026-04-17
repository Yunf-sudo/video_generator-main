import requests
import time
import json
import os
from datetime import datetime
import schedule
import sys

# ==========================================
# 1. 系统权限与目标配置
# ==========================================
ACCESS_TOKEN = "EAAcfRzZABmv8BRKzUlBhKbXOuw8b3bfcvyKtKo05SgnEk9qjz6W5GoEZAAz0MZCJbXj7fzhvZAmt1jdyVkno8sYIxHLjKZCWCr57wZATjCgECZAKA78SJjLnaL0wYl7689mVBWRLEYTRRcfZBuDZCAhbZAo00tolVj8pL26dvUiYnfmfeyhelHpJ9dRmFflgu0zgZDZD"
API_VERSION = "v19.0"

TARGET_ADSET_IDS = [
    "120244986089430635",
]

# ==========================================
# 2. 动态比例与考核参数设定
# ==========================================
GATE_RATIO_1 = 0.3
GATE_RATIO_2 = 0.8
GATE_RATIO_3 = 1.6

MIN_IMPRESSIONS = 800
MIN_CTR = 5.0
MIN_3S_PLAY_RATE = 30.0
MIN_ATC = 1
MIN_ROAS = 1.5

EXPIRE_DAYS_1_PURCHASE = 4.0
EXPIRE_DAYS_2_PURCHASE = 7.0

# ==========================================
# 3. 本地记忆库引擎
# ==========================================
STATE_FILE = "agent_state.json"


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {"zombie_tracker": {}, "purchase_tracker": {}, "blacklist": []}


def save_state(state):
    with open(STATE_FILE, 'w') as f: json.dump(state, f)


# ==========================================
# 4. 底层 API 执行函数
# ==========================================
def extract_action(actions_list, action_type, key="value"):
    if not isinstance(actions_list, list): return 0.0
    for action in actions_list:
        if action.get("action_type") == action_type:
            return float(action.get(key, 0.0))
    return 0.0


def change_ad_status(ad_id, ad_name, new_status):
    url = f"https://graph.facebook.com/{API_VERSION}/{ad_id}"
    payload = {"status": new_status, "access_token": ACCESS_TOKEN}
    try:
        response = requests.post(url, data=payload)
        response.raise_for_status()
        action_str = "🛑 关停" if new_status == "PAUSED" else "🟢 开启"
        print(f"[{action_str}成功] 广告: {ad_name}")
        return True
    except requests.exceptions.RequestException as e:
        try:
            err = e.response.json().get('error', {})
            print(f"      ❌ 状态修改失败[{ad_name}] => {err.get('error_user_msg', '未知报错')}")
        except:
            print(f"      ❌ 状态修改失败[{ad_name}]")
        return False


def get_adset_daily_budget(adset_id):
    url = f"https://graph.facebook.com/{API_VERSION}/{adset_id}"
    params = {"access_token": ACCESS_TOKEN, "fields": "daily_budget,lifetime_budget"}
    try:
        res = requests.get(url, params=params).json()
        if "daily_budget" in res:
            return float(res["daily_budget"]) / 100.0
        elif "lifetime_budget" in res:
            return float(res["lifetime_budget"]) / 100.0 / 7.0
    except:
        pass
    return 50.0


def fetch_adset_insights(adset_id):
    url = f"https://graph.facebook.com/{API_VERSION}/{adset_id}/ads"
    fields = [
        "name", "status", "effective_status",
        "insights.date_preset(maximum){spend,impressions,ctr,actions,action_values}"
    ]
    params = {"access_token": ACCESS_TOKEN, "fields": ",".join(fields)}
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        return response.json().get("data", [])
    except Exception as e:
        print(f"      ⚠️ 获取数据异常: {e}")
        return []


# ==========================================
# 5. 核心大脑：动态研判与处决逻辑
# ==========================================
def process_single_adset(adset_id, state):
    daily_budget = get_adset_daily_budget(adset_id)
    sg1 = daily_budget * GATE_RATIO_1
    sg2 = daily_budget * GATE_RATIO_2
    sg3 = daily_budget * GATE_RATIO_3
    print(f"   💰 日预算: ${daily_budget:.2f} | 动态阈值: 一阶[${sg1:.1f}] 二阶[${sg2:.1f}] 三阶[${sg3:.1f}]")

    ads_data = fetch_adset_insights(adset_id)
    if not ads_data: return

    active_ads = []
    paused_backup_ads = []
    killed_count = 0
    now_ts = time.time()

    blacklist = state.setdefault("blacklist", [])

    # ================= 遍历每一条广告 开始 =================
    for ad in ads_data:
        ad_id = ad.get("id")
        ad_name = ad.get("name")
        status = ad.get("status")
        insights_data = ad.get("insights", {}).get("data", [])

        if status == "PAUSED":
            if ad_id in blacklist:
                continue
            if not insights_data or float(insights_data[0].get("spend", 0)) < 2.0:
                paused_backup_ads.append({"id": ad_id, "name": ad_name})
            continue

        if status != "ACTIVE":
            continue

        if not insights_data:
            active_ads.append(ad_id)
            print(f"   📊 监控中: {ad_name} [刚开启，暂无展现数据...]")
            continue

        insights = insights_data[0]
        spend = float(insights.get("spend", 0.0))
        impressions = int(insights.get("impressions", 0))
        ctr = float(insights.get("ctr", 0.0))

        actions = insights.get("actions", [])
        action_values = insights.get("action_values", [])

        atc = extract_action(actions, "add_to_cart")
        purchases = extract_action(actions, "purchase")
        roas = extract_action(action_values, "purchase") / spend if spend > 0 else 0.0
        play_rate_3s = (extract_action(actions, "video_view") / impressions * 100) if impressions > 0 else 0.0

        print(
            f"   📊 监控中: {ad_name} | 花费: ${spend:.2f} | 展现: {impressions} | CTR: {ctr:.2f}% | 加购: {atc} | 出单: {purchases} | ROAS: {roas:.2f}")

        # 僵尸与出单记忆追踪
        zombie_tracker = state["zombie_tracker"]
        purchase_tracker = state["purchase_tracker"]

        is_zombie = False
        if ad_id not in zombie_tracker:
            zombie_tracker[ad_id] = {"spend": spend, "time": now_ts}
        else:
            hours_passed = (now_ts - zombie_tracker[ad_id]["time"]) / 3600.0
            if spend - zombie_tracker[ad_id]["spend"] > 0.5:
                zombie_tracker[ad_id] = {"spend": spend, "time": now_ts}
            elif hours_passed >= 3.0 and spend >= sg1 and atc < MIN_ATC:
                is_zombie = True

        if ad_id not in purchase_tracker:
            purchase_tracker[ad_id] = {"count": purchases, "last_time": now_ts}
        elif purchases > purchase_tracker[ad_id]["count"]:
            purchase_tracker[ad_id] = {"count": purchases, "last_time": now_ts}

        days_since_last_purchase = (now_ts - purchase_tracker[ad_id]["last_time"]) / 86400.0

        # 极限斩杀判定树
        kill_reason = None
        is_safe = False

        if purchases >= 3 and roas >= MIN_ROAS:
            is_safe = True
        elif purchases == 2 and roas >= MIN_ROAS:
            if days_since_last_purchase > EXPIRE_DAYS_2_PURCHASE:
                kill_reason = f"出2单后已 {days_since_last_purchase:.1f}天未出第3单，潜力枯竭"
            else:
                is_safe = True
        elif purchases == 1 and roas >= MIN_ROAS:
            if days_since_last_purchase > EXPIRE_DAYS_1_PURCHASE:
                kill_reason = f"首单后已 {days_since_last_purchase:.1f}天未出第2单，骗出单"
            else:
                is_safe = True

        if is_safe and not kill_reason:
            print("      👉[安全保护期] 持续出单表现良好。")
            active_ads.append(ad_id)
            continue

        if spend >= sg3 and (purchases == 0 or roas < MIN_ROAS):
            kill_reason = f"消耗破三阶红线 ${sg3:.1f}，ROAS ({roas:.2f}) 不及格"
        elif spend >= sg2 and atc < MIN_ATC:
            kill_reason = f"消耗破二阶意图线 ${sg2:.1f}，0加购"
        elif is_zombie:
            kill_reason = f"僵尸卡顿：连续系统不给量，卡在 ${spend:.2f} 占坑不拉屎"
        elif spend >= sg1 and impressions >= MIN_IMPRESSIONS:
            if ctr < MIN_CTR:
                kill_reason = f"CTR ({ctr:.2f}%) 过低"
            elif play_rate_3s < MIN_3S_PLAY_RATE:
                kill_reason = f"前3秒完播率极差"

        if kill_reason:
            print(f"      ⚠️ 触发处决: {kill_reason}")
            if change_ad_status(ad_id, ad_name, "PAUSED"):
                killed_count += 1
                blacklist.append(ad_id)
                if ad_id in zombie_tracker: del zombie_tracker[ad_id]
                if ad_id in purchase_tracker: del purchase_tracker[ad_id]
        else:
            active_ads.append(ad_id)
    # ================= 遍历每一条广告 结束 =================

    # ----------------------------------------------------
    # 🔄 替补上场 (已经完全移出循环外部，现在只报一次了！)
    # ----------------------------------------------------
    if len(active_ads) < 3:
        if paused_backup_ads:
            needed_new_ads = 3 - len(active_ads)
            print(f"   🔄 该组活跃仅 {len(active_ads)} 条，准备开启 {needed_new_ads} 条替补...")
            for i in range(min(needed_new_ads, len(paused_backup_ads))):
                backup = paused_backup_ads[i]
                change_ad_status(backup["id"], backup["name"], "ACTIVE")
        else:
            print(f"   ⚠️ 该组活跃仅 {len(active_ads)} 条，但【替补弹药库已空】！请去FB后台新建暂停状态的广告。")
    else:
        print(f"   ✅ 该组生态健康，活跃人数 {len(active_ads)}，无需干预。")

# ==========================================
# 6. 系统调度
# ==========================================
def agent_job():
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 🤖 启动雷达扫描...")
    state = load_state()
    try:
        for adset_id in TARGET_ADSET_IDS:
            print(f"\n📂 开始扫描广告组: {adset_id}")
            process_single_adset(adset_id, state)
        save_state(state)
    except Exception as e:
        print(f"\n❌ [系统异常]: {e}")

def start_daemon_mode(interval_minutes=60):
    print("=================================================================")
    print(f"🚀 Anywell Agent 8.3 - 终身数据防错乱版")
    print(f"=================================================================\n")
    agent_job()
    schedule.every(interval_minutes).minutes.do(agent_job)
    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 退出。")
        sys.exit(0)


if __name__ == "__main__":
    start_daemon_mode(interval_minutes=60)