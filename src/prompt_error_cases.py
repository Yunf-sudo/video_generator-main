from __future__ import annotations


_SHARED_ERROR_CASES = [
    "Do not drift away from the exact same wheelchair identity, colorway, frame silhouette, joystick position, armrest, footrest, wheel proportion, or seat structure.",
    "Do not invent extra rods, antenna-like parts, cane-like extensions, exaggerated push bars, or other fake rear structures.",
    "Do not show a rear or lower external battery pack, exposed battery cable, folded state, semi-folded state, compact storage form, or folding demonstration.",
    "Do not place the camera behind the rider or rely on a rear three-quarter angle that makes the back panel or lower rear area the hero feature.",
    "Do not show hands-free autonomous riding. During self-operated motion, the rider's right hand should stay on the right-side joystick.",
    "Do not insert white-background packshots, product-photo flash frames, readable text, watermark, UI overlays, or unrelated props that weaken product realism.",
    "Do not turn the powered wheelchair into a manual wheelchair, transport chair, hospital chair, or mobility scooter.",
]

_IMAGE_ERROR_CASES = [
    "Do not make the frame look like an illustration, concept sketch, fantasy render, or physically impossible studio setup.",
    "Do not age-swap, identity-swap, wardrobe-swap, or body-type drift the same rider across connected scenes.",
    "Do not make a clearly heavyset or plus-size rider look merely average-sized or slightly stocky when that body type is explicitly required.",
]

_VIDEO_ERROR_CASES = [
    "Do not create morphing, object drift, warped anatomy, jumpy continuity, looped replay, or sudden scene resets.",
    "Do not let the product shape, rider identity, or wardrobe drift during motion.",
    "Do not generate loud unrelated audio, distorted speech, or background sounds that conflict with the scene.",
]


def _normalized_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in str(text or "").splitlines():
        line = raw.strip().lstrip("-").strip()
        if line:
            lines.append(line)
    return lines


def list_error_cases(target: str, extra_notes: str = "") -> list[str]:
    normalized_target = str(target or "").strip().lower()
    cases = list(_SHARED_ERROR_CASES)
    if normalized_target == "video":
        cases.extend(_VIDEO_ERROR_CASES)
    else:
        cases.extend(_IMAGE_ERROR_CASES)
    cases.extend(_normalized_lines(extra_notes))
    return cases


def render_error_case_text(target: str, extra_notes: str = "") -> str:
    return "\n".join(f"- {item}" for item in list_error_cases(target, extra_notes))
