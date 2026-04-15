# Video Generator 视频生成项目

这是一个面向产品短视频广告的 AI 生成工作流。当前交接版本已针对 AnyWell 轮椅情感营销场景配置好：产品外观参考来自本地 `白底图/` 文件夹，系统会先生成脚本和分镜图，再通过 302.ai 的 Veo 图生视频接口生成竖版短视频，最后合成旁白、字幕和最终 MP4。

## 项目能力

- 生成广告脚本、标题、描述和分镜图。
- 使用 `白底图/` 中的产品图片保持轮椅外观一致。
- 通过 302.ai `veo3-pro-frames` 生成 `9:16` 竖版视频片段。
- 自动合成旁白、字幕和最终成片。
- 交接输出保持清爽：`outputs/final/` 只放最终视频。

## 目录结构

```text
.
|-- app.py                         # Streamlit 网页端入口
|-- src/                           # 核心业务代码
|-- scripts/                       # CLI 运行脚本和交付打包脚本
|-- configs/                       # 活动配置文件
|-- prompts/                       # 活动提示词和合规约束
|-- prompt_overrides.example.json  # 提示词覆盖示例
|-- prompt_overrides.json          # 本地提示词覆盖配置
|-- .env.example                   # 环境变量模板
|-- requirements.txt               # Python 依赖
|-- 白底图/                         # 产品白底参考图，本地保留，不提交
|-- generated/                     # 运行产物、缓存、历史归档
|-- logs/                          # 运行日志
|-- reports/                       # QA 报告和抽帧检查图
`-- outputs/final/                 # 最终交付视频
    |-- captioned/                 # 字幕版
    `-- clean/                     # 无字幕版
```

`generated/`、`logs/`、`reports/`、`outputs/`、`.env` 和大体积媒体文件默认不提交到 git。需要交接这些文件时，请单独打包发送。

## 环境准备

建议使用 Python 3.11 或更高版本。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

项目需要 `ffmpeg` 和 `ffprobe` 做视频合成、裁切和时长检测。如果系统没有安装，代码会尝试使用 `imageio-ffmpeg` 兜底，但生产环境建议安装系统版 `ffmpeg`。

复制环境变量模板：

```powershell
Copy-Item .env.example .env
```

然后在 `.env` 中填写真实密钥。不要把 `.env` 提交到 git。

当前 AnyWell 流程至少需要这些配置：

```text
JENIYA_API_TOKEN=你的中转站密钥
V302_API_KEY=你的302.ai密钥
VIDEO_PROVIDER=302ai
VIDEO_MODEL=veo3-pro-frames
VIDEO_302_SUBMIT_URL=https://api.302.ai/302/submit/veo3-pro-frames
VIDEO_302_QUERY_URL=https://api.302.ai/302/submit/veo3-pro-frames
VIDEO_302_UPLOAD_URL=https://api.302.ai/302/upload-file
VIDEO_GENERATE_AUDIO=false
```

说明：

- `JENIYA_API_TOKEN` 用于脚本、分镜图、旁白等环节。
- `V302_API_KEY` 用于 302.ai 视频生成和图片上传。
- `VIDEO_GENERATE_AUDIO=false` 代表最终合成时使用项目自己的旁白音轨；Veo 原片音轨不会作为最终广告音轨使用。

## 产品参考图

产品参考图放在：

```text
白底图/
```

当前 AnyWell 配置优先使用侧面或前侧产品图作为外观参考。白底图只用于识别产品结构和外观，不应该作为白底产品图、棚拍图或闪帧出现在最终广告里。

## 网页端使用

启动 Streamlit 网页端：

```powershell
streamlit run app.py
```

网页端适合逐步测试脚本、分镜、视频片段和最终合成。

## CLI 生成 AnyWell 视频

推荐把中间产物输出到 `generated/` 下，不要直接写入 `outputs/final/`。

```powershell
python scripts/run_anywell_campaign.py `
  --config configs/anywell_freedom_campaign.json `
  --prompt prompts/anywell_freedom_campaign.md `
  --output-root generated/deliverables/anywell_campaign `
  --log-path logs/anywell_campaign.log `
  --summary-path reports/anywell_campaign_summary.md `
  --max-concepts 1
```

生成完成后，概念目录里会包含脚本、分镜图、视频片段、旁白、字幕、合成视频和报告。这些都属于运行中间产物，不应该直接放进最终交付目录。

## 打包最终视频

生成成功后，把最终 MP4 复制到清爽的交付目录：

```powershell
python scripts/package_final_outputs.py generated/deliverables/anywell_campaign/concept_a `
  --slug anywell_nature_within_reach
```

交付目录结构应为：

```text
outputs/final/
|-- captioned/
|   `-- anywell_nature_within_reach_captioned.mp4
`-- clean/
    `-- anywell_nature_within_reach_clean.mp4
```

使用建议：

- `clean/`：无字幕版，适合后续在广告平台或剪辑工具里重新加字幕。
- `captioned/`：烧录字幕版，适合需要直接发布带字幕视频的场景。

## 当前交付视频

当前已经整理好的最终视频位于：

```text
outputs/final/captioned/anywell_nature_within_reach_captioned.mp4
outputs/final/clean/anywell_nature_within_reach_clean.mp4
```

视频规格：

- 格式：MP4
- 画幅：`9:16`
- 分辨率：`1080x1920`
- 时长：约 16 秒
- 视频模型：`veo3-pro-frames`
- 视频服务：302.ai

## AnyWell 质量和合规约束

当前配置和提示词会强制约束以下规则：

- 不引用、不复刻、不二创真实客户视频。
- 使用匿名欧美市场人物和通用家庭/户外场景。
- 轮椅由乘坐者自己操作时，右手必须在右侧遥杆上。
- 如果右手不在遥杆上，必须明显有人从后方推行。
- 避免单一后视角或后方跟拍视角。
- 不展示轮椅后下方外置电池包。
- 不展示折叠、半折叠、收纳形态或折叠演示。
- 不把白底产品参考图插入广告视频。

## 常见问题

### 302.ai requires a public HTTP(S) input image URL

302.ai 视频接口需要公网图片 URL。当前代码会优先把分镜图上传到 `VIDEO_302_UPLOAD_URL`。请检查：

- `V302_API_KEY` 是否有效。
- `VIDEO_302_UPLOAD_URL` 是否为 `https://api.302.ai/302/upload-file`。

RustFS 只是兜底方案。如果 RustFS 返回 `file://` 本地地址，302.ai 无法使用。

### 下载生成视频时出现 HTTP Error 403

下载器会在普通下载失败后，自动带 302.ai Bearer 鉴权重试。请确认 `V302_API_KEY` 没有过期或被限流。

### AUDIO_GENERATION_FILTERED

不要在视频提示词里写“不要生成音频、对白、音效”等过强的音频禁令。Veo 端可能因此触发音频过滤。最终合成阶段会去掉或替换原片音轨，所以提示词不需要强行禁止音频。

### 最终视频不是严格 15.0 秒

Veo 原片通常会返回 8 秒视频。合成阶段会根据旁白长度和场景时长做裁切/适配。如果需要严格 15.0 秒，请缩短旁白文本，或在合成后再做精确裁切。

## 交接注意事项

- `.env` 包含真实密钥，只能本地保留，不要提交。
- `白底图/` 包含大体积产品参考图，默认不提交。
- `outputs/final/` 只放最终可交付 MP4。
- 历史中间输出已经移动到 `generated/archive/`，没有删除。
- 原始客户上传视频如果存在，应归档在 `generated/archive/source_media/`，不要用于生成广告素材。
