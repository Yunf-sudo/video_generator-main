from __future__ import annotations


# 这个文件专门放“运行时可调参数”。
# 和产品简报、风格默认值不同，这里更偏底层控制，例如：
# - 每分钟最多请求多少次
# - 超时时间
# - 重试次数
# - 默认使用哪个模型
# - 是否保留生成视频自带音频


MODEL_CONFIG = {
    # 文本生成默认模型：作为全局文本模型兜底。
    "text_model": "gemini-2.5-flash",
    # 脚本生成模型：广告脚本 JSON 结构生成。
    "script_model": "gemini-2.5-flash",
    # 图片生成模型：用于分镜图/关键帧生成。
    "image_model": "gemini-2.5-flash-image",
    # 视频生成模型：用于图生视频。
    "video_model": "veo-3.1-generate-preview",
    # TTS 模型：用于配音生成展示。
    "tts_model": "native-video-audio",
    # 竞品分析模型：用于分析 YouTube 视频风格。
    "youtube_analysis_model": "gemini-2.5-flash",
    # 标题/描述/标签生成模型。
    "meta_model": "gemini-2.5-flash",
    # 提示词整合模型：把多个输入块整合成最终 prompt。
    "prompt_composer_model": "gemini-2.5-flash",
    # 产品视觉结构分析模型。
    "vision_model": "gemini-2.5-flash",
    # 输入翻译模型：把中文交互输入翻成英文后再喂给主生成链路。
    "translation_model": "gemini-2.5-flash",
}


APP_RUNTIME_FLAGS = {
    # 是否在最终导出时保留视频生成接口自带的音轨。
    # True：直接保留片段音频，不再强制生成单独 TTS。
    # False：使用项目自己的配音和字幕流程。
    "use_generated_video_audio": True,
}


GOOGLE_API_RUNTIME = {
    # Gemini / Generative Language API 的基础地址。
    "google_api_base_url": "https://generativelanguage.googleapis.com/v1beta",
    # Gemini 文本/图片接口的单次请求在限流或临时错误时最多重试次数。
    "google_gemini_request_max_attempts": 5,
    # Gemini 接口重试的基础退避时间，单位秒。
    "google_gemini_retry_base_seconds": 5.0,
    # Gemini 接口重试的最大退避时间，单位秒。
    "google_gemini_retry_max_seconds": 45.0,
    # Gemini 返回 429 时，至少等待多久再重试，单位秒。
    "google_gemini_rate_limit_cooldown_seconds": 30.0,
    # 每次重试额外加入的随机抖动上限，单位秒。
    "google_gemini_retry_jitter_seconds": 1.0,
}


VIDEO_RUNTIME = {
    # 视频接口基础地址。
    "google_video_base_url": "https://generativelanguage.googleapis.com/v1beta",
    # 视频提供商标识，目前代码主流程默认是 google。
    "video_provider": "google",
    # 参考图模式，通常保持 image。
    "video_reference_mode": "image",
    # 请求的视频分辨率。
    "video_resolution": "1080p",
    # 负向提示词，留空表示不额外传 negative prompt。
    "video_negative_prompt": "",
    # 单次 HTTP 请求超时时间，单位秒。
    "video_http_timeout_seconds": 180.0,
    # 是否启用成本安全模式。
    # True 时会更保守，减少自动重试和兜底尝试。
    "google_veo_cost_safe_mode": True,
    # 每分钟允许向视频接口发起的最大请求数。
    "google_veo_max_requests_per_minute": 2,
    # 速率限制窗口大小，单位秒。一般保持 60 即可。
    "google_veo_rate_window_seconds": 60.0,
    # 提交视频生成任务时最多尝试多少次。
    "google_veo_submit_max_attempts": 1,
    # 查询远端视频任务状态时最多尝试多少次。
    "google_veo_query_max_attempts": 3,
    # 是否允许在严格参考图失败后继续尝试 prompt-only 兜底。
    "google_veo_allow_prompt_fallbacks": False,
    # 模型可用性预检查缓存时间，单位秒。
    "google_veo_preflight_ttl_seconds": 600.0,
    # 如果发生 quota/billing 类错误，暂停多久再重试，单位秒。
    "google_veo_quota_cooldown_seconds": 1800.0,
    # Veo rejects oversized prompt strings with HTTP 400. Keep generated video prompts compact.
    "google_veo_prompt_max_chars": 950,
}


SUBTITLE_RUNTIME = {
    # 字幕字体名称。
    "subtitle_font_name": "Avenir Next Condensed",
    # 字幕字号。
    "subtitle_font_size": "24",
    # 是否加粗。
    "subtitle_bold": 1,
    # 是否斜体。
    "subtitle_italic": 0,
    # 描边粗细。
    "subtitle_outline": "1.6",
    # 阴影强度。
    "subtitle_shadow": "0.4",
    # 字间距。
    "subtitle_spacing": "0.2",
    # 左右边距。
    "subtitle_margin_l": "44",
    "subtitle_margin_r": "44",
    # 字幕距离底部的边距。
    "subtitle_margin_v": "60",
    # 主色和描边色，保持醒目但不刺眼。
    "subtitle_primary_colour": "&H00F6F1E8",
    "subtitle_outline_colour": "&H80151210",
    "subtitle_back_colour": "&H00000000",
}


TTS_RUNTIME = {
    # TTS 提供商。
    # 可选：edge_tts / macos_say / windows_sapi / silent / auto
    "provider": "edge_tts",
    # Edge TTS 英文神经音色。当前默认用更柔和的 Ava。
    "edge_voice": "en-US-AvaNeural",
    # Edge TTS 语速。负值更慢，正值更快。
    "edge_rate": "-18%",
    # Edge TTS 音高。轻微下调会更沉稳。
    "edge_pitch": "-8Hz",
    # macOS say 的音色名。
    "macos_voice": "Ava",
    # macOS say 语速，单位是每分钟词数附近的系统值。
    "macos_rate": 145,
    # Windows SAPI 可选音色名。留空表示使用系统默认音色。
    "windows_voice": "",
    # Windows SAPI 语速，范围通常在 -10 到 10。
    "windows_rate": 0,
    # 当前 provider 失败后，是否允许退化成静音占位音频。
    "allow_silent_fallback": True,
}
