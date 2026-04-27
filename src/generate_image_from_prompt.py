from __future__ import annotations

import os

from dotenv import load_dotenv

from google_gemini_api import DEFAULT_IMAGE_MODEL as DEFAULT_GEMINI_IMAGE_MODEL, generate_image as generate_gemini_image
from openrouter_image_api import DEFAULT_IMAGE_MODEL as DEFAULT_OPENROUTER_IMAGE_MODEL, generate_image as generate_openrouter_image


load_dotenv()


def generate_image_from_prompt(
    prompt: str,
    out_dir: str | None = None,
    model: str = DEFAULT_OPENROUTER_IMAGE_MODEL,
    aspect_ratio: str = "9:16",
    reference_pic_paths: list[str] | None = None,
    system_prompt: str | None = None,
) -> str:
    resolved_model = model or os.getenv("IMAGE_MODEL", DEFAULT_OPENROUTER_IMAGE_MODEL)
    if str(resolved_model).strip().startswith("gemini"):
        return generate_gemini_image(
            prompt=prompt,
            model=resolved_model or os.getenv("IMAGE_MODEL", DEFAULT_GEMINI_IMAGE_MODEL),
            aspect_ratio=aspect_ratio,
            reference_pic_paths=reference_pic_paths,
            system_prompt=system_prompt,
            out_dir=out_dir,
        )
    return generate_openrouter_image(
        prompt=prompt,
        model=resolved_model,
        aspect_ratio=aspect_ratio,
        reference_pic_paths=reference_pic_paths,
        system_prompt=system_prompt,
        out_dir=out_dir,
    )
