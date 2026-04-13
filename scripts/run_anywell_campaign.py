from __future__ import annotations

import argparse

import _bootstrap  # noqa: F401

from anywell_campaign import run_anywell_campaign


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the AnyWell emotional campaign content-generation test.")
    parser.add_argument("--config", default="configs/anywell_freedom_campaign.json", help="Path to campaign config JSON.")
    parser.add_argument("--prompt", default="prompts/anywell_freedom_campaign.md", help="Path to campaign prompt/guardrails file.")
    parser.add_argument("--output-root", default="outputs/anywell_campaign", help="Directory for packaged deliverables.")
    parser.add_argument("--log-path", default="logs/anywell_campaign_run.log", help="Path to run log file.")
    parser.add_argument("--summary-path", default="reports/anywell_campaign_summary.md", help="Path to markdown summary report.")
    parser.add_argument("--max-concepts", type=int, default=None, help="Optional limit on how many concepts to run.")
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
    )
    print(summary["output_root"])


if __name__ == "__main__":
    main()
