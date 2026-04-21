from __future__ import annotations

import argparse

import _bootstrap  # noqa: F401

from anywell_campaign import run_anywell_campaign


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the AnyWell emotional campaign content-generation test.")
    parser.add_argument("--config", default="configs/anywell_freedom_campaign.json", help="Path to campaign config JSON.")
    parser.add_argument("--prompt", default="prompts/anywell_freedom_campaign.md", help="Path to campaign prompt/guardrails file.")
    parser.add_argument(
        "--output-root",
        default="generated/deliverables/anywell_campaign",
        help="Directory for intermediate campaign deliverables. Copy final videos to outputs/final for handoff.",
    )
    parser.add_argument("--log-path", default="logs/anywell_campaign_run.log", help="Path to run log file.")
    parser.add_argument("--summary-path", default="reports/anywell_campaign_summary.md", help="Path to markdown summary report.")
    parser.add_argument("--max-concepts", type=int, default=None, help="Optional limit on how many concepts to run.")
    parser.add_argument("--max-scenes", type=int, default=None, help="Optional limit on how many scenes to run per concept.")
    parser.add_argument(
        "--no-storyboard-crop",
        action="store_true",
        help="Use the original storyboard image as the video input instead of creating a cropped copy.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = run_anywell_campaign(
        config_path=args.config,
        prompt_path=args.prompt,
        output_root=args.output_root,
        log_path=args.log_path,
        summary_path=args.summary_path,
        max_concepts=args.max_concepts,
        max_scenes_per_concept=args.max_scenes,
        skip_storyboard_crop_for_video=args.no_storyboard_crop,
    )
    print(summary["output_root"])


if __name__ == "__main__":
    main()
