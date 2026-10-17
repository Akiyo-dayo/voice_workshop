import io
import wave
import pytest
from test_voice_workshop import plugin, reset, run
from voice_workshop.acting import EMOTIONS, DELIVERIES, acting_payload


def opts(**changes):
    return dict(emotion='neutral',delivery='normal',intensity=.5,instruction='',**changes)


def test_fish_experimental_and_negative_emotions():
    for emotion in EMOTIONS:
        o={'emotion':emotion,'delivery':'normal','intensity':.5,'instruction':''}
        result=acting_payload('完整台词。','fishaudio-s21pro',o,experimental=True)
        assert result['text'].endswith('完整台词。')
    with pytest.raises(ValueError,match='实验'):
        acting_payload('台词','fishaudio-s21pro',{'emotion':'sad','delivery':'crying','intensity':.5,'instruction':''})


@pytest.mark.parametrize('delivery',list(DELIVERIES))
def test_delivery_catalog(delivery):
    o={'emotion':'sad','delivery':delivery,'intensity':.5,'instruction':''}
    assert acting_payload('台词','fishaudio-s21pro',o,experimental=True)['text'].endswith('台词')


def test_minimax_only_declared_controls():
    o={'emotion':'sad','delivery':'normal','intensity':.5,'instruction':''}
    assert acting_payload('台词','minimax-2.8-hd',o)['emotion']=='sad'
    o['delivery']='sobbing'
    with pytest.raises(ValueError): acting_payload('台词','minimax-2.8-hd',o)


def test_director_instruction_not_spoken():
    o={'emotion':'hurt','delivery':'choked','intensity':.8,'instruction':'不要喊叫'}
    fields=acting_payload('台词','qwen-audio-3.0-tts-flash',o,{'instruction':True})
    assert fields['text']=='台词'
    assert '不要喊叫' in fields['instruction'] and '委屈' in fields['instruction']
    with pytest.raises(ValueError): acting_payload('台词','qwen3-tts-flash',o,{})


def test_new_options_permissions_and_legacy():
    plugin.config.ALLOW_EXPERIMENTAL_ACTING=True
    assert plugin._options(emotion='angry',delivery='choked')['delivery']=='choked'
    with pytest.raises(ValueError): plugin._options(style='excited',emotion='sad')
    plugin.config.ALLOWED_EMOTIONS='neutral'
    with pytest.raises(ValueError): plugin._options(emotion='angry')
    with pytest.raises(ValueError): plugin._options(style='excited')


def test_no_fabricated_fish_intensity():
    with pytest.raises(ValueError,match='强度'):
        plugin._options(intensity=.9)


def test_wav_validation():
    b=io.BytesIO()
    with wave.open(b,'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(bytes(48000))
    assert plugin.validate_wav(b.getvalue())==1
    with pytest.raises(ValueError): plugin.validate_wav(b.getvalue()[:-1])
    with pytest.raises(ValueError): plugin.validate_wav(b'not wav')
