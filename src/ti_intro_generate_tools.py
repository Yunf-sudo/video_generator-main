from prompts_en import ti_intro_generator_prompt, ti_intro_generator_prompt_with_ref

import json
import os
import uuid

from dotenv import load_dotenv
from openai import OpenAI

from prompt_context import build_prompt_context
from youtube_fetch.youtube_fetcher import fetch_channel_info
from workspace_paths import ensure_active_run

try:
    import json_repair
except ImportError:  # pragma: no cover - optional dependency
    json_repair = None


load_dotenv()

client = OpenAI(
  base_url="http://jeniya.cn/v1",
  api_key=os.getenv("JENIYA_API_TOKEN"),
)

DEFAULT_META_MODEL = os.getenv("META_MODEL", "gpt-5.2-all")


def _load_json(content: str) -> dict:
    payload = json_repair.loads(content) if json_repair is not None else json.loads(content)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected title metadata JSON object, got {type(payload).__name__}.")
    return payload


def _fallback_intro(video_info: dict) -> tuple[dict, list[dict]]:
    meta = video_info.get("meta", {}) if isinstance(video_info, dict) else {}
    prompt_context = build_prompt_context(meta)
    scenes_root = video_info.get("scenes", {}) if isinstance(video_info, dict) else {}
    scenes = scenes_root.get("scenes", []) if isinstance(scenes_root, dict) else []
    main_theme = scenes_root.get("main_theme") or meta.get("concept_title") or "Brand campaign"
    title = f"{prompt_context['marketing_product_name']} | {main_theme}".strip()
    lead = next(
        (
            (scene.get("audio", {}).get("text") or scene.get("key_message") or "").strip()
            for scene in scenes
            if (scene.get("audio", {}).get("text") or scene.get("key_message") or "").strip()
        ),
        "",
    )
    close = meta.get("concept_cta") or "Discover more moments outside."
    description = " ".join(part for part in [lead, close] if part).strip()
    tags = [
        prompt_context["marketing_product_name"],
        meta.get("brand_name") or meta.get("product_brand_name") or "mobility",
        "wheelchair",
        "dignity",
        "freedom",
        "outdoor mobility",
    ]
    tags = [str(tag).strip() for tag in tags if str(tag).strip()]
    return {
        "title": title[:90],
        "description": description[:400],
        "tags": list(dict.fromkeys(tags))[:8],
    }, []


def generate_ti_intro_with_ref(video_info: dict, ref_channel_identity: str):
    channel_info_file = fetch_channel_info(ref_channel_identity, str(ensure_active_run().youtube_data))
    with open(channel_info_file, "r", encoding="utf-8") as f:
        channel_info = json.load(f)

    all_tags = set()

    for video in channel_info["videos"]:
        tags = video.get("snippet", {}).get("tags", [])
        all_tags.update(tags)
        if len(all_tags) > 50:
            break

    prompt_context = build_prompt_context(video_info.get("meta", {}))
    messages = [
        {
            "role": "system",
            "content": ti_intro_generator_prompt_with_ref.format(reference_tags=str(all_tags), **prompt_context)
        },
        {
            "role": "user",
            "content": f"Script is below: \n{json.dumps(video_info, ensure_ascii=False, indent=2)}"
        }
    ]
    try:
        completion = client.chat.completions.create(
            model=DEFAULT_META_MODEL,
            messages=messages
        )
        messages.append(
            {
                "role": "assistant",
                "content": completion.choices[0].message.content
            }
        )
        json_ret = _load_json(completion.choices[0].message.content)
        return json_ret, messages
    except Exception:
        fallback, fallback_messages = _fallback_intro(video_info)
        return fallback, messages + fallback_messages


def generate_ti_intro(video_info: dict) -> str:
    prompt_context = build_prompt_context(video_info.get("meta", {}))
    messages = [
        {
            "role": "system",
            "content": ti_intro_generator_prompt.format(**prompt_context)
        },
        {
            "role": "user",
            "content": f"Script is below:\n{json.dumps(video_info, ensure_ascii=False, indent=2)}"
        }
    ]
    try:
        completion = client.chat.completions.create(
            model=DEFAULT_META_MODEL,
            messages=messages
        )
        messages.append(
            {
                "role": "assistant",
                "content": completion.choices[0].message.content
            }
        )
        json_ret = _load_json(completion.choices[0].message.content)
        return json_ret, messages
    except Exception:
        fallback, fallback_messages = _fallback_intro(video_info)
        return fallback, messages + fallback_messages


def repair_ti_intro(messages: list[dict], feedback: str) -> str:
    messages.append(
        {
            "role": "user",
            "content": feedback
        }
    )
    try:
        completion = client.chat.completions.create(
            model=DEFAULT_META_MODEL,
            messages=messages
        )
        messages.append(
            {
                "role": "assistant",
                "content": completion.choices[0].message.content
            }
        )
        json_ret = _load_json(completion.choices[0].message.content)
        return json_ret, messages
    except Exception:
        fallback = {
            "title": f"Draft {uuid.uuid4().hex[:6]}",
            "description": feedback,
            "tags": ["draft", "campaign"],
        }
        return fallback, messages
