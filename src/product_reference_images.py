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
    "Production rendering exclusions: show the wheelchair only in its normal open riding position. "
    "Do not show any rear/lower external battery pack, removable battery, dangling or exposed battery cable, "
    "folded chair, semi-folded chair, collapsed chair, compact storage form, or folding/unfolding demonstration. "
    "If a reference photo contains a rear lower battery pack, treat it as an omitted accessory for advertising visuals; "
    "hide it by angle, rider body, shadow, or framing while preserving the rest of the wheelchair identity. "
    "Never use a rear-facing or rear three-quarter product angle for ad generation. Keep the back panel and lower rear quadrant "
    "out of frame or fully occluded. Do not render any rectangular box mounted behind or below the seat; that area should read as "
    "open tubular frame, wheel shadow, or plain dark under-seat space. Prefer front, front three-quarter, or joystick-side front-profile framing. "
    "Use the white-background photos only for product identity; never reproduce the white studio background, packshot, cutaway, or product-photo flash frame."
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
)
PREFERRED_REFERENCE_BASENAMES = [
    "DSC_0395.JPG",
    "DSC_0401.JPG",
    "DSC_0400.JPG",
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
            "Match the real wheelchair from the white-background product photos exactly.\n"
            f"{structure_text}"
        )
    return (
        "Match the real wheelchair from the white-background product photos exactly. "
        "It is a compact electric wheelchair shown in normal open riding position with a metallic silver-gray tubular frame, black armrests, "
        "a black seat cushion and black backrest, and a distinct red fabric strip across the top of the backrest. "
        "There is a joystick controller mounted on the rider's right side above the armrest and a dark gray side housing "
        "with a smooth wave-like contour under the armrest, large rear drive wheels with silver hub covers and red center caps, "
        "small black front casters with thin multi-spoke rims, and black swing-away footrests and footplates. "
        "Do not replace it with a generic rehab wheelchair, molded shell chair, thick-spoke manual chair, or a different frame shape. "
        "Keep the same proportions, frame geometry, wheel layout, armrest shape, controller placement, and red backrest accent as the real product photos. "
        f"{PRODUCT_VISUAL_EXCLUSION_RULES}"
    )


def _sanitize_product_visual_structure_for_ads(structure: dict) -> dict:
    if not isinstance(structure, dict) or not structure:
        return {}

    sanitized = dict(structure)
    sanitized.pop("rear_details", None)

    must_keep = []
    for item in sanitized.get("must_keep", []) or []:
        text = str(item).strip()
        lowered = text.lower()
        if any(term in lowered for term in REAR_DETAIL_BLOCKLIST):
            continue
        must_keep.append(text)
    if must_keep:
        sanitized["must_keep"] = must_keep

    colors = str(sanitized.get("colors_and_materials") or "")
    if colors:
        sanitized["colors_and_materials"] = colors.replace(
            "red accent on backrest",
            "small red upholstery accent only if naturally visible from a front-side angle",
        )

    must_avoid = [str(item).strip() for item in sanitized.get("must_avoid", []) or [] if str(item).strip()]
    for item in [
        "rear-facing or rear three-quarter product angles",
        "visible back panel and lower rear quadrant",
        "rectangular box behind or below the seat",
        "rear/lower battery pack or exposed cables",
        "folded or collapsed configurations",
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
