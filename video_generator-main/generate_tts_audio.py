import os
import uuid

from dotenv import load_dotenv
from openai import OpenAI

from media_pipeline import probe_audio_duration, safe_file_uri
from rustfs_util import upload_file_to_rustfs


load_dotenv()

client = OpenAI(
    base_url="http://jeniya.cn/v1",
    api_key=os.getenv("JENIYA_API_TOKEN"),
)

DEFAULT_TTS_MODEL = os.getenv("TTS_MODEL", "gpt-4o-mini-tts")


def generate_and_upload_tts(
    text: str,
    output_dir: str = "audio_output",
    bucket_name: str = os.getenv("RUSTFS_BUCKET_NAME_AUDIO"),
    voice: str = "alloy",
    model: str = DEFAULT_TTS_MODEL,
) -> tuple[str, str, float]:
    os.makedirs(output_dir, exist_ok=True)
    filename = f"tts_{uuid.uuid4()}.mp3"
    file_path = os.path.join(output_dir, filename)

    try:
        response = client.audio.speech.create(
            model=model,
            voice=voice,
            input=text,
            timeout=300,
        )
        response.stream_to_file(file_path)

        duration_seconds = probe_audio_duration(file_path)
        url = upload_file_to_rustfs(file_path, bucket_name, object_name=filename)
        if url:
            return url, file_path, duration_seconds
        return safe_file_uri(file_path), file_path, duration_seconds
    except Exception as exc:
        print(f"Error generating or uploading TTS: {exc}")
        return "", "", 0.0


def generate_tts_audio(script: dict):
    full_text = ""
    scenes_root = script.get("scenes", {})
    scenes = scenes_root.get("scenes", []) if isinstance(scenes_root, dict) else []
    for scene in scenes:
        full_text += (scene.get("audio", {}).get("text") or "") + " "

    return generate_and_upload_tts(full_text.strip())
