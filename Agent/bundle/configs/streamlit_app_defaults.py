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


PRODUCT_GEOMETRY_NOTES = (
    "Product geometry calibration for the AnyWell reference wheelchair:\n"
    "- Use the exact same wheelchair model in every scene and every shot, matching the uploaded white-background reference photos.\n"
    "- Front caster fork direction rule: when the wheelchair moves forward, each front caster assembly must be rotated 180 degrees around its vertical swivel axis from the wrong forward-facing orientation. The vertical swivel stem/pivot sits ahead. The two fork/yoke arms must extend backward from that vertical stem toward the chair body, gripping the small wheel from its rear/side-rear position. The small caster wheel axle/center trails behind the pivot; never draw the fork arms projecting forward in front of the small wheel, and never place the wheel center ahead of the pivot.\n"
    "- Wheel proportion rule: preserve the reference wheel layout, with small black front casters and larger rear drive wheels. Keep the rear drive wheels, front casters, hub covers, tire thickness, spacing, and size ratio consistent with the reference photos.\n"
    "- Logo placement rule: the AnyWell brand mark/logo belongs only on the rear/back panel area. Side panels, side frame, armrests, wheels, and front area must stay plain with no side logo, no side text, no decals, and no invented badges.\n"
    "- Keep the same metallic silver-gray tubular frame, black armrests, black seat/backrest, right-side joystick, dark gray side housing, footrests, and open riding silhouette across all three shots."
)


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
    "style_tone": "温暖、克制、真实、电影感，必须是真人实拍广告照片质感，避免动画、卡通、插画、3D渲染、CGI、游戏感和医疗化表达",
    # 产品一致性锚点：这里写“必须保持一致”的硬约束，尤其适合产品结构和造型。
    "consistency_anchor": "Match the same AnyWell electric wheelchair across all scenes: consistent frame, armrest, footrest, wheel size, right-side joystick, seat cushion, and side housing. Keep the rear/top-back structure compact and proportional to the real product. Do not invent extra rods, poles, antenna-like parts, cane-like extensions, or exaggerated push bars behind the backrest. Do not show a rear/lower battery pack, exposed cable, folded state, or storage configuration.",
    # 产品几何校准：专门写轮椅结构、logo 位置、前后轮比例、前叉方向等画面细节。
    "product_geometry_notes": PRODUCT_GEOMETRY_NOTES,
    # 补充说明：这里适合写人物一致性、操作逻辑、禁忌事项等。
    "additional_info": "The rider should be the same dignified heavyset or plus-size Western senior across all scenes, clearly broader than an average or slightly stocky build. Show a broad torso and shoulders, rounded belly under normal clothing, thicker arms and legs, and a seated posture that naturally fills the wheelchair seat. Keep body type, wardrobe, posture, and identity consistent. During self-operated motion, the rider's right hand should control the right-side joystick with a natural precision pinch: thumb and index finger lightly pinching the joystick knob, other fingers relaxed near the armrest. Do not use a clenched fist, flat palm, floating hand, or hands-free autonomous motion. If short integrated rear handles are naturally visible, keep them subtle, short, close to the backrest, and never the visual focus. White-background product photos are identity references only and must never appear as ad frames or flash cuts.",
    # 场景描述补充：会和每个场景脚本一起打包给 AI，用于强化整体世界观和路线感。
    "prompt_scene_description_notes": "Keep every scene grounded in one coherent outdoor route and make the wheelchair feel naturally integrated into everyday life.",
    # 特殊点强调：这里写你最想让模型额外重视的卖点或画面重点。
    "prompt_special_emphasis": "Emphasize product realism, continuity of the same rider and wheelchair, confident self-operated movement, and conversion-ready product readability.",
    # 易出错点补充：这里只写你明确填写或勾选的错误约束。
    "prompt_error_notes": "- Avoid rear battery-pack exposure.\n- Avoid invented rear poles or exaggerated push handles.\n- Avoid body-type drift for the same rider.\n- Avoid white-background reference-photo look.\n- Avoid cartoon, animation, anime, illustration, stylized painting, 3D render, CGI, toy-like character, game asset, or plastic-looking synthetic people.\n- Avoid hands-free motion when the rider is self-operating.\n- Avoid wrong joystick grip: the right hand should not use a fist, flat palm, floating fingers, or vague contact; thumb and index finger should lightly pinch the joystick knob.\n- Avoid front caster forks pointing forward during forward motion; the fork/yoke arms must extend backward from the vertical stem toward the chair body, gripping the small wheel from its rear/side-rear position, with the wheel axle/center behind the pivot.\n- Avoid side logos, side text, decals, or invented badges on the wheelchair.\n- Avoid changing the front/rear wheel appearance, hub shape, tire thickness, spacing, or size ratio from the reference photos.",
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
