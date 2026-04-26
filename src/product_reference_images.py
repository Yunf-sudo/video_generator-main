from __future__ import annotations

import json
from pathlib import Path

from workspace_paths import PROJECT_ROOT


PRODUCT_REFERENCE_DIR_CANDIDATES = [
    PROJECT_ROOT.parent / "白底图",
    PROJECT_ROOT / "白底图",
]
SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
PRODUCT_VISUAL_EXCLUSION_RULES = (
    "广告生成约束：轮椅只能以正常展开、可骑乘的状态出现。"
    "后背上部结构要紧凑、真实，并与实物比例一致。"
    "不要凭空生成额外杆件、天线状结构、拐杖状延伸件、夸张推手或任何从靠背后方高高竖起的金属件。"
    "正式产品没有头枕或颈托。后背顶部如果可见，应是贴近靠背上角的短小结构，而不是高耸支撑件。"
    "不要出现后下方外挂电池、可拆电池、外露电池线、折叠状态、半折叠状态、收纳形态或折叠演示。"
    "如果参考图里存在后下方电池，请在广告画面里通过角度、人物遮挡、轮子、阴影或构图把它完全隐藏，同时保留其他产品身份特征。"
    "必须保留参考图中的轮组关系：小号黑色前万向轮、大号后驱动轮、匹配的轮毂罩、胎宽、间距和前后轮比例。"
    "前进时，前万向轮必须符合物理逻辑：垂直转轴在前，小轮中心在后，前叉从转轴向后包住小轮，不能画成前叉朝前。"
    "生成画面必须是真人实拍质感：不要卡通、动画、二次元、插画、风格化绘画、3D 渲染、CGI、游戏资产或塑料假人质感。"
    "品牌标识必须遵循参考产品：如果能看到后背上半部布面，居中的白色 AnyWell 标识只能出现在该布面/口袋区域，不能跑到下方壳体、保险杠或底盘。"
    "侧板、侧架、扶手、轮子和前部区域都应保持干净，不要额外生成侧边 logo、文字、贴纸或虚构徽标。"
    "不要使用正后方居中的产品角度。即便需要带一点后背信息，也只允许轻微、抬高的侧后角度，并且要让后下部区域保持隐藏。"
    "座椅下方和后下方不要变成黑盒、电池块、袋子或实心黑块，应尽量表现为轻盈、开放的管架关系。"
    "镜头不要放在骑手正后方；生活方式场景里，观众应能看到人物前胸、柔和侧脸、右前臂和右侧摇杆手。"
    "白底产品图只用于识别产品身份，正式广告里不要复现白底棚拍、packshot、剖面图或产品页闪帧。"
)
REAR_DETAIL_BLOCKLIST = (
    "battery",
    "cable",
    "fold",
    "collapsed",
    "storage pocket",
    "rear backrest panel",
    "back panel with storage",
    "mounting point",
    "red backrest",
    "red fabric strip",
    "red mesh",
    "backrest accent",
    "rear caregiver",
    "long rod",
    "pole",
    "antenna-like",
    "push bar",
)
PREFERRED_REFERENCE_BASENAMES = [
    "DSC_0401.JPG",
    "DSC_0400.JPG",
    "DSC_0396.JPG",
    "DSC_0395.JPG",
    "DSC_0384.JPG",
]


def _find_reference_dir() -> Path | None:
    for candidate in PRODUCT_REFERENCE_DIR_CANDIDATES:
        if candidate.exists() and candidate.is_dir():
            return candidate
    return None


def _sample_evenly(paths: list[Path], limit: int) -> list[Path]:
    if limit <= 0 or not paths:
        return []
    if len(paths) <= limit:
        return paths
    if limit == 1:
        return [paths[0]]

    last_index = len(paths) - 1
    chosen_indexes = sorted({round(index * last_index / (limit - 1)) for index in range(limit)})
    sampled = [paths[index] for index in chosen_indexes]
    if len(sampled) >= limit:
        return sampled[:limit]

    for path in paths:
        if path in sampled:
            continue
        sampled.append(path)
        if len(sampled) >= limit:
            break
    return sampled


def get_product_reference_images(limit: int = 5) -> list[str]:
    reference_dir = _find_reference_dir()
    if reference_dir is None:
        return []

    image_paths = sorted(
        path for path in reference_dir.iterdir() if path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS
    )
    preferred_paths = [
        reference_dir / basename
        for basename in PREFERRED_REFERENCE_BASENAMES
        if (reference_dir / basename).exists()
    ]
    if preferred_paths:
        remaining_paths = [
            path for path in image_paths if path.name not in PREFERRED_REFERENCE_BASENAMES
        ]
        sampled = preferred_paths[:limit]
        sampled.extend(_sample_evenly(remaining_paths, limit=limit - len(sampled)))
    else:
        sampled = _sample_evenly(image_paths, limit=limit)
    return [str(path.resolve()) for path in sampled]


def get_product_reference_signature() -> str:
    structure_text = get_product_visual_structure_signature()
    if structure_text:
        return (
            "尽量准确匹配白底产品图中的真实轮椅。\n"
            f"{structure_text}"
        )
    return (
        "请尽量准确匹配白底产品图中的真实轮椅。"
        "它是一台正常展开状态的紧凑型电动轮椅，具有银灰色金属管架、黑色扶手、黑色坐垫和黑色靠背。"
        "右侧扶手前上方有摇杆控制器，扶手下方是深灰色流线型侧壳。"
        "后轮较大，带银色轮毂罩和红色中心点缀；前轮较小，为黑色万向轮；脚踏为黑色翻转式脚踏。"
        "顶部后背轮廓紧凑，不要把它替换成医院轮椅、手动轮椅、厚辐条轮椅或完全不同的车架。"
        "前进时，前万向轮必须符合物理方向：小轮中心在转轴后方，前叉从转轴向后包住小轮。"
        "轮椅侧面应保持干净，不要出现侧边 logo、文字、贴纸或虚构品牌件；如果能看到后背上半部布面，居中的白色 AnyWell 标识只能在该区域。"
        "必须保持与实拍参考图一致的比例、车架关系、轮组布局、扶手形状、控制器位置、侧壳和轮毂特征。"
        f"{PRODUCT_VISUAL_EXCLUSION_RULES}"
    )


def _strip_rear_detail_language(text: str) -> str:
    replacements = {
        "rectangular back panel with branding; red accent strip at top rear": "black fabric backrest visible only as a side or front edge",
        "rectangular back panel with branding": "black fabric backrest visible only as a side or front edge",
        "red accent strip at top rear": "small side-visible red hub accent",
        "red accent elements": "small side-visible red hub accents",
        "red mesh upper back panel": "small side-visible red hub accents",
        "red fabric strip across the top of the backrest": "small side-visible red hub accents",
        "distinct red fabric strip across the top of the backrest": "small side-visible red hub accents",
        "red backrest accent": "small side-visible red hub accents",
        "red accent on backrest": "small side-visible red hub accent",
        "red upholstery accent": "small side-visible red hub accent",
        "two tall black rear caregiver push handles": "exactly two short top-corner rear handles close to the backrest",
        "left/right vertical tubes rising clearly above the backrest": "two short handle stems at the upper backrest corners",
        "short rearward-curved rubber grips": "two short top-corner rear handles with compact grips",
        "two small handle horns above the backrest": "exactly two short top-corner rear handles",
    }
    cleaned = text
    for old, new in replacements.items():
        cleaned = cleaned.replace(old, new)
    return cleaned


def _coerce_text_items(value: object) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if ";" in text:
            return [part.strip() for part in text.split(";") if part.strip()]
        if "," in text:
            return [part.strip() for part in text.split(",") if part.strip()]
        return [text]
    return []


def _sanitize_product_visual_structure_for_ads(structure: dict) -> dict:
    if not isinstance(structure, dict) or not structure:
        return {}

    sanitized = dict(structure)
    sanitized.pop("rear_details", None)

    must_keep = []
    for item in _coerce_text_items(sanitized.get("must_keep")):
        text = str(item).strip()
        lowered = text.lower()
        if any(term in lowered for term in REAR_DETAIL_BLOCKLIST):
            continue
        must_keep.append(_strip_rear_detail_language(text))
    sanitized["must_keep"] = must_keep

    for key, value in list(sanitized.items()):
        if isinstance(value, str):
            sanitized[key] = _strip_rear_detail_language(value)

    must_avoid = _coerce_text_items(sanitized.get("must_avoid"))
    for item in [
        "头枕、颈枕或高背支撑件",
        "靠背上方出现中间支撑柱",
        "正后方或后 3/4 产品角度",
        "镜头放在骑手正后方",
        "以骑手背面作为主要画面",
        "把后背颜色细节当成主角",
        "直接暴露后背下半部和后下方区域",
        "座椅后下方出现矩形黑盒或实体块",
        "后下方电池或外露线缆",
        "折叠、塌缩、收纳形态",
        "靠背后方额外长出杆件、天线状结构或夸张推手",
        "明显高于靠背的夸张后部把手结构",
        "前进时前叉朝前",
        "前轮中心跑到垂直转轴前方",
        "前叉不是从转轴向后包住小轮",
        "卡通、动画、二次元、插画、3D、CGI 或风格化合成质感",
        "轮椅侧面出现 logo、文字、贴纸或虚构徽标",
        "把 logo 放在前侧附件或不合理位置",
        "前后轮外观、轮毂、胎宽、间距或比例漂移",
    ]:
        if item not in must_avoid:
            must_avoid.append(item)
    sanitized["must_avoid"] = must_avoid
    return sanitized


def get_product_visual_structure(force_refresh: bool = False) -> dict:
    try:
        from vision_product_structure import analyze_product_visual_structure

        structure = analyze_product_visual_structure(get_product_reference_images(), force_refresh=force_refresh)
        return _sanitize_product_visual_structure_for_ads(structure)
    except Exception:
        return {}


def get_product_visual_structure_json(force_refresh: bool = False) -> str:
    structure = get_product_visual_structure(force_refresh=force_refresh)
    if not structure:
        return ""
    return json.dumps(structure, ensure_ascii=False, indent=2)


def get_product_visual_structure_signature(force_refresh: bool = False) -> str:
    try:
        from vision_product_structure import format_product_visual_structure

        structure = get_product_visual_structure(force_refresh=force_refresh)
        structure_text = format_product_visual_structure(structure)
        return "\n".join(part for part in [structure_text, PRODUCT_VISUAL_EXCLUSION_RULES] if part)
    except Exception:
        return PRODUCT_VISUAL_EXCLUSION_RULES


def merge_reference_images(*groups: list[str] | None, limit: int = 6) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for raw_path in group or []:
            path = str(Path(raw_path).resolve())
            if path in seen:
                continue
            seen.add(path)
            merged.append(path)
            if limit > 0 and len(merged) >= limit:
                return merged
    return merged
