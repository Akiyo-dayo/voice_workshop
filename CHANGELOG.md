# 更新日志

## [1.3.1] - 2026-10-17

- 新增QQ尾音保护：默认请求PCM WAV，在原始采样后追加1秒静音，避免QQ播放结束时截掉最后字音；不改台词、音色或有效采样。
- NA配置开放TAIL_SILENCE_SECONDS（0–3秒，0关闭）；启用时输出WAV，关闭后恢复OUTPUT_FORMAT，模型不支持WAV时明确报错。
- 三条真实问题音频通过PCM WAV＋1秒静音对照发送，两位接收端均认可改善；此前仅网关时长取整修复不足以覆盖这类QQ播放问题。
- PCM8/16/24位样本保留及尾部静音测试，保留异步取消与总预算。该保护不承诺补回上游未生成的字音。

## [1.3.0] - 2026-10-17

- 拆分情绪、发声方式、软强度和独立导演指令，增加负面情绪与复合演绎。
- 明确Fish实验标签与许可开关；不虚构精确强度或全情绪覆盖。
- v3按能力目录和音色modelIds适配Fish/MiniMax/Qwen，旧v1及旧style兼容。
- 增加WAV结构检查与发送，支持仅WAV模型；管理员模型切换先验证兼容。
- 用户NA配置开放默认演绎与Agent许可范围，保留异步/全文/超时安全措施。

## [1.2.0] - 2026-10-17

- 真异步 HTTP、可取消总超时和实例有界并发，替代阻塞请求/线程临时热修。
- 移除静默300字截断，完整台词按句分段；所有段合成校验完成后才发送。
- 校验响应类型、传输长度及MP3帧，明确报告部分发送和超时，不自动重试付费合成。
- NA配置开放语速、音量、稳定度、相似度、语言、演绎风格、角色引导及限制。
- Agent工具新增单次可选调音参数，配置可禁用覆盖；保留旧调用兼容。
- 增加角色演绎提示注入和受控Fish S2风格标签，不冒充音高控制或未支持的instruction。
- 群/私聊统一路径失败回退；修复保存失败误报、旧模型/音色指引和日志占位符。

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
