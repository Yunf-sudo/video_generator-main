from __future__ import annotations


# 这个文件管理“Meta 暂存池 + 广告监控”的业务参数。
# 不放 Access Token。密钥一律走环境变量。


META_POOL_STATE = {
    # 本地状态目录。这里只保存轻量状态、告警和复盘结果，不再额外复制视频素材。
    "state_root": "generated/ad_ops_state",
    # 是否把视频文件再复制一份到本地状态目录。
    # 你当前诉求是不搭建额外素材库，所以默认关闭。
    "copy_assets_to_workspace": False,
    # 当“Meta 暂存池里可用待投素材”低于这个数量时，系统会提示需要补量生成。
    "min_ready_materials": 3,
    # 系统希望长期维持的 Meta 暂存池库存目标，用于给生成侧做补量建议。
    "target_ready_materials": 8,
    # 新生成素材默认审核状态。
    # 可选：pending_review / approved / rejected
    "default_review_status": "pending_review",
    # 是否允许“未人工审核”的素材直接预上架到 Meta 广告组。
    # 这里默认允许预上架，但默认是 PAUSED，不自动启用。
    "allow_prelaunch_before_manual_review": True,
    # 预上架后的默认广告状态。你们当前流程建议保持 PAUSED。
    "default_meta_ad_status": "PAUSED",
    # 成功素材归档目录名。
    "success_archive_bucket": "success_ads",
    # 失败/下架素材归档目录名。
    "failed_archive_bucket": "failed_ads",
    # 告警文件目录名。
    "alerts_bucket": "alerts",
}


META_ADS = {
    # Marketing API 版本。后续如果 Meta 升级，这里统一改。
    "api_version": "v19.0",
    # 广告账户 ID。建议也可以通过环境变量 META_AD_ACCOUNT_ID 覆盖。
    "ad_account_id": "act_2083051298789582",
    # Facebook Page ID。建议也可以通过环境变量 META_PAGE_ID 覆盖。
    "page_id": "325789213957232",
    # 默认预上架广告组。建议也可以通过环境变量 META_DEFAULT_ADSET_ID 覆盖。
    "default_target_adset_ids": [
        "120244986089430635",
    ],
    # 默认落地页。你当前给的是 16-1 的商品链接。
    "default_landing_page_url": "https://anywellshop.com/products/150kg-capacity-electric-wheelchair",
    # 默认 CTA 类型。
    "default_call_to_action": "LEARN_MORE",
    # 新建广告的命名前缀。
    "ad_name_prefix": "[Auto-Gen]",
    # 创意命名前缀。
    "creative_name_prefix": "[Auto-Creative]",
    # 是否启用本地 dry-run 模式。
    # True 时不会真的请求 Meta API，而是返回模拟的 video_id / creative_id / ad_id。
    "dry_run_mode": False,
    # 是否启用真实 Meta 只读模式。
    # True 时会调用真实 GET 接口拉取广告状态和表现，但禁止上传素材、创建广告、修改广告状态。
    "read_only_mode": True,
    # dry-run 模式下广告组预算，供 Agent 计算阈值用。
    "dry_run_daily_budget": 50.0,
}


MONITOR_RULES = {
    # 单个广告组希望保持的活跃广告数量。
    "target_active_ads_per_adset": 3,
    # 日预算分阶阈值倍率。
    "gate_ratio_1": 0.3,
    "gate_ratio_2": 0.8,
    "gate_ratio_3": 1.6,
    # 一阶判断前需要至少多少曝光。
    "min_impressions": 800,
    # CTR 低于这个值就认为素材弱。
    "min_ctr": 5.0,
    # 3 秒播放率低于这个值就认为视频吸引力不足。
    "min_3s_play_rate": 30.0,
    # 二阶线时至少应有的加购数。
    "min_atc": 1,
    # 认定“安全素材”的最低 ROAS。
    "min_roas": 1.5,
    # 出 1 单后，多少天没有第 2 单就判定衰退。
    "expire_days_1_purchase": 4.0,
    # 出 2 单后，多少天没有第 3 单就判定衰退。
    "expire_days_2_purchase": 7.0,
    # 僵尸广告判断：至少持续多少小时不动。
    "zombie_freeze_hours": 3.0,
    # 如果 24 小时内下架数量达到这个值，就触发人工告警。
    "frequent_pause_warning_count": 5,
    # 告警统计窗口，单位小时。
    "frequent_pause_warning_window_hours": 24.0,
    # 轮询频率，单位分钟。你同事原版是 60 分钟。
    "monitor_interval_minutes": 60,
    # 多少单开始标记为成功素材。
    "winner_purchase_count": 3,
}
