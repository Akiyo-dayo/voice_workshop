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

import math
import re
from urllib.parse import parse_qs, urlparse

import httpx

from .audio import validate_mp3, validate_wav, pad_wav_tail, normalize_wav
from .acting import EMOTIONS, DELIVERIES, PRESETS, acting_payload
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
    version="1.3.1",
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
        description="单次调用文本上限；超限返回错误供 Agent 缩短或明确分次发送，绝不静默截断",
        ge=1, le=3000,
    )
    SEGMENT_CHARS: int = Field(default=100, ge=20, le=500, title="每段合成字符数", description="优先按句末分段，保留全文；短段降低长文本漏读风险，每段各发一条语音")
    SPLIT_SENTENCES: bool = Field(default=True, title="逐句合成", description="每个完整句子单独合成，降低上游漏读后半句风险；关闭后仅按每段字数分段")
    MAX_SEGMENTS: int = Field(default=6, ge=1, le=20, title="最多语音段数", description="超过则请求 Agent 缩短文本，不丢弃后文")
    SPEED: float = Field(default=1, ge=0.5, le=2, title="默认语速")
    VOLUME: float = Field(default=0, ge=-20, le=20, title="默认音量（dB）")
    STABILITY: float = Field(default=1, ge=0.5, le=1.5, title="默认稳定度", description="效果须试听验证，不保证数值越大越自然")
    SIMILARITY: float = Field(default=1, ge=0.5, le=1.5, title="默认音色相似度")
    LANGUAGE: str = Field(default="zh", title="语言提示", description="留空自动识别；默认中文")
    DEFAULT_STYLE: str = Field(default="neutral", title="默认演绎风格", description="neutral / excited / whisper；Fish S2 系列以内联标签控制，非音高参数")
    ENABLE_STYLE_TAGS: bool = Field(default=True, title="启用 Fish 演绎标签", description="仅 Fish S2 系列启用经文档确认的 [excited] / [whisper] 标签；若服务将标签读出请关闭")
    DEFAULT_EMOTION: str = Field(default="neutral", title="默认情绪", description="neutral/happy/sad/angry/fearful/surprised/disgusted/excited/gentle/comforting/shy/sarcastic/impatient/hurt/disappointed")
    DEFAULT_DELIVERY: str = Field(default="normal", title="默认发声方式", description="normal/whisper/crying/sobbing/choked/laughing/shouting/tired；是否支持依模型而定")
    DEFAULT_INTENSITY: float = Field(default=.5, ge=0, le=1, title="默认演绎程度", description="仅指令型模型支持软提示；Fish和MiniMax须保持.5，不冒充精确强度")
    DEFAULT_INSTRUCTION: str = Field(default="", max_length=1200, title="默认导演指令", description="仅支持instruction的模型；独立于朗读正文")
    ALLOWED_EMOTIONS: str = Field(default=",".join(EMOTIONS), title="Agent允许情绪", description="英文名称逗号分隔；只是许可，仍需模型支持")
    ALLOWED_DELIVERIES: str = Field(default=",".join(DELIVERIES), title="Agent允许发声方式", description="英文名称逗号分隔")
    ALLOW_EXPERIMENTAL_ACTING: bool = Field(default=False, title="允许实验性Fish标签", description="愤怒/悲伤/哭腔等可尝试但不保证生效，默认关闭；接口成功不等于听感确认")
    TAIL_SILENCE_SECONDS: float = Field(default=1, ge=0, le=3, title="QQ尾音保护静音（秒）", description="默认在PCM WAV末尾补1秒静音，避免QQ收音过早；设0关闭。开启时服务请求WAV，不改变台词或音色")
    OUTPUT_FORMAT: str = Field(default="mp3", title="输出格式", description="mp3或wav，需模型支持；Qwen3仅wav")
    ROLE_GUIDANCE: str = Field(default="保持当前角色人设，像自然对话而非播报；使用完整口语句子，通过标点表达停顿，结合上下文选择克制的情绪，确保最后一句说完。", title="角色演绎引导", description="注入给 Agent 的写作与演绎指导，不作为台词朗读，也不冒充服务支持的 instruction 参数")
    ALLOW_AGENT_OVERRIDES: bool = Field(default=True, title="允许 Agent 单次调音", description="允许工具参数覆盖语速/音量/稳定度/相似度/语言/风格；不会修改实例默认或更换模型音色")
    REQUEST_TIMEOUT: float = Field(default=25, ge=5, le=60, title="单段请求超时（秒）")
    TOTAL_TIMEOUT: float = Field(default=85, ge=10, le=100, title="整次任务总时限（秒）", description="涵盖冷却、所有合成及发送；低于120秒沙盒预算，超时取消异步请求，不自动重试扣费")
    COOLDOWN_SECONDS: int = Field(
        default=10, ge=0, le=60,
        title="调用冷却（秒）",
        description="两次工具调用之间的最小间隔；并发任务直接返回忙碌，不无限排队",
    )


config = plugin.get_config(TTSConfig)

_last_call: float = 0.0
_call_lock = asyncio.Lock()
_STYLES = {"neutral": "", "excited": "[excited]", "whisper": "[whisper]"}


def _split_text(text: str, limit: int) -> list[str]:
    """Split without discarding any characters, preferring sentence endings."""
    chunks = []
    while len(text) > limit:
        boundaries = [m.end() for m in re.finditer(r"[。！？!?；;\n]+[”’\"']?", text[:limit])]
        end = boundaries[-1] if boundaries else limit
        # Do not split an English word when there is a usable whitespace boundary.
        if not boundaries:
            space = text.rfind(" ", 0, limit)
            if space > limit // 2:
                end = space + 1
        chunks.append(text[:end])
        text = text[end:]
    if text:
        chunks.append(text)
    return chunks


def _prepare_chunks(text: str) -> list[str]:
    # Finish colloquial trailing ellipses without dropping the preceding words.
    text = re.sub(r"(?:…+|\.{3,})\s*$", "。", text)
    chunks = []
    sentences = re.findall(r".*?[。！？!?；;\n]+[”’\"']?|.+$", text, flags=re.S) if config.SPLIT_SENTENCES else [text]
    for sentence in sentences:
        for chunk in _split_text(sentence, config.SEGMENT_CHARS):
            if not chunk.strip():
                continue
            # Give every independent synthesis a completed ending, including hard splits.
            if not re.search(r"[。！？!?；;][”’\"']?$", chunk.rstrip()):
                chunk = chunk.rstrip() + "。"
            chunks.append(chunk)
    return chunks


def _options(speed=None, volume=None, stability=None, similarity=None, language=None, style=None, emotion=None, delivery=None, intensity=None, instruction=None) -> dict:
    values = dict(speed=speed, volume=volume, stability=stability, similarity=similarity, language=language, style=style, emotion=emotion, delivery=delivery, intensity=intensity, instruction=instruction)
    explicit = {k for k,v in values.items() if v is not None}
    if not config.ALLOW_AGENT_OVERRIDES and any(v is not None for v in values.values()):
        raise ValueError("管理员已关闭 Agent 单次调音，请省略所有可选参数")
    bounds = {"speed": (0.5, 2), "volume": (-20, 20), "stability": (0.5, 1.5), "similarity": (0.5, 1.5)}
    for key, (lo, hi) in bounds.items():
        value = values[key] if values[key] is not None else getattr(config, key.upper())
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not lo <= value <= hi:
            raise ValueError(f"{key} 必须为 {lo}–{hi} 之间的有限数值")
        values[key] = value
    values["language"] = config.LANGUAGE if language is None else language
    if not isinstance(values["language"], str) or len(values["language"]) > 64:
        raise ValueError("language 必须是最多64字符的语言提示")
    values["style"] = config.DEFAULT_STYLE if style is None else style
    if values["style"] not in _STYLES:
        raise ValueError("style 仅支持 neutral / excited / whisper")
    if values["style"] != "neutral" and (not config.ENABLE_STYLE_TAGS or not config.DEFAULT_MODEL.startswith(("fishaudio-s2", "fishaudio-s21"))):
        raise ValueError("当前配置或模型不支持演绎标签，请使用 style='neutral'")
    if style is not None and (emotion is not None or delivery is not None):
        raise ValueError('旧style与emotion/delivery不能同时传入')
    values['emotion'] = config.DEFAULT_EMOTION if emotion is None else emotion
    values['delivery'] = config.DEFAULT_DELIVERY if delivery is None else delivery
    values['intensity'] = config.DEFAULT_INTENSITY if intensity is None else intensity
    values['instruction'] = config.DEFAULT_INSTRUCTION if instruction is None else instruction
    if not isinstance(values['instruction'],str) or len(values['instruction'])>1200:
        raise ValueError('instruction最多1200字符')
    if style is not None or (emotion is None and delivery is None and config.DEFAULT_STYLE!='neutral'):
        values['emotion']='excited' if values['style']=='excited' else 'neutral'
        values['delivery']='whisper' if values['style']=='whisper' else 'normal'
    for key,allowed in [('emotion',config.ALLOWED_EMOTIONS),('delivery',config.ALLOWED_DELIVERIES)]:
        legacy_override = style is not None
        if (key in explicit or legacy_override) and values[key] not in {s.strip() for s in allowed.split(',')}:
            raise ValueError(f'管理员未允许{key}={values[key]}')
    values['_explicit']=explicit
    acting_payload('',config.DEFAULT_MODEL,values,experimental=config.ALLOW_EXPERIMENTAL_ACTING) if config.DEFAULT_MODEL.startswith('fishaudio-') else None
    return values


def _output_format():
    return 'wav' if config.TAIL_SILENCE_SECONDS > 0 else config.OUTPUT_FORMAT


async def _model_capabilities(client):
    if not config.API_BASE.rstrip('/').endswith('/v3'):
        if not config.DEFAULT_MODEL.startswith('fishaudio-'):
            raise ValueError('跨引擎控制需要管理员显式设置并验证v3接口；保留v1不会静默迁移')
        return None
    response=await client.get(f"{config.API_BASE.rstrip('/')}/speech/tts/capabilities")
    response.raise_for_status()
    model=next((m for m in response.json()['models'] if m['id']==config.DEFAULT_MODEL),None)
    if not model or not model.get('available'):
        raise ValueError('模型不可用，请查询当前能力目录')
    if _output_format() not in model['outputFormats']:
        raise ValueError('模型不支持所选输出格式')
    response=await client.get(f"{config.API_BASE.rstrip('/')}/voices/{config.DEFAULT_REFERENCE_ID}")
    response.raise_for_status()
    voice=response.json().get('voice',{})
    if config.DEFAULT_MODEL not in voice.get('modelIds',[]):
        raise ValueError('所选音色不兼容当前模型')
    return model


async def _fish_audio_tts(client: httpx.AsyncClient, text: str, options: dict) -> bytes:
    controls=options.get('_controls')
    acting=acting_payload(text,config.DEFAULT_MODEL,options,controls,config.ALLOW_EXPERIMENTAL_ACTING)
    if not config.ENABLE_STYLE_TAGS and acting['text']!=text:
        raise ValueError('管理员已关闭Fish标签，请使用neutral/normal')
    if config.OUTPUT_FORMAT not in ('mp3','wav'):
        raise ValueError('输出格式须为mp3或wav')
    payload = {**acting, 'modelId':config.DEFAULT_MODEL,'format':_output_format()}
    for key in ('speed','volume','stability','similarity','language'):
        if controls is not None and not controls.get(key):
            if key in options.get('_explicit',set()):
                raise ValueError(f'当前模型不支持显式参数{key}')
            continue
        if key=='language' and not options[key]: continue
        payload[key]=options[key]
    if config.DEFAULT_REFERENCE_ID:
        payload["voiceId"] = config.DEFAULT_REFERENCE_ID
    async with client.stream("POST", f"{config.API_BASE.rstrip('/')}/speech/tts", json=payload) as resp:
        if resp.status_code != 200:
            # Do not log response bodies which can contain credentials or text.
            raise RuntimeError(f"FishAudio API 返回 HTTP {resp.status_code}；未自动重试，请检查服务/额度")
        content_type = resp.headers.get("content-type", "").split(";", 1)[0].lower()
        allowed_types=('audio/mpeg','audio/mp3','application/octet-stream') if _output_format()=='mp3' else ('audio/wav','audio/x-wav','audio/wave','application/octet-stream')
        if content_type not in allowed_types:
            raise RuntimeError(f"FishAudio 返回非预期音频响应（{content_type}）")
        audio = bytearray()
        async for part in resp.aiter_bytes():
            audio.extend(part)
            if len(audio) > 12 * 1024 * 1024:
                raise RuntimeError("返回音频超出12 MiB安全上限")
        expected = resp.headers.get("content-length")
        if expected and not resp.headers.get("content-encoding") and len(audio) != int(expected):
            raise RuntimeError("音频下载长度不完整，未发送")
        ignored = resp.headers.get("x-openapi-ignored-parameters", "")
        if ignored:
            raise RuntimeError(f"服务忽略了请求参数 {ignored[:150]}，请调整配置；本次未发送音频")
    result = bytes(audio)
    if _output_format()=='wav': result=normalize_wav(result)
    duration = validate_mp3(result) if _output_format()=='mp3' else validate_wav(result)
    if config.TAIL_SILENCE_SECONDS > 0:
        result = pad_wav_tail(result, config.TAIL_SILENCE_SECONDS)
        logger.info(f'[akiyo_tts] QQ尾音保护 已补{config.TAIL_SILENCE_SECONDS}s静音')
    logger.info(f"[akiyo_tts] 音频校验完成 chars={len(text)} bytes={len(result)} duration={duration:.2f}s")
    return result



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
        with tempfile.NamedTemporaryFile(suffix='.'+_output_format(), delete=False) as f:
            f.write(audio)
            tmp_path = f.name
        segment = MessageSegment.record(file=tmp_path)

        if chat_type not in ("onebot_v11-group", "onebot_v11-private"):
            raise ValueError(f"不支持的聊天类型: {chat_type}")
        send = bot.send_group_msg if chat_type == "onebot_v11-group" else bot.send_private_msg
        target = {"group_id" if chat_type == "onebot_v11-group" else "user_id": int(chat_id)}
        try:
            response = await send(**target, message=segment)
        except Exception:
            logger.warning("[akiyo_tts] 本地路径发送失败，改用 base64 重试")
            b64 = base64.b64encode(audio).decode()
            response = await send(**target, message=MessageSegment.record(file=f"base64://{b64}"))
        logger.info(f"[akiyo_tts] OneBot 语音发送成功 chat_key={chat_key}")

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


@plugin.mount_prompt_inject_method(name="角色语音演绎指导", description="当前调音默认值、角色演绎和完整台词要求")
async def voice_guidance(_ctx: AgentCtx) -> str:
    return (
        "【声色工坊】仅在用户明确要求语音时调用 akiyo_tts。content 只写实际朗读的完整台词，"
        "不要夹带动作描写、Markdown、音效说明或把‘请温柔地说’当台词。"
        "根据当前人设和上下文组织自然口语，用标点控制停顿，确保结尾完整；不要用省略后文掩盖长度错误。"
        f"每次最多 {config.MAX_CHARS} 字，内部按约 {config.SEGMENT_CHARS} 字分段，每段一条语音。"
        f"角色演绎要求：{config.ROLE_GUIDANCE}\n"
        f"当前默认：speed={config.SPEED}, volume={config.VOLUME}, stability={config.STABILITY}, "
        f"similarity={config.SIMILARITY}, language={config.LANGUAGE!r}, style={config.DEFAULT_STYLE!r}。"
        f"Agent 单次覆盖：{'允许' if config.ALLOW_AGENT_OVERRIDES else '禁止，请省略可选参数'}。"
        f"演绎emotion许可：{config.ALLOWED_EMOTIONS}；delivery许可：{config.ALLOWED_DELIVERIES}。"
        f"默认emotion={config.DEFAULT_EMOTION},delivery={config.DEFAULT_DELIVERY},intensity={config.DEFAULT_INTENSITY}。"
        f"Fish实验标签许可={config.ALLOW_EXPERIMENTAL_ACTING}；Fish仅excited/whisper标签有当前文档依据，其他标签属实验。"
        "Fish使用emotion/delivery时强度须省略(.5)，MiniMax仅基础emotion，指令型模型才支持自由导演instruction及软强度。"
        "复合状态示例：克制悲伤sad+normal，愤怒委屈angry+choked，崩溃sad+sobbing；仅在模型和管理员允许时使用。"
        "不要把所有复合情绪当成已验证功能；不支持会报错，不要反复付费试错。旧style不可与emotion/delivery同时传。"
        "MiniMax推荐language='zh-CN'；Qwen使用zh。Qwen3仅自然朗读，不接受未声明的情绪指令。"
        f"当前模型={config.DEFAULT_MODEL}，协议={config.API_BASE.rsplit('/',1)[-1]}，默认导演指令是否配置={bool(config.DEFAULT_INSTRUCTION)}。"
        "可按情境克制地调整参数，不要每句随机改变，不改变角色音色或全局配置。"
        "出错时向用户明确说明；若已有部分语音发送，不要整段重发造成重复。"
    )


@plugin.mount_sandbox_method(
    SandboxMethodType.TOOL,
    name="FishAudio发送角色语音",
    description="按角色人设合成完整台词并发送语音，支持单次语速/音量/稳定度/相似度/语言/演绎风格。仅用户明确要求语音时使用，不改用内置语音工具。",
)
async def akiyo_tts(
    _ctx: AgentCtx, content: str, speed: float | None = None,
    volume: float | None = None, stability: float | None = None,
    similarity: float | None = None, language: str | None = None,
    style: str | None = None, emotion: str | None = None,
    delivery: str | None = None, intensity: float | None = None,
    instruction: str | None = None,
) -> str:
    """按当前角色音色发送完整语音；可选参数仅对本次有效，不修改默认值。

    Args:
        content: 实际朗读的完整台词，不写动作或风格说明。超限会报错，绝不偷偷截断。
        speed: 语速0.5–2；省略使用用户配置。不是音高控制。
        volume: 音量-20–20 dB；省略使用用户配置。
        stability: 稳定度0.5–1.5；避免大幅随机变化。
        similarity: 音色相似度0.5–1.5；不保证越高越好。
        language: 语言提示，如zh；空字符串自动检测。
        style: 兼容旧参数neutral/excited/whisper；不可与emotion/delivery同时传。
        emotion: 基础/社交情绪，neutral/happy/sad/angry/fearful/surprised/disgusted/excited/gentle/comforting/shy/sarcastic/impatient/hurt/disappointed。
        delivery: 发声方式normal/whisper/crying/sobbing/choked/laughing/shouting/tired，按当前模型支持选择。
        intensity: 0–1软提示，仅指令型模型；Fish/MiniMax须省略使用.5。
        instruction: 最多1200字导演指令，仅支持instruction的模型；绝不放进朗读正文。

    Example:
        akiyo_tts("早上好！今天也要元气满满哦。", speed=1.05, style="excited")
    """
    global _last_call
    if not config.API_KEY:
        raise RuntimeError("未配置 API_KEY，请在插件配置中填入 TTS 服务密钥")
    if config.PROVIDER != "fishaudio":
        raise ValueError("目前仅实现 fishaudio 提供商")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("合成文本不能为空")
    text = content.strip()
    if len(text) > config.MAX_CHARS:
        raise ValueError(f"台词共{len(text)}字，超过{config.MAX_CHARS}字上限；未合成、未截断。请缩短或明确分次调用并保留后文。")
    if re.search(r"\[[^\]\n]{1,80}\]", text):
        raise ValueError("content 不允许内联标签；请用 style 参数控制演绎，台词保持纯文本")
    options = _options(speed, volume, stability, similarity, language, style, emotion, delivery, intensity, instruction)
    chunks = _prepare_chunks(text)
    if len(chunks) > config.MAX_SEGMENTS:
        raise ValueError(f"台词需{len(chunks)}段，超过{config.MAX_SEGMENTS}段限制；未合成，请减少文本或分次调用")
    if _call_lock.locked():
        raise RuntimeError("语音服务忙碌，请稍后再试；本次未排队、未合成")
    async with _call_lock:
        sent = 0
        sending = False

        async def run():
            nonlocal sent, sending
            global _last_call
            wait = config.COOLDOWN_SECONDS - (time.monotonic() - _last_call)
            if wait > 0:
                await asyncio.sleep(wait)
            _last_call = time.monotonic()
            kwargs = dict(
                headers={"Authorization": f"Bearer {config.API_KEY}", "Accept": "audio/mpeg"},
                timeout=httpx.Timeout(config.REQUEST_TIMEOUT, connect=min(8, config.REQUEST_TIMEOUT)),
                trust_env=False,
            )
            if config.PROXY:
                kwargs["proxy"] = config.PROXY
            audio_parts = []
            async with httpx.AsyncClient(**kwargs) as client:
                model=await _model_capabilities(client)
                if model is not None: options['_controls']=model['controls']
                acting_payload('',config.DEFAULT_MODEL,options,options.get('_controls'),config.ALLOW_EXPERIMENTAL_ACTING)
                for chunk in chunks:
                    audio_parts.append(await _fish_audio_tts(client, chunk, options))
            # Never send the first part if synthesis of a later part failed.
            for chunk, audio in zip(chunks, audio_parts):
                sending = True
                await _send_audio(_ctx.from_chat_key, audio, chunk)
                sent += 1
                sending = False

        try:
            await asyncio.wait_for(run(), timeout=config.TOTAL_TIMEOUT)
        except asyncio.CancelledError:
            logger.warning(f"[akiyo_tts] 任务取消，已确认发送{sent}/{len(chunks)}段，当前段状态{'未知' if sending else '未在发送'}")
            raise
        except Exception as exc:
            detail = "任务超时" if isinstance(exc, (asyncio.TimeoutError, httpx.TimeoutException)) else str(exc)
            uncertain = "当前段可能已送达，请勿盲目重发。" if sending else ""
            raise RuntimeError(f"语音失败：{detail}；已确认发送{sent}/{len(chunks)}段。{uncertain}未自动重试合成。") from exc
    return f"已发送完整角色语音：{len(text)}字，{sent}段；style={options['style']}，speed={options['speed']}。"


@plugin.mount_cleanup_method()
async def clean_up():
    """清理插件资源（每次请求的异步客户端由上下文管理器关闭）"""
    logger.info("[akiyo_tts] 插件资源已清理")


@on_command("tts_set_model").handle()
async def tts_set_model(matcher: Matcher, event: MessageEvent, bot: Bot, arg: Message = CommandArg()):
    username, cmd_content, chat_key, chat_type = await command_guard(event, bot, arg, matcher)
    if not cmd_content:
        await matcher.finish(message="用法: /tts_set_model <模型名>\n例: /tts_set_model fishaudio-s21pro-flash\n影响本实例全部聊天，请确认音色兼容。")
    selected=cmd_content.strip()
    if not config.API_BASE.rstrip('/').endswith('/v3') and not selected.startswith('fishaudio-'):
        await matcher.finish(message='跨引擎模型须先在配置面板显式设置v3接口与兼容音色；未修改模型。')
    try:
        kwargs={'timeout':httpx.Timeout(12,connect=5),'trust_env':False,'headers':{'Authorization':f'Bearer {config.API_KEY}'}}
        if config.PROXY: kwargs['proxy']=config.PROXY
        async def check_selection():
            async with httpx.AsyncClient(**kwargs) as client:
                origin=config.API_BASE.rstrip('/').rsplit('/api/open/',1)[0]
                r=await client.get(origin+'/api/open/v3/speech/tts/capabilities')
                r.raise_for_status()
                candidate=next((x for x in r.json()['models'] if x['id']==selected and x.get('available')),None)
                if not candidate: raise ValueError('模型不存在或当前不可用')
                if _output_format() not in candidate['outputFormats']: raise ValueError('请先设置模型支持的输出格式')
                r=await client.get(origin+'/api/open/v3/voices/'+config.DEFAULT_REFERENCE_ID)
                r.raise_for_status()
                if selected not in r.json().get('voice',{}).get('modelIds',[]): raise ValueError('当前音色与目标模型不兼容')
                return candidate
        candidate=await asyncio.wait_for(check_selection(),timeout=20)
    except Exception as exc:
        await matcher.finish(message=f'模型/音色校验未通过（{type(exc).__name__}），未修改配置。请查询兼容目录。')
    success, error = await save_plugin_config("Akiyo_dayo.voice_workshop", {"DEFAULT_MODEL": selected})
    if not success:
        await matcher.finish(message=f"保存失败: {error}")
    await matcher.finish(message=f"已切换本实例 TTS 模型为: {cmd_content.strip()}")


@on_command("tts_set_voice").handle()
async def tts_set_voice(matcher: Matcher, event: MessageEvent, bot: Bot, arg: Message = CommandArg()):
    username, cmd_content, chat_key, chat_type = await command_guard(event, bot, arg, matcher)
    if not cmd_content:
        await matcher.finish(message="用法: /tts_set_voice <UUID或fishaudio.org音色链接|none>\n取链接中 voiceId 参数。影响本实例全部聊天。")
    voice = cmd_content.strip()
    if voice.lower() in ("none", "clear", "清空"):
        voice = ""
    else:
        if "://" in voice:
            url = urlparse(voice)
            if url.hostname not in ("fishaudio.org", "www.fishaudio.org"):
                await matcher.finish(message="请提供 fishaudio.org 音色链接或 voiceId UUID")
            voice = parse_qs(url.query).get("voiceId", [""])[0]
        if not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", voice):
            await matcher.finish(message="无效音色 UUID，请复制 fishaudio.org 链接中的 voiceId")
    success, error = await save_plugin_config("Akiyo_dayo.voice_workshop", {"DEFAULT_REFERENCE_ID": voice})
    if not success:
        await matcher.finish(message=f"保存失败: {error}")
    label = voice if voice else "（基础音色）"
    await matcher.finish(message=f"已切换角色音色为: {label}")


@on_command("tts_status").handle()
async def tts_status(matcher: Matcher, event: MessageEvent, bot: Bot, arg: Message = CommandArg()):
    await command_guard(event, bot, arg, matcher)
    await matcher.finish(
        message=(
            "声色工坊 当前配置（实例级，影响所有聊天）:\n"
            f"- 提供商: {config.PROVIDER}\n"
            f"- 模型: {config.DEFAULT_MODEL}\n"
            f"- 角色音色: {config.DEFAULT_REFERENCE_ID or '（基础音色）'}\n"
            f"- API Base: {config.API_BASE}\n"
            f"- 单次上限: {config.MAX_CHARS} 字符，每段{config.SEGMENT_CHARS}字/最多{config.MAX_SEGMENTS}段；超限报错不截断\n"
            f"- 语速/音量: {config.SPEED}/{config.VOLUME}，稳定度/相似度: {config.STABILITY}/{config.SIMILARITY}\n"
            f"- 语言/风格: {config.LANGUAGE or '自动'}/{config.DEFAULT_STYLE}，Agent覆盖: {config.ALLOW_AGENT_OVERRIDES}\n"
            f"- 冷却: {config.COOLDOWN_SECONDS}s，总时限: {config.TOTAL_TIMEOUT}s\n"
            "调音默认值和角色演绎引导可在NA插件配置中修改。\n"
            "命令: /tts_set_model <模型> | /tts_set_voice <ID|none> | /tts_status"
        )
    )
