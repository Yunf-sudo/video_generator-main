from __future__ import annotations

import json
import re

from generation_prompt_builder import compose_generation_prompt
from generate_image_from_prompt import generate_image_from_prompt
from input_translation import translate_text_to_english
from local_storyboard_placeholder import create_storyboard_placeholder
from prompt_context import build_prompt_context
from prompt_overrides import apply_override
from product_reference_images import (
    get_product_reference_images,
    get_product_reference_bundle,
    get_product_reference_signature,
    get_product_visual_structure_json,
    merge_reference_images,
)
from prompts_en import generate_scene_pic_system_prompt
from runtime_tunables_config import load_runtime_tunables
from storyboard_image_guardrails import (
    inspect_storyboard_image_cleanliness,
    inspect_storyboard_image_visual_quality,
)


RUNTIME_TUNABLES = load_runtime_tunables()
APP_RUNTIME_FLAGS = RUNTIME_TUNABLES["app_runtime_flags"]
STORYBOARD_TEXT_GUARDRAIL_APPEND = (
    "画面清洁硬约束：最终分镜图本身不能出现任何字幕、lower-third、价格字、营销文案、按钮、角标、水印、界面 UI、"
    "社媒壳层、贴片文案或任何可读/半可读字符，包括中文、英文、数字、符号和乱码字形。"
    "唯一例外是参考实物本身自带、位于靠背上半部布面/口袋区域的居中白色 AnyWell 品牌布标；它属于产品本体，不属于后期字幕或 UI。"
    "如果脚本里提到 caption、subtitle、hook、offer、price、CTA 或后期文案，只表示后期可用的留白区域，"
    "不是让你把文字真的生成进画面。"
)

STORYBOARD_TEXT_RISK_PATTERNS = [
    r"\bsubtitle(?:_text)?\b",
    r"\bcaption\b",
    r"\blower[\s-]?third\b",
    r"\bcta\b",
    r"\bcall to action\b",
    r"\bbrand graphic\b",
    r"\bbrand lockup\b",
    r"\blogo lockup\b",
    r"\blogo overlay\b",
    r"\bend card\b",
    r"\bprice\b",
    r"\boffer\b",
    r"\bwatermark\b",
    r"\btagline\b",
]

STORYBOARD_TEXT_RISK_REGEXES = [re.compile(pattern, flags=re.IGNORECASE) for pattern in STORYBOARD_TEXT_RISK_PATTERNS]


def _extract_scene_root(scene_info: dict) -> tuple[str, list[dict], dict]:
    if "meta" in scene_info and "scenes" in scene_info:
        scenes_root = scene_info["scenes"]
        meta = scene_info.get("meta", {})
    else:
        scenes_root = scene_info
        meta = {}

    main_theme = scenes_root["main_theme"]
    scenes = scenes_root["scenes"]
    return main_theme, scenes, meta


def _resolve_scene_generation_context(scene_info: dict) -> dict:
    main_theme, scenes, meta = _extract_scene_root(scene_info)
    prompt_context = build_prompt_context(meta)
    use_product_reference_images = bool(meta.get("use_product_reference_images", True))
    product_reference_limit = int(meta.get("product_reference_image_limit", 5) or 5)
    product_reference_paths = get_product_reference_images(limit=product_reference_limit) if use_product_reference_images else []
    product_reference_bundle = get_product_reference_bundle(limit=product_reference_limit) if use_product_reference_images else {"all": [], "overview": [], "detail": [], "generic": [], "roles": {}, "source": ""}
    product_reference_signature = meta.get("product_reference_signature")
    if product_reference_signature is None:
        product_reference_signature = get_product_reference_signature() if use_product_reference_images else ""
    product_visual_structure = meta.get("product_visual_structure")
    if product_visual_structure is None:
        product_visual_structure = get_product_visual_structure_json() if use_product_reference_images else ""
    continuity_rider_anchor = (
        meta.get("continuity_rider_anchor")
        or "相连场景默认保持完全同一位成年人：同一张脸、同一发型、同一体型、同一肤色、同一套服装、同一年龄感；同时保持同一台轮椅，除非需求明确要求变化。"
    )
    return {
        "main_theme": main_theme,
        "scenes": scenes,
        "meta": meta,
        "prompt_context": prompt_context,
        "product_reference_paths": product_reference_paths,
        "product_reference_bundle": product_reference_bundle,
        "product_reference_signature": product_reference_signature,
        "product_visual_structure": product_visual_structure,
        "continuity_rider_anchor": continuity_rider_anchor,
    }


def _append_guardrail(base_text: str, extra_text: str) -> str:
    normalized_base = str(base_text or "").strip()
    normalized_extra = str(extra_text or "").strip()
    if not normalized_extra:
        return normalized_base
    if normalized_extra in normalized_base:
        return normalized_base
    return "\n\n".join(part for part in [normalized_base, normalized_extra] if part)


def _roll_forward_continuity_reference_paths(
    existing_paths: list[str] | None,
    new_path: str,
) -> list[str]:
    cleaned = [str(path).strip() for path in existing_paths or [] if str(path).strip()]
    new_value = str(new_path or "").strip()
    if not new_value:
        return cleaned
    if not cleaned:
        return [new_value]
    anchor = cleaned[0]
    if new_value == anchor:
        return [anchor]
    return [anchor, new_value]


def _build_storyboard_scene_reference_paths(
    continuity_reference_paths: list[str] | None,
    uploaded_reference_paths: list[str] | None,
    product_reference_paths: list[str] | None,
    limit: int = 6,
) -> list[str]:
    # For same-person continuity, prior approved storyboard frames must take priority.
    # Product identity references remain important, but should not crowd out continuity frames.
    return merge_reference_images(
        continuity_reference_paths or [],
        uploaded_reference_paths or [],
        product_reference_paths or [],
        limit=limit,
    )


def _scene_requests_controller_detail(scene_description: str, visuals: dict | None) -> bool:
    haystack = " ".join(
        [
            str(scene_description or ""),
            json.dumps(visuals or {}, ensure_ascii=False),
        ]
    ).lower()
    return any(
        token in haystack
        for token in [
            "joystick",
            "controller",
            "control panel",
            "thumb",
            "index finger",
            "precision pinch",
            "grip",
            "handle detail",
            "armrest close",
        ]
    )


def _scene_requests_front_caster_visible(scene_description: str, visuals: dict | None) -> bool:
    haystack = " ".join(
        [
            str(scene_description or ""),
            json.dumps(visuals or {}, ensure_ascii=False),
        ]
    ).lower()
    return any(
        token in haystack
        for token in [
            "front caster",
            "front wheel",
            "front-profile",
            "front profile",
            "front-side",
            "side profile",
            "joystick-side",
            "wheel profile",
            "前万向轮",
            "前轮",
            "前侧",
            "侧面",
        ]
    )


def _scene_requests_forward_motion(scene_description: str, visuals: dict | None) -> bool:
    haystack = " ".join(
        [
            str(scene_description or ""),
            json.dumps(visuals or {}, ensure_ascii=False),
        ]
    ).lower()
    return any(
        token in haystack
        for token in [
            "moving",
            "glides",
            "drives",
            "driving",
            "rolls",
            "rolling",
            "continues",
            "tracking shot",
            "forward travel",
            "moving left to right",
            "平稳前行",
            "继续前进",
            "向前",
            "行驶",
            "移动",
            "跟拍",
        ]
    )


def _scene_requests_chassis_detail(scene_description: str, visuals: dict | None) -> bool:
    haystack = " ".join(
        [
            str(scene_description or ""),
            json.dumps(visuals or {}, ensure_ascii=False),
        ]
    ).lower()
    return any(
        token in haystack
        for token in [
            "chassis",
            "underframe",
            "undercarriage",
            "underbody",
            "underside",
            "under-seat",
            "under seat",
            "wheel hub close",
            "rear wheel connection",
            "rear wheel joint",
            "motor close",
            "motor detail",
            "axle detail",
            "cross brace",
            "x-brace",
            "support bar",
            "底盘",
            "底部连杆",
            "底盘连接",
            "后轮与底盘连接",
            "后轮连接",
            "轮毂特写",
            "电机特写",
            "交叉支撑",
        ]
    )


def _build_scene_product_reference_plan(
    scene_description: str,
    visuals: dict | None,
    product_reference_bundle: dict | None,
) -> tuple[list[str], str]:
    bundle = product_reference_bundle if isinstance(product_reference_bundle, dict) else {}
    all_paths = [str(path).strip() for path in bundle.get("all", []) if str(path).strip()]
    if not all_paths:
        return [], ""

    overview_paths = [str(path).strip() for path in bundle.get("overview", []) if str(path).strip()]
    detail_paths = [str(path).strip() for path in bundle.get("detail", []) if str(path).strip()]
    chassis_overview_paths = [str(path).strip() for path in bundle.get("chassis_overview", []) if str(path).strip()]
    chassis_detail_paths = [str(path).strip() for path in bundle.get("chassis_detail", []) if str(path).strip()]
    chassis_paths = chassis_overview_paths + chassis_detail_paths
    generic_paths = [str(path).strip() for path in bundle.get("generic", []) if str(path).strip()]

    needs_joystick_detail = _scene_requests_controller_detail(scene_description, visuals)
    needs_chassis_detail = _scene_requests_chassis_detail(scene_description, visuals)
    needs_backrest_logo = _scene_requests_backrest_logo(scene_description, visuals)

    strategy_notes: list[str] = []
    selected_product_paths: list[str]

    if overview_paths:
        strategy_notes.append(
            "参考图分配规则：轮椅整体身份、车架比例、前后轮关系、侧壳、脚踏、靠背布面、后把手和 logo 位置，始终以多视角全景拼版为主锚点。"
        )
        strategy_notes.append(
            "如果镜头能看到前万向轮，就从全景拼版里的前轮细节继承真实前叉总成：保持黑色小前轮、真实叉架厚度、连接点和轮轴关系，不要画成自行车前叉、细杆脚轮或错误的双叉结构。"
        )
        strategy_notes.append(
            "只有当镜头是后背正向或后侧 3/4，且后背口袋区域正面朝向镜头时，才允许看到参考产品自带的居中白色 AnyWell 布标；前侧或纯侧构图里不要读到任何 side logo。"
        )
    if chassis_paths:
        strategy_notes.append(
            "如果镜头会看到底盘、后轮连接处、电机、交叉支撑管或座椅下方开放结构，就把底盘参考图当成局部硬锚点，锁定 X 形支撑管、后轮与底盘连接件、后轮内侧电机/轮毂关系和开放式底部结构。"
        )

    if needs_joystick_detail and needs_chassis_detail and (detail_paths or chassis_paths):
        selected_product_paths = merge_reference_images(
            detail_paths,
            chassis_detail_paths,
            chassis_overview_paths,
            overview_paths,
            generic_paths,
            limit=len(all_paths),
        )
        strategy_notes.append(
            "这个镜头同时涉及右手控制和底盘可见区域，所以优先锁定把手/摇杆细节与底盘结构，再由全景拼版维持整车比例。"
        )
    elif needs_joystick_detail and detail_paths:
        selected_product_paths = merge_reference_images(
            detail_paths,
            overview_paths,
            chassis_overview_paths,
            generic_paths,
            limit=len(all_paths),
        )
        strategy_notes.append(
            "这个镜头能看到右手、摇杆或控制面板，所以把手/摇杆细节拼版必须作为局部强锚点：保持弯管把手、橡胶握把、摇杆帽形状、控制器外壳体块、按键布局和指示灯位置一致。"
        )
    elif needs_chassis_detail and chassis_paths:
        selected_product_paths = merge_reference_images(
            chassis_detail_paths,
            chassis_overview_paths,
            overview_paths,
            generic_paths,
            limit=len(all_paths),
        )
        strategy_notes.append(
            "这个镜头会暴露底盘、后轮与底盘连接处或座椅下方开放结构，所以底盘参考图必须优先：保持 X 形交叉支撑管、后轮内侧电机位置、连接件角度、银灰/黑色金属件比例和开放式底部关系一致。"
        )
    elif needs_backrest_logo:
        selected_product_paths = merge_reference_images(overview_paths, chassis_overview_paths, generic_paths, limit=len(all_paths))
        strategy_notes.append(
            "这个镜头能看到靠背上半部或侧后方，所以必须从全景拼版继承后背布面、AnyWell 标识位置和短小后把手关系。"
        )
        if detail_paths:
            strategy_notes.append(
                "如果这个镜头并没有清楚看到摇杆和控制面板，就不要让把手/摇杆细节拼版喧宾夺主。"
            )
    elif overview_paths:
        selected_product_paths = merge_reference_images(overview_paths, generic_paths, chassis_overview_paths, limit=len(all_paths))
        if detail_paths:
            strategy_notes.append(
                "这不是摇杆近景时，不要为了呼应细节拼版而强行放大控制器或额外暴露手部近景。"
            )
        if chassis_paths:
            strategy_notes.append(
                "这不是底盘特写时，不要为了呼应底盘参考图而刻意使用过低机位或无缘无故暴露座椅下方。"
            )
    else:
        selected_product_paths = all_paths

    return selected_product_paths, "\n".join(strategy_notes)


def _scene_requests_joystick_pinch(scene_description: str, visuals: dict | None) -> bool:
    haystack = " ".join(
        [
            str(scene_description or ""),
            json.dumps(visuals or {}, ensure_ascii=False),
        ]
    ).lower()
    return any(
        token in haystack
        for token in [
            "joystick",
            "self-drive",
            "self drive",
            "self-operated",
            "right hand",
            "driving himself",
            "moves independently",
            "navigating",
            "maneuvers",
        ]
    )


def _scene_requests_backrest_logo(scene_description: str, visuals: dict | None) -> bool:
    haystack = " ".join(
        [
            str(scene_description or ""),
            json.dumps(visuals or {}, ensure_ascii=False),
        ]
    ).lower()
    explicit_logo_signal = any(
        token in haystack
        for token in [
            "logo visible",
            "brand is visible",
            "anywell brand is visible",
            "anywell logo",
            "backrest pocket logo",
            "rear logo visible",
            "rear backrest logo visible",
            "backrest logo faces camera",
        ]
    )
    rear_visibility_signal = any(
        token in haystack
        for token in [
            "from behind",
            "behind and slightly to the side",
            "rear three-quarter",
            "rear 3/4",
            "back view",
            "rear view",
        ]
    )
    return explicit_logo_signal or rear_visibility_signal


def _scene_specific_storyboard_guardrail(
    scene_description: str,
    visuals: dict | None,
) -> tuple[str, bool, bool]:
    expect_joystick_pinch_visible = _scene_requests_joystick_pinch(scene_description, visuals)
    expect_backrest_logo_visible = _scene_requests_backrest_logo(scene_description, visuals)
    expect_front_caster_visible = _scene_requests_front_caster_visible(scene_description, visuals)
    expect_forward_motion = _scene_requests_forward_motion(scene_description, visuals)
    expect_chassis_detail = _scene_requests_chassis_detail(scene_description, visuals)
    instructions: list[str] = []
    if expect_joystick_pinch_visible:
        instructions.append(
            "场景级硬约束：这是自驾镜头，必须能看清乘坐者右手用大拇指和食指捏住右侧摇杆，形成明确的 precision pinch；不要让手势含糊、不要只把手搭在扶手上，也不要被构图完全挡住。"
        )
    if expect_front_caster_visible:
        instructions.append(
            "场景级硬约束：如果前万向轮可见，必须匹配参考图里的真实前叉总成与轮轴关系：保持黑色小前轮、厚实黑色叉架/支架、真实连接件与轮轴位置，不要简化成细杆脚轮、自行车前叉、手推轮椅那种错误双叉，或其他被重新设计过的前轮结构。"
        )
    if expect_front_caster_visible and expect_forward_motion:
        instructions.append(
            "因为这是明确前进镜头，前万向轮要呈现自然拖曳后的受力关系：转轴在前，小轮中心优先在后，前叉从转轴向后包住小轮；不要出现前叉朝前硬伸、像反装、像僵死锁住的错误方向。"
        )
    if expect_chassis_detail:
        instructions.append(
            "场景级硬约束：这个镜头会看到座椅下方、后轮内侧或底盘连接处，因此必须保留参考图里的开放式底盘结构：中央 X 形交叉支撑管、左右对称的下部管架、后轮内侧圆柱电机/轮毂关系，以及靠近后轮的真实连接支架。不要把底盘改成整块封闭底板、黑盒、假悬挂、单杆替代或左右不对称的错误连杆。"
        )
    if expect_backrest_logo_visible:
        instructions.append(
            "场景级硬约束：只有当镜头是后背正向或后侧 3/4，且后背口袋区域正面朝向镜头时，才允许在靠背上半部布面看到居中的白色 AnyWell 标识；不要缺失，也不要把标识放到侧板、扶手、轮子或底盘。"
        )
    else:
        instructions.append(
            "场景级硬约束：这不是后背正向口袋视角，因此侧边、前侧和纯侧构图里绝对不要读到 AnyWell logo；靠背侧边应保持纯黑布面，不要出现可读字样。"
        )
    return "\n".join(instructions), expect_joystick_pinch_visible, expect_backrest_logo_visible


def _scene_background_progression_guardrail(
    scene_number: int,
    previous_scene: dict | None,
    next_scene: dict | None,
) -> str:
    instructions: list[str] = [
        "背景连续性硬约束：三个场景必须属于一次连续出行，但每个场景的背景身份必须清楚不同，不能只是相似绿植或相似门口背景的重复变体。"
    ]
    if scene_number == 1:
        instructions.append(
            "当前是第一场景：背景必须清楚读出住宅出入口、门廊、门框、阈值或 patio 起点，让观众一眼知道这是从家门口出发。"
        )
    elif scene_number == 2:
        instructions.append(
            "当前是第二场景：背景必须转到更封闭的院子、花园路径、灌木边或小路中段，不能还像第一场景那样以门廊/门框为主背景。"
        )
    elif scene_number >= 3:
        instructions.append(
            "当前是第三场景或最后一段：背景必须明显更开阔，读出街边、人行道、社区道路或公园边缘，不能继续像院子内部或门口附近。"
        )
    if previous_scene:
        instructions.append("当前场景背景必须明显区别于上一镜的主要空间身份，但仍保持同一路线的前进逻辑。")
    if next_scene:
        instructions.append("当前场景结尾应为下一镜留出自然过渡，不要把后续场景会出现的背景提前重复完。")
    return "\n".join(instructions)


def _contains_storyboard_text_risk(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    return any(pattern.search(text) for pattern in STORYBOARD_TEXT_RISK_REGEXES)


def _strip_storyboard_text_risk_phrases(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    replacements = [
        (r"(?i)\b(?:subtle\s+)?brand graphic\b", ""),
        (r"(?i)\bbrand lockup\b", ""),
        (r"(?i)\blogo lockup\b", ""),
        (r"(?i)\blogo overlay\b", ""),
        (r"(?i)\bend card\b", ""),
        (r"(?i)\bcall to action\b", ""),
        (r"(?i)\bCTA\b", ""),
        (r"(?i)\bsubtitle(?:_text)?\b", ""),
        (r"(?i)\bcaption\b", ""),
        (r"(?i)\blower[\s-]?third\b", ""),
        (r"(?i)\btagline\b", ""),
        (r"(?i)\bwatermark\b", ""),
        (r"(?i)\bprice\b", ""),
        (r"(?i)\boffer\b", ""),
    ]
    sanitized = text
    for pattern, replacement in replacements:
        sanitized = re.sub(pattern, replacement, sanitized)
    sanitized = re.sub(r"(?i)\bthe\s+the\b", "the", sanitized)
    sanitized = re.sub(r"\(\s*(?:the\s+)?(?:clean\s+fabric\s+detail|clean\s+backrest\s+fabric)\s*\)", "", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"\s+", " ", sanitized)
    sanitized = re.sub(r"\s+([,.;:!?])", r"\1", sanitized)
    return sanitized.strip(" ,.;:")


def _sanitize_storyboard_text(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    stripped = _strip_storyboard_text_risk_phrases(text)
    if stripped and not _contains_storyboard_text_risk(stripped):
        return stripped
    if not _contains_storyboard_text_risk(text):
        return text
    sanitized_lines = [
        _strip_storyboard_text_risk_phrases(line).strip()
        for line in text.splitlines()
        if _strip_storyboard_text_risk_phrases(line).strip() and not _contains_storyboard_text_risk(_strip_storyboard_text_risk_phrases(line))
    ]
    sanitized = " ".join(sanitized_lines).strip()
    if sanitized:
        return sanitized
    return ""


def _sanitize_storyboard_visuals(visuals: dict | None) -> dict:
    raw = visuals if isinstance(visuals, dict) else {}
    cleaned: dict = {}
    for key, value in raw.items():
        text = str(value or "").strip()
        if not text:
            continue
        if key == "transition_anchor" and _contains_storyboard_text_risk(text):
            cleaned[key] = "End on a clean visual beat for the next cut without any text, logo lockup, brand card, or graphic overlay."
            continue
        sanitized = _sanitize_storyboard_text(text)
        if sanitized:
            cleaned[key] = sanitized
    return cleaned


def _sanitize_storyboard_audio(audio: dict | None) -> dict:
    raw = audio if isinstance(audio, dict) else {}
    cleaned: dict = {}
    for key, value in raw.items():
        if key in {"text", "subtitle_text", "subtitle", "subtitle_zh"}:
            continue
        text = str(value or "").strip()
        if not text:
            continue
        sanitized = _sanitize_storyboard_text(text)
        if sanitized:
            cleaned[key] = sanitized
    return cleaned


def _sanitize_storyboard_key_message(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    sanitized = _sanitize_storyboard_text(text)
    if not sanitized:
        return ""
    lowered = sanitized.lower()
    if "call to action" in lowered or "cta" in lowered:
        return ""
    return sanitized


def _sanitize_storyboard_scene_description(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    sanitized = _sanitize_storyboard_text(text)
    if sanitized:
        return sanitized
    return (
        "Keep the same rider and wheelchair in a clean, photorealistic outdoor lifestyle shot with no text, "
        "no logo lockup, and no graphic overlay."
    )


def build_storyboard_scene_request(
    scene_info: dict,
    scene_number: int,
    reference_image_paths: list[str] | None = None,
    aspect_ratio: str = "9:16",
    continuity_reference_paths: list[str] | None = None,
    prompt_override: str | None = None,
    system_prompt_override: str | None = None,
    allow_ai_composer: bool = False,
) -> dict:
    context = _resolve_scene_generation_context(scene_info)
    scenes = context["scenes"]
    scene_index = max(0, int(scene_number) - 1)
    if scene_index >= len(scenes):
        raise IndexError(f"Scene {scene_number} is out of range for storyboard generation.")

    scene = scenes[scene_index]
    previous_scene = scenes[scene_index - 1] if scene_index > 0 else None
    next_scene = scenes[scene_index + 1] if scene_index + 1 < len(scenes) else None
    sanitized_scene_description = _sanitize_storyboard_scene_description(scene.get("scene_description", ""))
    sanitized_scene_visuals = _sanitize_storyboard_visuals(scene.get("visuals", {}))
    sanitized_scene_audio = _sanitize_storyboard_audio(scene.get("audio", {}))
    sanitized_scene_key_message = _sanitize_storyboard_key_message(scene.get("key_message", ""))
    scene_specific_guardrail, expect_joystick_pinch_visible, expect_backrest_logo_visible = _scene_specific_storyboard_guardrail(
        sanitized_scene_description,
        sanitized_scene_visuals,
    )
    background_progression_guardrail = _scene_background_progression_guardrail(
        int(scene.get("scene_number", scene_index + 1) or scene_index + 1),
        previous_scene,
        next_scene,
    )
    selected_product_reference_paths, scene_reference_strategy = _build_scene_product_reference_plan(
        sanitized_scene_description,
        sanitized_scene_visuals,
        context.get("product_reference_bundle"),
    )
    continuity = {
        "same_rider_default": context["continuity_rider_anchor"],
        "previous_scene": {
            "scene_number": previous_scene.get("scene_number", scene_index),
            "theme": previous_scene.get("theme", ""),
            "key_message": _sanitize_storyboard_key_message(previous_scene.get("key_message", "")),
            "scene_description": _sanitize_storyboard_scene_description(previous_scene.get("scene_description", "")),
            "visuals": _sanitize_storyboard_visuals(previous_scene.get("visuals", {})),
        }
        if previous_scene
        else None,
        "next_scene": {
            "scene_number": next_scene.get("scene_number", scene_index + 2),
            "theme": next_scene.get("theme", ""),
            "key_message": _sanitize_storyboard_key_message(next_scene.get("key_message", "")),
            "scene_description": _sanitize_storyboard_scene_description(next_scene.get("scene_description", "")),
            "visuals": _sanitize_storyboard_visuals(next_scene.get("visuals", {})),
        }
        if next_scene
        else None,
    }

    model_input = {
        "product_name": context["meta"].get("product_name", ""),
        "product_category": context["meta"].get("product_category", ""),
        "consistency_anchor": context["meta"].get("consistency_anchor", ""),
        "product_geometry_notes": context["meta"].get("product_geometry_notes", ""),
        "product_reference_signature": context["product_reference_signature"],
        "product_visual_structure": context["product_visual_structure"],
        "main_theme": context["main_theme"],
        "aspect_ratio": aspect_ratio,
        "continuity": continuity,
        "scene_to_generate": {
            "scene_number": scene.get("scene_number", scene_index + 1),
            "theme": scene.get("theme", ""),
            "duration_seconds": scene.get("duration_seconds", 8),
            "scene_description": sanitized_scene_description,
            "visuals": sanitized_scene_visuals,
            "audio": sanitized_scene_audio,
            "key_message": sanitized_scene_key_message,
        },
    }
    prompt_composition = compose_generation_prompt(
        target="image",
        scene_description=sanitized_scene_description,
        visuals=sanitized_scene_visuals,
        scene_audio=sanitized_scene_audio,
        continuity=continuity,
        aspect_ratio=aspect_ratio,
        duration_seconds=int(scene.get("duration_seconds", 8) or 8),
        meta=context["meta"],
        hero_product_name=context["meta"].get("hero_product_name") or context["meta"].get("product_name"),
        product_reference_signature=context["product_reference_signature"],
        product_visual_structure=context["product_visual_structure"],
        allow_ai_composer=allow_ai_composer,
    )
    filled_prompt = str(prompt_override or prompt_composition["prompt"]).strip()
    if not filled_prompt:
        filled_prompt = prompt_composition["fallback_prompt"]
    filled_prompt = _append_guardrail(filled_prompt, scene_reference_strategy)
    filled_prompt = _append_guardrail(filled_prompt, background_progression_guardrail)
    filled_prompt = _append_guardrail(filled_prompt, scene_specific_guardrail)
    filled_prompt = _append_guardrail(filled_prompt, STORYBOARD_TEXT_GUARDRAIL_APPEND)
    system_prompt = str(
        system_prompt_override
        or apply_override(
            generate_scene_pic_system_prompt.format(**context["prompt_context"]),
            "scene_pic_system_append",
        )
    ).strip()
    system_prompt = _append_guardrail(system_prompt, scene_reference_strategy)
    system_prompt = _append_guardrail(system_prompt, background_progression_guardrail)
    system_prompt = _append_guardrail(system_prompt, scene_specific_guardrail)
    system_prompt = _append_guardrail(system_prompt, STORYBOARD_TEXT_GUARDRAIL_APPEND)

    storyboard_text_guardrail_enabled = bool(
        context["meta"].get(
            "storyboard_text_guardrail_enabled",
            APP_RUNTIME_FLAGS.get("storyboard_text_guardrail_enabled", True),
        )
    )
    storyboard_text_guardrail_retry_count = max(
        1,
        int(
            context["meta"].get(
                "storyboard_text_guardrail_retry_count",
                APP_RUNTIME_FLAGS.get("storyboard_text_guardrail_retry_count", 3),
            )
            or 1
        ),
    )
    storyboard_visual_guardrail_enabled = bool(
        context["meta"].get(
            "storyboard_visual_guardrail_enabled",
            APP_RUNTIME_FLAGS.get("storyboard_visual_guardrail_enabled", True),
        )
    )
    storyboard_allow_placeholder_fallback = bool(
        context["meta"].get(
            "storyboard_allow_placeholder_fallback",
            APP_RUNTIME_FLAGS.get("storyboard_allow_placeholder_fallback", False),
        )
    )

    continuity_reference_paths = [
        str(path).strip()
        for path in continuity_reference_paths or []
        if str(path or "").strip()
    ]
    uploaded_reference_paths = [
        str(path).strip()
        for path in reference_image_paths or []
        if str(path or "").strip()
    ]
    scene_reference_paths = _build_storyboard_scene_reference_paths(
        continuity_reference_paths=continuity_reference_paths,
        uploaded_reference_paths=uploaded_reference_paths,
        product_reference_paths=selected_product_reference_paths,
        limit=6,
    )
    return {
        "scene_number": scene.get("scene_number", scene_index + 1),
        "duration_seconds": scene.get("duration_seconds", 8),
        "scene_description": sanitized_scene_description,
        "visuals": sanitized_scene_visuals,
        "audio": sanitized_scene_audio,
        "key_message": sanitized_scene_key_message,
        "continuity": continuity,
        "image_prompt_bundle": model_input,
        "image_prompt_composer_bundle": prompt_composition["bundle"],
        "image_prompt_fallback": prompt_composition["fallback_prompt"],
        "image_prompt_mode": prompt_composition["composition_mode"],
        "image_prompt_model": prompt_composition["composer_model"],
        "image_prompt": filled_prompt,
        "image_system_prompt": system_prompt,
        "scene_reference_strategy": scene_reference_strategy,
        "background_progression_guardrail": background_progression_guardrail,
        "scene_reference_paths": scene_reference_paths,
        "scene_product_reference_paths": selected_product_reference_paths,
        "product_reference_roles": dict((context.get("product_reference_bundle") or {}).get("roles") or {}),
        "continuity_reference_paths": continuity_reference_paths,
        "expect_joystick_pinch_visible": expect_joystick_pinch_visible,
        "expect_backrest_logo_visible": expect_backrest_logo_visible,
        "storyboard_text_guardrail_enabled": storyboard_text_guardrail_enabled,
        "storyboard_text_guardrail_retry_count": storyboard_text_guardrail_retry_count,
        "storyboard_visual_guardrail_enabled": storyboard_visual_guardrail_enabled,
        "storyboard_allow_placeholder_fallback": storyboard_allow_placeholder_fallback,
    }


def generate_storyboard_scene(
    scene_info: dict,
    scene_number: int,
    reference_image_paths: list[str] | None = None,
    aspect_ratio: str = "9:16",
    continuity_reference_paths: list[str] | None = None,
    prompt_override: str | None = None,
    system_prompt_override: str | None = None,
    allow_ai_composer: bool = False,
) -> dict:
    frame = build_storyboard_scene_request(
        scene_info=scene_info,
        scene_number=scene_number,
        reference_image_paths=reference_image_paths,
        aspect_ratio=aspect_ratio,
        continuity_reference_paths=continuity_reference_paths,
        prompt_override=prompt_override,
        system_prompt_override=system_prompt_override,
        allow_ai_composer=allow_ai_composer,
    )

    generated_pic_path = ""
    image_generation_mode = "remote"
    image_generation_error = ""
    image_generation_warnings: list[str] = []
    image_validation: dict = {"status": "skipped", "has_disallowed_text": False, "reason": "", "evidence": []}
    visual_validation: dict = {
        "status": "skipped",
        "is_photorealistic": True,
        "has_identity_drift": False,
        "has_wheelchair_drift": False,
        "reason": "",
        "evidence": [],
    }
    image_validation_attempts = 0
    retry_limit = int(frame.get("storyboard_text_guardrail_retry_count", 1) or 1)
    try:
        for attempt in range(1, retry_limit + 1):
            image_validation_attempts = attempt
            attempt_feedback = ""
            if attempt > 1:
                retry_notes = []
                if image_validation.get("status") == "failed":
                    retry_notes.append("上一版分镜图被质检判定含有画面内文字、字幕、水印、角标或 UI，这一版必须保持相同场景意图，但整个画面完全无字。")
                    if str(image_validation.get("reason", "") or "").strip():
                        retry_notes.append(f"文字质检原因：{str(image_validation.get('reason', '')).strip()}")
                if visual_validation.get("status") == "failed":
                    retry_notes.append("上一版分镜图不够照片级真实，或者没有保持同一个人物/同一台轮椅，这一版必须修正。")
                    if str(visual_validation.get("reason", "") or "").strip():
                        retry_notes.append(f"视觉质检原因：{str(visual_validation.get('reason', '')).strip()}")
                evidence = list(image_validation.get("evidence") or []) + list(visual_validation.get("evidence") or [])
                evidence_text = "; ".join(str(item).strip() for item in evidence if str(item).strip())
                attempt_feedback = "\n".join(note for note in retry_notes if note)
                if evidence_text:
                    attempt_feedback += f"\n可见问题证据：{evidence_text}"
            generated_pic_path = generate_image_from_prompt(
                prompt=_append_guardrail(frame["image_prompt"], attempt_feedback),
                system_prompt=_append_guardrail(frame["image_system_prompt"], attempt_feedback),
                reference_pic_paths=frame["scene_reference_paths"] or None,
                aspect_ratio=aspect_ratio,
            )
            if not bool(frame.get("storyboard_text_guardrail_enabled", True)):
                image_validation = {"status": "skipped", "has_disallowed_text": False, "reason": "", "evidence": []}
            else:
                image_validation = inspect_storyboard_image_cleanliness(generated_pic_path)
            if not bool(frame.get("storyboard_visual_guardrail_enabled", True)):
                visual_validation = {
                    "status": "skipped",
                    "is_photorealistic": True,
                    "has_identity_drift": False,
                    "has_wheelchair_drift": False,
                    "reason": "",
                    "evidence": [],
                }
            else:
                visual_validation = inspect_storyboard_image_visual_quality(
                    generated_pic_path,
                    continuity_reference_paths=frame.get("continuity_reference_paths") or [],
                    expect_joystick_pinch_visible=bool(frame.get("expect_joystick_pinch_visible", False)),
                    expect_backrest_logo_visible=bool(frame.get("expect_backrest_logo_visible", False)),
                )
            if (
                not image_validation.get("has_disallowed_text")
                and visual_validation.get("status") != "failed"
            ):
                break
            if attempt >= retry_limit:
                risk_messages = []
                if image_validation.get("status") == "failed":
                    risk_messages.append(
                        "分镜图存在文字风险：检测到画面内字幕、文字、水印或 UI。"
                        f" {image_validation.get('reason', '')}".strip()
                    )
                if visual_validation.get("status") == "failed":
                    risk_messages.append(
                        "分镜图存在视觉风险：画面不够照片级真实，或没有保持同一个人物/同一台轮椅。"
                        f" {visual_validation.get('reason', '')}".strip()
                    )
                image_generation_mode = "remote_with_risk"
                image_generation_error = " ".join(message for message in risk_messages if message).strip()
                image_generation_warnings = [message for message in risk_messages if message]
                break
        if (
            image_validation_attempts > 1
            and image_validation.get("status") == "passed"
            and visual_validation.get("status") in {"passed", "skipped", "unknown"}
        ):
            image_generation_mode = "remote_retry_succeeded"
    except Exception as exc:
        image_generation_error = str(exc)
        if bool(frame.get("storyboard_allow_placeholder_fallback", False)):
            image_generation_mode = "placeholder"
            generated_pic_path = create_storyboard_placeholder(
                scene_number=int(frame.get("scene_number", scene_number)),
                scene_description=frame.get("scene_description", ""),
                key_message=frame.get("key_message", ""),
                aspect_ratio=aspect_ratio,
            )
        else:
            image_generation_mode = "failed"
            generated_pic_path = ""

    return {
        **frame,
        "saved_path": generated_pic_path,
        "image_generation_mode": image_generation_mode,
        "image_generation_error": image_generation_error,
        "image_generation_warnings": image_generation_warnings,
        "image_validation": image_validation,
        "visual_validation": visual_validation,
        "image_validation_attempts": image_validation_attempts,
    }


def generate_storyboard(
    scene_info: dict,
    reference_image_paths: list[str] | None = None,
    aspect_ratio: str = "9:16",
    prompt_overrides: dict[str, dict] | None = None,
):
    _, scenes, _ = _extract_scene_root(scene_info)
    prompt_overrides = prompt_overrides or {}
    ret = []
    continuity_reference_paths: list[str] = []

    for index, scene in enumerate(scenes, start=1):
        override = prompt_overrides.get(str(scene.get("scene_number", index))) or {}
        frame = generate_storyboard_scene(
            scene_info=scene_info,
            scene_number=int(scene.get("scene_number", index) or index),
            reference_image_paths=reference_image_paths,
            aspect_ratio=aspect_ratio,
            continuity_reference_paths=continuity_reference_paths,
            prompt_override=override.get("image_prompt"),
            system_prompt_override=override.get("image_system_prompt"),
        )
        ret.append(frame)
        if frame.get("saved_path") and str(frame.get("image_generation_mode") or "").strip() in {"remote", "remote_retry_succeeded", "remote_with_risk"}:
            continuity_reference_paths = _roll_forward_continuity_reference_paths(
                continuity_reference_paths,
                str(frame.get("saved_path") or "").strip(),
            )

    return ret


def repair_single_pic(pic_path: str, feedback: str, aspect_ratio: str = "9:16"):
    translated_feedback = translate_text_to_english(feedback)
    filled_prompt = (
        "Refine the uploaded storyboard frame while preserving its overall subject continuity unless the user "
        "explicitly asks to change it.\n"
        f"Reference product context: {get_product_reference_signature()}\n"
        f"Requested change: {translated_feedback}"
    )
    filled_prompt = _append_guardrail(filled_prompt, STORYBOARD_TEXT_GUARDRAIL_APPEND)
    system_prompt = (
        "Edit the uploaded image with minimal necessary change. Keep the overall visual direction coherent, "
        "improve realism and physical plausibility, and respect the user's requested adjustment."
    )
    system_prompt = _append_guardrail(system_prompt, STORYBOARD_TEXT_GUARDRAIL_APPEND)

    return generate_image_from_prompt(
        filled_prompt,
        reference_pic_paths=merge_reference_images((get_product_reference_bundle(limit=5).get("overview") or get_product_reference_images()), [pic_path], limit=5),
        system_prompt=apply_override(system_prompt, "scene_pic_system_append"),
        aspect_ratio=aspect_ratio,
    )
