from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import _bootstrap  # noqa: F401


def _slug_from_concept_dir(concept_dir: Path) -> str:
    parent = concept_dir.parent.name
    stem = concept_dir.name
    if parent and parent != ".":
        return f"{parent}_{stem}"
    return stem


def _copy_required(source: Path, target: Path) -> None:
    if not source.exists():
        raise FileNotFoundError(f"Missing required video: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Copy final videos into the clean handoff output layout.")
    parser.add_argument("concept_dir", help="Concept output directory that contains final_video.mp4.")
    parser.add_argument("--output-root", default="outputs/final", help="Clean output root for final videos only.")
    parser.add_argument("--slug", default="", help="Optional file-name slug. Defaults to run and concept names.")
    parser.add_argument(
        "--clean-source",
        default="",
        help="Optional clean/no-subtitle video path. Defaults to final_video_clean.mp4 in concept_dir if present.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    concept_dir = Path(args.concept_dir)
    output_root = Path(args.output_root)
    slug = (args.slug or _slug_from_concept_dir(concept_dir)).strip().replace(" ", "_")

    captioned_source = concept_dir / "final_video.mp4"
    clean_source = Path(args.clean_source) if args.clean_source else concept_dir / "final_video_clean.mp4"

    captioned_target = output_root / "captioned" / f"{slug}_captioned.mp4"
    clean_target = output_root / "clean" / f"{slug}_clean.mp4"

    _copy_required(captioned_source, captioned_target)
    if clean_source.exists():
        _copy_required(clean_source, clean_target)

    print(captioned_target.resolve())
    if clean_source.exists():
        print(clean_target.resolve())


if __name__ == "__main__":
    main()
