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
    "Preserve the paired upper rear push handles as slim handles visible above or just behind the backrest from side/front-profile angles; "
    "do not omit them, melt them into the backrest, or confuse them with a rear/lower battery box. "
    "Never use a rear-facing or rear three-quarter product angle for ad generation. Keep the back panel and lower rear quadrant "
    "out of frame or fully occluded while the upper push handles remain readable. Do not render any rectangular box mounted behind or below the seat; that area should read as "
    "open tubular frame, wheel shadow, or plain dark under-seat space. Prefer front, front three-quarter, or joystick-side front-profile framing. "
    "The camera must not sit behind the rider; in lifestyle scenes the viewer should be able to see the rider's front torso, "
    "soft facial profile, right forearm, and right-side joystick hand. Treat rear backrest color details as nonessential for advertising shots; "
    "do not rotate backward just to show the back panel. "
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
    "red backrest",
    "red fabric strip",
    "red mesh",
    "backrest accent",
)
PREFERRED_REFERENCE_BASENAMES = [
    "DSC_0384.JPG",
    "DSC_0395.JPG",
    "DSC_0401.JPG",
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
        "a black seat cushion and black backrest. "
        "There is a joystick controller mounted on the rider's right side above the armrest and a dark gray side housing "
        "with a smooth wave-like contour under the armrest, large rear drive wheels with silver hub covers and red center caps, "
        "small black front casters with thin multi-spoke rims, black swing-away footrests and footplates, and paired upper rear push handles "
        "rising as slim handles above or just behind the backrest. "
        "Do not replace it with a generic rehab wheelchair, molded shell chair, thick-spoke manual chair, or a different frame shape. "
        "Keep the same proportions, frame geometry, wheel layout, armrest shape, controller placement, side housing, and wheel hubs as the real product photos. "
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
    handle_keep = "paired upper rear push handles visible as slim handles above or just behind the backrest from side/front-profile angles"
    if handle_keep not in must_keep:
        must_keep.append(handle_keep)
    sanitized["must_keep"] = must_keep

    for key, value in list(sanitized.items()):
        if isinstance(value, str):
            sanitized[key] = _strip_rear_detail_language(value)

    must_avoid = _coerce_text_items(sanitized.get("must_avoid"))
    for item in [
        "rear-facing or rear three-quarter product angles",
        "camera placed behind the rider",
        "viewer's main view of the rider's back",
        "rear backrest color as a hero detail",
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
