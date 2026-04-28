from __future__ import annotations

import json
import re
from pathlib import Path

import cv2

from workspace_paths import PROJECT_ROOT


PRODUCT_REFERENCE_DIR_CANDIDATES = [
    PROJECT_ROOT.parent / "白底图",
    PROJECT_ROOT / "白底图",
]
CURATED_REFERENCE_PREFIX = "ChatGPT Image "
EXPLICIT_CURATED_REFERENCE_BASENAMES = [
    "chassis_reference_sheet_clean.png",
    "rear_wheel_chassis_joint.png",
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
    "如果前万向轮可见，必须保留参考图里的真实前叉总成，不要把它简化成细杆脚轮、自行车前叉、双叉医院脚轮或其他错误结构。"
    "多视角参考图或白底参考图只用于锁定产品身份与轮组结构，不要求逐像素复制前万向轮的瞬时摆角。"
    "如果静态参考图里的前叉刚好朝前，那只是停放状态下的局部朝向，不要把它误写成所有镜头都要固定朝前。"
    "如果镜头表现轮椅正在明确向前行驶，前万向轮应呈现自然拖曳后的受力关系：优先让小轮中心落在转轴后方，前叉从转轴向后包住小轮，避免出现反装、僵硬或违和的前伸结构。"
    "生成画面必须是真人实拍质感：不要卡通、动画、二次元、插画、风格化绘画、3D 渲染、CGI、游戏资产或塑料假人质感。"
    "品牌标识必须遵循参考产品：只有当镜头是后背正向或后侧 3/4，且后背口袋区域正面朝向镜头时，居中的白色 AnyWell 标识才允许出现在该布面/口袋区域。"
    "前侧、纯侧、前 3/4 和侧向跟拍角度都不允许读到 AnyWell 字样；侧板、侧架、扶手、轮子和前部区域都应保持干净，不要额外生成侧边 logo、文字、贴纸或虚构徽标。"
    "不要使用正后方居中的产品角度。即便需要带一点后背信息，也只允许轻微、抬高的侧后角度，并且要让后下部区域保持隐藏。"
    "座椅下方和后下方不要变成黑盒、电池块、袋子或实心黑块，应尽量表现为轻盈、开放的管架关系。"
    "如果镜头或角度露出座椅下方结构，必须保留参考图里的开放式底盘：中央可见 X 形交叉支撑管、左右对称的下部管架、后轮内侧的圆柱电机/轮毂关系，以及靠近后轮的真实连接支架。"
    "不要把底盘画成整块封闭底板、厚重塑料盒、悬空黑箱、错误单杆结构、左右不对称的怪异连杆，或与后轮脱节的假悬挂。"
    "镜头不要放在骑手正后方；生活方式场景里，观众应能看到人物前胸、柔和侧脸、右前臂和右侧摇杆手。"
    "多视角参考图或白底产品图只用于识别产品身份，正式广告里不要复现拼版标签、分隔线、白底棚拍、packshot、剖面图或产品页闪帧。"
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
_REFERENCE_IMAGE_STATS_CACHE: dict[str, dict[str, float]] = {}


def _reference_search_roots() -> list[Path]:
    repo_root = PROJECT_ROOT
    for candidate in [PROJECT_ROOT, PROJECT_ROOT.parent, PROJECT_ROOT.parent.parent]:
        if (candidate / "src").exists() and (candidate / "Agent").exists():
            repo_root = candidate
            break

    roots = [repo_root]
    current_dir = Path.cwd().resolve()
    try:
        current_dir.relative_to(repo_root.resolve())
        if current_dir != repo_root.resolve():
            roots.insert(0, current_dir)
    except ValueError:
        pass

    resolved_roots: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        try:
            resolved = root.resolve()
        except Exception:
            continue
        if resolved in seen or not resolved.exists() or not resolved.is_dir():
            continue
        seen.add(resolved)
        resolved_roots.append(resolved)
    return resolved_roots


def _find_curated_reference_images() -> list[Path]:
    matches: list[Path] = []
    seen: set[Path] = set()
    for root in _reference_search_roots():
        for basename in EXPLICIT_CURATED_REFERENCE_BASENAMES:
            path = root / basename
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_IMAGE_EXTENSIONS:
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            matches.append(resolved)
        for path in sorted(root.glob(f"{CURATED_REFERENCE_PREFIX}*")):
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_IMAGE_EXTENSIONS:
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            matches.append(resolved)
    return matches


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


def _reference_image_stats(path: Path) -> dict[str, float]:
    cache_key = str(path.resolve())
    cached = _REFERENCE_IMAGE_STATS_CACHE.get(cache_key)
    if cached is not None:
        return cached
    try:
        image = cv2.imread(str(path))
        if image is None:
            stats: dict[str, float] = {}
        else:
            height, width = image.shape[:2]
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            stats = {
                "width": float(width),
                "height": float(height),
                "aspect_ratio": float(width / max(height, 1)),
                "mean_gray": float(gray.mean()),
                "bright_ratio": float((gray > 235).mean()),
                "dark_ratio": float((gray < 60).mean()),
            }
    except Exception:
        stats = {}
    _REFERENCE_IMAGE_STATS_CACHE[cache_key] = stats
    return stats


def _legacy_reference_image_paths(limit: int = 5) -> list[str]:
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


def _infer_curated_reference_role(path: Path) -> str:
    name = path.stem.lower()
    if any(token in name for token in ["joystick", "controller", "control", "handle", "detail", "panel", "grip"]):
        return "detail_sheet"
    if "rear_wheel_chassis_joint" in name:
        return "chassis_detail"
    if any(token in name for token in ["chassis_reference_sheet", "chassis_overview", "undercarriage", "underbody"]):
        return "chassis_sheet"
    if any(token in name for token in ["overview", "sheet", "front", "back", "left", "right", "view"]):
        return "overview_sheet"

    stats = _reference_image_stats(path)
    aspect_ratio = float(stats.get("aspect_ratio") or 0.0)
    bright_ratio = float(stats.get("bright_ratio") or 0.0)
    mean_gray = float(stats.get("mean_gray") or 0.0)
    if aspect_ratio >= 1.35 and bright_ratio >= 0.30:
        return "overview_sheet"
    if aspect_ratio <= 1.28 and mean_gray <= 145.0:
        return "detail_sheet"
    return "generic"


def _curated_reference_sort_key(path: Path) -> tuple:
    role = _infer_curated_reference_role(path)
    stats = _reference_image_stats(path)
    role_priority = {
        "overview_sheet": 0,
        "detail_sheet": 1,
        "chassis_sheet": 2,
        "chassis_detail": 3,
        "generic": 4,
    }
    if role == "overview_sheet":
        return (
            role_priority[role],
            -float(stats.get("bright_ratio") or 0.0),
            -float(stats.get("aspect_ratio") or 0.0),
            path.name.lower(),
        )
    if role == "detail_sheet":
        return (
            role_priority[role],
            float(stats.get("mean_gray") or 999.0),
            float(stats.get("aspect_ratio") or 999.0),
            path.name.lower(),
        )
    if role == "chassis_sheet":
        return (
            role_priority[role],
            0 if path.name.lower() == "chassis_reference_sheet_clean.png" else 1,
            path.name.lower(),
        )
    if role == "chassis_detail":
        return (role_priority[role], path.name.lower())
    return (role_priority[role], path.name.lower())


def get_product_reference_bundle(limit: int = 5) -> dict:
    curated_paths = _find_curated_reference_images()
    if curated_paths:
        curated_paths = sorted(curated_paths, key=_curated_reference_sort_key)
        selected = curated_paths[:limit] if limit > 0 else curated_paths
        roles = {str(path): _infer_curated_reference_role(path) for path in selected}
        overview_paths = [str(path) for path in selected if roles[str(path)] == "overview_sheet"]
        detail_paths = [str(path) for path in selected if roles[str(path)] == "detail_sheet"]
        chassis_overview_paths = [str(path) for path in selected if roles[str(path)] == "chassis_sheet"]
        chassis_detail_paths = [str(path) for path in selected if roles[str(path)] == "chassis_detail"]
        chassis_paths = chassis_overview_paths + chassis_detail_paths
        generic_paths = [str(path) for path in selected if roles[str(path)] == "generic"]

        if not overview_paths and selected:
            overview_candidate = max(
                selected,
                key=lambda candidate: (
                    float(_reference_image_stats(candidate).get("bright_ratio") or 0.0),
                    float(_reference_image_stats(candidate).get("aspect_ratio") or 0.0),
                ),
            )
            overview_paths = [str(overview_candidate)]
            roles[str(overview_candidate)] = "overview_sheet"
            detail_paths = [path for path in detail_paths if path != str(overview_candidate)]
            generic_paths = [path for path in generic_paths if path != str(overview_candidate)]

        if not detail_paths:
            remaining = [str(path) for path in selected if str(path) not in overview_paths]
            if remaining:
                detail_candidate = min(
                    remaining,
                    key=lambda candidate: (
                        float(_reference_image_stats(Path(candidate)).get("mean_gray") or 999.0),
                        float(_reference_image_stats(Path(candidate)).get("aspect_ratio") or 999.0),
                    ),
                )
                detail_paths = [detail_candidate]
                roles[detail_candidate] = "detail_sheet"
                generic_paths = [path for path in generic_paths if path != detail_candidate]

        return {
            "all": [str(path) for path in selected],
            "overview": overview_paths,
            "detail": detail_paths,
            "chassis_overview": chassis_overview_paths,
            "chassis_detail": chassis_detail_paths,
            "chassis": chassis_paths,
            "generic": generic_paths,
            "roles": roles,
            "source": "curated_chatgpt_images",
        }

    legacy_paths = _legacy_reference_image_paths(limit=limit)
    roles = {path: ("overview_sheet" if index == 0 else "generic") for index, path in enumerate(legacy_paths)}
    return {
        "all": legacy_paths,
        "overview": legacy_paths[:1],
        "detail": [],
        "chassis_overview": [],
        "chassis_detail": [],
        "chassis": [],
        "generic": legacy_paths[1:],
        "roles": roles,
        "source": "legacy_reference_dir",
    }


def get_product_reference_images(limit: int = 5) -> list[str]:
    return list(get_product_reference_bundle(limit=limit).get("all") or [])


def get_product_reference_signature() -> str:
    structure_text = get_product_visual_structure_signature()
    if structure_text:
        return (
            "尽量准确匹配参考图中的真实轮椅。\n"
            f"{structure_text}"
        )
    return (
        "请尽量准确匹配参考图中的真实轮椅。"
        "它是一台正常展开状态的紧凑型电动轮椅，具有银灰色金属管架、黑色扶手、黑色坐垫和黑色靠背。"
        "右侧扶手前上方有摇杆控制器，扶手下方是深灰色流线型侧壳。"
        "后轮较大，带银色轮毂罩和红色中心点缀；前轮较小，为黑色万向轮；脚踏为黑色翻转式脚踏。"
        "如果前万向轮可见，必须保持参考图里的真实前叉总成、叉架厚度、连接点和轮轴关系，不要改成自行车前叉、双叉脚轮或细杆脚轮。"
        "如果镜头露出座椅下方或后轮内侧区域，必须保留开放式底盘：中央 X 形交叉支撑管、左右对称的下部管架、后轮内侧圆柱电机/轮毂关系，以及靠近后轮的真实连接支架。"
        "顶部后背轮廓紧凑，不要把它替换成医院轮椅、手动轮椅、厚辐条轮椅或完全不同的车架。"
        "只有当镜头是后背正向或后侧 3/4，且后背口袋区域正面朝向镜头时，才允许看到参考产品自带、位于该布面/口袋区域的居中白色 AnyWell 布标。"
        "多视角参考图或白底参考图只用于锁定产品身份与轮组结构，不要求逐像素复制前万向轮的瞬时摆角。"
        "如果静态参考图里的前叉刚好朝前，可视为停放状态下的局部角度。"
        "如果镜头表现轮椅正在明确向前行驶，前万向轮应呈现自然拖曳后的受力关系：小轮中心优先在转轴后方，前叉从转轴向后包住小轮。"
        "轮椅侧面应保持干净，不要出现侧边 logo、文字、贴纸或虚构品牌件；前侧和纯侧视角里不要读到 AnyWell 字样，只有后背正向或后侧 3/4 且口袋区域正面朝向镜头时，居中的白色 AnyWell 标识才能出现。"
        "必须保持与实拍参考图一致的比例、车架关系、轮组布局、扶手形状、控制器位置、侧壳和轮毂特征。"
        f"{PRODUCT_VISUAL_EXCLUSION_RULES}"
    )


def _strip_rear_detail_language(text: str) -> str:
    regex_replacements = [
        (r"(?i)\bthe left armrest features the mounted joystick controller\b", "the right armrest features the mounted joystick controller"),
        (r"(?i)\ba joystick controller is mounted on the left armrest\b", "a joystick controller is mounted on the right armrest"),
        (r"(?i)\bmounted on the left armrest\b", "mounted on the right armrest"),
        (r"(?i)\bjoystick controller mounted on the left armrest\b", "joystick controller mounted on the right armrest"),
        (r"(?i)\bjoystick on the left armrest\b", "joystick on the right armrest"),
        (r"(?i)\bleft-side mounted joystick controller\b", "right-side mounted joystick controller"),
        (r"(?i)\bleft-side joystick controller\b", "right-side joystick controller"),
        (r"(?i)\bleft-side joystick\b", "right-side joystick"),
        (r"(?i)\bboth armrests with the integrated joystick controller\b", "both armrests with the right-side integrated joystick controller"),
    ]
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
    for pattern, replacement in regex_replacements:
        cleaned = re.sub(pattern, replacement, cleaned)
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

    if not any("right-side joystick" in item.lower() or "右侧扶手前上方的摇杆控制器" in item for item in must_keep):
        must_keep.append("右侧扶手前上方的摇杆控制器")
    if not any("frame" in item.lower() or "管架" in item or "轮廓" in item for item in must_keep):
        must_keep.append("银灰色金属管架与紧凑的整车轮廓")
    if not any("rear wheel" in item.lower() or "后驱动轮" in item for item in must_keep):
        must_keep.append("大号后驱动轮、银色轮毂罩与小红色中心点缀")
    if not any("front caster" in item.lower() or "前万向轮" in item for item in must_keep):
        must_keep.append("小号黑色前万向轮、真实前叉总成、叉架厚度、连接点与镜头状态一致的自然前叉姿态")
    if not any("x 形" in item.lower() or "x-shaped" in item.lower() or "交叉支撑" in item or "底盘" in item for item in must_keep):
        must_keep.append("座椅下方开放式底盘、中央 X 形交叉支撑管与左右对称的下部管架")
    if not any("电机" in item or "motor" in item.lower() or "轮毂" in item for item in must_keep):
        must_keep.append("后轮内侧圆柱电机/轮毂关系，以及靠近后轮的真实连接支架")
    if not any("footrest" in item.lower() or "脚踏" in item for item in must_keep):
        must_keep.append("黑色脚踏与黑色扶手")
    if not any("top-corner rear handles" in item.lower() or "后把手" in item for item in must_keep):
        must_keep.append("如果靠背上角可见，保持两侧贴近靠背的短小一体式后把手")

    for key, value in list(sanitized.items()):
        if isinstance(value, str):
            sanitized[key] = _strip_rear_detail_language(value)
        elif isinstance(value, list):
            sanitized[key] = [_strip_rear_detail_language(str(item).strip()) for item in value if str(item).strip()]

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
        "在明确前进镜头里把前叉画成反物理前伸",
        "在明确前进镜头里让前轮中心跑到垂直转轴前方",
        "在明确前进镜头里把前叉画成不是从转轴向后包住小轮",
        "卡通、动画、二次元、插画、3D、CGI 或风格化合成质感",
        "轮椅侧面出现 logo、文字、贴纸或虚构徽标",
        "把 logo 放在前侧附件或不合理位置",
        "前后轮外观、轮毂、胎宽、间距或比例漂移",
        "座椅下方的 X 形交叉支撑消失或被改单杆/封闭板",
        "底盘下方变成整体黑盒、塑料箱体、厚重电池块或悬空实体块",
        "后轮内侧电机/轮毂关系丢失或改成错误外形",
        "靠近后轮的底盘连接支架、连杆或下部管架左右不对称",
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
