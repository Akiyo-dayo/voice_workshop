# akiyo_tts

NekroAgent 外部角色语音 TTS 插件：调用云端 TTS 服务（默认 [FishAudio](https://fish.audio/zh)）合成语音，经 OneBot 以语音条发送到 QQ 群/私聊，替代 QQ 协议端自带 TTS。

**核心卖点：直接套用 FishAudio 社区 200 万个第三方训练的角色音色模型**（动漫/游戏角色音），也可以用 10–15 秒参考音频克隆自己的音色。

## 功能

- 🤖 Agent 工具 `发送角色语音`：NA 的 LLM 在合适场景自动合成语音发出
- 🎭 角色音色模型：填 FishAudio 模型页 URL 末段的 ID 即可换角色音
- 🔧 群内命令动态切换模型/音色（无需重启）
- 🛡️ 账单护栏：单次字符上限 + 调用冷却

## 安装

NA 插件管理中添加仓库：`https://github.com/Akiyo-dayo/akiyo_tts`

## 配置

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `API_BASE` | `https://api.fish.audio/v1` | TTS API 基础地址 |
| `API_KEY` | （空） | FishAudio API Key（`sk-fish-...`） |
| `PROVIDER` | `fishaudio` | 服务提供商（`openai_compatible` 预留） |
| `DEFAULT_MODEL` | `s2.1-pro` | 默认模型；`s2.1-pro-free` 为免费 fair-use 档 |
| `DEFAULT_REFERENCE_ID` | （空） | 角色音色模型 ID，见下 |
| `PROXY` | （空） | 代理地址，如 `http://127.0.0.1:7890` |
| `MAX_CHARS` | `300` | 单次合成字符上限（超出截断） |
| `COOLDOWN_SECONDS` | `10` | 两次合成的最小间隔 |

### 怎么找角色音色模型 ID

1. 打开 <https://fish.audio/zh/models> 搜索角色名（如「鸣潮」「芙宁娜」），或直接用接口：
   `https://api.fish.audio/model?page_number=1&page_size=20&title=<关键词>`
2. 选中模型的 `_id` 即 `reference_id`
3. 群内发 `/tts_set_voice <ID>`，或填进配置 `DEFAULT_REFERENCE_ID`

> 已实测可用：鸣潮-漂泊者 `51a1f823b33b4bdb9440222a30f31748`、鸣潮散华 `3de2b456b20e43ee970b3c4fe102632d`（免费模型 + reference_id 出音正常）

## 命令

| 命令 | 说明 |
|---|---|
| `/tts_set_model <模型>` | 切换模型，如 `/tts_set_model s2.1-pro-free` |
| `/tts_set_voice <ID\|none>` | 切换/清除角色音色 |
| `/tts_status` | 查看当前配置 |

## 定价参考（FishAudio）

- 付费模型 s2.1-pro：$15 / 百万字节（1 汉字 = 3 字节，30 字一句 ≈ ¥0.01）
- 免费模型 s2.1-pro-free：fair-use 限额，效果同 pro

## 许可

MIT
