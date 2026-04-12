import json

from generate_image_from_prompt import generate_image_from_prompt
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
    product_reference_paths = get_product_reference_images()
    continuity_reference_paths = list(reference_image_paths or [])

    for index, scene in enumerate(scenes):
        previous_scene = scenes[index - 1] if index > 0 else None
        next_scene = scenes[index + 1] if index + 1 < len(scenes) else None
        continuity = {
            "same_rider_default": (
                "Use the same confident adult rider across connected scenes, about 30-55 years old, "
                "healthy-looking, everyday commercial styling, not elderly-coded unless explicitly requested."
            ),
            "previous_scene": {
                "scene_number": previous_scene["scene_number"],
                "theme": previous_scene["theme"],
                "key_message": previous_scene["key_message"],
                "scene_description": previous_scene["scene_description"],
                "visuals": previous_scene.get("visuals", {}),
            }
            if previous_scene
            else None,
            "next_scene": {
                "scene_number": next_scene["scene_number"],
                "theme": next_scene["theme"],
                "key_message": next_scene["key_message"],
                "scene_description": next_scene["scene_description"],
                "visuals": next_scene.get("visuals", {}),
            }
            if next_scene
            else None,
        }
        model_input = {
            "product_name": meta.get("product_name", ""),
            "product_category": meta.get("product_category", ""),
            "consistency_anchor": meta.get("consistency_anchor", ""),
            "product_reference_signature": get_product_reference_signature(),
            "product_visual_structure": get_product_visual_structure_json(),
            "main_theme": main_theme,
            "aspect_ratio": aspect_ratio,
            "continuity": continuity,
            "scene_to_generate": {
                "scene_number": scene["scene_number"],
                "theme": scene["theme"],
                "duration_seconds": scene["duration_seconds"],
                "scene_description": scene["scene_description"],
                "visuals": scene["visuals"],
                "key_message": scene["key_message"],
            },
        }
        filled_prompt = apply_override(
            generate_scene_pic_user_prompt.format(
                structured_input=json.dumps(model_input, ensure_ascii=False, indent=2)
            ),
            "scene_pic_user_append",
        )
        scene_reference_paths = merge_reference_images(
            product_reference_paths,
            continuity_reference_paths,
            limit=6,
        )

        generated_pic_path = generate_image_from_prompt(
            prompt=filled_prompt,
            system_prompt=apply_override(generate_scene_pic_system_prompt, "scene_pic_system_append"),
            reference_pic_paths=scene_reference_paths or None,
            aspect_ratio=aspect_ratio,
        )
        ret.append(
            {
                "scene_number": scene["scene_number"],
                "duration_seconds": scene["duration_seconds"],
                "saved_path": generated_pic_path,
                "scene_description": scene["scene_description"],
                "visuals": scene["visuals"],
                "key_message": scene["key_message"],
                "continuity": continuity,
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
