from __future__ import annotations

from typing import Any


OPTIMIZATION_DIRECTIONS: list[dict[str, str]] = [
    {
        "label": "前3秒更抓人",
        "description": "强化第一镜头的进入感，让用户更快停留。",
        "scene_notes": "开场前三秒就要有明显进入感或情绪反差，不要慢热。",
        "special_emphasis": "首帧要一眼能看懂，停留点明确，适合冷启动投流。",
    },
    {
        "label": "更像真实广告，不像AI图",
        "description": "减少概念图、摆拍感、过度完美环境。",
        "scene_notes": "环境要像真实有人生活过的地方，路线和镜头行为都要自然可信。",
        "special_emphasis": "优先保证真实物理感、真实镜头感、正常光线衰减和可信的产品重量感。",
    },
    {
        "label": "产品卖点更直接",
        "description": "让轮椅结构、操控和使用收益更容易看懂。",
        "scene_notes": "让轮椅的摇杆操控、座椅支撑、轮组比例和户外通过性在各场景里都看得清。",
        "special_emphasis": "优先提升产品可读性和转化表达，不要只靠氛围和生活方式感。",
    },
    {
        "label": "人物情绪更能转化",
        "description": "突出安全感、尊严感、陪伴感和恢复外出自由。",
        "scene_notes": "通过姿态、节奏和与陪伴者的互动，明确表现情绪上的变化和释放。",
        "special_emphasis": "强调尊严感、松弛感、自信感和重新走向户外的自由，而不是泛泛微笑。",
    },
    {
        "label": "镜头连续性更稳",
        "description": "减少人物、服装、轮椅、空间关系在前后镜头漂移。",
        "scene_notes": "所有场景都放在一条连贯路线里，保持人物身份、服装、轮椅形态和时间逻辑一致。",
        "special_emphasis": "优先保护镜头间连续性，让广告像同一次拍摄，而不是 AI 碎片拼接。",
    },
    {
        "label": "更适合冷启动测试",
        "description": "更关注首屏理解、卖点传达和可测试性。",
        "scene_notes": "每个场景的目的要单一、镜头要清晰，便于后续把投放反馈映射回具体创意方向。",
        "special_emphasis": "优先简单、清楚、可测试的创意选择，不要过度追求复杂艺术表达。",
    },
]


ERROR_EXAMPLES: list[dict[str, str]] = [
    {
        "label": "轮椅后部乱长杆件",
        "symptom": "后面凭空多出杆子、天线、夸张推手或不真实结构。",
        "prompt_fix": "不要在轮椅后部凭空生成杆件、天线状结构、拐杖状延伸件或夸张推手。",
    },
    {
        "label": "同一人物体型漂移",
        "symptom": "前后镜头里同一个人忽胖忽瘦、年龄和身份变化。",
        "prompt_fix": "保持同一个肥胖或 plus-size 老年人的身份、体型比例、服装和姿态在相邻场景里一致。",
    },
    {
        "label": "轮椅像概念图不是实物",
        "symptom": "画面像 CG、海报、概念设计图，不像真实产品拍摄。",
        "prompt_fix": "不要把轮椅画成概念渲染图、幻想产品或不可能存在的棚拍英雄物件。",
    },
    {
        "label": "手没碰摇杆却自动行驶",
        "symptom": "轮椅自己跑，操控逻辑不可信。",
        "prompt_fix": "如果是用户自驾，右手要明确放在右侧摇杆上，用拇指和食指自然捏住摇杆；不要出现放手自动行驶、握拳、平掌覆盖或含糊接触。",
    },
    {
        "label": "白底参考图混进广告画面",
        "symptom": "白底 packshot、参考图闪现进正式广告镜头。",
        "prompt_fix": "不要把白底参考图、产品目录图或身份参考页闪切进正式广告画面。",
    },
    {
        "label": "视频运动时结构变形",
        "symptom": "动起来后轮椅、人物或背景发生 morph、重置、拉扯。",
        "prompt_fix": "运动过程中避免形变、人物结构扭曲、产品漂移、连续性跳变和突然重置。",
    },
    {
        "label": "前轮前叉方向错误",
        "symptom": "前进时小前轮的前叉朝前，像反装或被模型画错。",
        "prompt_fix": "前进时前万向轮必须符合物理逻辑：垂直转轴在前，小轮中心在后，前叉从转轴向后包住小轮，不要把前叉画成朝前伸出。",
    },
    {
        "label": "摇杆手势不清楚",
        "symptom": "右手握成拳、手掌盖住摇杆、手指悬空，操控感不真实。",
        "prompt_fix": "右手操控摇杆时，要用拇指和食指自然捏住摇杆，其他手指自然放松，不要出现不真实的手势。",
    },
    {
        "label": "侧边多出logo文字",
        "symptom": "轮椅侧面、轮子、扶手或车架上出现品牌字、贴纸或假标。",
        "prompt_fix": "轮椅侧板、侧架、扶手、轮子和前部区域要保持干净，不要出现侧边 logo、文字、贴纸或虚构徽标；品牌标识只能出现在合理的后背区域。",
    },
    {
        "label": "前后轮比例漂移",
        "symptom": "前轮、后轮、轮毂、胎宽或间距和参考图不一致。",
        "prompt_fix": "严格保持参考图里的轮组关系：小号黑色前万向轮、大号后驱动轮、对应轮毂罩、胎宽、间距和前后轮比例。",
    },
    {
        "label": "凭空多出头枕靠枕",
        "symptom": "轮椅顶部突然多出头部靠枕、颈枕或高背支撑，和参考图不符。",
        "prompt_fix": "除非参考轮椅明确有头枕，否则不要凭空生成头枕、颈枕或高背支撑件。",
    },
    {
        "label": "logo跑到头枕正面",
        "symptom": "品牌标识出现在头枕、前侧面或其他不该出现的位置。",
        "prompt_fix": "不要把品牌标识放到头枕、前侧面或附件上；如果能看到靠背上半部布面，logo 只能放在那里。",
    },
    {
        "label": "后部双把手缺失或变形",
        "symptom": "椅背顶部不是左右各一个短把手，而是缺失、数量不对、变成头枕或多出支撑件。",
        "prompt_fix": "后背顶部结构必须贴近参考图，不要缺失、乱加或变形成头枕、中间支撑柱或额外上部结构。",
    },
    {
        "label": "后轮导轮乱晃",
        "symptom": "后部小导轮、防倾轮或辅助轮像松了一样晃动、摆动、乱跳。",
        "prompt_fix": "如果后部防倾轮、导轮或辅助轮可见，它们必须短、正、稳，不能乱晃、乱摆、乱跳。",
    },
    {
        "label": "画面变成动画片",
        "symptom": "人物、环境或产品变成卡通、插画、3D、CGI或游戏资产风格。",
        "prompt_fix": "必须是真人实拍质感：真实镜头、真实成年人、真实皮肤纹理、真实布料、真实光线和真实户外材质。不要卡通、动画、二次元、插画、3D、CGI、游戏资产或塑料假人感。",
    },
]


def _normalize_lines(value: Any) -> list[str]:
    lines: list[str] = []
    if value is None:
        return lines
    if isinstance(value, str):
        candidates = value.splitlines()
    elif isinstance(value, (list, tuple)):
        candidates = [str(item or "") for item in value]
    else:
        candidates = [str(value)]
    for raw in candidates:
        line = str(raw or "").strip()
        if not line:
            continue
        if line.startswith("-"):
            line = line[1:].strip()
        if line:
            lines.append(line)
    return lines


def _unique_lines(*parts: Any) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for part in parts:
        for line in _normalize_lines(part):
            key = line.lower()
            if key in seen:
                continue
            seen.add(key)
            ordered.append(line)
    return ordered


def _lookup(items: list[dict[str, str]], labels: list[str]) -> list[dict[str, str]]:
    wanted = {str(label or "").strip() for label in labels}
    if not wanted:
        return []
    return [item for item in items if str(item.get("label") or "").strip() in wanted]


def optimization_labels() -> list[str]:
    return [item["label"] for item in OPTIMIZATION_DIRECTIONS]


def error_example_labels() -> list[str]:
    return [item["label"] for item in ERROR_EXAMPLES]


def selected_optimization_directions(labels: list[str]) -> list[dict[str, str]]:
    return _lookup(OPTIMIZATION_DIRECTIONS, labels)


def selected_error_examples(labels: list[str]) -> list[dict[str, str]]:
    return _lookup(ERROR_EXAMPLES, labels)


def compose_prompt_editor_fields(
    *,
    optimization_labels_selected: list[str] | None = None,
    error_labels_selected: list[str] | None = None,
    manual_scene_notes: str = "",
    manual_special_emphasis: str = "",
    manual_error_notes: str = "",
) -> dict[str, str]:
    optimization_items = selected_optimization_directions(list(optimization_labels_selected or []))
    error_items = selected_error_examples(list(error_labels_selected or []))

    scene_lines = _unique_lines(
        [item.get("scene_notes", "") for item in optimization_items],
        manual_scene_notes,
    )
    special_lines = _unique_lines(
        [item.get("special_emphasis", "") for item in optimization_items],
        manual_special_emphasis,
    )
    error_lines = _unique_lines(
        [item.get("prompt_fix", "") for item in error_items],
        manual_error_notes,
    )

    return {
        "prompt_scene_description_notes": "\n".join(scene_lines),
        "prompt_special_emphasis": "\n".join(special_lines),
        "prompt_error_notes": "\n".join(f"- {line}" for line in error_lines),
    }
