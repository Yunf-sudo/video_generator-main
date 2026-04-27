from __future__ import annotations

import os

from agent_bundle_env import load_agent_bundle_env

from google_gemini_api import DEFAULT_IMAGE_MODEL, generate_image


load_agent_bundle_env()


def generate_image_from_prompt(
    prompt: str,
    out_dir: str | None = None,
    model: str = DEFAULT_IMAGE_MODEL,
    aspect_ratio: str = "9:16",
    reference_pic_paths: list[str] | None = None,
    system_prompt: str | None = None,
) -> str:
    return generate_image(
        prompt=prompt,
        model=model or os.getenv("IMAGE_MODEL", DEFAULT_IMAGE_MODEL),
        aspect_ratio=aspect_ratio,
        reference_pic_paths=reference_pic_paths,
        system_prompt=system_prompt,
        out_dir=out_dir,
    )
