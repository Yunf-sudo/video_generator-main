# Video Generator

AI video generation workflow for product-led short-form ads. The current handoff build is configured for the AnyWell wheelchair campaign: product appearance comes from the local `白底图/` reference-image folder, storyboard images are generated first, and video clips are generated through 302.ai's Veo image-to-video endpoint.

## What This Project Does

- Generates a campaign script and storyboard keyframes.
- Uses product reference images to keep wheelchair appearance consistent.
- Generates vertical `9:16` video clips with 302.ai `veo3-pro-frames`.
- Assembles clips with voice-over, subtitles, and final MP4 exports.
- Keeps handoff outputs clean: only final videos belong in `outputs/final/`.

## Project Layout

```text
.
├── app.py                         # Streamlit entrypoint
├── src/                           # Core pipeline code
├── scripts/                       # CLI runners and packaging helpers
├── configs/                       # Campaign configs
├── prompts/                       # Campaign guardrails and prompt text
├── prompt_overrides.example.json  # Safe prompt override template
├── prompt_overrides.json          # Local prompt overrides
├── .env.example                   # Environment variable template
├── requirements.txt               # Python dependencies
├── 白底图/                         # Local product reference photos, not committed
├── generated/                     # Run artifacts, caches, archived intermediates
├── logs/                          # Runtime logs
├── reports/                       # QA reports and contact sheets
└── outputs/final/                 # Final handoff videos only
    ├── captioned/
    └── clean/
```

`generated/`, `logs/`, `reports/`, `outputs/`, `.env`, and large media files are ignored by git. Share them separately when needed.

## Setup

Use Python 3.11+.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Install `ffmpeg` if it is not already available. The project can fall back to `imageio-ffmpeg`, but a system `ffmpeg`/`ffprobe` install is better for production runs.

Create your environment file:

```powershell
Copy-Item .env.example .env
```

Fill in `.env` with real keys. Do not commit `.env`.

Required for the current AnyWell pipeline:

- `JENIYA_API_TOKEN`: used by script/image/TTS calls in this project.
- `V302_API_KEY`: used by 302.ai video generation and 302 file upload.
- `VIDEO_PROVIDER=302ai`
- `VIDEO_MODEL=veo3-pro-frames`
- `VIDEO_302_SUBMIT_URL=https://api.302.ai/302/submit/veo3-pro-frames`
- `VIDEO_302_UPLOAD_URL=https://api.302.ai/302/upload-file`

## Product Reference Images

Put product appearance references in:

```text
白底图/
```

For the current AnyWell setup, the pipeline prefers side/front-side wheelchair photos and treats white-background images only as product identity references. It should not insert white studio frames into the ad video.

## Run The Web App

```powershell
streamlit run app.py
```

The web app is useful for manual testing and step-by-step generation.

## Run The AnyWell Campaign CLI

For a normal CLI run, keep intermediates under `generated/`:

```powershell
python scripts/run_anywell_campaign.py `
  --config configs/anywell_freedom_campaign.json `
  --prompt prompts/anywell_freedom_campaign.md `
  --output-root generated/deliverables/anywell_campaign `
  --log-path logs/anywell_campaign.log `
  --summary-path reports/anywell_campaign_summary.md `
  --max-concepts 1
```

The concept folder will contain storyboards, prompts, clips, audio, subtitles, and assembled videos. These are run artifacts and should stay outside `outputs/final/`.

## Package Final Videos

After a successful run, copy only the final MP4s into the clean handoff layout:

```powershell
python scripts/package_final_outputs.py generated/deliverables/anywell_campaign/concept_a `
  --slug anywell_nature_within_reach
```

Expected handoff layout:

```text
outputs/final/
├── captioned/
│   └── anywell_nature_within_reach_captioned.mp4
└── clean/
    └── anywell_nature_within_reach_clean.mp4
```

Use the `clean` version when subtitles or platform captions will be added later. Use the `captioned` version when burned-in English subtitles are required.

## Current Handoff Videos

The current cleaned output folder contains:

```text
outputs/final/captioned/anywell_nature_within_reach_captioned.mp4
outputs/final/clean/anywell_nature_within_reach_clean.mp4
```

Video specs:

- Format: MP4
- Orientation: `9:16`
- Resolution: `1080x1920`
- Duration: about 16 seconds
- Model: `veo3-pro-frames`
- Provider: 302.ai

## Quality Guardrails

The AnyWell config and prompts enforce these rules:

- Do not reference or reproduce the real customer video.
- Use anonymous Western-market actors and generic outdoor/home scenes.
- Rider-operated movement must show the right hand on the right-side joystick.
- If the hand is not on the joystick, an adult must visibly push the chair.
- Avoid rear-only camera angles.
- Do not show a rear/lower external battery pack.
- Do not show folded, half-folded, storage, or folding/unfolding wheelchair states.
- Do not insert white-background product-photo frames into final ads.

## Troubleshooting

`302.ai requires a public HTTP(S) input image URL`

The pipeline first uploads storyboard frames to `VIDEO_302_UPLOAD_URL`. Confirm `V302_API_KEY` and `VIDEO_302_UPLOAD_URL` are correct. RustFS is only a fallback and may return local `file://` URLs, which 302.ai cannot use.

`HTTP Error 403` while downloading generated video

The downloader retries with 302.ai Bearer authentication. Confirm `V302_API_KEY` is still valid.

`AUDIO_GENERATION_FILTERED`

Do not add prompt text that tells Veo to suppress all audio/dialogue/sound. The assembly step strips/replaces audio later.

Final video is longer than exactly 15 seconds

Veo clips usually arrive as 8-second source clips. Assembly trims/fits them to the voice-over duration. Shorten the voice-over lines if a stricter 15.0-second runtime is required.

## Handoff Notes

- `.env` contains private keys and must stay local.
- `白底图/` contains large/private product references and is ignored by git.
- `outputs/final/` is for client-ready MP4s only.
- Older intermediate output folders have been archived under `generated/archive/` instead of deleted.
- The original customer-uploaded source video, if present, is archived under `generated/archive/source_media/` and should not be used in generated ads.
