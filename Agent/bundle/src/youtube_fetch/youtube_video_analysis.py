from __future__ import annotations

import json
import os
from typing import Any

import requests
from agent_bundle_env import load_agent_bundle_env

from google_gemini_api import DEFAULT_TEXT_MODEL, extract_response_text, generate_content
from runtime_tunables_config import load_runtime_tunables


load_agent_bundle_env()

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"
RUNTIME_TUNABLES = load_runtime_tunables()
PRIMARY_ANALYSIS_MODEL = os.getenv(
    "YOUTUBE_ANALYSIS_MODEL",
    str(RUNTIME_TUNABLES["model_config"].get("youtube_analysis_model") or DEFAULT_TEXT_MODEL),
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
    extra_text = extra_prompt.strip() if extra_prompt else "No additional instruction."
    return (
        "You are a cross-border ecommerce ad strategist. "
        "You only have public YouTube metadata, channel info, tags, and comments. "
        "Do not pretend you watched the video frame by frame. "
        "When you infer hook style, pacing, or emotional angle, explicitly treat it as an evidence-based inference.\n\n"
        "Write a 5-part Chinese analysis covering:\n"
        "1. Likely content structure and opening hook\n"
        "2. Borrowable pacing, selling-point sequence, and CTA style\n"
        "3. What can transfer into electric wheelchair advertising\n"
        "4. What should not be copied\n"
        "5. A short prompt-ready style summary block\n\n"
        f"Additional instruction: {extra_text}\n\n"
        f"Metadata:\n{json.dumps(metadata, ensure_ascii=False, indent=2)}"
    )


def analyze_video(video_id: str, prompt: str | None = None) -> str:
    metadata = _build_analysis_payload(video_id)
    response = generate_content(
        model=PRIMARY_ANALYSIS_MODEL,
        messages=[
            {
                "role": "system",
                "content": "Turn public competitor-video signals into practical advertising style guidance.",
            },
            {
                "role": "user",
                "content": _analysis_prompt(metadata, extra_prompt=prompt),
            },
        ],
        timeout_seconds=180.0,
    )
    return extract_response_text(response)


if __name__ == "__main__":
    print(analyze_video("dQw4w9WgXcQ"))
