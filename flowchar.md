graph TD
    classDef input fill:#e1f5fe,stroke:#03a9f4,stroke-width:2px;
    classDef ai_text fill:#f3e5f5,stroke:#9c27b0,stroke-width:2px;
    classDef ai_visual fill:#e8f5e9,stroke:#4caf50,stroke-width:2px;
    classDef ai_audio fill:#fff9c4,stroke:#fbc02d,stroke-width:2px;
    classDef media fill:#fff3e0,stroke:#ff9800,stroke-width:2px;
    classDef output fill:#ffebee,stroke:#f44336,stroke-width:3px;

    subgraph 阶段一：业务需求与配置
        A[产品简报输入 Brief<br/>(目标, 卖点, 受众, 风格)]:::input --> B(状态管理器<br/>State & Workspace)
        K[批量配置文件<br/>anywell_campaign.json]:::input -.->|静默批处理| B
    end

    subgraph 阶段二：脚本与分镜引擎
        B --> |请求 Gemini 2.5 Flash| C[生成结构化广告脚本<br/>Script JSON]:::ai_text
        C --> |提取场景画面描述 & 产品特征| D[生成静态分镜图<br/>Storyboard Images]:::ai_visual
        C -.-> |提取旁白与对白文本| E[生成配音音频<br/>TTS Audio]:::ai_audio
    end

    subgraph 阶段三：视频动态化与对齐
        E --> |分析音频时长/ASR| E1[生成字幕时间轴<br/>SRT Asset]:::ai_audio
        D --> |图生视频请求 + 连续性锚点| F[生成远端动态片段<br/>Google Veo Video Clips]:::ai_visual
        F -.-> |若远端配额耗尽或降级| F1[生成本地占位片段<br/>FFmpeg Zoom/Pan]:::media
        
        E1 --> |传递精确时长映射| G[片段时长重定时<br/>Video Retiming]:::media
        F --> G
        F1 --> G
    end

    subgraph 阶段四：视音频总装线 (Media Pipeline)
        G --> H[视频流拼接与转场添加<br/>Concat & Xfade]:::media
        E1 --> |挂载音频流| H
        H --> I[字幕滤镜烧录<br/>Burn-in Subtitles]:::media
        E1 --> |挂载字幕流| I
        I --> J(((导出最终广告成片<br/>Final MP4 Delivery))):::output
    end
