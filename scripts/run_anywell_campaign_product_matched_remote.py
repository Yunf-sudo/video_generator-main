from __future__ import annotations

import _bootstrap  # noqa: F401

from anywell_campaign import run_anywell_campaign


def main() -> None:
    summary = run_anywell_campaign(
        config_path="configs/anywell_freedom_campaign_product_matched_remote.json",
        prompt_path="prompts/anywell_freedom_campaign.md",
        output_root="outputs/anywell_campaign_product_matched_remote",
        log_path="logs/anywell_campaign_product_matched_remote.log",
        summary_path="reports/anywell_campaign_product_matched_remote_summary.md",
    )
    print(summary["output_root"])


if __name__ == "__main__":
    main()
