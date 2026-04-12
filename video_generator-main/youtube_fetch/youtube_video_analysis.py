from __future__ import annotations

import json
import os
from typing import Any

import requests
from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"
DEFAULT_ANALYSIS_MODELS = [
    model.strip()
    for model in os.getenv("YOUTUBE_ANALYSIS_FALLBACK_MODELS", "gpt-5-mini,gpt-4o-mini,qwen3.6-plus").split(",")
    if model.strip()
]
PRIMARY_ANALYSIS_MODEL = os.getenv("YOUTUBE_ANALYSIS_MODEL", DEFAULT_ANALYSIS_MODELS[0] if DEFAULT_ANALYSIS_MODELS else "gpt-5-mini")

client = OpenAI(
    base_url="http://jeniya.cn/v1",
    api_key=os.getenv("JENIYA_API_TOKEN"),
)


def _youtube_api_get(endpoint: str, params: dict[str, str]) -> dict[str, Any]:
    api_key = os.getenv("YOUTUBE_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("Missing YOUTUBE_API_KEY or GOOGLE_API_KEY for competitor video analysis.")

    response = requests.get(
        f"{YOUTUBE_API_BASE}/{endpoint}",
        params={"key": api_key, **params},
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("error"):
        raise RuntimeError(f"YouTube API error: {json.dumps(payload['error'], ensure_ascii=False)}")
    return payload


def _fetch_video_metadata(video_id: str) -> dict[str, Any]:
    payload = _youtube_api_get(
        "videos",
        {
            "part": "snippet,statistics,contentDetails",
            "id": video_id,
        },
    )
    items = payload.get("items", [])
    if not items:
        raise RuntimeError(f"Could not find YouTube video: {video_id}")
    return items[0]


def _fetch_channel_metadata(channel_id: str) -> dict[str, Any]:
    payload = _youtube_api_get(
        "channels",
        {
            "part": "snippet,statistics",
            "id": channel_id,
        },
    )
    items = payload.get("items", [])
    return items[0] if items else {}


def _fetch_top_comments(video_id: str, max_results: int = 8) -> list[dict[str, Any]]:
    try:
        payload = _youtube_api_get(
            "commentThreads",
            {
                "part": "snippet",
                "videoId": video_id,
                "maxResults": str(max_results),
                "order": "relevance",
                "textFormat": "plainText",
            },
        )
    except Exception:
        return []

    comments = []
    for item in payload.get("items", []):
        top_comment = item.get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
        if not top_comment:
            continue
        comments.append(
            {
                "author": top_comment.get("authorDisplayName", ""),
                "likeCount": top_comment.get("likeCount", 0),
                "text": top_comment.get("textDisplay", ""),
            }
        )
    return comments


def _build_analysis_payload(video_id: str) -> dict[str, Any]:
    video = _fetch_video_metadata(video_id)
    snippet = video.get("snippet", {})
    statistics = video.get("statistics", {})
    content_details = video.get("contentDetails", {})
    channel_id = snippet.get("channelId", "")
    channel = _fetch_channel_metadata(channel_id) if channel_id else {}

    return {
        "video_id": video_id,
        "title": snippet.get("title", ""),
        "description": snippet.get("description", "")[:4000],
        "published_at": snippet.get("publishedAt", ""),
        "channel_title": snippet.get("channelTitle", ""),
        "channel": {
            "title": channel.get("snippet", {}).get("title", ""),
            "description": channel.get("snippet", {}).get("description", "")[:1000],
            "subscriber_count": channel.get("statistics", {}).get("subscriberCount", ""),
            "video_count": channel.get("statistics", {}).get("videoCount", ""),
        },
        "tags": snippet.get("tags", [])[:30],
        "category_id": snippet.get("categoryId", ""),
        "duration_iso8601": content_details.get("duration", ""),
        "definition": content_details.get("definition", ""),
        "view_count": statistics.get("viewCount", ""),
        "like_count": statistics.get("likeCount", ""),
        "comment_count": statistics.get("commentCount", ""),
        "top_comments": _fetch_top_comments(video_id),
    }


def _analysis_prompt(metadata: dict[str, Any], extra_prompt: str | None = None) -> str:
    extra_text = extra_prompt.strip() if extra_prompt else "无额外说明。"
    return (
        "你是跨境电商广告导演与内容策略顾问。请基于下面这条 YouTube 视频的公开元数据、频道信息、标签与评论，"
        "总结它对广告创意的可复用价值。注意：你不是直接看到了原始画面，所以凡是关于镜头、节奏、情绪的判断，"
        "都要写成基于证据的推断，不要假装逐帧看过视频。\n\n"
        "请输出一段 400-800 字中文分析，覆盖：\n"
        "1. 可能的内容结构与开头钩子\n"
        "2. 适合借鉴的镜头节奏、卖点组织与 CTA 方式\n"
        "3. 适合迁移到“电动轮椅”广告里的风格要点\n"
        "4. 不建议照搬的点\n"
        "5. 最后给一个可直接塞进提示词的“风格参考总结”小段落\n\n"
        f"额外说明：{extra_text}\n\n"
        f"视频资料：\n{json.dumps(metadata, ensure_ascii=False, indent=2)}"
    )


def _complete_with_fallback(messages: list[dict[str, str]]) -> str:
    candidate_models = [PRIMARY_ANALYSIS_MODEL] + [model for model in DEFAULT_ANALYSIS_MODELS if model != PRIMARY_ANALYSIS_MODEL]
    last_error: Exception | None = None
    for model in candidate_models:
        try:
            completion = client.chat.completions.create(
                model=model,
                messages=messages,
                timeout=300,
            )
            return completion.choices[0].message.content
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"YouTube analysis failed across models: {last_error}")


def analyze_video(video_id: str, prompt: str | None = None) -> str:
    metadata = _build_analysis_payload(video_id)
    messages = [
        {
            "role": "system",
            "content": "你擅长把竞品视频信号转成可执行的商品广告风格参考。",
        },
        {
            "role": "user",
            "content": _analysis_prompt(metadata, extra_prompt=prompt),
        },
    ]
    return _complete_with_fallback(messages)


if __name__ == "__main__":
    print(analyze_video("dQw4w9WgXcQ"))
