from __future__ import annotations

from prompt_templates_config import load_prompt_templates


PROMPT_TEMPLATES = load_prompt_templates()

generate_script_system_prompt = PROMPT_TEMPLATES["generate_script_system_prompt"]
generate_script_user_prompt = PROMPT_TEMPLATES["generate_script_user_prompt"]
generate_scene_pic_system_prompt = PROMPT_TEMPLATES["generate_scene_pic_system_prompt"]
generate_scene_pic_user_prompt = PROMPT_TEMPLATES["generate_scene_pic_user_prompt"]
video_generate_prompt = PROMPT_TEMPLATES["video_generate_prompt"]
ti_intro_generator_prompt = PROMPT_TEMPLATES["ti_intro_generator_prompt"]
ti_intro_generator_prompt_with_ref = PROMPT_TEMPLATES["ti_intro_generator_prompt_with_ref"]
