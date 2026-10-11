# 更新日志

## [1.1.0] - 2026-10-12

### 变更：正式更名为「声色工坊」并迁移模块标识

- 插件正式名称从「外部角色语音 TTS」调整为 **声色工坊**。
- Python 模块名从 `akiyo_tts` 迁移为 `voice_workshop`。
- 插件包目录从 `akiyo_tts/` 迁移为 `voice_workshop/`。
- NekroAgent 配置键从 `Akiyo_dayo.akiyo_tts` 迁移为 `Akiyo_dayo.voice_workshop`。
- 插件启用项同步迁移为 `Akiyo_dayo.voice_workshop`。
- 现有 API Key、Fish Audio API 地址、模型、音色 UUID 和其他配置保持不变。
- 仓库更名为 `voice_workshop`，后续安装地址统一使用：
  `https://github.com/Akiyo-dayo/voice_workshop`

### Fish Audio

- 迁移至 Fish Audio Open API：`https://fishaudio.org/api/open/v1/speech/tts`。
- 使用 `voiceId` UUID 和 `modelId` 请求字段。
- 支持私聊和群聊语音发送。
- 私聊本地文件发送失败时自动回退到 `base64://` 语音段重试。

### NekroAgent 集成

- 语音发送成功后同步写入 NekroAgent 消息历史，使 NA WebUI 可以显示语音记录。
- Agent 工具名称统一为 `FishAudio发送角色语音`。
- 保持与原版 NekroAgent v2.3.3 和 Akiyo 版本的现有兼容适配。
