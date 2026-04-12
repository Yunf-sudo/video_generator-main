import os

import requests

from rustfs_util import upload_file_to_rustfs


def _new_draft_with_video(video_url, ext_dict):
    params = {"video_url": video_url}
    params.update(ext_dict)
    response = requests.post(os.getenv("CAPCUT_API_URL") + "/add_video", json=params, timeout=120)
    response_json = response.json()
    return response_json, response_json["output"]["draft_id"], response_json["output"]["draft_url"]


def _add_video_to_draft(draft_id, video_url, ext_dict):
    params = {"draft_id": draft_id, "video_url": video_url}
    params.update(ext_dict)
    response = requests.post(os.getenv("CAPCUT_API_URL") + "/add_video", json=params, timeout=120)
    response_json = response.json()
    return response_json, response_json["output"]["draft_id"], response_json["output"]["draft_url"]


def _add_audio_to_draft(draft_id, audio_url, ext_dict):
    params = {"draft_id": draft_id, "audio_url": audio_url}
    params.update(ext_dict)
    response = requests.post(os.getenv("CAPCUT_API_URL") + "/add_audio", json=params, timeout=120)
    response_json = response.json()
    return response_json, response_json["output"]["draft_id"], response_json["output"]["draft_url"]


def _add_srt_to_draft(draft_id, srt_url, ext_dict):
    params = {"draft_id": draft_id, "srt": srt_url}
    params.update(ext_dict)
    response = requests.post(os.getenv("CAPCUT_API_URL") + "/add_subtitle", json=params, timeout=120)
    response_json = response.json()
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
