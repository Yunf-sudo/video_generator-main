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
}


SUBTITLE_RUNTIME = {
    # 字幕字体名称。
    "subtitle_font_name": "Cambria",
    # 字幕字号。
    "subtitle_font_size": "13",
    # 字幕距离底部的边距。
    "subtitle_margin_v": "52",
}
