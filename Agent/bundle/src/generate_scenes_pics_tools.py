from __future__ import annotations

import json

from generation_prompt_builder import compose_generation_prompt
from generate_image_from_prompt import generate_image_from_prompt
from input_translation import translate_text_to_english
from local_storyboard_placeholder import create_storyboard_placeholder
from prompt_context import build_prompt_context
from prompt_overrides import apply_override
from product_reference_images import (
    get_product_reference_images,
    get_product_reference_signature,
    get_product_visual_structure_json,
    merge_reference_images,
)
from prompts_en import generate_scene_pic_system_prompt


def _extract_scene_root(scene_info: dict) -> tuple[str, list[dict], dict]:
    if "meta" in scene_info and "scenes" in scene_info:
        scenes_root = scene_info["scenes"]
        meta = scene_info.get("meta", {})
    else:
        scenes_root = scene_info
        meta = {}

    main_theme = scenes_root["main_theme"]
    scenes = scenes_root["scenes"]
    return main_theme, scenes, meta


def _resolve_scene_generation_context(scene_info: dict) -> dict:
    main_theme, scenes, meta = _extract_scene_root(scene_info)
    prompt_context = build_prompt_context(meta)
    use_product_reference_images = bool(meta.get("use_product_reference_images", True))
    product_reference_limit = int(meta.get("product_reference_image_limit", 5) or 5)
    product_reference_paths = get_product_reference_images(limit=product_reference_limit) if use_product_reference_images else []
    product_reference_signature = meta.get("product_reference_signature")
    if product_reference_signature is None:
        product_reference_signature = get_product_reference_signature() if use_product_reference_images else ""
    product_visual_structure = meta.get("product_visual_structure")
    if product_visual_structure is None:
        product_visual_structure = get_product_visual_structure_json() if use_product_reference_images else ""
    continuity_rider_anchor = (
        meta.get("continuity_rider_anchor")
        or "Use a coherent rider identity across connected scenes unless the user explicitly asks for a change."
    )
    return {
        "main_theme": main_theme,
        "scenes": scenes,
        "meta": meta,
        "prompt_context": prompt_context,
        "product_reference_paths": product_reference_paths,
        "product_reference_signature": product_reference_signature,
        "product_visual_structure": product_visual_structure,
        "continuity_rider_anchor": continuity_rider_anchor,
    }


def build_storyboard_scene_request(
    scene_info: dict,
    scene_number: int,
    reference_image_paths: list[str] | None = None,
    aspect_ratio: str = "9:16",
    continuity_reference_paths: list[str] | None = None,
    prompt_override: str | None = None,
    system_prompt_override: str | None = None,
    allow_ai_composer: bool = True,
) -> dict:
    context = _resolve_scene_generation_context(scene_info)
    scenes = context["scenes"]
    scene_index = max(0, int(scene_number) - 1)
    if scene_index >= len(scenes):
        raise IndexError(f"Scene {scene_number} is out of range for storyboard generation.")

    scene = scenes[scene_index]
    previous_scene = scenes[scene_index - 1] if scene_index > 0 else None
    next_scene = scenes[scene_index + 1] if scene_index + 1 < len(scenes) else None
    continuity = {
        "same_rider_default": context["continuity_rider_anchor"],
        "previous_scene": {
            "scene_number": previous_scene.get("scene_number", scene_index),
            "theme": previous_scene.get("theme", ""),
            "key_message": previous_scene.get("key_message", ""),
            "scene_description": previous_scene.get("scene_description", ""),
            "visuals": previous_scene.get("visuals", {}),
        }
        if previous_scene
        else None,
        "next_scene": {
            "scene_number": next_scene.get("scene_number", scene_index + 2),
            "theme": next_scene.get("theme", ""),
            "key_message": next_scene.get("key_message", ""),
            "scene_description": next_scene.get("scene_description", ""),
            "visuals": next_scene.get("visuals", {}),
        }
        if next_scene
        else None,
    }

    model_input = {
        "product_name": context["meta"].get("product_name", ""),
        "product_category": context["meta"].get("product_category", ""),
        "consistency_anchor": context["meta"].get("consistency_anchor", ""),
        "product_geometry_notes": context["meta"].get("product_geometry_notes", ""),
        "product_reference_signature": context["product_reference_signature"],
        "product_visual_structure": context["product_visual_structure"],
        "main_theme": context["main_theme"],
        "aspect_ratio": aspect_ratio,
        "continuity": continuity,
        "scene_to_generate": {
            "scene_number": scene.get("scene_number", scene_index + 1),
            "theme": scene.get("theme", ""),
            "duration_seconds": scene.get("duration_seconds", 8),
            "scene_description": scene.get("scene_description", ""),
            "visuals": scene.get("visuals", {}),
            "audio": scene.get("audio", {}),
            "key_message": scene.get("key_message", ""),
        },
    }
    prompt_composition = compose_generation_prompt(
        target="image",
        scene_description=scene.get("scene_description", ""),
        visuals=scene.get("visuals", {}),
        scene_audio=scene.get("audio", {}),
        continuity=continuity,
        aspect_ratio=aspect_ratio,
        duration_seconds=int(scene.get("duration_seconds", 8) or 8),
        meta=context["meta"],
        hero_product_name=context["meta"].get("hero_product_name") or context["meta"].get("product_name"),
        product_reference_signature=context["product_reference_signature"],
        product_visual_structure=context["product_visual_structure"],
        allow_ai_composer=allow_ai_composer,
    )
    filled_prompt = str(prompt_override or prompt_composition["prompt"]).strip()
    if not filled_prompt:
        filled_prompt = prompt_composition["fallback_prompt"]
    system_prompt = str(
        system_prompt_override
        or apply_override(
            generate_scene_pic_system_prompt.format(**context["prompt_context"]),
            "scene_pic_system_append",
        )
    ).strip()

    scene_reference_paths = merge_reference_images(
        context["product_reference_paths"],
        list(reference_image_paths or []) + list(continuity_reference_paths or []),
        limit=6,
    )
    return {
        "scene_number": scene.get("scene_number", scene_index + 1),
        "duration_seconds": scene.get("duration_seconds", 8),
        "scene_description": scene.get("scene_description", ""),
        "visuals": scene.get("visuals", {}),
        "audio": scene.get("audio", {}),
        "key_message": scene.get("key_message", ""),
        "continuity": continuity,
        "image_prompt_bundle": model_input,
        "image_prompt_composer_bundle": prompt_composition["bundle"],
        "image_prompt_fallback": prompt_composition["fallback_prompt"],
        "image_prompt_mode": prompt_composition["composition_mode"],
        "image_prompt_model": prompt_composition["composer_model"],
        "image_prompt": filled_prompt,
        "image_system_prompt": system_prompt,
        "scene_reference_paths": scene_reference_paths,
    }


def generate_storyboard_scene(
    scene_info: dict,
    scene_number: int,
    reference_image_paths: list[str] | None = None,
    aspect_ratio: str = "9:16",
    continuity_reference_paths: list[str] | None = None,
    prompt_override: str | None = None,
    system_prompt_override: str | None = None,
    allow_ai_composer: bool = True,
) -> dict:
    frame = build_storyboard_scene_request(
        scene_info=scene_info,
        scene_number=scene_number,
        reference_image_paths=reference_image_paths,
        aspect_ratio=aspect_ratio,
        continuity_reference_paths=continuity_reference_paths,
        prompt_override=prompt_override,
        system_prompt_override=system_prompt_override,
        allow_ai_composer=allow_ai_composer,
    )

    generated_pic_path = ""
    image_generation_mode = "remote"
    image_generation_error = ""
    try:
        generated_pic_path = generate_image_from_prompt(
            prompt=frame["image_prompt"],
            system_prompt=frame["image_system_prompt"],
            reference_pic_paths=frame["scene_reference_paths"] or None,
            aspect_ratio=aspect_ratio,
        )
    except Exception as exc:
        image_generation_mode = "placeholder"
        image_generation_error = str(exc)
        generated_pic_path = create_storyboard_placeholder(
            scene_number=int(frame.get("scene_number", scene_number)),
            scene_description=frame.get("scene_description", ""),
            key_message=frame.get("key_message", ""),
            aspect_ratio=aspect_ratio,
        )

    return {
        **frame,
        "saved_path": generated_pic_path,
        "image_generation_mode": image_generation_mode,
        "image_generation_error": image_generation_error,
    }


def generate_storyboard(
    scene_info: dict,
    reference_image_paths: list[str] | None = None,
    aspect_ratio: str = "9:16",
    prompt_overrides: dict[str, dict] | None = None,
):
    _, scenes, _ = _extract_scene_root(scene_info)
    prompt_overrides = prompt_overrides or {}
    ret = []
    continuity_reference_paths = list(reference_image_paths or [])

    for index, scene in enumerate(scenes, start=1):
        override = prompt_overrides.get(str(scene.get("scene_number", index))) or {}
        frame = generate_storyboard_scene(
            scene_info=scene_info,
            scene_number=int(scene.get("scene_number", index) or index),
            reference_image_paths=reference_image_paths,
            aspect_ratio=aspect_ratio,
            continuity_reference_paths=continuity_reference_paths,
            prompt_override=override.get("image_prompt"),
            system_prompt_override=override.get("image_system_prompt"),
        )
        ret.append(frame)
        continuity_reference_paths = (continuity_reference_paths + [frame["saved_path"]])[-2:]

    return ret


def repair_single_pic(pic_path: str, feedback: str, aspect_ratio: str = "9:16"):
    translated_feedback = translate_text_to_english(feedback)
    filled_prompt = (
        "Refine the uploaded storyboard frame while preserving its overall subject continuity unless the user "
        "explicitly asks to change it.\n"
        f"Reference product context: {get_product_reference_signature()}\n"
        f"Requested change: {translated_feedback}"
    )
    system_prompt = (
        "Edit the uploaded image with minimal necessary change. Keep the overall visual direction coherent, "
        "improve realism and physical plausibility, and respect the user's requested adjustment."
    )

    return generate_image_from_prompt(
        filled_prompt,
        reference_pic_paths=merge_reference_images(get_product_reference_images(), [pic_path], limit=5),
        system_prompt=apply_override(system_prompt, "scene_pic_system_append"),
        aspect_ratio=aspect_ratio,
    )
