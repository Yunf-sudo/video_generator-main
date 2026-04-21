from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.config import resolve_path


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def history_path(settings: dict[str, Any]) -> Path:
    runtime = settings.get("runtime", {}) if isinstance(settings.get("runtime"), dict) else {}
    path = resolve_path(str(runtime.get("task_history_path") or "runtime/task_history.jsonl"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def append_history(
    settings: dict[str, Any],
    *,
    event_type: str,
    status: str,
    title: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    item = {
        "time": _utc_now_iso(),
        "event_type": str(event_type or "").strip(),
        "status": str(status or "").strip(),
        "title": str(title or "").strip(),
        "payload": payload or {},
    }
    path = history_path(settings)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    return item


def load_history(settings: dict[str, Any], *, limit: int = 200) -> list[dict[str, Any]]:
    path = history_path(settings)
    if not path.exists():
        return []
    items: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if isinstance(payload, dict):
            items.append(payload)
    return items[-limit:][::-1]


def history_summary(settings: dict[str, Any], *, limit: int = 200) -> dict[str, Any]:
    items = load_history(settings, limit=limit)
    summary = {
        "total": len(items),
        "success": sum(1 for item in items if str(item.get("status") or "").lower() == "success"),
        "failed": sum(1 for item in items if str(item.get("status") or "").lower() == "failed"),
        "blocked": sum(1 for item in items if str(item.get("status") or "").lower() == "blocked"),
    }
    return {"summary": summary, "items": items}
