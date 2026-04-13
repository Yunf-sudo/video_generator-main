import os
import sys
import uuid
import json
import re
from typing import Dict, List, Optional
from dotenv import load_dotenv

load_dotenv()

import requests


API_BASE = "https://www.googleapis.com/youtube/v3"


class YouTubeAPIError(Exception):
    pass


def _get_api_key(explicit: Optional[str] = None) -> str:
    key = explicit or os.getenv("YOUTUBE_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key:
        raise YouTubeAPIError(
            "未找到 API Key，请在环境变量 YOUTUBE_API_KEY 或 GOOGLE_API_KEY 中配置，或通过命令行 --api-key 传入。"
        )
    return key


def _api_get(endpoint: str, params: Dict[str, str], api_key: str) -> Dict:
    url = f"{API_BASE}/{endpoint}"
    p = {"key": api_key, **params}
    resp = requests.get(url, params=p, timeout=30)
    if resp.status_code != 200:
        raise YouTubeAPIError(f"YouTube API 请求失败: {resp.status_code} {resp.text}")
    data = resp.json()
    if "error" in data:
        raise YouTubeAPIError(f"YouTube API 错误: {json.dumps(data['error'], ensure_ascii=False)}")
    return data


def resolve_channel_id(identifier: str, api_key: str) -> str:
    """
    将用户提供的标识解析为 channelId。

    支持：
    - 直接传入 channelId（UC 开头）
    - 自定义 URL：/channel/UCxxx, /c/<name>, /user/<name>
    - 传入 @handle（频道 handle）或名称时尝试搜索
    """
    ident = identifier.strip()
    if ident.startswith("UC") and len(ident) >= 20:
        return ident

    # 如果传的是一个 URL，尝试解析
    if ident.startswith("http://") or ident.startswith("https://"):
        # 常见形式：/channel/UC... 或 /@handle
        parts = ident.split("/")
        for i, part in enumerate(parts):
            if part == "channel" and i + 1 < len(parts):
                candidate = parts[i + 1]
                if candidate.startswith("UC"):
                    return candidate
            if part.startswith("@"):
                ident = part
                break

    # 优先通过 channels.list 的 forHandle 解析（2023+ 支持）
    handle = ident if ident.startswith("@") else None
    if handle:
        # 优先尝试 forHandle（若 API 不支持该参数或报错，则回退到 search）
        try:
            data = _api_get(
                "channels",
                {"part": "id", "forHandle": handle.lstrip("@")},
                api_key,
            )
            items = data.get("items", [])
            if items:
                return items[0]["id"]
        except YouTubeAPIError:
            pass

    # 兼容 legacy：user 名称和自定义名称通过 search.list 搜索频道
    data = _api_get(
        "search",
        {"part": "snippet", "q": ident, "type": "channel", "maxResults": "1"},
        api_key,
    )
    items = data.get("items", [])
    if not items:
        raise YouTubeAPIError(f"无法解析频道标识为 channelId: {identifier}")
    return items[0]["snippet"]["channelId"]


def get_upload_playlist_id(channel_id: str, api_key: str) -> str:
    # 通过 channels.list 获取 uploads 播放列表 ID
    data = _api_get(
        "channels",
        {"part": "contentDetails", "id": channel_id},
        api_key,
    )
    items = data.get("items", [])
    if not items:
        raise YouTubeAPIError("未找到频道 contentDetails")
    uploads = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    return uploads


def list_all_videos_from_uploads(playlist_id: str, api_key: str) -> List[Dict]:
    # 遍历 playlistItems 拿到所有 videoId
    video_ids: List[str] = []
    page_token: Optional[str] = None
    while True:
        params = {
            "part": "contentDetails",
            "playlistId": playlist_id,
            "maxResults": "50",
        }
        if page_token:
            params["pageToken"] = page_token
        data = _api_get("playlistItems", params, api_key)
        items = data.get("items", [])
        for it in items:
            vid = it["contentDetails"]["videoId"]
            video_ids.append(vid)
        page_token = data.get("nextPageToken")
        if not page_token:
            break

    # 批量获取视频详情（分批，每次最多 50 个）
    results: List[Dict] = []
    for i in range(0, len(video_ids), 50):
        batch = ",".join(video_ids[i : i + 50])
        detail = _api_get(
            "videos",
            {
                "part": "snippet,contentDetails,statistics",
                "id": batch,
            },
            api_key,
        )
        results.extend(detail.get("items", []))
    return results


def fetch_channel_videos(identifier: str, api_key: Optional[str] = None) -> List[Dict]:
    key = _get_api_key(api_key)
    channel_id = resolve_channel_id(identifier, key)
    uploads_id = get_upload_playlist_id(channel_id, key)
    videos = list_all_videos_from_uploads(uploads_id, key)
    return videos


def _parse_iso8601_duration_to_seconds(iso_duration: str) -> int:
    """解析 ISO8601 的时长格式（如 PT1M5S）为秒。"""
    if not iso_duration:
        return 0
    # 处理常见的小时/分钟/秒组成：PT#H#M#S
    pattern = re.compile(r"^PT(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?(?:(?P<s>\d+)S)?$")
    m = pattern.match(iso_duration)
    if not m:
        return 0
    hours = int(m.group("h") or 0)
    minutes = int(m.group("m") or 0)
    seconds = int(m.group("s") or 0)
    return hours * 3600 + minutes * 60 + seconds


def is_shorts(item: Dict) -> bool:
    """根据时长与标签/标题中的 #shorts 进行启发式判断。"""
    snippet = item.get("snippet", {})
    content = item.get("contentDetails", {})
    duration_iso = content.get("duration")
    secs = _parse_iso8601_duration_to_seconds(duration_iso)
    title = (snippet.get("title") or "").lower()
    description = (snippet.get("description") or "").lower()
    tags = [t.lower() for t in snippet.get("tags", []) if isinstance(t, str)]

    hashtag = "#shorts" in title or "#shorts" in description or "#shorts" in tags or "shorts" in tags
    return secs <= 60 or hashtag


def split_videos_and_shorts(items: List[Dict]) -> Dict[str, List[Dict]]:
    videos: List[Dict] = []
    shorts: List[Dict] = []
    for it in items:
        if is_shorts(it):
            shorts.append(it)
        else:
            videos.append(it)
    return {"videos": videos, "shorts": shorts}

def fetch_channel_info(channel_identifier: str, output_dir: str):

    items = fetch_channel_videos(channel_identifier)
    output_obj = split_videos_and_shorts(items)
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, f"{uuid.uuid4()}.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output_obj, f, ensure_ascii=False, indent=2)
    print(f"已写入: {output_file}")
    return output_file


def main(argv: List[str]) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="使用 YouTube Data API 获取指定频道的所有上传视频详情"
    )
    parser.add_argument(
        "identifier",
        help="频道标识：可为 channelId(UC开头)、频道URL、@handle 或名称",
    )
    parser.add_argument(
        "--api-key",
        help="显式传入 API Key，或使用环境变量 YOUTUBE_API_KEY/GOOGLE_API_KEY",
    )
    parser.add_argument(
        "--output",
        help="输出文件路径（JSON），不传则打印到标准输出",
    )
    parser.add_argument(
        "--split-shorts",
        action="store_true",
        help="在生成的 JSON 中将普通视频和 Shorts 分开为两个数组",
    )

    args = parser.parse_args(argv)

    try:
        items = fetch_channel_videos(args.identifier, args.api_key)
    except YouTubeAPIError as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)

    if args.split_shorts:
        output_obj = split_videos_and_shorts(items)
    else:
        output_obj = items

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(output_obj, f, ensure_ascii=False, indent=2)
        print(f"已写入: {args.output}")
    else:
        print(json.dumps(output_obj, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    fetch_channel_info("https://www.youtube.com/@KimCartomancer","youtube_data")