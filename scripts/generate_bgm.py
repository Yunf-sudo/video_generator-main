import json
import time
import requests
import os
import uuid
import Sign
import _bootstrap  # noqa: F401
from google_gemini_api import extract_response_text, generate_content
from rustfs_util import upload_file_to_rustfs
from dotenv import load_dotenv

load_dotenv()

STATUS_CODE_SUCCESS = 0

QUERY_STATUS_CODE_WAITING = 0
QUERY_STATUS_CODE_HANDING = 1
QUERY_STATUS_CODE_SUCCESS = 2
QUERY_STATUS_CODE_FAILED = 3

def get_response(response):
    response_json = json.loads(response.text)
    return response_json.get('Code'), response_json.get('Message'), response_json.get('Result'), response_json.get(
        'ResponseMetadata')

def generate_music_prompt(script: str) -> str:
    """
    Generate a music prompt based on the video script using LLM.
    
    Args:
        script (str): The video script.
        
    Returns:
        str: The generated music prompt.
    """
    prompt = f"""
    Please generate a short background music description prompt based on the following video script.
    The prompt should include key information such as music style, mood, and instruments, suitable as input for AI music generation.
    Please output the prompt directly in English, without any explanatory text.
    
    Video Script:
    {script}
    """
    
    try:
        response = generate_content(
            model=os.getenv("META_MODEL", "gemini-2.5-flash"),
            messages=[{"role": "user", "content": prompt}],
            timeout_seconds=120.0,
        )
        return extract_response_text(response).strip() or "Relaxing and happy background music"
    except Exception as e:
        print(f"Error calling Gemini for music prompt: {e}")
        return "Relaxing and happy background music"

def generate_music(text: str, duration: int = 15) -> str:
    """
    Generate background music based on the prompt text.
    
    Args:
        text (str): The prompt text for music generation.
        duration (int): Duration of the music in seconds (1-60).
        
    Returns:
        str: The URL of the generated music uploaded to rustfs.
    """
    ak = os.getenv('VOLC_AK', "")
    sk = os.getenv('VOLC_SK', "")
    
    # Basic parameters
    # In a real scenario, these might also be inferred from the text or passed as args,
    # but for now we keep them static or default as per original code structure, 
    # relying on 'text' to drive the main style.
    genre = ["corporate"]
    mood = ["peaceful", 'soft']
    instrument = ['piano', 'strings']
    theme = ["every day"]
    
    action = "GenBGMForTime"
    version = "2024-08-12"
    region = "cn-beijing"
    service = 'imagination'
    host = "open.volcengineapi.com"
    path = "/"
    
    query = {
        'Action': action,
        'Version': version
    }
    
    body = {
        'Text': text,
        'Theme': theme,
        'Genre': genre,
        'Mood': mood,
        'Instrument': instrument,
        'Duration': duration,
    }
    
    x_content_sha256 = Sign.hash_sha256(json.dumps(body))
    headers = {
        "Content-Type": 'application/json',
        'Host': host,
        'X-Date': Sign.get_x_date(),
        'X-Content-Sha256': x_content_sha256
    }
    
    authorization = Sign.get_authorization("POST", headers=headers, query=query, service=service, region=region, ak=ak, sk=sk)
    headers["Authorization"] = authorization

    print(f"Generating music for prompt: {text}")
    response = requests.post(Sign.get_url(host, path, action, version), data=json.dumps(body), headers=headers)
    
    code, message, result, ResponseMetadata = get_response(response)
    if code != STATUS_CODE_SUCCESS or not response.ok:
        raise RuntimeError(f"Failed to start music generation: {response.text}")
        
    task_id = result['TaskID']
    predicted_wait_time = 5
    print(f"Task started, ID: {task_id}, waiting for generation...")
    time.sleep(predicted_wait_time)
    
    # Query loop
    body = {'TaskID': task_id}
    x_content_sha256 = Sign.hash_sha256(json.dumps(body))
    headers['X-Content-Sha256'] = x_content_sha256
    headers['X-Date'] = Sign.get_x_date()
    
    query_action = 'QuerySong'
    query["Action"] = query_action
    
    authorization = Sign.get_authorization("POST", headers=headers, query=query, service=service, region=region, ak=ak, sk=sk)
    headers["Authorization"] = authorization
    
    audio_url = None
    
    while True:
        response = requests.post(Sign.get_url(host, path, query_action, version), data=json.dumps(body), headers=headers)
        if not response.ok:
            raise RuntimeError(f"Failed to query status: {response.text}")

        code, message, result, ResponseMetadata = get_response(response)
        status = result.get('Status')
        progress = result.get('Progress')

        if status == QUERY_STATUS_CODE_FAILED:
            raise RuntimeError(f"Music generation failed: {response.text}")
        elif status == QUERY_STATUS_CODE_SUCCESS:
            song_detail = result.get('SongDetail')
            audio_url = song_detail.get('AudioUrl')
            print("Music generation finished.")
            break
        elif status == QUERY_STATUS_CODE_WAITING or status == QUERY_STATUS_CODE_HANDING:
            print(f"Progress: {progress}%")
            time.sleep(5)
        else:
            print(f"Unknown status: {response.text}")
            break
            
    if not audio_url:
        raise RuntimeError("Failed to retrieve audio URL")
        
    # Download the file
    print(f"Downloading music from {audio_url}")
    response = requests.get(audio_url)
    if response.status_code != 200:
        raise RuntimeError(f"Failed to download generated music: {response.status_code}")
        
    # Save to local file
    output_dir = "audio_gen"
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    file_name = f"{uuid.uuid4()}.mp3"
    local_file_path = os.path.join(output_dir, file_name)
    
    with open(local_file_path, 'wb') as f:
        f.write(response.content)
    print(f"Saved locally to {local_file_path}")
    
    # Upload to rustfs
    print("Uploading to rustfs...")
    bucket_name = os.getenv('RUSTFS_BUCKET_NAME_AUDIO', "audio-clips")
    
    rustfs_url = upload_file_to_rustfs(local_file_path, bucket_name, rename_file=True)
    print(f"Uploaded to rustfs: {rustfs_url}")
    
    return rustfs_url, local_file_path

def generate_bgm_from_script(script: str, duration: int = 15) -> str:
    """
    Generate background music based on a video script.
    
    Args:
        script (str): The video script content.
        duration (int): Duration of the music in seconds.
        
    Returns:
        str: The URL of the generated music uploaded to rustfs.
    """
    print("Generating music prompt from script...")
    music_prompt = generate_music_prompt(script)
    print(f"Generated Music Prompt: {music_prompt}")
    
    return generate_music(music_prompt, duration)

if __name__ == "__main__":
    # Test the function
    try:
        test_script = "This is a video about a vacation by the sea, with bright sunshine, waves gently lapping at the beach, and people enjoying a leisurely time."
        url, local_file_path = generate_bgm_from_script(test_script)
        print(f"Final Result: {url}")
    except Exception as e:
        print(f"Error: {e}")
