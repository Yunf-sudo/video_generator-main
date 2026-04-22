## Agent 交接版

`Agent/` 是为同事移交准备的整理版目录。它不再把日常操作参数散落在多个配置脚本里，而是把交接过程中最关键的能力统一收敛到一个配置文件：

- 统一配置
- 素材加载监控
- Meta 只读监控
- 生成命令桥接
- 独立打包的生成管线资源
- 历史素材导入
- 任务历史追踪
- bundle 清单与裁剪审计
- 健康检查
- 前端工作台

这个目录默认是安全模式：

- Meta 监控只读
- 不上传素材
- 不创建广告
- 不修改广告状态

如果后续需要开启真实写操作，请先在正式代码里做单独审批，不建议在交接版里直接放开。

### 目录结构

```text
Agent/
├── app.py
├── README.md
├── requirements.txt
├── bundle/
│   ├── configs/
│   ├── prompts/
│   ├── scripts/
│   ├── src/
│   └── 白底图/
├── config/
│   └── agent_settings.json
├── runtime/
├── scripts/
│   ├── audit_bundle.py
│   ├── build_bundle_manifest.py
│   ├── healthcheck.py
│   ├── import_legacy_assets.py
│   ├── run_generation_bridge.py
│   ├── scan_meta.py
│   └── validate_frontend.py
└── src/
    └── agent/
        ├── __init__.py
        ├── bundle_audit.py
        ├── bundle_manifest.py
        ├── config.py
        ├── dashboard.py
        ├── env.py
        ├── frontend_validation.py
        ├── generation_bridge.py
        ├── healthcheck.py
        ├── history.py
        ├── legacy_import.py
        ├── material_loader.py
        ├── meta_upload.py
        ├── meta_monitor.py
        └── tts_settings.py
```

### 统一配置

唯一参数配置文件是：

- [agent_settings.json](/Users/yf/Downloads/wok/video_v1/Agent/config/agent_settings.json)

这个文件集中管理：

- 工作区路径
- 素材扫描规则
- 生成桥接默认参数
- TTS 配音默认参数
- Meta 上传默认参数
- Meta 只读监控参数
- 广告监控规则
- 历史素材导入规则
- 运行时状态文件路径

说明：

- 非敏感参数全部放在这个文件中
- 敏感信息仍建议放 `.env`，例如 `META_ACCESS_TOKEN`
- 这样可以避免把 token 硬编码进源码
- 日常交接和运行时，优先只改这一个文件

### 当前能力

#### 1. 独立打包生成资源

`Agent/bundle/` 已经打包了一份本地化的生成管线资源，包括：

- 本地脚本
- 本地源码
- 本地配置
- 本地提示词
- 本地参考图

这意味着 `Agent` 的生成入口不再依赖根目录的 `src/`、`scripts/`、`configs/`、`prompts/`。

#### 2. 素材加载监控

素材加载监控会扫描：

- `Agent/bundle/generated/ad_ops_state/materials/*.json`
- `Agent/bundle/generated/deliverables/**/final_video.mp4`
- `Agent/bundle/generated/runs/**/exports/*.mp4`

会自动判断：

- 素材记录是否可解析
- 视频文件是否存在
- 缩略图是否存在
- 是否存在“有视频但没登记到素材记录”的孤立素材

前端会给出：

- 加载成功提醒
- 缩略图缺失提醒
- 视频丢失提醒
- 未登记素材提醒

#### 3. 历史素材导入

为了平稳交接，`Agent` 提供了一个历史素材导入脚本，可以把旧项目的素材记录和关联媒体复制到 `Agent` 本地工作区：

```bash
python Agent/scripts/import_legacy_assets.py
```

导入后：

- `Agent` 前端直接读取本地副本
- 交接时不需要再依赖旧目录里的素材文件
- 可以更安全地做独立验证

#### 4. Meta 只读监控

监控逻辑沿用了你们现有项目和 `facebook.py` 的核心判断方式，但在交接版中只保留只读行为。

监控会读取：

- 广告组预算
- 广告状态
- 花费
- 展现
- CTR
- 3 秒播放率
- 加购
- 购买
- ROAS

并输出：

- 当前活跃广告数
- 暂停备用广告数
- 计划暂停动作
- 计划激活动作

不会执行任何线上写入。

#### 5. 生成桥接

交接版现在已经改为调用 `Agent/bundle/` 内部自己的生成脚本和资源，不再指向旧项目根目录。

默认桥接脚本：

- `Agent/bundle/scripts/run_anywell_campaign.py`

默认桥接参数也统一由 `agent_settings.json` 管理。

现在桥接还会自动注入一份运行时 TTS 覆盖文件：

- `Agent/runtime/runtime_tunables.generated.py`

也就是说，同事在网页端改完音色、语速、音高后，后续执行生成任务时会自动吃到这些设置，不需要手动改 bundle 里的底层配置。

日常入口仍然只需要通过 `Agent/config/agent_settings.json` 管理，不要求同事直接改 bundle 内部文件。

#### 6. TTS 网页调参

前端“生成桥接”页现在已经支持直接调整：

- TTS provider
- Edge 常用音色
- Edge 语速
- Edge 音高
- macOS fallback 音色与语速
- Windows fallback 音色与语速
- 是否允许静音兜底

同时提供 3 个快捷预设：

- 舒缓温柔
- 中性自然
- 清晰有力

保存后会同时完成两件事：

- 更新 `Agent/config/agent_settings.json`
- 生成 `Agent/runtime/runtime_tunables.generated.py`

#### 7. 视频合成与字幕

“视频合成”区现在会单独展示：

- 最终成片是否存在
- 字幕文件是否存在
- 字幕是否已经烧录进最终视频

这次也修正了一个关键问题：

- 即使使用生成视频自带音轨，也会继续按脚本生成 SRT
- 最终合成时仍然会尝试把字幕烧录进成片

也就是说，前端现在能区分：

- 只是有字幕文件
- 还是字幕已经真正进了最终视频

#### 8. Meta 上传

前端“Meta 上传”区现在是手动模式，不自动上传。

你需要显式做两件事：

1. 打开“允许写入 Meta”
2. 点击上传按钮

支持两种模式：

- `仅登记本地素材`
- `直达广告组（创建 PAUSED 广告）`

其中“直达广告组”并不是只把视频放进素材库。它会顺序完成：

- 上传 advideo
- 上传缩略图
- 创建 creative
- 在指定 adset 下创建 `PAUSED` 广告

所以最终会直接出现在广告组里。

同时也支持两类来源：

- 最近生成成片
- 已入库素材

Meta 上传桥接运行时配置会写到：

- `Agent/runtime/ad_ops.generated.py`

#### 9. 任务历史追踪

交接版会把关键动作写入任务历史，包括：

- 刷新 bundle 清单
- 审计 bundle 保留集
- 导入历史素材
- 刷新生成状态
- 执行默认生成任务
- 保存 TTS 配置
- 保存 Meta 上传默认值
- 健康检查
- Meta 只读扫描

这些记录会写入：

- `Agent/runtime/task_history.jsonl`

并且会在前端“任务历史”页签中直接展示。

#### 10. Bundle 清单与裁剪审计

交接版已经加入两层 bundle 管理能力：

- 清单：统计当前 `Agent/bundle/` 内有哪些源码、脚本、配置、提示词和参考图
- 审计：基于保留基线，输出“建议复核”的候选文件列表

当前保留基线文件：

- [bundle_retain.json](/Users/yf/Downloads/wok/video_v1/Agent/config/bundle_retain.json)

### 环境准备

建议在项目根目录执行：

```bash
pip install -r Agent/requirements.txt
```

如果需要 Meta 只读监控，请准备 `.env`：

```env
META_ACCESS_TOKEN=你的token
META_ADS_READ_ONLY=true
```

也可以直接参考：

- [Agent/.env.example](/Users/yf/Downloads/wok/video_v1/Agent/.env.example)

环境加载优先级：

1. `Agent/.env`
2. 项目根目录 `.env`

也就是说，同事接手时优先把配置写进 `Agent/.env`，这样不会污染旧项目环境。

如果没有 token，素材加载监控和健康检查仍可运行，但 Meta 只读扫描会返回阻塞提示。

### 启动方式

#### 前端工作台

```bash
streamlit run Agent/app.py
```

前端包含 7 个区域：

- 概览
- 素材监控
- Meta 监控
- 生成桥接
- 健康检查
- 任务历史
- 配置

其中“生成桥接”页现在支持：

- 调整 TTS 音色、语速、音高
- 一键套用 TTS 音色预设
- 保存 TTS 配置并生成运行时覆盖文件
- 查看字幕是否已烧录进最终视频
- 手动控制是否上传到 Meta
- 直接把成片接到指定广告组并创建 `PAUSED` 广告
- 刷新生成状态
- 执行默认生成任务
- 查看最近成片、日志和概念报告
- 默认按需加载视频预览，避免页面首屏过重

“配置”页现在支持：

- 刷新 bundle 清单
- 审计 bundle 保留集
- 查看建议复核文件

### 验证命令

如果你要做“不生成视频”的前后端联调，直接运行：

```bash
python Agent/scripts/validate_frontend.py
```

这条命令会自动验证：

- 前端 7 个页签是否能正常渲染
- 生成区的 3 个二级页签是否正常渲染
- 素材导入、素材扫描、素材预览开关是否正常
- TTS 网页配置是否能保存并生成运行时覆盖文件
- Meta 上传默认值是否能保存
- Meta 无 token 的阻塞提示是否正常
- Meta 有 token 时的真实只读扫描和健康检查联动是否正常
- 生成桥接“刷新状态”是否正常
- 健康检查是否落盘
- bundle 清单和裁剪审计是否正常
- 任务历史是否记录了关键动作

注意：

- 这个验证不会点击“执行默认生成任务”
- 不会生成新视频
- 不会对 Meta 做任何写操作

验证报告会写到：

- `Agent/runtime/frontend_validation_report.json`
- `Agent/runtime/healthcheck_report.json`
- `Agent/runtime/task_history.jsonl`

### 已完成的实测结果

当前交接版已经完成一轮前端全功能验证，结果如下：

- 前端 7 个页签渲染正常
- 生成区 3 个二级页签渲染正常
- 素材记录：`5`
- 可加载素材：`5`
- 加载失败：`0`
- TTS 网页保存验证通过
- TTS 运行时覆盖文件已生成
- Meta 上传默认值保存验证通过
- Meta 阻塞路径验证通过
- Meta 真实只读扫描验证通过
- 真实只读扫描广告组数：`1`
- 当前计划动作数：`0`
- bundle 总文件数：`150`
- bundle 建议复核文件：`87`

最新验证报告见：

- [frontend_validation_report.json](/Users/yf/Downloads/wok/video_v1/Agent/runtime/frontend_validation_report.json)

#### Meta 只读扫描

```bash
python Agent/scripts/scan_meta.py
```

#### 导入历史素材

```bash
python Agent/scripts/import_legacy_assets.py
```

#### 刷新 bundle 清单

```bash
python Agent/scripts/build_bundle_manifest.py
```

#### 审计 bundle 保留集

```bash
python Agent/scripts/audit_bundle.py
```

#### 健康检查

不带 Meta：

```bash
python Agent/scripts/healthcheck.py
```

带 Meta：

```bash
python Agent/scripts/healthcheck.py --with-meta
```

#### 生成桥接

只打印命令，不执行：

```bash
python Agent/scripts/run_generation_bridge.py
```

执行默认生成命令：

```bash
python Agent/scripts/run_generation_bridge.py --execute
```

### 验证建议

建议交接前按下面顺序验证：

1. 跑健康检查，确认路径和桥接脚本存在
2. 打开前端，确认素材表能看到现有成片
3. 点开素材预览，确认视频能正常加载
4. 在有 token 的前提下执行一次 Meta 只读扫描
5. 核对 `planned_actions` 是否符合预期

### 已完成的本地验证

本次已经完成的验证包括：

- `Agent/` 目录结构创建完成
- 统一配置读取通过
- `Agent/bundle/scripts/run_anywell_campaign.py --help` 可正常启动
- 旧项目素材已成功导入到 `Agent` 本地工作区
- 导入后素材扫描结果：`5` 条素材，`5` 条可加载，`0` 条加载失败
- Meta 只读扫描脚本可运行，并已成功读取广告组 `120244986089430635`
- 生成桥接命令可构造，并且已切到 `Agent/bundle/` 本地资源
- `Agent` 前端已实际启动探活成功
- `bundle` 清单脚本可生成结构清单
- `bundle` 审计脚本已输出保留集与复核候选
- 健康检查脚本可输出报告

说明：

- 本轮没有执行新的远程视频生成任务
- 原因是生成链路会消耗外部模型额度，当前验证重点放在“独立目录、独立资源、独立前端、独立监控、独立导入”是否成立

### 交接注意事项

#### 1. `facebook.py` 不建议继续直接使用

原因：

- 里面曾存在硬编码 token
- 直接运行容易触发线上写操作
- 已经不符合现在“默认只读”的交接要求

#### 2. Token 统一走 `.env`

不要把以下内容写入源码：

- Meta token
- 业务私密落地页参数
- 临时测试账号

#### 3. 运行时状态文件

交接版会自动写入：

- `Agent/runtime/monitor_state.json`
- `Agent/runtime/healthcheck_report.json`
- `Agent/runtime/task_history.jsonl`
- `Agent/runtime/bundle_manifest.json`

这些文件属于运行时产物，不要手工维护。

### 推荐移交说明

如果你要把这个目录交给同事，可以直接给下面这三样：

1. `Agent/` 目录
2. `Agent/.env.example`
3. 这份 README

同事只需要：

1. 安装依赖
2. 填好 token
3. 跑健康检查
4. 打开前端

就能开始接手日常查看和只读监控。
