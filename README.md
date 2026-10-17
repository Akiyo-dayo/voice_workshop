# 声色工坊

NekroAgent 角色语音插件，使用 Fish Audio Open API，支持群聊/私聊语音及 NA 消息历史。插件 ID 保持 `Akiyo_dayo.voice_workshop`。

## 完整台词与可靠性

- 真正异步 HTTP，单段超时 + 整次任务总时限；不使用后台同步线程继续占用连接。
- 超过字符上限明确报错，**不静默截断**。保留全部文字并按标点优先分段，每段一条语音。
- 全部段合成和校验成功后才开始发送；发送中失败报告已确认发送的段数，不能盲目整段重发。
- 校验响应类型、传输长度和 MP3 帧完整性；这不等于 ASR 全文识别，无法保证上游模型绝不漏字。
- 每实例只允许一个调用执行；其他调用返回忙碌而非无限排队。不自动重试付费合成。

## 配置（NA → 插件 → 声色工坊）

| 配置 | 默认 | 说明 |
|---|---|---|
| API_BASE | https://fishaudio.org/api/open/v1 | 保持现有协议，不自动迁移 v3 |
| API_KEY | 空 | 服务密钥 |
| PROVIDER | fishaudio | 目前仅实现此提供商 |
| DEFAULT_MODEL | fishaudio-s21pro-flash | 不自动更换模型 |
| DEFAULT_REFERENCE_ID | 空 | fishaudio.org 音色链接 voiceId UUID |
| PROXY | 空 | 显式代理；空时不读取环境代理 |
| MAX_CHARS | 300 | 单次台词上限，1–3000；超限报错 |
| SEGMENT_CHARS | 100 | 每段20–500字符，优先句末分段 |
| SPLIT_SENTENCES | true | 逐句合成，降低上游漏读后文风险；补齐各段句末，末尾省略号改完整句号 |
| MAX_SEGMENTS | 6 | 最多语音段数，超限报错不丢后文 |
| COOLDOWN_SECONDS | 10 | 实例级调用间隔 |
| SPEED | 1 | 0.5–2，语速不是音高 |
| VOLUME | 0 | -20–20 dB |
| STABILITY | 1 | 0.5–1.5，需试听而非越高越好 |
| SIMILARITY | 1 | 0.5–1.5，音色相似度 |
| LANGUAGE | zh | 语言提示，留空自动识别 |
| DEFAULT_STYLE | neutral | neutral / excited / whisper |
| ENABLE_STYLE_TAGS | true | Fish S2 系列使用原生演绎标签；若被服务读出可关闭 |
| ROLE_GUIDANCE | 自然口语、保持角色、结尾完整 | 注入给Agent的演绎要求，不作为台词朗读 |
| ALLOW_AGENT_OVERRIDES | true | 允许工具参数仅覆盖本次；不会修改默认值 |
| REQUEST_TIMEOUT | 25 | 每段HTTP超时秒数，连接最多8秒 |
| TOTAL_TIMEOUT | 85 | 冷却、全部合成及发送总预算，最多100秒 |

全部默认设置为**实例级**，影响该机器人所有聊天。模型、音色、密钥、端点与费用限制不对 Agent 开放覆盖。

## Agent 调用

旧的 `akiyo_tts(content)` 继续兼容。可选参数省略时使用用户配置：

```python
akiyo_tts("早上好！今天也要元气满满哦。", speed=1.05, style="excited")
akiyo_tts("夜深了，晚安。", speed=0.95, style="whisper", stability=1.05, similarity=1.0)
```

工具参数：`content, speed, volume, stability, similarity, language, style`。

`content` 仅包含实际完整台词，不写动作、Markdown、括号式导演说明或内联标签。角色引导注入 Agent，帮助其根据当前人设和上下文组织台词、标点与风格。

Fish S2 原生文档确认了 `[excited]` / `[whisper]` 标签；1.3扩展实验性情绪映射，详情见下。对Fish不发送未声明支持的pitch或instruction，不承诺标签的实际听感。

## 1.3 演绎与模型适配

演绎分为 `emotion`（情绪/社交语气）、`delivery`（发声方式）、`intensity`（软强度）、`instruction`（独立导演指令）。不是每个模型都支持全部维度；不支持会明确报错，不把指令当台词朗读。

- 情绪：neutral、happy、sad、angry、fearful、surprised、disgusted、excited、gentle、comforting、shy、sarcastic、impatient、hurt、disappointed。
- 发声：normal、whisper、crying、sobbing、choked、laughing、shouting、tired。
- 组合示例：克制悲伤 `sad+normal`，愤怒委屈 `angry+choked`，濒临崩溃 `sad+sobbing`。这是引导意图，不保证模型实现相同听感。
- Fish S2：原生标签；已核验文档的excited/whisper可直接用，其他映射属于实验，须开启 `ALLOW_EXPERIMENTAL_ACTING`。Fish强度必须省略（.5），不支持独立instruction。
- MiniMax：仅基础emotion；哭腔/哽咽/强度/自由导演指令明确不支持，不假装生效。
- Qwen Audio 3.0指令型：通过独立instruction表达组合、软强度。Qwen3 TTS Flash不支持同样的导演控制，仅自然朗读。
- 跨引擎需管理员显式配置v3、兼容音色和输出格式；v3每次先读取能力目录并核验voice.modelIds。不会自动更换线上默认。
- MP3与PCM WAV均检查结构完整性；Qwen3仅WAV。`/tts_set_model`核验可用性、格式和当前音色兼容。

新增NA配置：`DEFAULT_EMOTION`、`DEFAULT_DELIVERY`、`DEFAULT_INTENSITY`、`DEFAULT_INSTRUCTION`、`ALLOWED_EMOTIONS`、`ALLOWED_DELIVERIES`、`ALLOW_EXPERIMENTAL_ACTING`、`OUTPUT_FORMAT`。实验开关默认关闭；XYJ本次按用户授权开启以使用扩展演绎，其余原有默认保持。

```python
# Fish S2，需允许实验标签；台词与导演标签由插件分离
akiyo_tts("你为什么不告诉我？", emotion="angry", delivery="choked")
# 指令型模型，须管理员选择兼容模型/音色与v3
akiyo_tts("我没事。真的，你不用担心。", emotion="hurt", delivery="choked", intensity=0.7, instruction="强忍眼泪，保持轻声，不要喊叫")
```

旧style继续兼容，但不能与emotion/delivery同时传。Agent不得自主换模型、音色或凭据。许可范围不等于后端支持范围，也不代表已听感验收。此服务由Kitta Audio独立运营，并非Fish官方服务。

## 命令

- `/tts_set_model fishaudio-s21pro-flash`：管理员设置实例模型，须自己确认音色兼容。
- `/tts_set_voice <UUID或fishaudio.org音色链接|none>`：设置实例音色。
- `/tts_status`：管理员查看默认参数与限制。

设置失败不会回复“已切换”。调整调音默认值请使用 NA 插件配置面板。

## 验证

`python -m pytest tests -q`。测试不需要 NekroAgent 安装，使用框架桩和 HTTP mock，不发真实QQ消息、不调用付费接口。

## 参考

- [当前服务 HTTP TTS 文档](https://docs.fishaudio.org/zh/docs/api-reference/text-to-speech/sync-http)
- [当前服务公开能力目录](https://fishaudio.org/api/open/v3/speech/tts/capabilities)
- [Fish S2 原生演绎标签说明](https://github.com/fishaudio/fish-speech#fish-audio-s2-pro)

MIT
