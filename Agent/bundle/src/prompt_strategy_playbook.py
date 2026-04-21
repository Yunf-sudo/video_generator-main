from __future__ import annotations

from typing import Any


OPTIMIZATION_DIRECTIONS: list[dict[str, str]] = [
    {
        "label": "前3秒更抓人",
        "description": "强化第一镜头的进入感，让用户更快停留。",
        "scene_notes": "Open with immediate visual tension or emotional contrast in the first three seconds and avoid slow warm-up.",
        "special_emphasis": "Make the opening frame instantly readable, decisive, and thumb-stopping for a cold Meta feed.",
    },
    {
        "label": "更像真实广告，不像AI图",
        "description": "减少概念图、摆拍感、过度完美环境。",
        "scene_notes": "Keep the environment grounded in believable lived-in spaces, practical outdoor routes, and natural camera behavior.",
        "special_emphasis": "Prioritize physical realism, believable lensing, normal lighting falloff, and credible product weight.",
    },
    {
        "label": "产品卖点更直接",
        "description": "让轮椅结构、操控和使用收益更容易看懂。",
        "scene_notes": "Frame the wheelchair so the joystick control, seating support, wheel proportion, and outdoor usability stay legible across scenes.",
        "special_emphasis": "Make product readability conversion-ready instead of relying only on atmosphere or lifestyle mood.",
    },
    {
        "label": "人物情绪更能转化",
        "description": "突出安全感、尊严感、陪伴感和恢复外出自由。",
        "scene_notes": "Show a clear before-versus-after emotional lift through posture, pace, and interaction with the companion.",
        "special_emphasis": "Emphasize dignity, relief, confidence, and regained freedom rather than generic smiling.",
    },
    {
        "label": "镜头连续性更稳",
        "description": "减少人物、服装、轮椅、空间关系在前后镜头漂移。",
        "scene_notes": "Keep all scenes on one coherent route and maintain consistent rider identity, wardrobe, wheelchair shape, and time-of-day logic.",
        "special_emphasis": "Protect continuity between adjacent scenes so the ad feels like one shoot instead of disconnected AI fragments.",
    },
    {
        "label": "更适合冷启动测试",
        "description": "更关注首屏理解、卖点传达和可测试性。",
        "scene_notes": "Keep each scene single-minded and easy to classify by angle so performance feedback can map back to one creative direction.",
        "special_emphasis": "Bias toward simple, readable, testable creative choices over artistic complexity.",
    },
]


ERROR_EXAMPLES: list[dict[str, str]] = [
    {
        "label": "轮椅后部乱长杆件",
        "symptom": "后面凭空多出杆子、天线、夸张推手或不真实结构。",
        "prompt_fix": "Avoid invented rear poles, antenna-like parts, cane-like extensions, or exaggerated push handles behind the wheelchair backrest.",
    },
    {
        "label": "同一人物体型漂移",
        "symptom": "前后镜头里同一个人忽胖忽瘦、年龄和身份变化。",
        "prompt_fix": "Keep the same heavyset or plus-size senior identity, body proportions, wardrobe, and posture across connected scenes.",
    },
    {
        "label": "轮椅像概念图不是实物",
        "symptom": "画面像 CG、海报、概念设计图，不像真实产品拍摄。",
        "prompt_fix": "Do not stylize the wheelchair into a concept render, fantasy product, or impossible studio hero object.",
    },
    {
        "label": "手没碰摇杆却自动行驶",
        "symptom": "轮椅自己跑，操控逻辑不可信。",
        "prompt_fix": "During self-operated motion, keep the rider's right hand on the right-side joystick and avoid hands-free driving.",
    },
    {
        "label": "白底参考图混进广告画面",
        "symptom": "白底 packshot、参考图闪现进正式广告镜头。",
        "prompt_fix": "Do not insert white-background reference photos, product catalog frames, or flash-cut identity sheets into the ad.",
    },
    {
        "label": "视频运动时结构变形",
        "symptom": "动起来后轮椅、人物或背景发生 morph、重置、拉扯。",
        "prompt_fix": "Avoid morphing, warped anatomy, product drift, jumpy continuity, and sudden scene resets during motion.",
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
