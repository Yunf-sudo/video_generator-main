from __future__ import annotations


# 这个文件专门存放 Streamlit 工作台里“经常需要改”的默认参数。
# 之所以使用 Python 文件，而不是 JSON，是因为 Python 文件可以直接写中文注释，
# 更适合日常人工维护。


STYLE_PRESETS = {
    # 适合偏产品说明、演示卖点、给客户介绍产品功能的画面风格。
    "产品演示型": "真实、高级、产品中心构图，突出电动操控、稳定和舒适，适合商务演示与客户沟通。",
    # 适合更偏成交、招商、渠道合作导向的视频。
    "渠道招商型": "镜头更偏成交导向，强调产品卖点、采购场景和合作价值，节奏更利落。",
    # 适合偏家庭陪伴、户外回归、情感广告风格。
    "家庭关怀型": "画面更温暖，突出日常代步、省力和陪伴感，但仍保持真实可信。",
    # 适合机构采购、医院、养老场景等更专业稳重的表达。
    "机构采购型": "突出稳重、专业、耐看，适合康复机构、医院和养老场景展示。",
}


# 可选语言列表。
# 会直接用于网页端“输出语言”的下拉选项。
LANGUAGE_OPTIONS = [
    "Chinese",
    "English",
]


# 可选画幅比例列表。
# 会直接用于网页端“画幅比例”的下拉选项。
VIDEO_ORIENTATION_OPTIONS = [
    "9:16",
    "16:9",
    "1:1",
]


DEFAULT_INPUTS = {
    # 产品名称：最终会进入脚本、分镜图、视频提示词。
    "product_name": "AnyWell 电动轮椅",
    # 产品品类：帮助模型理解这是什么产品，避免跑偏。
    "product_category": "电动轮椅 / mobility chair",
    # 投放目标：说明这条视频想解决什么问题、打什么方向。
    "campaign_goal": "生成一条面向欧美市场的竖版情感广告视频，突出明显肥胖/大体重老年人重新安全走向户外的自由感和尊严感",
    # 目标市场：告诉模型内容面向哪些国家或区域。
    "target_market": "美国、加拿大、英国和西欧",
    # 目标受众：决定人物设定、场景习惯、语言表达风格。
    "target_audience": "欧美市场明显肥胖、heavyset、plus-size 老年人、配偶、35-55 岁成年子女，以及正在为家人评估户外出行辅助产品的家庭",
    # 核心卖点：建议用多行 bullet，后续会直接参与提示词整合。
    "core_selling_points": "- 平顺双动力系统\n- 稳定的户外通行支持\n- 温和起步和可控转向\n- 支持明显肥胖/大体重长者安心回到户外",
    # 使用场景：建议用多行 bullet，便于脚本模型提炼镜头。
    "use_scenarios": "- 家庭门口和坡道\n- 后院小路\n- 林地边缘或安静社区道路\n- 与伴侣一起外出看风景",
    # 风格模板：必须对应 STYLE_PRESETS 里的某个 key。
    "style_preset": "家庭关怀型",
    # 自定义风格说明：如果你想覆盖模板默认描述，可以直接改这里。
    "custom_style_notes": STYLE_PRESETS["家庭关怀型"],
    # 风格语气：决定整体广告是温暖、理性、克制还是更偏转化。
    "style_tone": "温暖、克制、真实、电影感，避免煽情和医疗化表达",
    # 产品一致性锚点：这里写“必须保持一致”的硬约束，尤其适合产品结构和造型。
    "consistency_anchor": "Match the same AnyWell electric wheelchair across all scenes: consistent frame, armrest, footrest, wheel size, right-side joystick, seat cushion, and side housing. Keep the rear/top-back structure compact and proportional to the real product. Do not invent extra rods, poles, antenna-like parts, cane-like extensions, or exaggerated push bars behind the backrest. Do not show a rear/lower battery pack, exposed cable, folded state, or storage configuration.",
    # 补充说明：这里适合写人物一致性、操作逻辑、禁忌事项等。
    "additional_info": "The rider should be the same dignified heavyset or plus-size Western senior across all scenes, clearly broader than an average or slightly stocky build. Show a broad torso and shoulders, rounded belly under normal clothing, thicker arms and legs, and a seated posture that naturally fills the wheelchair seat. Keep body type, wardrobe, posture, and identity consistent. During self-operated motion, the right hand should remain on the right-side joystick. Do not present the chair as autonomous hands-free motion. If short integrated rear handles are naturally visible, keep them subtle, short, close to the backrest, and never the visual focus. White-background product photos are identity references only and must never appear as ad frames or flash cuts.",
    # 场景描述补充：会和每个场景脚本一起打包给 AI，用于强化整体世界观和路线感。
    "prompt_scene_description_notes": "Keep every scene grounded in one coherent outdoor route and make the wheelchair feel naturally integrated into everyday life.",
    # 特殊点强调：这里写你最想让模型额外重视的卖点或画面重点。
    "prompt_special_emphasis": "Emphasize product realism, continuity of the same rider and wheelchair, confident self-operated movement, and conversion-ready product readability.",
    # 易出错点补充：这里写模型常见错误，系统还会叠加代码里的默认错误模块。
    "prompt_error_notes": "- Avoid rear battery-pack exposure.\n- Avoid invented rear poles or exaggerated push handles.\n- Avoid body-type drift for the same rider.\n- Avoid white-background reference-photo look.\n- Avoid hands-free motion when the rider is self-operating.",
    # 输出语言：必须来自 LANGUAGE_OPTIONS。
    "language": "English",
    # 视频画幅：必须来自 VIDEO_ORIENTATION_OPTIONS。
    "video_orientation": "9:16",
    # 目标场景数：用于脚本规划场景数量。
    "desired_scene_count": 5,
    # 目标总时长：用于脚本和后续视频节奏规划。
    "preferred_runtime_seconds": 28,
    # 外部风格参考：通常由竞品分析自动写入，也可以手动填。
    "reference_style": "",
}
