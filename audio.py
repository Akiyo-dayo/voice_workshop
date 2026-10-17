"""Audio integrity checks; validate transport/frames, not spoken completeness."""


def validate_wav(data: bytes) -> float:
    import io
    import wave
    import struct
    if len(data)<44 or data[:4]!=b'RIFF' or data[8:12]!=b'WAVE':
        raise ValueError('无效WAV文件')
    if struct.unpack_from('<I',data,4)[0]+8 != len(data):
        raise ValueError('WAV长度不完整')
    with wave.open(io.BytesIO(data),'rb') as f:
        frames=f.getnframes()
        body=f.readframes(frames)
        if not frames or len(body)!=frames*f.getnchannels()*f.getsampwidth():
            raise ValueError('WAV采样数据不完整')
        return frames/f.getframerate()



def validate_mp3(data: bytes) -> float:
    """Return frame duration, rejecting truncated or invalid MPEG Layer III data."""
    pos = 0
    if data.startswith(b"ID3"):
        if len(data) < 10 or any(x & 0x80 for x in data[6:10]):
            raise ValueError("无效 ID3 标签")
        size = sum(x << shift for x, shift in zip(data[6:10], (21, 14, 7, 0)))
        pos = 10 + size + (10 if data[5] & 0x10 else 0)
    frames = 0
    duration = 0.0
    while pos < len(data):
        remaining = len(data) - pos
        if remaining == 128 and data[pos:pos + 3] == b"TAG":
            break
        if data[pos] == 0 and not data[pos:].strip(b"\x00"):
            break
        if pos + 4 > len(data):
            raise ValueError("MP3 帧头截断")
        header = int.from_bytes(data[pos:pos + 4], "big")
        version = (header >> 19) & 3
        layer = (header >> 17) & 3
        bitrate_index = (header >> 12) & 15
        rate_index = (header >> 10) & 3
        if header >> 21 != 0x7FF or version == 1 or layer != 1 or bitrate_index in (0, 15) or rate_index == 3:
            raise ValueError("响应不是完整的 MP3 Layer III 音频")
        rates = (44100, 48000, 32000)
        rate = rates[rate_index] // (1 if version == 3 else 2 if version == 2 else 4)
        bitrates = (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320) if version == 3 else (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160)
        length = (144000 if version == 3 else 72000) * bitrates[bitrate_index] // rate + ((header >> 9) & 1)
        if pos + length > len(data):
            raise ValueError("MP3 最后一帧不完整，拒绝发送截断音频")
        duration += (1152 if version == 3 else 576) / rate
        frames += 1
        pos += length
    if frames < 2:
        raise ValueError("返回音频没有足够的有效 MP3 帧")
    return duration
