# Video Generator 视频生成项目

这是一个面向产品短视频广告的 AI 生成工作流。当前交接版本已针对 AnyWell 轮椅情感营销场景完成配置：产品外观参考来自本地 `白底图/` 文件夹，系统会先生成脚本和分镜图，再通过 302.ai 的 Veo 图生视频接口生成竖版短视频，最后合成旁白、字幕并输出最终 MP4。

## 项目能力

- 生成广告脚本、标题、描述和分镜图。
- 使用 `白底图/` 中的产品图片保持轮椅外观一致。
- 通过 302.ai `veo3-pro-frames` 生成 `9:16` 竖版视频片段。
- 自动合成旁白、字幕和最终成片。
- 交接输出保持清晰：`outputs/final/` 只放最终视频。

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

`generated/`、`logs/`、`reports/`、`outputs/`、`.env` 和大体积媒体文件默认不会提交到 git。需要交接这些文件时，请单独打包发送。

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
V302_API_KEY=你的 302.ai 密钥
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
- `VIDEO_GENERATE_AUDIO=false` 表示最终合成时使用项目自己的旁白音轨；Veo 原片音轨不会作为最终广告音轨使用。

## 产品参考图

产品参考图放在：

```text
白底图/
```

当前 AnyWell 配置优先使用侧面或前侧产品图作为外观参考。白底图只用于识别产品结构和外观，不应该作为白底产品图、棚拍图或闪帧出现在最终广告里。

## 程序运行方式

项目有两个主要运行入口：网页端适合人工检查和逐步调整，CLI 适合在配置稳定后跑完整流程。

### 网页端运行

在项目根目录启动 Streamlit：

```powershell
streamlit run app.py
```

启动后，浏览器会打开本地工作台。如果没有自动打开，请复制终端里的 Local URL 到浏览器。根目录的 `app.py` 是启动入口，实际界面逻辑在 `src/app.py`。

### CLI 一键生成 AnyWell 视频

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

常用参数说明：

- `--config`：活动配置，控制产品、受众、卖点、场景和时长等结构化信息。
- `--prompt`：活动提示词，控制整体创意方向、视觉约束和合规要求。
- `--output-root`：中间产物目录，建议使用 `generated/deliverables/...`。
- `--log-path`：运行日志路径，便于排查 API、下载和合成问题。
- `--summary-path`：生成结果摘要路径。
- `--max-concepts`：本次生成的概念数量。当前交接建议先设为 `1`，确认质量后再增加。

## 网页端交互方式

网页端按从左到右的 6 个页签推进：

1. 产品简报：填写产品名称、目标市场、目标受众、核心卖点、使用场景、风格语气、画幅和参考图。保存简报后会创建新的 Run，并清空下游旧结果。
2. 广告脚本：点击“生成广告脚本”创建分场景脚本。若脚本不符合预期，可在“脚本修改意见”中输入反馈，再点击“应用脚本修改”。
3. 分镜图：点击“生成全部分镜图”。每张分镜都可以单独展开“修改这个分镜”，输入修改意见后重新生成对应画面。
4. 视频片段：点击“批量提交远端任务”提交到 302.ai，随后用“刷新远端状态”检查结果；也可以直接点击“提交并等待全部完成”。
5. 配音字幕：依次生成标题描述、配音和字幕。最终成片会使用项目自己的旁白音轨，不依赖 Veo 原片音频。
6. 导出成片：当前所有分镜对应的视频片段都生成完成后，直接点击“拼接并导出完整视频”。如果还没有生成配音和字幕，系统会在导出前自动补齐，再一起合成进最终视频。只有在确实还要进剪映微调时，才使用可选的“上传片段并导入剪映”。

左侧栏会显示当前 Run、输出目录、脚本场景数、分镜数量、远端片段数量和当前模型。侧栏顶部的“历史记录”可以加载最近 20 个 Run；生成流程启动后，网页地址会自动带上 `?run_id=...`，刷新页面时会按这个 Run 自动恢复脚本、分镜、视频片段、配音字幕和最终成片状态。侧栏的“一键生成正式版”会从简报一路跑到正式成片，适合配置已经确认后的完整测试。

说明：`上传片段并导入剪映` 依赖一个单独运行的本地剪映桥接服务，默认读取 `CAPCUT_API_URL`，当前默认值为 `http://localhost:9000`。这个服务不包含在本仓库中；如果该地址没有服务监听，网页端会直接提示“剪映桥接服务未启动或不可达”，按钮也会禁用。

## 打包最终视频

生成成功后，把最终 MP4 复制到干净的交付目录：

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

## 修改方式

常见修改入口如下：

- 修改产品外观参考：替换 `白底图/` 下的产品图片，或在网页端“产品简报”页签上传新的参考图。参考图应只用于产品外观识别，不应作为广告画面直接出现。
- 修改网页端默认参数：优先修改 `configs/streamlit_app_defaults.py`。这个文件带中文注释，适合统一调整产品名称、受众、卖点、场景、提示词补充项、语言和画幅等默认值。
- 修改运行时调参：优先修改 `configs/runtime_tunables/runtime_settings.py`。这里集中管理模型名、每分钟请求次数、超时、重试次数、字幕样式、是否保留生成视频音轨等底层参数。
- 修改基础提示词模板：优先修改 `configs/prompt_inputs/prompt_templates.py`。这里集中管理脚本生成、分镜图生成、视频生成、标题描述生成、翻译步骤、prompt 组装器等基础提示词文本。
- 修改广告业务链路：优先修改 `configs/ad_ops/material_flow_settings.py`。这里集中管理 Meta 暂存池库存阈值、Meta 预上架参数、广告监控规则、频繁下架告警阈值等。
- 修改受众、卖点、场景数量和目标时长：优先修改 `configs/anywell_freedom_campaign.json`。如果只是临时测试，也可以直接在网页端“产品简报”里改。
- 修改整体创意方向和合规约束：修改 `prompts/anywell_freedom_campaign.md`。这里适合写品牌调性、禁用内容、镜头偏好和跨场景一致性要求。
- 修改局部强约束：修改 `prompt_overrides.json`。这里适合放容易被模型忽略的硬性要求，例如不露出后下方电池、不展示折叠形态、不插入白底图闪帧。
- 修改视频模型、接口地址或密钥：修改 `.env`。真实密钥只能保留在本地，不要提交到仓库。
- 修改最终交付文件名：运行 `scripts/package_final_outputs.py` 时调整 `--slug` 参数。
- 修改网页端交互逻辑：主要改 `src/app.py`。根目录 `app.py` 只是 Streamlit 启动入口。
- 修改中文交互转英文模型输入的翻译逻辑：主要改 `src/input_translation.py`，提示词模板在 `configs/prompt_inputs/prompt_templates.py`。
- 修改 Meta 暂存池状态、Meta 预上架和广告监控主链路：主要看 `src/meta_pool_state.py`、`src/meta_ads_service.py`、`src/ad_management_agent.py`。

## 广告主链路

当前项目已经补上一条可落地的广告业务骨架：

1. 生成正式成片
2. 直接上传到 Meta 暂存池
3. 广告默认保持 `PAUSED`
4. 人工审核素材
5. 广告管理 Agent 自动按库存与规则启停广告、归档成功/失败素材，并输出告警

相关入口：

- `scripts/register_latest_run_material.py`
  - 把最近一个或指定 run 直接上传到 Meta 暂存池，并保持关停
- `scripts/review_material.py`
  - 更新素材审核状态，例如标记为 `approved`
- `scripts/import_backup_material.py`
  - 把手工备用视频直接上传到 Meta 暂存池，并保持关停
- `scripts/run_ad_management_agent.py`
  - 单次或循环运行广告管理 Agent

工作台里在“广告运营”页签下会集中处理这些操作：

- `当前 Run 上传到 Meta 暂存池（关停）`
- 修改视频提交、查询、下载逻辑：主要改 `src/generate_video_tools.py`。
- 修改最终合成、字幕和音轨处理：主要改 `src/media_pipeline.py`。
- 修改 AnyWell 批量生成流程：主要改 `src/anywell_campaign.py` 和 `scripts/run_anywell_campaign.py`。

修改后建议先做基础检查：

```powershell
python -m json.tool configs/anywell_freedom_campaign.json
python -m py_compile app.py src/app.py src/generate_video_tools.py src/media_pipeline.py src/anywell_campaign.py scripts/run_anywell_campaign.py scripts/package_final_outputs.py
```

## AnyWell 质量和合规约束

当前配置和提示词会强制约束以下规则：

- 不引用、不复刻、不对真实客户视频进行二次创作。
- 使用面向欧美市场的匿名明显肥胖/heavyset/plus-size 老年人物和通用家庭/户外场景。
- 保持同一位明显肥胖长者的体型、服装、姿态和身份一致，画面应体现宽厚躯干、圆腹、较粗胳膊和腿，以及明显占满轮椅座椅的坐姿；不把体型处理成戏谑或病态化表达。
- 轮椅由乘坐者自己操作时，右手必须在右侧摇杆上。
- 如果右手不在摇杆上，必须明显有人从后方推行。
- 轮椅后方上部的成对推把必须清楚可见：两根黑色竖管从靠背后上方伸出，顶部带向后弯曲的黑色握把；不能因此露出后下方电池区域。
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
