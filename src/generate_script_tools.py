import os
import uuid
import json
from dotenv import load_dotenv
from openai import OpenAI
from prompt_context import build_prompt_context
from prompt_overrides import apply_override
from product_reference_images import get_product_visual_structure_json
from prompts_en import generate_script_system_prompt, generate_script_user_prompt

try:
    import json_repair
except ImportError:  # pragma: no cover - optional dependency
    json_repair = None

load_dotenv()

client = OpenAI(
  base_url="http://jeniya.cn/v1",
  api_key=os.getenv("JENIYA_API_TOKEN"),
)

DEFAULT_SCRIPT_MODEL = os.getenv("SCRIPT_MODEL", "gpt-5-mini")


def _loads_script_json(content: str) -> dict:
    if json_repair is not None:
        return json_repair.loads(content)
    return json.loads(content)


def _normalize_script_json(script_json: dict) -> dict:
    scenes = script_json.get("scenes", [])
    for scene in scenes:
        audio = scene.setdefault("audio", {})
        voice_over = (audio.get("voice_over") or "").strip()
        text = (audio.get("text") or "").strip()
        if not text and voice_over:
            audio["text"] = voice_over
    return script_json

def generate_scripts(params: dict) -> str:
    enriched_params = dict(params)
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
                    preferred_runtime_seconds=enriched_params.get("preferred_runtime_seconds", 24),
                    **prompt_context,
                ),
                "script_system_append",
            ),
        },
        {
            "role": "user",
            "content": user_prompt
        }
    ]
    completion = client.chat.completions.create(
        model=DEFAULT_SCRIPT_MODEL,
        messages=messages
    )
    messages.append(
        {
            "role": "assistant",
            "content": completion.choices[0].message.content
        }
    )
    json_ret = _normalize_script_json(_loads_script_json(completion.choices[0].message.content))
    with_meta_ret = {
        "id": str(uuid.uuid4()),
        "version": 1,
        "meta": enriched_params,
        "scenes": json_ret,
        "history": [],
    }
    return with_meta_ret, messages

def repair_script(messages: list[dict], feedback: str) -> str:
    messages.append(
        {
            "role": "user",
            "content": feedback
        }
    )
    completion = client.chat.completions.create(
        model=DEFAULT_SCRIPT_MODEL,
        messages=messages
    )
    messages.append(
        {
            "role": "assistant",
            "content": completion.choices[0].message.content
        }
    )
    json_ret = _normalize_script_json(_loads_script_json(completion.choices[0].message.content))
    with_meta_ret = {
        "id": str(uuid.uuid4()),
        "scenes": json_ret,
    }
    # print(with_meta_ret)
    return with_meta_ret, messages

if __name__ == "__main__":
    pass
    # Simple test call for generate_scripts
    # theme = "Summer Sale"
    # style = "Energetic"
    # age = "25-35"
    # gender = "All"
    # interest = "Fashion"
    # more_info = "Limited time offer"

    # try:
    #     response, messages = generate_scripts(theme, style, age, gender, interest, more_info)
    #     print("Generated Script:")
    #     print(response)
    #     print("\nFull conversation messages:")
    #     for msg in messages:
    #         print(f"{msg['role']}: {msg['content']}")
    # except Exception as e:
    #     print("Error during script generation:", e)
