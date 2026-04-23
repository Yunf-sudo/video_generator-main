from __future__ import annotations


def _normalized_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in str(text or "").splitlines():
        line = raw.strip().lstrip("-").strip()
        if line:
            lines.append(line)
    return lines


def list_error_cases(target: str, extra_notes: str = "") -> list[str]:
    return _normalized_lines(extra_notes)


def render_error_case_text(target: str, extra_notes: str = "") -> str:
    return "\n".join(f"- {item}" for item in list_error_cases(target, extra_notes))
