# 声色工坊

NekroAgent 外部角色语音 TTS 插件：调用云端 Fish Audio 合成语音，经 OneBot 以语音条发送到 QQ 群/私聊。

插件显示名：**声色工坊**
模块名：`voice_workshop`

## 功能

- 🤖 Agent 工具 `FishAudio发送角色语音`：NA 的 LLM 在合适场景自动合成语音发出
- 🎭 角色音色模型：填 Fish Audio 音色页面 URL 中的 `voiceId` UUID 即可换角色音色
- 🔧 群内命令动态切换模型/音色（无需重启）
- 🛡️ 账单护栏：单次字符上限 + 调用冷却

## 安装

NA 插件管理中添加仓库：`https://github.com/Akiyo-dayo/voice_workshop`

## 配置

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `API_BASE` | `https://fishaudio.org/api/open/v1` | Fish Audio Open API 基础地址 |
| `API_KEY` | （空） | Fish Audio Open API Key |
| `PROVIDER` | `fishaudio` | 服务提供商（`openai_compatible` 预留） |
| `DEFAULT_MODEL` | `fishaudio-s21pro-flash` | 默认模型 |
| `DEFAULT_REFERENCE_ID` | （空） | 角色音色 UUID，来自 Fish Audio 页面 URL 的 `voiceId` 参数 |
| `PROXY` | （空） | 代理地址，如 `http://127.0.0.1:7890` |
| `MAX_CHARS` | `300` | 单次合成字符上限（超出截断） |
| `COOLDOWN_SECONDS` | `10` | 两次合成的最小间隔 |

### 怎么找角色音色 UUID

打开 Fish Audio 角色音色页面，复制 URL 中 `voiceId` 参数的值。例如：

```text
https://fishaudio.org/zh/app/text-to-speech?voiceId=0c8b9dbf-932a-48c3-845a-109cfe5beffd
```

对应的 `DEFAULT_REFERENCE_ID` 就是：

```text
0c8b9dbf-932a-48c3-845a-109cfe5beffd
```

也可以调用 Open API：
`https://fishaudio.org/api/open/v1/voices`，返回数据中的 `voiceId` 即为 UUID。

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
