from __future__ import annotations

import json
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
PRODUCT_REFERENCE_DIR_CANDIDATES = [
    BASE_DIR.parent / "白底图",
    BASE_DIR / "白底图",
]
SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
PREFERRED_REFERENCE_BASENAMES = [
    "DSC_0382.JPG",
    "DSC_0396.JPG",
    "DSC_0402.JPG",
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


def get_product_reference_images(limit: int = 3) -> list[str]:
    reference_dir = _find_reference_dir()
    if reference_dir is None:
        return []

    image_paths = sorted(
        path for path in reference_dir.iterdir() if path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS
    )
    preferred_paths = [reference_dir / basename for basename in PREFERRED_REFERENCE_BASENAMES if (reference_dir / basename).exists()]
    if preferred_paths:
        image_paths = preferred_paths + [path for path in image_paths if path.name not in PREFERRED_REFERENCE_BASENAMES]
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
        "It is a compact folding electric wheelchair with a metallic silver-gray tubular frame, black armrests, "
        "a black seat cushion and black backrest, and a distinct red fabric strip across the top of the backrest. "
        "There is a joystick controller mounted on the rider's right side above the armrest, a dark gray side battery housing "
        "with a smooth wave-like contour under the armrest, large rear drive wheels with silver hub covers and red center caps, "
        "small black front casters with thin multi-spoke rims, black swing-away footrests and footplates, and small rear anti-tip wheels. "
        "Do not replace it with a generic rehab wheelchair, molded shell chair, thick-spoke manual chair, or a different frame shape. "
        "Keep the same proportions, frame geometry, wheel layout, armrest shape, controller placement, and red backrest accent as the real product photos."
    )


def get_product_visual_structure(force_refresh: bool = False) -> dict:
    try:
        from vision_product_structure import analyze_product_visual_structure

        return analyze_product_visual_structure(get_product_reference_images(), force_refresh=force_refresh)
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
        return format_product_visual_structure(structure)
    except Exception:
        return ""


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
