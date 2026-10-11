"""voice_workshop - 声色工坊

调用云端 Fish Audio 合成角色语音，经 OneBot 以语音消息发出，
支持群聊和私聊，并将发送记录同步到 NekroAgent 历史。

仓库: https://github.com/Akiyo-dayo/voice_workshop
"""

import asyncio
import base64
import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

# XYJ's upstream image does not ship third-party plugin dependencies.  Keep
# the dependency in the persistent plugin data directory and prefer it when
# available; normal installations continue to use the system package.
_vendor_dir = Path(__file__).with_name("vendor")
if _vendor_dir.is_dir():
    sys.path.insert(0, str(_vendor_dir))

import requests
from nonebot import on_command, get_bot
from nonebot.adapters import Bot, Message
from nonebot.adapters.onebot.v11 import MessageEvent, MessageSegment
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from pydantic import Field

from nekro_agent.adapters.onebot_v11.matchers.command import command_guard
from nekro_agent.api.schemas import AgentCtx
from nekro_agent.core import logger
from nekro_agent.schemas.agent_message import AgentMessageSegment, AgentMessageSegmentType
from nekro_agent.services.message_service import message_service
from nekro_agent.services.plugin.base import (
    ConfigBase,
    NekroPlugin,
    SandboxMethodType,
)
from nekro_agent.services.plugin.manager import save_plugin_config

plugin = NekroPlugin(
    name="声色工坊",
    module_name="voice_workshop",
    description="调用 FishAudio 等外部 TTS 服务合成角色语音并发送到聊天，支持社区训练音色模型",
    version="1.1.0",
    author="Akiyo_dayo",
    url="https://github.com/Akiyo-dayo/voice_workshop",
)


@plugin.mount_config()
class TTSConfig(ConfigBase):
    """语音合成配置"""

    API_BASE: str = Field(
        default="https://fishaudio.org/api/open/v1",
        title="API Base URL",
        description="Fish Audio Open API 基础地址：https://fishaudio.org/api/open/v1",
    )
    API_KEY: str = Field(
        default="",
        title="API Key",
        description="TTS 服务的访问密钥（FishAudio 的 sk-fish-...）",
    )
    PROVIDER: str = Field(
        default="fishaudio",
        title="服务提供商",
        description="fishaudio（REST）/ openai_compatible（MiMo、百炼等 OpenAI 兼容接口，预留）",
    )
    DEFAULT_MODEL: str = Field(
        default="fishaudio-s21pro-flash",
        title="默认模型",
        description="默认 TTS 模型。Fish Audio Open API v1 可用 fishaudio-s21pro-flash 等模型",
    )
    DEFAULT_REFERENCE_ID: str = Field(
        default="",
        title="默认角色音色 UUID",
        description=(
            "Fish Audio 角色音色 UUID，直接取音色页面 URL 的 voiceId 参数；"
            "例如 voiceId=0c8b9dbf-932a-48c3-845a-109cfe5beffd。留空则使用服务默认音色"
        ),
    )
    PROXY: str = Field(
        default="",
        title="代理地址",
        description="访问 API 走的代理，如 http://127.0.0.1:7890。留空为直连",
    )
    MAX_CHARS: int = Field(
        default=300,
        title="单次最大字符数",
        description="单次合成允许的最大文本长度，超出自动截断，防止跑爆账单",
    )
    COOLDOWN_SECONDS: int = Field(
        default=10,
        title="合成冷却（秒）",
        description="两次合成请求之间的最小间隔",
    )


config = plugin.get_config(TTSConfig)

_last_call: float = 0.0


def _http_kwargs() -> dict:
    kwargs: dict = {"timeout": 120}
    if config.PROXY:
        kwargs["proxies"] = {"http": config.PROXY, "https": config.PROXY}
    return kwargs


def _fish_audio_tts(text: str, model: str, reference_id: str) -> bytes:
    """调用 FishAudio Open API /speech/tts，返回音频字节"""
    headers = {
        "Authorization": f"Bearer {config.API_KEY}",
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    payload: dict = {
        "text": text,
        "modelId": model,
        "format": "mp3",
        "speed": 1,
        "volume": 0,
        "stability": 1,
        "similarity": 1,
    }
    if reference_id:
        payload["voiceId"] = reference_id

    resp = requests.post(
        f"{config.API_BASE.rstrip('/')}/speech/tts",
        headers=headers,
        json=payload,
        **_http_kwargs(),
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"FishAudio API 返回 {resp.status_code}: {resp.text[:300]}"
        )
    audio = resp.content
    if len(audio) < 1000:
        raise RuntimeError(f"FishAudio 返回音频异常过小（{len(audio)} 字节）")
    return audio


def _openai_compatible_tts(text: str, model: str, voice: str) -> bytes:
    """OpenAI 兼容的 TTS 接口（MiMo / 百炼等，预留路径）"""
    raise RuntimeError(
        "openai_compatible 提供商暂未实现，请使用 fishaudio 或等待后续版本"
    )


async def _send_audio(chat_key: str, audio: bytes, text: str = "") -> None:
    """经 OneBot 发送语音消息"""
    chat_type, separator, chat_id = chat_key.rpartition("_")
    if not separator or not chat_id:
        raise ValueError(f"无法解析聊天标识: {chat_key}")
    bot = get_bot()

    tmp_path: str = ""
    try:
        # Use a local MP3 path so OneBot can send it and NA can copy the same
        # file into its persistent uploads/history store.
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(audio)
            tmp_path = f.name
        segment = MessageSegment.record(file=tmp_path)

        if chat_type == "onebot_v11-group":
            logger.info("[akiyo_tts] 正在发送 OneBot 群语音 chat_id=%s bytes=%d", chat_id, len(audio))
            response = await bot.send_group_msg(group_id=int(chat_id), message=segment)
        else:
            logger.info("[akiyo_tts] 正在发送 OneBot 私聊语音 user_id=%s bytes=%d", chat_id, len(audio))
            try:
                response = await bot.send_private_msg(user_id=int(chat_id), message=segment)
            except Exception as local_error:
                # Some NapCat versions cannot read the agent's temporary path.
                # Retry with a base64 record segment before failing the tool.
                logger.warning("[akiyo_tts] 本地音频路径发送失败，改用 base64 重试: %s", local_error)
                b64 = base64.b64encode(audio).decode()
                response = await bot.send_private_msg(
                    user_id=int(chat_id),
                    message=MessageSegment.record(file=f"base64://{b64}"),
                )
        logger.info(
            "[akiyo_tts] OneBot 语音发送成功 chat_key=%s response=%s",
            chat_key,
            response,
        )

        # lightweight file record so NA WebUI/history can show the event.
        try:
            response_id = getattr(response, "message_id", "")
            if isinstance(response, dict):
                response_id = response.get("message_id", "")
            await message_service.push_bot_message(
                chat_key,
                [
                    AgentMessageSegment(type=AgentMessageSegmentType.TEXT, content=f"🔊 语音：{text}"),
                    AgentMessageSegment(type=AgentMessageSegmentType.FILE, content=tmp_path),
                ],
                SimpleNamespace(message_id=str(response_id or "")),
            )
        except Exception:
            logger.exception("[akiyo_tts] 语音已发送，但写入 NA 消息历史失败")
    except Exception as e:
        raise RuntimeError(f"发送语音消息失败: {e}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


@plugin.mount_sandbox_method(
    SandboxMethodType.TOOL,
    name="FishAudio发送角色语音",
    description=(
        "使用 FishAudio 云端角色音色合成并发送语音消息。群聊和私聊均支持，当前聊天会自动作为发送目标。"
        "必须在用户明确要求语音时调用；不要改用 NekroAgent 内置的‘发送消息语音’工具。"
        "调用后语音会自动发出，无需再发送文字替代。"
    ),
)
async def akiyo_tts(_ctx: AgentCtx, content: str) -> str:
    """文本转语音并发送到当前聊天

    Args:
        content: 要合成的文本（会自动截断到配置的上限）

    Returns:
        str: 发送结果说明

    Raises:
        RuntimeError: API 调用或发送失败时

    Example:
        akiyo_tts("早上好呀，今天也要元气满满哦")
    """
    global _last_call

    if not config.API_KEY:
        raise RuntimeError("未配置 API_KEY，请在插件配置中填入 TTS 服务密钥")

    text = content.strip()
    if not text:
        raise ValueError("合成文本不能为空")

    if len(text) > config.MAX_CHARS:
        text = text[: config.MAX_CHARS]
        logger.info(f"[akiyo_tts] 文本超长，已截断至 {config.MAX_CHARS} 字符")

    now = time.time()
    wait = config.COOLDOWN_SECONDS - (now - _last_call)
    if wait > 0:
        await asyncio.sleep(wait)
    _last_call = time.time()

    if config.PROVIDER == "fishaudio":
        audio = _fish_audio_tts(text, config.DEFAULT_MODEL, config.DEFAULT_REFERENCE_ID)
    else:
        audio = _openai_compatible_tts(text, config.DEFAULT_MODEL, config.DEFAULT_REFERENCE_ID)

    logger.info(f"[akiyo_tts] 合成完成，音频 {len(audio)} 字节")
    await _send_audio(_ctx.from_chat_key, audio, text)
    return f"已发送角色语音（{len(text)} 字符，{len(audio)} 字节音频）"


@plugin.mount_cleanup_method()
async def clean_up():
    """清理插件资源"""
    logger.info("[akiyo_tts] 插件资源已清理")


@on_command("tts_set_model").handle()
async def tts_set_model(matcher: Matcher, event: MessageEvent, bot: Bot, arg: Message = CommandArg()):
    username, cmd_content, chat_key, chat_type = await command_guard(event, bot, arg, matcher)
    if not cmd_content:
        await matcher.finish(message="用法: /tts_set_model <模型名>\n例: /tts_set_model s2.1-pro-free")
    await save_plugin_config("Akiyo_dayo.voice_workshop", {"DEFAULT_MODEL": cmd_content.strip()})
    await matcher.finish(message=f"已切换 TTS 模型为: {cmd_content.strip()}")


@on_command("tts_set_voice").handle()
async def tts_set_voice(matcher: Matcher, event: MessageEvent, bot: Bot, arg: Message = CommandArg()):
    username, cmd_content, chat_key, chat_type = await command_guard(event, bot, arg, matcher)
    if not cmd_content:
        await matcher.finish(message="用法: /tts_set_voice <角色音色模型ID>\n在 https://fish.audio/zh/models 打开模型页，URL 末段即 ID\n留空表示清除: /tts_set_voice none")
    voice = cmd_content.strip()
    if voice.lower() in ("none", "clear", "清空", ""):
        voice = ""
    await save_plugin_config("Akiyo_dayo.voice_workshop", {"DEFAULT_REFERENCE_ID": voice})
    label = voice if voice else "（基础音色）"
    await matcher.finish(message=f"已切换角色音色为: {label}")


@on_command("tts_status").handle()
async def tts_status(matcher: Matcher, event: MessageEvent, bot: Bot, arg: Message = CommandArg()):
    await matcher.finish(
        message=(
            "voice_workshop 当前配置:\n"
            f"- 提供商: {config.PROVIDER}\n"
            f"- 模型: {config.DEFAULT_MODEL}\n"
            f"- 角色音色: {config.DEFAULT_REFERENCE_ID or '（基础音色）'}\n"
            f"- API Base: {config.API_BASE}\n"
            f"- 单次上限: {config.MAX_CHARS} 字符，冷却 {config.COOLDOWN_SECONDS}s\n"
            "命令: /tts_set_model <模型> | /tts_set_voice <ID|none> | /tts_status"
        )
    )
