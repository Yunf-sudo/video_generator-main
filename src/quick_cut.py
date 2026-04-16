import os
import socket
from urllib.parse import urlparse

import requests

from rustfs_util import upload_file_to_rustfs


class CapCutServiceError(RuntimeError):
    """Raised when the external CapCut bridge service is unavailable or invalid."""


def get_capcut_api_url() -> str:
    return (os.getenv("CAPCUT_API_URL") or "").strip().rstrip("/")


def capcut_service_status(timeout: float = 2.0) -> tuple[bool, str]:
    base_url = get_capcut_api_url()
    if not base_url:
        return False, "未配置 CAPCUT_API_URL，无法导入剪映。"

    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False, f"CAPCUT_API_URL 配置无效：{base_url}"

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((parsed.hostname, port), timeout=timeout):
            pass
    except OSError as exc:
        return False, f"剪映桥接服务未启动或不可达：{base_url}（{exc}）"
    return True, f"剪映桥接服务可用：{base_url}"


def _post_capcut(path: str, params: dict):
    base_url = get_capcut_api_url()
    ok, message = capcut_service_status()
    if not ok:
        raise CapCutServiceError(f"{message}。请先启动该服务，再点击“上传片段并导入剪映”。")

    try:
        response = requests.post(base_url + path, json=params, timeout=120)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise CapCutServiceError(f"请求剪映桥接服务失败：{base_url + path}。{exc}") from exc

    try:
        response_json = response.json()
    except ValueError as exc:
        raise CapCutServiceError("剪映桥接服务返回的不是合法 JSON。") from exc

    output = response_json.get("output")
    if not isinstance(output, dict):
        raise CapCutServiceError(f"剪映桥接服务返回异常：{response_json}")
    return response_json


def _new_draft_with_video(video_url, ext_dict):
    params = {"video_url": video_url}
    params.update(ext_dict)
    response_json = _post_capcut("/add_video", params)
    return response_json, response_json["output"]["draft_id"], response_json["output"]["draft_url"]


def _add_video_to_draft(draft_id, video_url, ext_dict):
    params = {"draft_id": draft_id, "video_url": video_url}
    params.update(ext_dict)
    response_json = _post_capcut("/add_video", params)
    return response_json, response_json["output"]["draft_id"], response_json["output"]["draft_url"]


def _add_audio_to_draft(draft_id, audio_url, ext_dict):
    params = {"draft_id": draft_id, "audio_url": audio_url}
    params.update(ext_dict)
    response_json = _post_capcut("/add_audio", params)
    return response_json, response_json["output"]["draft_id"], response_json["output"]["draft_url"]


def _add_srt_to_draft(draft_id, srt_url, ext_dict):
    params = {"draft_id": draft_id, "srt": srt_url}
    params.update(ext_dict)
    response_json = _post_capcut("/add_subtitle", params)
    return response_json, response_json["output"]["draft_id"], response_json["output"]["draft_url"]


def upload_all_videos_to_rustfs(video_result: dict):
    update_result = {}
    for key, value in video_result.items():
        updated = dict(value)
        upload_url = upload_file_to_rustfs(
            value["video_path"],
            os.getenv("RUSTFS_BUCKET_NAME_VIDEO"),
            rename_file=True,
        )
        updated["rustfs_url"] = upload_url
        update_result[key] = updated
    return update_result


def quick_cut_video(video_result: dict, tts_result: dict, bgm_result: dict | None = None):
    if not video_result:
        return None, None

    ordered_items = sorted(video_result.items(), key=lambda item: int(item[0]))
    first_key, first_value = ordered_items[0]
    first_duration = float(first_value.get("duration_seconds", 8))
    _, draft_id, draft_url = _new_draft_with_video(
        first_value["rustfs_url"],
        {"start": 0, "end": first_duration},
    )

    begin_time = first_duration
    for key, value in ordered_items[1:]:
        duration = float(value.get("duration_seconds", 8))
        _, draft_id, draft_url = _add_video_to_draft(
            draft_id,
            value["rustfs_url"],
            {"target_start": begin_time, "start": 0, "end": duration},
        )
        begin_time += duration

    audio_url = tts_result.get("audio_url") or tts_result.get("url")
    if audio_url:
        _, draft_id, draft_url = _add_audio_to_draft(
            draft_id,
            audio_url,
            {
                "target_start": 0,
                "end": tts_result.get("duration_seconds") or tts_result.get("duration") or begin_time,
                "track_name": "Voiceover",
            },
        )

    if bgm_result and bgm_result.get("url"):
        _, draft_id, draft_url = _add_audio_to_draft(
            draft_id,
            bgm_result["url"],
            {
                "target_start": 0,
                "end": tts_result.get("duration_seconds") or tts_result.get("duration") or begin_time,
                "track_name": "BGM",
            },
        )

    srt_url = tts_result.get("srt_url")
    if srt_url:
        _, draft_id, draft_url = _add_srt_to_draft(
            draft_id,
            srt_url,
            {
                "target_start": 0,
                "end": tts_result.get("duration_seconds") or tts_result.get("duration") or begin_time,
                "track_name": "SRT",
            },
        )

    return draft_id, draft_url
