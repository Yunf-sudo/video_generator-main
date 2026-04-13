$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$rootDir = Split-Path -Parent $scriptDir

Set-Location $rootDir

python scripts/run_anywell_campaign.py `
  --config configs/anywell_freedom_campaign_product_matched_remote.json `
  --prompt prompts/anywell_freedom_campaign.md `
  --output-root outputs/anywell_campaign_veo31_best `
  --log-path logs/anywell_campaign_veo31_best.log `
  --summary-path reports/anywell_campaign_veo31_best_summary.md
