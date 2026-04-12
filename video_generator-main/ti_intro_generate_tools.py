from prompts_en import ti_intro_generator_prompt, ti_intro_generator_prompt_with_ref

import os
import uuid
import json
import json_repair
from dotenv import load_dotenv
from openai import OpenAI
from youtube_fetch.youtube_fetcher import fetch_channel_info

client = OpenAI(
  base_url="http://jeniya.cn/v1",
  api_key=os.getenv("JENIYA_API_TOKEN"),
)

youtube_out_dir = "youtube_data"
DEFAULT_META_MODEL = os.getenv("META_MODEL", "gpt-5-mini")

def generate_ti_intro_with_ref(video_info: dict, ref_channel_identity: str):
    channel_info_file = fetch_channel_info(ref_channel_identity, youtube_out_dir)
    with open(channel_info_file, "r", encoding="utf-8") as f:
        channel_info = json.load(f)

    all_tags = set()

    for video in channel_info["videos"]:
        tags = video.get("snippet", {}).get("tags", [])
        all_tags.update(tags)
        if len(all_tags) > 50:
            break
    
    messages = [
        {
            "role": "system",
            "content": ti_intro_generator_prompt_with_ref.format(reference_tags=str(all_tags))
        },
        {
            "role": "user",
            "content": f"Script is below: \n{json.dumps(video_info, ensure_ascii=False, indent=2)}"
        }
    ]
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
    json_ret = json_repair.loads(completion.choices[0].message.content)
    return json_ret, messages


def generate_ti_intro(video_info: dict) -> str:
    messages = [
        {
            "role": "system",
            "content": ti_intro_generator_prompt
        },
        {
            "role": "user",
            "content": f"Script is below:\n{json.dumps(video_info, ensure_ascii=False, indent=2)}"
        }
    ]
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
    json_ret = json_repair.loads(completion.choices[0].message.content)
    return json_ret, messages

def repair_ti_intro(messages: list[dict], feedback: str) -> str:
    messages.append(
        {
            "role": "user",
            "content": feedback
        }
    )
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
    json_ret = json_repair.loads(completion.choices[0].message.content)
    return json_ret, messages
