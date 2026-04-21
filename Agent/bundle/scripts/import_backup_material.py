from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from meta_ads_service import create_paused_ad_for_material
from meta_pool_state import register_backup_material


def main() -> None:
    parser = argparse.ArgumentParser(description="把手工备用素材直接上传到 Meta 暂存池，并保持关停。")
    parser.add_argument("video_path", help="备用视频文件路径")
    parser.add_argument("--primary-text", required=True, help="主文案")
    parser.add_argument("--headline", required=True, help="标题")
    parser.add_argument("--description", default="", help="描述")
    parser.add_argument("--landing-page-url", default="", help="落地页链接")
    parser.add_argument("--page-id", default="", help="Page ID")
    parser.add_argument("--target-adset-id", default="", help="默认测试广告组 ID")
    parser.add_argument("--cta", default="LEARN_MORE", help="CTA 类型")
    parser.add_argument("--tags", default="", help="用逗号分隔的标签列表")
    args = parser.parse_args()

    material = register_backup_material(
        video_path=args.video_path,
        primary_text=args.primary_text,
        headline=args.headline,
        description=args.description,
        landing_page_url=args.landing_page_url,
        page_id=args.page_id,
        target_adset_id=args.target_adset_id,
        cta=args.cta,
        tags=[item.strip() for item in args.tags.split(",") if item.strip()],
    )
    material = create_paused_ad_for_material(str(material.get("material_id") or ""))
    print(json.dumps(material, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
