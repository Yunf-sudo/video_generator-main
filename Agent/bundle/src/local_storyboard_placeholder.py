from __future__ import annotations

import hashlib
import math
import uuid
from pathlib import Path

import cv2
import numpy as np

from workspace_paths import ensure_active_run


def _size_for_ratio(aspect_ratio: str) -> tuple[int, int]:
    mapping = {
        "9:16": (720, 1280),
        "16:9": (1280, 720),
        "1:1": (1080, 1080),
    }
    return mapping.get(aspect_ratio, (720, 1280))


def _keyword_palette(text: str) -> dict[str, tuple[int, int, int]]:
    lowered = (text or "").lower()
    if any(keyword in lowered for keyword in ("sunset", "dusk", "golden", "evening", "twilight")):
        return {
            "sky_top": (38, 72, 140),
            "sky_bottom": (102, 148, 235),
            "ground": (58, 88, 62),
            "path": (120, 156, 178),
            "accent": (242, 180, 104),
        }
    if any(keyword in lowered for keyword in ("woods", "forest", "nature", "trail", "trees")):
        return {
            "sky_top": (70, 102, 144),
            "sky_bottom": (148, 182, 196),
            "ground": (52, 92, 68),
            "path": (104, 126, 120),
            "accent": (208, 194, 142),
        }
    if any(keyword in lowered for keyword in ("ramp", "porch", "backyard", "door", "home", "house")):
        return {
            "sky_top": (98, 122, 146),
            "sky_bottom": (172, 194, 208),
            "ground": (92, 118, 88),
            "path": (138, 144, 138),
            "accent": (188, 164, 124),
        }
    return {
        "sky_top": (74, 96, 126),
        "sky_bottom": (156, 176, 188),
        "ground": (78, 104, 86),
        "path": (126, 132, 136),
        "accent": (210, 182, 140),
    }


def _apply_vertical_gradient(canvas: np.ndarray, top: tuple[int, int, int], bottom: tuple[int, int, int]) -> None:
    height = canvas.shape[0]
    for row in range(height):
        blend = row / max(1, height - 1)
        color = np.array(top, dtype=np.float32) * (1.0 - blend) + np.array(bottom, dtype=np.float32) * blend
        canvas[row, :, :] = color.astype(np.uint8)


def _draw_path(canvas: np.ndarray, path_color: tuple[int, int, int]) -> None:
    height, width = canvas.shape[:2]
    polygon = np.array(
        [
            [int(width * 0.12), height],
            [int(width * 0.88), height],
            [int(width * 0.58), int(height * 0.58)],
            [int(width * 0.42), int(height * 0.58)],
        ],
        dtype=np.int32,
    )
    cv2.fillConvexPoly(canvas, polygon, path_color)


def _draw_trees(canvas: np.ndarray, seed: int) -> None:
    height, width = canvas.shape[:2]
    rng = np.random.default_rng(seed)
    trunk_color = (54, 60, 70)
    foliage_color = (66, 96, 72)
    for x_pos in np.linspace(0.08, 0.92, 6):
        center_x = int(width * x_pos + rng.integers(-25, 26))
        trunk_width = int(width * 0.012)
        trunk_height = int(height * 0.12 + rng.integers(-24, 24))
        trunk_top = int(height * 0.56 - trunk_height)
        cv2.rectangle(
            canvas,
            (center_x - trunk_width, trunk_top),
            (center_x + trunk_width, int(height * 0.56)),
            trunk_color,
            thickness=-1,
        )
        radius = int(width * 0.07 + rng.integers(-10, 14))
        cv2.circle(canvas, (center_x, trunk_top + int(height * 0.03)), radius, foliage_color, thickness=-1)


def _draw_home_and_ramp(canvas: np.ndarray) -> None:
    height, width = canvas.shape[:2]
    house_color = (126, 134, 144)
    roof_color = (82, 92, 108)
    porch_color = (118, 104, 90)
    cv2.rectangle(
        canvas,
        (int(width * 0.08), int(height * 0.26)),
        (int(width * 0.42), int(height * 0.55)),
        house_color,
        thickness=-1,
    )
    roof = np.array(
        [
            [int(width * 0.06), int(height * 0.30)],
            [int(width * 0.25), int(height * 0.16)],
            [int(width * 0.44), int(height * 0.30)],
        ],
        dtype=np.int32,
    )
    cv2.fillConvexPoly(canvas, roof, roof_color)
    ramp = np.array(
        [
            [int(width * 0.34), int(height * 0.56)],
            [int(width * 0.62), int(height * 0.63)],
            [int(width * 0.62), int(height * 0.68)],
            [int(width * 0.34), int(height * 0.60)],
        ],
        dtype=np.int32,
    )
    cv2.fillConvexPoly(canvas, ramp, porch_color)


def _draw_sun(canvas: np.ndarray, accent_color: tuple[int, int, int], text: str) -> None:
    height, width = canvas.shape[:2]
    lowered = (text or "").lower()
    center = (int(width * 0.72), int(height * (0.22 if "sunset" not in lowered and "dusk" not in lowered else 0.28)))
    radius = int(width * 0.11)
    overlay = canvas.copy()
    cv2.circle(overlay, center, radius, accent_color, thickness=-1)
    cv2.addWeighted(overlay, 0.28, canvas, 0.72, 0, canvas)


def _draw_wheelchair_group(canvas: np.ndarray, include_companion: bool) -> None:
    height, width = canvas.shape[:2]
    wheel_color = (34, 38, 44)
    body_color = (82, 94, 108)
    accent_color = (154, 68, 68)
    rider_color = (208, 196, 174)

    anchor_x = int(width * 0.55)
    anchor_y = int(height * 0.73)
    rear_radius = int(width * 0.07)
    front_radius = int(width * 0.035)

    cv2.circle(canvas, (anchor_x, anchor_y), rear_radius, wheel_color, thickness=-1)
    cv2.circle(canvas, (anchor_x + int(width * 0.16), anchor_y + int(height * 0.01)), front_radius, wheel_color, thickness=-1)
    cv2.line(canvas, (anchor_x - int(width * 0.02), anchor_y - int(height * 0.10)), (anchor_x + int(width * 0.13), anchor_y - int(height * 0.08)), body_color, thickness=10)
    cv2.line(canvas, (anchor_x + int(width * 0.06), anchor_y - int(height * 0.18)), (anchor_x + int(width * 0.06), anchor_y - int(height * 0.07)), body_color, thickness=10)
    cv2.line(canvas, (anchor_x + int(width * 0.06), anchor_y - int(height * 0.18)), (anchor_x + int(width * 0.15), anchor_y - int(height * 0.18)), body_color, thickness=8)
    cv2.line(canvas, (anchor_x + int(width * 0.15), anchor_y - int(height * 0.08)), (anchor_x + int(width * 0.21), anchor_y - int(height * 0.03)), body_color, thickness=8)
    cv2.line(canvas, (anchor_x + int(width * 0.02), anchor_y - int(height * 0.08)), (anchor_x - int(width * 0.05), anchor_y - int(height * 0.03)), body_color, thickness=8)
    cv2.ellipse(canvas, (anchor_x + int(width * 0.03), anchor_y - int(height * 0.22)), (int(width * 0.035), int(width * 0.045)), 0, 0, 360, rider_color, thickness=-1)
    cv2.line(canvas, (anchor_x + int(width * 0.03), anchor_y - int(height * 0.18)), (anchor_x + int(width * 0.02), anchor_y - int(height * 0.10)), rider_color, thickness=10)
    cv2.line(canvas, (anchor_x + int(width * 0.02), anchor_y - int(height * 0.12)), (anchor_x + int(width * 0.10), anchor_y - int(height * 0.10)), rider_color, thickness=8)
    cv2.line(canvas, (anchor_x + int(width * 0.02), anchor_y - int(height * 0.10)), (anchor_x + int(width * 0.10), anchor_y - int(height * 0.01)), rider_color, thickness=8)
    cv2.rectangle(
        canvas,
        (anchor_x - int(width * 0.01), anchor_y - int(height * 0.19)),
        (anchor_x + int(width * 0.07), anchor_y - int(height * 0.16)),
        accent_color,
        thickness=-1,
    )

    if include_companion:
        companion_x = anchor_x - int(width * 0.18)
        head_y = anchor_y - int(height * 0.26)
        cv2.ellipse(canvas, (companion_x, head_y), (int(width * 0.028), int(width * 0.038)), 0, 0, 360, rider_color, thickness=-1)
        cv2.line(canvas, (companion_x, head_y + int(height * 0.03)), (companion_x + int(width * 0.02), anchor_y - int(height * 0.08)), rider_color, thickness=9)
        cv2.line(canvas, (companion_x + int(width * 0.02), anchor_y - int(height * 0.08)), (companion_x - int(width * 0.02), anchor_y + int(height * 0.03)), rider_color, thickness=8)
        cv2.line(canvas, (companion_x + int(width * 0.02), anchor_y - int(height * 0.08)), (companion_x + int(width * 0.08), anchor_y + int(height * 0.02)), rider_color, thickness=8)


def _add_vignette(canvas: np.ndarray) -> None:
    height, width = canvas.shape[:2]
    y_grid, x_grid = np.ogrid[:height, :width]
    distance_x = (x_grid - width / 2.0) / (width / 2.0)
    distance_y = (y_grid - height / 2.0) / (height / 2.0)
    distance = np.sqrt(distance_x**2 + distance_y**2)
    vignette = np.clip(1.0 - 0.38 * distance, 0.65, 1.0)
    canvas[:] = np.clip(canvas.astype(np.float32) * vignette[..., None], 0, 255).astype(np.uint8)


def create_storyboard_placeholder(
    scene_number: int,
    scene_description: str,
    key_message: str,
    aspect_ratio: str = "9:16",
    output_dir: str | Path | None = None,
) -> str:
    width, height = _size_for_ratio(aspect_ratio)
    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    palette = _keyword_palette(f"{scene_description} {key_message}")
    seed = int(hashlib.md5(f"{scene_number}-{scene_description}-{key_message}".encode("utf-8")).hexdigest()[:8], 16)

    _apply_vertical_gradient(canvas, palette["sky_top"], palette["sky_bottom"])

    horizon = int(height * 0.56)
    cv2.rectangle(canvas, (0, horizon), (width, height), palette["ground"], thickness=-1)
    _draw_path(canvas, palette["path"])
    _draw_sun(canvas, palette["accent"], scene_description)

    lowered = f"{scene_description} {key_message}".lower()
    if any(keyword in lowered for keyword in ("woods", "forest", "nature", "trees", "trail")):
        _draw_trees(canvas, seed)
    if any(keyword in lowered for keyword in ("ramp", "porch", "backyard", "home", "house", "door")):
        _draw_home_and_ramp(canvas)

    include_companion = any(keyword in lowered for keyword in ("partner", "companion", "wife", "husband", "together", "beside"))
    _draw_wheelchair_group(canvas, include_companion=include_companion)
    _add_vignette(canvas)

    output_root = Path(output_dir or ensure_active_run().pics)
    output_root.mkdir(parents=True, exist_ok=True)
    out_path = output_root / f"placeholder_scene_{scene_number}_{uuid.uuid4().hex[:8]}.png"
    cv2.imwrite(str(out_path), canvas)
    return str(out_path)
