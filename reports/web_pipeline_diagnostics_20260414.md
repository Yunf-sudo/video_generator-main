# Web Pipeline Diagnostics

Checked at: 2026-04-14T13:39:00

## Result

- `app.py`, `src/app.py`, and `src/media_pipeline.py` compile successfully.
- Web export path `export_formal_video_step()` was exercised with completed remote clips.
- Final export succeeded with audio and burned-in subtitles.
- Output resolution verified with OpenCV: `1080x1920`, `24 fps`.
- ffmpeg is available through `imageio_ffmpeg`, so the web app does not depend on system PATH.

## Fixes Applied

- Web export now passes explicit `output_dir`, `aspect_ratio`, `transition_name`, and `transition_duration` into `assemble_final_video()`.
- No-transition concat exports are normalized to the target aspect ratio and 1080x1920 output instead of preserving whatever clip size came back from the provider.

## Speed Tests

### Final Export Only

- Source: existing completed `concept_b` remote clips, voice-over, and subtitles.
- Time: `9.04s`
- Output: `generated/runs/web-export-smoke-20260414-133557-ea7647/exports/wheelchair-0414-1335.mp4`
- Resolution: `1080x1920`
- Duration: `14.45s`
- Subtitles burned: `true`

### Web Post-Production Chain

Stages tested from existing script/storyboard/remote clips:

- Metadata: `11.40s`
- TTS: `25.59s`
- Subtitles: `0.03s`
- Final export: `8.57s`
- Total: `45.59s`

Output: `generated/runs/web-post-chain-smoke-20260414-133745-f2ac49/exports/wheelchair-0414-1338.mp4`

Notes:

- RustFS audio upload returned `502 Bad Gateway`; the system correctly fell back to a local file URL.
- Remote ASR requires HTTP(S), so subtitles correctly fell back to script-timed local SRT generation.

## Real Remote Full-Concept Timings

- `concept_b`: `1300.3s` total, about `21m40s`.
- `concept_c`: `1921.6s` total, about `32m02s`.

These include remote storyboard/video generation and provider waiting time. Provider failures/retries can add substantial variance.
