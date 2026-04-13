# Video Generator

## Structure

```text
.
├─ app.py                  # Streamlit entrypoint
├─ src/                    # Main application source code
├─ scripts/                # Demo, utility, and one-off scripts
├─ generated/
│  ├─ runs/                # New outputs, one folder per run
│  ├─ cache/               # Shared caches
│  └─ legacy/              # Archived outputs from before the reorg
├─ 白底图/                  # Product reference images
├─ prompt_overrides.json   # Local prompt tweaks
└─ .env                    # Environment variables
```

## Run The App

```powershell
streamlit run app.py
```

## Output Layout

Each new generation run is stored under:

```text
generated/runs/<run_id>/
├─ uploads/
├─ pics/
├─ clips/
├─ audio/
├─ subtitles/
├─ exports/
├─ youtube_data/
├─ local_storage/
└─ meta/
```

`generated/legacy/root_outputs/` keeps the old output folders that existed before the project was reorganized.
