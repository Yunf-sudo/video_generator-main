import json

from generate_image_from_prompt import generate_image_from_prompt
from local_storyboard_placeholder import create_storyboard_placeholder
from prompt_context import build_prompt_context
from prompt_overrides import apply_override
from product_reference_images import (
    get_product_reference_images,
    get_product_reference_signature,
    get_product_visual_structure_json,
    merge_reference_images,
)
from prompts_en import generate_scene_pic_system_prompt, generate_scene_pic_user_prompt


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


def generate_storyboard(
    scene_info: dict,
    reference_image_paths: list[str] | None = None,
    aspect_ratio: str = "9:16",
):
    main_theme, scenes, meta = _extract_scene_root(scene_info)
    ret = []
    prompt_context = build_prompt_context(meta)
    use_product_reference_images = bool(meta.get("use_product_reference_images", True))
    product_reference_limit = int(meta.get("product_reference_image_limit", 5) or 5)
    product_reference_paths = get_product_reference_images(limit=product_reference_limit) if use_product_reference_images else []
    continuity_reference_paths = list(reference_image_paths or [])
    product_reference_signature = meta.get("product_reference_signature")
    if product_reference_signature is None:
        product_reference_signature = get_product_reference_signature() if use_product_reference_images else ""
    product_visual_structure = meta.get("product_visual_structure")
    if product_visual_structure is None:
        product_visual_structure = get_product_visual_structure_json() if use_product_reference_images else ""
    continuity_rider_anchor = (
        meta.get("continuity_rider_anchor")
        or "Use the same confident adult rider across connected scenes. Keep the rider identity and wardrobe stable."
    )

    for index, scene in enumerate(scenes):
        previous_scene = scenes[index - 1] if index > 0 else None
        next_scene = scenes[index + 1] if index + 1 < len(scenes) else None
        continuity = {
            "same_rider_default": continuity_rider_anchor,
            "previous_scene": {
                "scene_number": previous_scene.get("scene_number", index),
                "theme": previous_scene.get("theme", ""),
                "key_message": previous_scene.get("key_message", ""),
                "scene_description": previous_scene.get("scene_description", ""),
                "visuals": previous_scene.get("visuals", {}),
            }
            if previous_scene
            else None,
            "next_scene": {
                "scene_number": next_scene.get("scene_number", index + 2),
                "theme": next_scene.get("theme", ""),
                "key_message": next_scene.get("key_message", ""),
                "scene_description": next_scene.get("scene_description", ""),
                "visuals": next_scene.get("visuals", {}),
            }
            if next_scene
            else None,
        }
        model_input = {
            "product_name": meta.get("product_name", ""),
            "product_category": meta.get("product_category", ""),
            "consistency_anchor": meta.get("consistency_anchor", ""),
            "product_reference_signature": product_reference_signature,
            "product_visual_structure": product_visual_structure,
            "main_theme": main_theme,
            "aspect_ratio": aspect_ratio,
            "continuity": continuity,
                "scene_to_generate": {
                    "scene_number": scene.get("scene_number", index + 1),
                    "theme": scene.get("theme", ""),
                    "duration_seconds": scene.get("duration_seconds", 8),
                    "scene_description": scene.get("scene_description", ""),
                    "visuals": scene.get("visuals", {}),
                    "audio": scene.get("audio", {}),
                    "key_message": scene.get("key_message", ""),
                },
            }
        filled_prompt = apply_override(
            generate_scene_pic_user_prompt.format(
                structured_input=json.dumps(model_input, ensure_ascii=False, indent=2)
            ),
            "scene_pic_user_append",
        )
        system_prompt = apply_override(
            generate_scene_pic_system_prompt.format(**prompt_context),
            "scene_pic_system_append",
        )
        scene_reference_paths = merge_reference_images(
            product_reference_paths,
            continuity_reference_paths,
            limit=6,
        )

        generated_pic_path = ""
        image_generation_mode = "remote"
        image_generation_error = ""
        try:
            generated_pic_path = generate_image_from_prompt(
                prompt=filled_prompt,
                system_prompt=system_prompt,
                reference_pic_paths=scene_reference_paths or None,
                aspect_ratio=aspect_ratio,
            )
        except Exception as exc:
            image_generation_mode = "placeholder"
            image_generation_error = str(exc)
            generated_pic_path = create_storyboard_placeholder(
                scene_number=int(scene.get("scene_number", index + 1)),
                scene_description=scene.get("scene_description", ""),
                key_message=scene.get("key_message", ""),
                aspect_ratio=aspect_ratio,
            )
        ret.append(
            {
                "scene_number": scene.get("scene_number", index + 1),
                "duration_seconds": scene.get("duration_seconds", 8),
                "saved_path": generated_pic_path,
                "scene_description": scene.get("scene_description", ""),
                "visuals": scene.get("visuals", {}),
                "audio": scene.get("audio", {}),
                "key_message": scene.get("key_message", ""),
                "continuity": continuity,
                "image_prompt": filled_prompt,
                "image_system_prompt": system_prompt,
                "image_generation_mode": image_generation_mode,
                "image_generation_error": image_generation_error,
            }
        )
        # Keep the earliest approved keyframes as identity anchors for later scenes.
        continuity_reference_paths = (continuity_reference_paths + [generated_pic_path])[-2:]

    return ret


def repair_single_pic(pic_path: str, feedback: str, aspect_ratio: str = "9:16"):
    filled_prompt = (
        "Refine the uploaded storyboard frame while keeping the same wheelchair product design.\n"
        f"Exact product identity to preserve: {get_product_reference_signature()}\n"
        f"Requested change: {feedback}"
    )
    system_prompt = (
        "Edit the uploaded image with minimal change. Keep the same product identity, "
        "same wheelchair design, same colorway, and same overall visual direction. "
        "Make the frame feel more realistic, physically plausible, and ready for a live-action ad shoot."
    )

    return generate_image_from_prompt(
        filled_prompt,
        reference_pic_paths=merge_reference_images(get_product_reference_images(), [pic_path], limit=5),
        system_prompt=apply_override(system_prompt, "scene_pic_system_append"),
        aspect_ratio=aspect_ratio,
    )
