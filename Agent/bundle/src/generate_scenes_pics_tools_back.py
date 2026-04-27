import os
import json
import base64
import mimetypes
import uuid
from pathlib import Path
import requests
from agent_bundle_env import load_agent_bundle_env
from prompts_en import generate_scene_pic_system_prompt, generate_scene_pic_user_prompt
import re

load_agent_bundle_env()

OPENROUTER_API_KEY = "sk-kww6u7AfYDmliGlw9lddZvJzobdn6bDDz30ubVDmJRKlBWEJ"
# OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_URL = "http://jeniya.cn/v1/chat/completions"
# OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
# Use preview image model per OpenRouter example
DEFAULT_MODEL = "gemini-2.5-flash-image"
# DEFAULT_MODEL = "google/gemini-2.5-flash-image"
OUT_DIR = "/home/wuzhicheng/code/ai_ads_generator/pics"

def _encode_image_to_base64(image_path: str) -> str:
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")

def _data_url_for_image(image_path: str) -> str:
    mime, _ = mimetypes.guess_type(image_path)
    mime = mime or "image/jpeg"
    base64_image = _encode_image_to_base64(image_path)
    return f"data:{mime};base64,{base64_image}"

def _guess_ext_from_mime(mime: str | None) -> str:
        if not mime:
            return ".jpg"
        base = mime.split(";")[0]
        ext = mimetypes.guess_extension(base)
        return ext or ".jpg"

def _save_data_url(data_url: str, out_dir: str) -> str:
        # data:image/png;base64,<data>
        header, b64 = data_url.split(",", 1)
        mime = header[5:].split(";")[0] if header.startswith("data:") else "image/jpeg"
        ext = _guess_ext_from_mime(mime)
        filename = f"generated_{uuid.uuid4().hex[:8]}{ext}"
        out_path = os.path.join(out_dir, filename)
        os.makedirs(out_dir, exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(base64.b64decode(b64))
        return out_path

def _save_url(url: str, out_dir: str) -> str:
    os.makedirs(out_dir, exist_ok=True)
    try:
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        mime = resp.headers.get("Content-Type")
        ext = _guess_ext_from_mime(mime)
        # Try to infer from URL if possible
        url_path = url.split("?")[0].split("#")[0]
        ext_from_url = os.path.splitext(url_path)[1]
        if ext_from_url:
            ext = ext_from_url
        filename = f"generated_{uuid.uuid4().hex[:8]}{ext}"
        out_path = os.path.join(out_dir, filename)
        with open(out_path, "wb") as f:
            f.write(resp.content)
        return out_path
    except Exception as e:
        print(f"  Failed to save {url}: {e}")
        return ""

def request_single_pic_generate(
    scene_info: dict,
    *,
    model: str = DEFAULT_MODEL,
    aspect_ratio: str = "16:9",
    reference_image_paths: list[str | Path] | None = None,
    jianyi: bool = True,
):
    """
    Generate a single image for a given scene using OpenRouter chat completions.

    Params:
    - scene_info: dict containing main_theme and scene_to_generate content
    - model: image-capable chat model id (default: Gemini 2.5 image preview)
    - aspect_ratio: image aspect ratio string like "16:9"

    Returns: list of image URLs (strings). Empty list if none.
    """
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is not set in environment.")

    # Render user prompt with structured JSON input
    structured_json = json.dumps(scene_info, ensure_ascii=False, indent=2)
    user_content = generate_scene_pic_user_prompt.format(structured_input=structured_json)

    # Prepare multi-modal content array (text + optional image)
    content_items: list[dict] = [
        {"type": "text", "text": user_content}
    ]



    if reference_image_paths is not None:
        for ref_path in reference_image_paths:
            ref_path = str(Path(ref_path))
            if not os.path.exists(ref_path):
                raise FileNotFoundError(f"Reference image path not found: {ref_path}")
            data_url = _data_url_for_image(ref_path)
            content_items.append({
                "type": "image_url",
                "image_url": {"url": data_url}
            })

    messages = [
        {"role": "system", "content": generate_scene_pic_system_prompt},
        {"role": "user", "content": content_items},
    ]

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "messages": messages,
        "modalities": ["image", "text"],
        "image_config": {
            "aspect_ratio": aspect_ratio,
        },
    }

    try:
        response = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=60)
    except requests.RequestException as e:
        raise RuntimeError(f"Failed to call OpenRouter: {e}")

    if not response.ok:
        # Include response text for easier debugging
        raise RuntimeError(f"OpenRouter returned status {response.status_code}: {response.text}")

    result = response.json()
    # with open("openrouter_response.json", "w") as f:
    #     json.dump(result, f, ensure_ascii=False, indent=2)

    # Handle possible error structure
    if isinstance(result, dict) and result.get("error"):
        err = result.get("error")
        raise RuntimeError(f"OpenRouter error: {err}")

    image_urls = []
    try:
        choices = result.get("choices", [])
        if choices:
            if jianyi:
                message = choices[0].get("message", {})
                content = message.get("content", "")
                # Extract URL from markdown image syntax: ![image](url)
                match = re.search(r'!\[.*?\]\((.*?)\)', content)
                if match:
                    image_urls.append(match.group(1))
            else:
                message = choices[0].get("message", {})
                images = message.get("images", [])
                for image in images:
                    # Expected shape: { "image_url": { "url": "..." } }
                    url_obj = image.get("image_url") or {}
                    url = url_obj.get("url")
                    if url:
                        image_urls.append(url)
    except Exception:
        # Be resilient to schema variations; do not crash
        pass

    return image_urls

def generate_storyboard(scene_info: dict, reference_image_paths: str):
    
    main_theme = scene_info["main_theme"]

    ret = []

    for scene in scene_info["scenes"]:
        model_input = {
            "main_theme": main_theme,
            "scene_to_generate": {
                "scene_number": scene["scene_number"],
                "theme": scene["theme"],
                "duration_seconds": scene["duration_seconds"],
                "scene_description": scene["scene_description"],
                "visuals": scene["visuals"],
                "key_message": scene["key_message"],
            }
        }
        urls = request_single_pic_generate(
            model_input,
            model=DEFAULT_MODEL,
            aspect_ratio="16:9",
            reference_image_paths=reference_image_paths,
        )
        for i, u in enumerate(urls, 1):
            saved_paths: list[str] = []
            for u in urls:
                if u.startswith("data:"):
                    p = _save_data_url(u, out_dir="pics")
                    saved_paths.append(p)
                else:
                    p = _save_url(u, out_dir="pics")
                    if p:
                        saved_paths.append(p)

        ret.append(
            {
                "scene_number": scene["scene_number"],
                "saved_path": saved_paths[0],
                "scene_description": scene["scene_description"],
                "visuals": scene["visuals"],
            }
        )

    return ret

def repair_single_pic(pic_path: str, feedback: str, model: str = DEFAULT_MODEL, aspect_ratio: str = "16:9"):        
    image_url = _data_url_for_image(pic_path)
    
    messages = [
        {
            "role": "system",
            "content": "请你按照用户的提示编辑图片，注意！不要改变图片的大致风格方向，只能对上传的图片进行微调。",
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": f"请你按照以下的要求，对上传的图片进行微调：\n{feedback}",
                },
                {
                    "type": "image_url",
                    "image_url": {"url": image_url}
                },
            ]
        }
    ]

    payload = {
        "model": model,
        "messages": messages,
        "modalities": ["image", "text"],
        "image_config": {
            "aspect_ratio": aspect_ratio,
        },
    }
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=60)
    except requests.RequestException as e:
        raise RuntimeError(f"Failed to call OpenRouter: {e}")

    if not response.ok:
        # Include response text for easier debugging
        raise RuntimeError(f"OpenRouter returned status {response.status_code}: {response.text}")

    result = response.json()
    # with open("openrouter_response.json", "w") as f:
    #     json.dump(result, f, ensure_ascii=False, indent=2)

    # Handle possible error structure
    if isinstance(result, dict) and result.get("error"):
        err = result.get("error")
        raise RuntimeError(f"OpenRouter error: {err}")

    image_urls = []
    try:
        choices = result.get("choices", [])
        if choices:
            message = choices[0].get("message", {})
            content = message.get("content", "")
            # Extract URL from markdown image syntax: ![image](url)
            match = re.search(r'!\[.*?\]\((.*?)\)', content)
            if match:
                image_urls.append(match.group(1))
    except Exception:
        # Be resilient to schema variations; do not crash
        pass

    # for i, u in enumerate(image_urls, 1):
    saved_paths = []
    for u in image_urls:
        if u.startswith("data:"):
            p = _save_data_url(u, out_dir="pics")
            saved_paths.append(p)
        else:
            p = _save_url(u, out_dir="pics")
            if p:
                saved_paths.append(p)

    return saved_paths[0]



if __name__ == "__main__":
    scene_info = {
        "main_theme": "科技助行，生活无界",
        "scene_to_generate": {
            "scene_number": 4,
            "theme": "户外 - 稳定行驶",
            "duration_seconds": 7,
            "scene_description": "阳光明媚的公园。一条铺有轻微起伏石板路的小径。周围绿树成荫，有其他成年人在远处活动。",
            "visuals": {
                "camera_movement": "（单一镜头）摄影机在侧方，使用稳定器（Steadicam）或轨道（Dolly）跟随轮椅和同行的老伴（均为成年人）一同前进，保持中景。",
                "lighting": "温暖的午后自然光（“黄金时刻”光线），光线从侧面照射，营造出幸福、活跃的氛围。",
                "composition_and_set_dressing": "画面构图平衡，张爷爷（轮椅）和他的老伴占据画面主体。背景是虚化的公园绿色景观。两人都在开心地微笑。"
            },
            "key_message": "展示产品的户外稳定性（即使在非平坦路面）。"
        },
    }

    reference_image_path = "/home/wuzhicheng/code/ai_ads_generator/pics/uploaded_5cbf6df4_Snipaste_2025-11-05_16-52-02.jpg"  # 可选：填写本地图片路径，例如 "./assets/wheelchair.jpg"

    try:
        urls = request_single_pic_generate(
            scene_info,
            model=DEFAULT_MODEL,
            aspect_ratio="16:9",
            reference_image_paths=[reference_image_path],
        )
    except Exception as e:
        print(f"Error: {e}")
        urls = []

    if urls:
        print(f"Generated {len(urls)} image(s):")
        for i, u in enumerate(urls, 1):
            print(f"  [{i}] {u}")
        # Save images to local directory
        def _guess_ext_from_mime(mime: str | None) -> str:
            if not mime:
                return ".jpg"
            base = mime.split(";")[0]
            ext = mimetypes.guess_extension(base)
            return ext or ".jpg"

        def _save_data_url(data_url: str, out_dir: str) -> str:
            # data:image/png;base64,<data>
            header, b64 = data_url.split(",", 1)
            mime = header[5:].split(";")[0] if header.startswith("data:") else "image/jpeg"
            ext = _guess_ext_from_mime(mime)
            filename = f"generated_{uuid.uuid4().hex[:8]}{ext}"
            out_path = os.path.join(out_dir, filename)
            os.makedirs(out_dir, exist_ok=True)
            with open(out_path, "wb") as f:
                f.write(base64.b64decode(b64))
            return out_path

        def _save_url(url: str, out_dir: str) -> str:
            os.makedirs(out_dir, exist_ok=True)
            try:
                resp = requests.get(url, timeout=60)
                resp.raise_for_status()
                mime = resp.headers.get("Content-Type")
                ext = _guess_ext_from_mime(mime)
                # Try to infer from URL if possible
                url_path = url.split("?")[0].split("#")[0]
                ext_from_url = os.path.splitext(url_path)[1]
                if ext_from_url:
                    ext = ext_from_url
                filename = f"generated_{uuid.uuid4().hex[:8]}{ext}"
                out_path = os.path.join(out_dir, filename)
                with open(out_path, "wb") as f:
                    f.write(resp.content)
                return out_path
            except Exception as e:
                print(f"  Failed to save {url}: {e}")
                return ""

        saved_paths: list[str] = []
        for u in urls:
            if u.startswith("data:"):
                p = _save_data_url(u, out_dir="pics")
                saved_paths.append(p)
            else:
                p = _save_url(u, out_dir="pics")
                if p:
                    saved_paths.append(p)
        if saved_paths:
            print(f"Saved {len(saved_paths)} image(s) to 'pics':")
            for p in saved_paths:
                print(f"  - {p}")
    else:
        print("No image URLs returned.")
    