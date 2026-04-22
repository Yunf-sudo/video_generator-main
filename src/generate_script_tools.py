from __future__ import annotations

import json
import os
import re
import uuid

from dotenv import load_dotenv

from google_gemini_api import DEFAULT_TEXT_MODEL, extract_response_text, generate_content
from input_translation import translate_inputs_to_english, translate_text_to_english
from prompt_context import build_prompt_context
from prompt_overrides import apply_override
from product_reference_images import get_product_visual_structure_json
from prompts_en import generate_script_system_prompt, generate_script_user_prompt
from runtime_tunables_config import load_runtime_tunables

try:
    import json_repair
except ImportError:  # pragma: no cover - optional dependency
    json_repair = None


load_dotenv()

RUNTIME_TUNABLES = load_runtime_tunables()
DEFAULT_SCRIPT_MODEL = os.getenv(
    "SCRIPT_MODEL",
    str(RUNTIME_TUNABLES["model_config"].get("script_model") or DEFAULT_TEXT_MODEL),
)
FIXED_DESIRED_SCENE_COUNT = 3
FIXED_PREFERRED_RUNTIME_SECONDS = 18
FIXED_SCENE_DURATION_SECONDS = 6

SCRIPT_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "main_theme": {"type": "string"},
        "scenes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "scene_number": {"type": "integer"},
                    "theme": {"type": "string"},
                    "duration_seconds": {"type": "integer"},
                    "scene_description": {"type": "string"},
                    "visuals": {
                        "type": "object",
                        "properties": {
                            "camera_movement": {"type": "string"},
                            "lighting": {"type": "string"},
                            "composition_and_set_dressing": {"type": "string"},
                            "transition_anchor": {"type": "string"},
                        },
                    },
                    "audio": {
                        "type": "object",
                        "properties": {
                            "voice_over": {"type": "string"},
                            "text": {"type": "string"},
                            "music": {"type": "string"},
                            "sfx": {"type": "string"},
                        },
                    },
                    "key_message": {"type": "string"},
                },
                "required": [
                    "scene_number",
                    "theme",
                    "duration_seconds",
                    "scene_description",
                    "visuals",
                    "audio",
                    "key_message",
                ],
            },
        },
    },
    "required": ["main_theme", "scenes"],
}


def _parse_json_text(text: str):
    if json_repair is not None:
        return json_repair.loads(text)
    return json.loads(text)


def _json_candidates(content: str) -> list[str]:
    stripped = content.strip()
    candidates: list[str] = []

    fenced = re.search(r"```(?:json)?\s*(.*?)```", stripped, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        candidates.append(fenced.group(1).strip())

    object_start = stripped.find("{")
    array_start = stripped.find("[")
    starts = [index for index in [object_start, array_start] if index >= 0]
    end = max(stripped.rfind("}"), stripped.rfind("]"))
    if starts and end > min(starts):
        candidates.append(stripped[min(starts) : end + 1])

    if stripped:
        candidates.append(stripped)

    unique: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in unique:
            unique.append(candidate)
    return unique


def _loads_script_json(content: str):
    last_error: Exception | None = None
    for candidate in _json_candidates(content):
        try:
            parsed = _parse_json_text(candidate)
            previous_text = candidate
            for _ in range(3):
                if not isinstance(parsed, str):
                    return parsed
                next_text = parsed.strip()
                if not next_text or next_text == previous_text:
                    break
                previous_text = next_text
                parsed = _parse_json_text(next_text)
        except Exception as exc:
            last_error = exc
    preview = content.strip().replace("\n", " ")[:500]
    raise ValueError(f"Unable to parse script JSON: {last_error}. Response preview: {preview}")


def _coerce_scene_dict(scene, index: int) -> dict:
    if isinstance(scene, str):
        try:
            scene = _loads_script_json(scene)
        except Exception:
            scene = {"scene_description": scene}
    if not isinstance(scene, dict):
        scene = {"scene_description": str(scene)}

    audio = scene.get("audio", {})
    if isinstance(audio, str):
        audio = {"voice_over": audio, "text": audio}
    elif not isinstance(audio, dict):
        audio = {}
    scene_voiceover = str(
        scene.get("voiceover")
        or scene.get("voice_over")
        or scene.get("voiceover_en")
        or scene.get("narration")
        or ""
    ).strip()
    voice_over = str(audio.get("voice_over") or scene_voiceover or audio.get("text") or "").strip()
    text = str(audio.get("text") or scene_voiceover or voice_over).strip()
    if voice_over:
        audio["voice_over"] = voice_over
    if text:
        audio["text"] = text
        audio.setdefault("subtitle_text", text)
    scene["audio"] = audio

    visuals = scene.get("visuals", {})
    if isinstance(visuals, str):
        visuals = {"camera_movement": visuals}
    elif not isinstance(visuals, dict):
        visuals = {}
    visuals.setdefault("camera_movement", "steady front-side product lifestyle shot")
    visuals.setdefault("lighting", "natural realistic light")
    visuals.setdefault("composition_and_set_dressing", "portrait product-and-rider composition in a believable everyday setting")
    visuals.setdefault("transition_anchor", "end on a clean visual beat for the next scene")
    scene["visuals"] = visuals
    scene["scene_number"] = int(scene.get("scene_number") or index)
    scene.setdefault("theme", f"Scene {index}")
    scene.setdefault("duration_seconds", FIXED_SCENE_DURATION_SECONDS)
    scene.setdefault("scene_description", "")
    scene.setdefault("key_message", "")
    return scene


def _normalize_script_json(script_json) -> dict:
    if isinstance(script_json, str):
        script_json = _loads_script_json(script_json)

    if isinstance(script_json, list):
        root = {"main_theme": "", "scenes": script_json}
    elif isinstance(script_json, dict):
        nested_scenes = script_json.get("scenes")
        if isinstance(nested_scenes, dict) and isinstance(nested_scenes.get("scenes"), list):
            root = {
                "main_theme": nested_scenes.get("main_theme") or script_json.get("main_theme", ""),
                "scenes": nested_scenes.get("scenes", []),
            }
        elif isinstance(nested_scenes, list):
            root = {
                "main_theme": script_json.get("main_theme", ""),
                "scenes": nested_scenes,
            }
        else:
            raise ValueError(f"Script JSON does not contain a scenes list: {script_json}")
    else:
        raise TypeError(f"Script JSON must be an object or list, got {type(script_json).__name__}")

    root["scenes"] = [_coerce_scene_dict(scene, index) for index, scene in enumerate(root.get("scenes", []), start=1)]
    return root


def _enforce_scene_count(script_json: dict, desired_scene_count: int = FIXED_DESIRED_SCENE_COUNT) -> dict:
    scenes = list(script_json.get("scenes", []))
    if len(scenes) < desired_scene_count:
        raise ValueError(f"Script generation returned {len(scenes)} scenes; expected {desired_scene_count}.")
    trimmed_scenes = scenes[:desired_scene_count]
    for index, scene in enumerate(trimmed_scenes, start=1):
        scene["scene_number"] = index
        scene["duration_seconds"] = FIXED_SCENE_DURATION_SECONDS
    script_json["scenes"] = trimmed_scenes
    return script_json


def _create_script_completion(messages: list[dict]) -> str:
    response = generate_content(
        model=DEFAULT_SCRIPT_MODEL,
        messages=messages,
        response_mime_type="application/json",
        response_json_schema=SCRIPT_JSON_SCHEMA,
        timeout_seconds=300.0,
    )
    return extract_response_text(response)


def _script_json_from_messages(messages: list[dict]) -> tuple[dict, list[dict]]:
    assistant_content = _create_script_completion(messages)
    first_messages = [
        *messages,
        {
            "role": "assistant",
            "content": assistant_content,
        },
    ]
    try:
        return _normalize_script_json(_loads_script_json(assistant_content)), first_messages
    except Exception:
        retry_messages = [
            *first_messages,
            {
                "role": "user",
                "content": (
                    "Convert your previous answer into one raw valid JSON object only. "
                    'The root object must contain "main_theme" and "scenes". '
                    f"Every scene duration should be {FIXED_SCENE_DURATION_SECONDS} seconds."
                ),
            },
        ]
        retry_content = _create_script_completion(retry_messages)
        retry_messages.append({"role": "assistant", "content": retry_content})
        return _normalize_script_json(_loads_script_json(retry_content)), retry_messages


def generate_scripts(params: dict) -> tuple[dict, list[dict]]:
    source_params = dict(params)
    source_params["desired_scene_count"] = FIXED_DESIRED_SCENE_COUNT
    source_params["preferred_runtime_seconds"] = FIXED_PREFERRED_RUNTIME_SECONDS
    enriched_params = translate_inputs_to_english(source_params)
    enriched_params["desired_scene_count"] = FIXED_DESIRED_SCENE_COUNT
    enriched_params["preferred_runtime_seconds"] = FIXED_PREFERRED_RUNTIME_SECONDS
    use_product_reference_images = bool(enriched_params.get("use_product_reference_images", True))
    enriched_params.setdefault(
        "product_visual_structure",
        get_product_visual_structure_json() if use_product_reference_images else "",
    )
    prompt_context = build_prompt_context(enriched_params)
    user_prompt = apply_override(
        generate_script_user_prompt.format(**enriched_params, **prompt_context),
        "script_user_append",
    )
    messages = [
        {
            "role": "system",
            "content": apply_override(
                generate_script_system_prompt.format(
                    reference_style=enriched_params.get("reference_style", "No external style reference provided."),
                    desired_scene_count=enriched_params.get("desired_scene_count", 5),
                    preferred_runtime_seconds=enriched_params.get(
                        "preferred_runtime_seconds",
                        FIXED_PREFERRED_RUNTIME_SECONDS,
                    ),
                    **prompt_context,
                ),
                "script_system_append",
            ),
        },
        {
            "role": "user",
            "content": user_prompt,
        },
    ]
    json_ret, messages = _script_json_from_messages(messages)
    json_ret = _enforce_scene_count(json_ret, FIXED_DESIRED_SCENE_COUNT)
    with_meta_ret = {
        "id": str(uuid.uuid4()),
        "version": 1,
        "meta": enriched_params,
        "source_meta": source_params,
        "scenes": json_ret,
        "history": [],
    }
    return with_meta_ret, messages


def repair_script(messages: list[dict], feedback: str) -> tuple[dict, list[dict]]:
    translated_feedback = translate_text_to_english(feedback)
    messages = [*messages, {"role": "user", "content": translated_feedback}]
    json_ret, messages = _script_json_from_messages(messages)
    with_meta_ret = {
        "id": str(uuid.uuid4()),
        "scenes": json_ret,
    }
    return with_meta_ret, messages


if __name__ == "__main__":
    pass
