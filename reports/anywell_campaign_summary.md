# AnyWell Campaign Summary

Generated at: 2026-04-13T11:25:51

## Delivery status

- `concept_a`: success
  - output: `outputs/anywell_campaign/concept_a`
  - final video: `outputs/anywell_campaign/concept_a/final_video.mp4`
  - runtime: about 14.30s
  - resolution: `720x1280`, `24fps`
  - storyboard generation: remote image model
  - clip generation: local video assembly from storyboard keyframes

- `concept_b`: success
  - output: `outputs/anywell_campaign/concept_b`
  - final video: `outputs/anywell_campaign/concept_b/final_video.mp4`
  - runtime: about 15.82s
  - resolution: `720x1280`, `24fps`
  - storyboard generation: remote image model
  - clip generation: local video assembly from storyboard keyframes

- `concept_c`: success
  - output: `outputs/anywell_campaign/concept_c`
  - final video: `outputs/anywell_campaign/concept_c/final_video.mp4`
  - runtime: about 12.96s
  - resolution: `720x1280`, `24fps`
  - storyboard generation: remote image model
  - clip generation: local video assembly from storyboard keyframes

## Files delivered per concept

- `script.json`
- `script.txt`
- `storyboard.json`
- `storyboard/scene_*.png`
- `prompts.txt`
- `video_result.json`
- `clips/scene_*.mp4`
- `voiceover.txt`
- `voiceover.mp3`
- `subtitles.srt`
- `cover_copy.txt`
- `cta.txt`
- `ti_intro.json`
- `concept_report.json`
- `final_video.mp4`

## What worked

- The repository now supports a dedicated AnyWell emotional-campaign run through `scripts/run_anywell_campaign.py`.
- Product and brand prompt hardcoding was generalized so the campaign no longer forces `Song` branding into new work.
- Storyboard generation can continue even if image generation fails, because local placeholder frames are now available as a fallback path.
- TTS can continue even if the remote voice API fails, because a Windows local-speech fallback was added.
- Subtitle generation can continue without remote ASR, because the system now falls back to script-derived subtitles.
- Final export produced three playable vertical MP4s with audio and burned-in subtitles.

## What fell back or failed

- RustFS upload returned `502 Bad Gateway` during TTS upload.
  - Impact: no blocker
  - Handling: the pipeline stored audio in local run storage and continued

- Remote ASR only accepts HTTP(S) audio URLs.
  - Impact: no blocker
  - Handling: subtitles fell back to local script-timed SRT generation

- Final motion clips are currently local Ken Burns style clips generated from storyboard keyframes, not remote motion-model clips.
  - Impact: usable for workflow testing and packaging, but not yet equivalent to production-quality AI motion ads

## Engineering assessment

Current system suitability for ad-material automation: usable with constraints.

Good enough now:
- campaign templating
- emotional ad copy packaging
- storyboard prompt generation
- remote storyboard image generation
- local clip assembly
- TTS generation with local fallback
- subtitle generation with local fallback
- vertical export packaging

Needs more engineering before production-scale use:
- stable object storage uploads
- remote ASR integration for word-level subtitle timing
- remote video generation reliability and quality control
- better per-run manifesting and incremental resume
- more explicit compliance guardrails in the general Streamlit UI, not just the AnyWell runner

## How to rerun

```powershell
python scripts\run_anywell_campaign.py
```

Optional:

```powershell
python scripts\run_anywell_campaign.py --max-concepts 1
```

## Key paths

- run log: `logs/anywell_campaign_run.log`
- packaged outputs: `outputs/anywell_campaign`
- summary JSON: `outputs/anywell_campaign/campaign_report.json`
- generated run artifacts: `generated/runs/anywell-*`
