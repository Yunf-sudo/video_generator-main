from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from material_library import append_material_event, load_material_record, update_material_record


def main() -> None:
    parser = argparse.ArgumentParser(description="更新素材审核状态，供广告启用前人工把关。")
    parser.add_argument("material_id", help="素材 ID，例如 mat_20260417_xxxxxx")
    parser.add_argument("--status", default="approved", choices=["approved", "rejected", "pending_review", "auto_approved"])
    parser.add_argument("--note", default="", help="审核备注")
    args = parser.parse_args()

    record = load_material_record(args.material_id)
    updated = update_material_record(
        args.material_id,
        {
            "review_status": args.status,
            "review_note": args.note.strip(),
        },
    )
    append_material_event(
        args.material_id,
        "review_status_updated",
        {
            "old_status": record.get("review_status"),
            "new_status": args.status,
            "note": args.note.strip(),
        },
    )
    print(json.dumps(updated, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
