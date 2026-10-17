"""Run without a NekroAgent installation; framework calls are isolated stubs."""
import asyncio
import importlib.util
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]


def module(name, **attrs):
    value = types.ModuleType(name)
    value.__dict__.update(attrs)
    sys.modules[name] = value
    return value


class Plugin:
    def __init__(self, **kwargs):
        self.methods = []

    def mount_config(self):
        return lambda cls: cls

    def get_config(self, cls):
        return cls()

    def mount_sandbox_method(self, *args, **kwargs):
        def decorate(fn):
            self.methods.append(fn)
            return fn
        return decorate

    def mount_prompt_inject_method(self, **kwargs):
        return lambda fn: fn

    def mount_cleanup_method(self):
        return lambda fn: fn


for name in ['nonebot', 'nonebot.adapters', 'nonebot.adapters.onebot', 'nonebot.adapters.onebot.v11',
             'nonebot.matcher', 'nonebot.params', 'nekro_agent', 'nekro_agent.adapters',
             'nekro_agent.adapters.onebot_v11', 'nekro_agent.adapters.onebot_v11.matchers',
             'nekro_agent.api', 'nekro_agent.services', 'nekro_agent.services.plugin', 'nekro_agent.schemas']:
    module(name)
module('nonebot', on_command=lambda *a, **k: SimpleNamespace(handle=lambda: lambda fn: fn), get_bot=lambda: None)
module('nonebot.adapters', Bot=object, Message=object)
module('nonebot.adapters.onebot.v11', MessageEvent=object, MessageSegment=SimpleNamespace(record=lambda **k: k))
module('nonebot.matcher', Matcher=object)
module('nonebot.params', CommandArg=lambda: None)
module('nekro_agent.adapters.onebot_v11.matchers.command', command_guard=AsyncMock(return_value=('user', '', 'onebot_v11-private_1', None)))
module('nekro_agent.api.schemas', AgentCtx=object)
module('nekro_agent.core', logger=SimpleNamespace(**{x: lambda *a, **k: None for x in ['info', 'warning', 'exception']}))
module('nekro_agent.schemas.agent_message', AgentMessageSegment=lambda **k: k, AgentMessageSegmentType=SimpleNamespace(TEXT='text', FILE='file'))
module('nekro_agent.services.message_service', message_service=SimpleNamespace(push_bot_message=AsyncMock()))
module('nekro_agent.services.plugin.base', ConfigBase=BaseModel, NekroPlugin=Plugin, SandboxMethodType=SimpleNamespace(TOOL=1))
module('nekro_agent.services.plugin.manager', save_plugin_config=AsyncMock(return_value=(True, None)))
spec = importlib.util.spec_from_file_location('voice_workshop', ROOT/'__init__.py', submodule_search_locations=[str(ROOT)])
plugin = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = plugin
spec.loader.exec_module(plugin)


def audio(frames=20):
    return (bytes.fromhex('fffb9000') + bytes(413)) * frames


REAL_SEND = plugin._send_audio


@pytest.fixture(autouse=True)
def reset(monkeypatch):
    monkeypatch.setattr(plugin, 'config', plugin.TTSConfig(API_KEY='test', COOLDOWN_SECONDS=0, SPLIT_SENTENCES=False, TAIL_SILENCE_SECONDS=0))
    monkeypatch.setattr(plugin, '_call_lock', asyncio.Lock())
    monkeypatch.setattr(plugin, '_last_call', 0.0)
    monkeypatch.setattr(plugin, '_send_audio', AsyncMock())


def run(awaitable):
    return asyncio.run(awaitable)


@pytest.mark.parametrize('text', ['这是完整的第一句。还有一句也要说完！结尾不能丢。'*30, 'one complete sentence, with many words. '*30, '啊'*500, '句子。”后面仍完整。'*30])
def test_split_preserves_every_character(text):
    chunks = plugin._split_text(text, 100)
    assert ''.join(chunks) == text
    assert all(0 < len(x) <= 100 for x in chunks)


def test_sentence_synthesis_finishes_each_sentence():
    plugin.config.SPLIT_SENTENCES = True
    chunks = plugin._prepare_chunks('前辈，等一下……不过这件事还没结束。还有后文，明天见……')
    assert chunks == ['前辈，等一下……不过这件事还没结束。', '还有后文，明天见。']
    assert plugin._prepare_chunks('啊'*150) == ['啊'*100+'。','啊'*50+'。']


def test_mp3_integrity():
    assert plugin.validate_mp3(audio()) > 0
    for bad in [audio()[:-1], b'{}', b'ID3', audio()+b'bad']:
        with pytest.raises(ValueError):
            plugin.validate_mp3(bad)
    assert plugin.validate_mp3(b'ID3\x04\x00\x00\x00\x00\x00\x00'+audio()) > 0


@pytest.mark.parametrize('kwargs', [{'speed': 0}, {'volume': float('nan')}, {'similarity': 2}, {'stability': True}, {'style':'angry'}, {'language':'x'*65}])
def test_bad_options(kwargs):
    with pytest.raises(ValueError):
        plugin._options(**kwargs)


def test_configuration_and_override():
    plugin.config.SPEED = 0.95
    assert plugin._options()['speed'] == .95
    assert plugin._options(speed=1.1)['speed'] == 1.1
    assert plugin.config.SPEED == .95
    plugin.config.ALLOW_AGENT_OVERRIDES = False
    assert plugin._options()['speed'] == .95
    with pytest.raises(ValueError):
        plugin._options(speed=1)


def test_prompt_exposes_guidance():
    plugin.config.ROLE_GUIDANCE = '轻声自然，不要播报腔'
    assert '轻声自然' in run(plugin.voice_guidance(None))
    assert 'similarity=' in run(plugin.voice_guidance(None))
    assert plugin.akiyo_tts in plugin.plugin.methods


@pytest.mark.parametrize('text', ['啊'*301, '[angry]你好', ' '])
def test_invalid_text_no_synthesis(text, monkeypatch):
    synth = AsyncMock()
    monkeypatch.setattr(plugin, '_fish_audio_tts', synth)
    with pytest.raises(ValueError):
        run(plugin.akiyo_tts(SimpleNamespace(from_chat_key='onebot_v11-private_1'), text))
    synth.assert_not_called()


def test_full_text_all_parts_sent(monkeypatch):
    synth = AsyncMock(return_value=audio())
    monkeypatch.setattr(plugin, '_fish_audio_tts', synth)
    text = '这是第一句。'*30+'结束。'
    result = run(plugin.akiyo_tts(SimpleNamespace(from_chat_key='onebot_v11-private_1'), text, style='excited'))
    assert ''.join(c.args[1].replace('。','') for c in synth.call_args_list) == text.replace('。','')
    assert ''.join(c.args[2].replace('。','') for c in plugin._send_audio.call_args_list) == text.replace('。','')
    assert '完整' in result


def test_failure_before_send_is_atomic(monkeypatch):
    monkeypatch.setattr(plugin, '_fish_audio_tts', AsyncMock(side_effect=[audio(), RuntimeError('failed')]))
    with pytest.raises(RuntimeError, match='已确认发送0/'):
        run(plugin.akiyo_tts(SimpleNamespace(from_chat_key='x'), '啊'*150))
    plugin._send_audio.assert_not_called()


def test_partial_delivery_message(monkeypatch):
    monkeypatch.setattr(plugin, '_fish_audio_tts', AsyncMock(return_value=audio()))
    plugin._send_audio.side_effect = [None, RuntimeError('failed')]
    with pytest.raises(RuntimeError, match='已确认发送1/2段'):
        run(plugin.akiyo_tts(SimpleNamespace(from_chat_key='x'), '啊'*150))


def test_timeout_cancels_and_does_not_block(monkeypatch):
    ticks = []
    cancelled = []
    async def slow(*args):
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.append(True)
    monkeypatch.setattr(plugin, '_fish_audio_tts', slow)
    plugin.config.TOTAL_TIMEOUT = .12
    async def scenario():
        async def ticker():
            for _ in range(5):
                await asyncio.sleep(.01)
                ticks.append(1)
        await asyncio.gather(ticker(), plugin.akiyo_tts(SimpleNamespace(from_chat_key='x'), '完整句子。'), return_exceptions=True)
        assert not plugin._call_lock.locked()
    run(scenario())
    assert len(ticks) == 5 and cancelled
    plugin._send_audio.assert_not_called()


@pytest.mark.parametrize('kind', ['group','private'])
def test_delivery_fallback_and_history(kind, monkeypatch):
    send = AsyncMock(side_effect=[RuntimeError('cannot read path'), {'message_id': 123}])
    bot=SimpleNamespace(send_group_msg=send,send_private_msg=send)
    monkeypatch.setattr(plugin,'get_bot',lambda:bot)
    plugin.message_service.push_bot_message.reset_mock()
    run(REAL_SEND(f'onebot_v11-{kind}_1',audio(),'完整台词。'))
    assert send.call_count==2
    assert send.call_args_list[1].kwargs['message']['file'].startswith('base64://')
    assert not Path(send.call_args_list[0].kwargs['message']['file']).exists()
    plugin.message_service.push_bot_message.assert_awaited_once()


def test_save_failure_never_claims_success(monkeypatch):
    class Finished(Exception): pass
    class Matcher:
        async def finish(self, message):
            raise Finished(message)
    monkeypatch.setattr(plugin,'command_guard',AsyncMock(return_value=('u','fishaudio-s21pro-flash','x',None)))
    monkeypatch.setattr(plugin,'save_plugin_config',AsyncMock(return_value=(False,'disk full')))
    original=httpx.AsyncClient
    def handler(request):
        if 'capabilities' in str(request.url):
            return httpx.Response(200,json={'models':[{'id':'fishaudio-s21pro-flash','available':True,'outputFormats':['mp3']}]})
        return httpx.Response(200,json={'voice':{'modelIds':['fishaudio-s21pro-flash']}})
    monkeypatch.setattr(plugin.httpx,'AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs))
    with pytest.raises(Finished,match='保存失败'):
        run(plugin.tts_set_model(Matcher(),None,None,None))


def test_busy_rejects_without_queue(monkeypatch):
    async def scenario():
        async with plugin._call_lock:
            with pytest.raises(RuntimeError, match='忙碌'):
                await plugin.akiyo_tts(SimpleNamespace(from_chat_key='x'), '你好。')
    run(scenario())


@pytest.mark.parametrize('status,ctype,body,headers,success', [
    (200,'audio/mpeg',audio(),{},True),
    (200,'application/json',b'{}',{},False),
    (200,'audio/mpeg',audio()[:-1],{},False),
    (200,'audio/mpeg',audio(),{'content-length':'99999'},False),
    (200,'audio/mpeg',audio(),{'x-openapi-ignored-parameters':'language'},False),
    (500,'application/json',b'{}',{},False),
] , ids=['valid','json','truncated','length','ignored','error'])
def test_http_validation(status,ctype,body,headers,success):
    async def scenario():
        def handler(request):
            data=json.loads(request.content)
            assert data['text']=='[whisper]你好。'
            assert data['speed']==.95
            assert 'instruction' not in data and 'pitch' not in data
            return httpx.Response(status,content=body,headers={'content-type':ctype,**headers})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            call=plugin._fish_audio_tts(client,'你好。',plugin._options(style='whisper',speed=.95))
            if success:
                assert await call == body
            else:
                with pytest.raises((RuntimeError,ValueError)):
                    await call
    run(scenario())
