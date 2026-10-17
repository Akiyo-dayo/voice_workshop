"""Bounded acting vocabulary and provider-specific request adaptation."""
EMOTIONS = {
    'neutral': ('自然', ''), 'happy': ('开心', '[happy]'),
    'sad': ('悲伤', '[sad]'), 'angry': ('愤怒', '[angry]'),
    'fearful': ('害怕', '[scared]'), 'surprised': ('惊讶', '[surprised]'),
    'disgusted': ('厌恶', '[disgusted]'), 'excited': ('兴奋', '[excited]'),
    'gentle': ('温柔', '[gentle]'), 'comforting': ('安慰', '[comforting]'),
    'shy': ('害羞', '[shy]'), 'sarcastic': ('讽刺', '[sarcastic]'),
    'impatient': ('不耐烦', '[impatient]'), 'hurt': ('委屈', '[sad]'),
    'disappointed': ('失望', '[disappointed]'),
}
DELIVERIES = {
    'normal': ('正常说话', ''), 'whisper': ('耳语', '[whisper]'),
    'crying': ('哭腔', '[crying]'), 'sobbing': ('抽泣', '[sobbing]'),
    'choked': ('哽咽', '[choked up]'), 'laughing': ('笑着说', '[laughing]'),
    'shouting': ('喊叫', '[shouting]'), 'tired': ('疲惫低语', '[tired]'),
}
PRESETS = {
    'restrained_sadness': ('sad', 'normal', .3),
    'angry_hurt': ('angry', 'choked', .7),
    'breakdown': ('sad', 'sobbing', 1.0),
    'gentle_comfort': ('comforting', 'normal', .4),
}
# Only excited/whisper are documented in the source we verified; others are experimental.
DOCUMENTED_TAGS = {'[excited]', '[whisper]'}
MINIMAX_EMOTIONS = {'neutral','happy','sad','angry','fearful','disgusted','surprised'}


def acting_payload(text, model, options, controls=None, experimental=False):
    """Return payload fields; never silently claim unsupported acting is applied."""
    emotion, delivery = options['emotion'], options['delivery']
    intensity, instruction = options['intensity'], options['instruction']
    if emotion not in EMOTIONS or delivery not in DELIVERIES:
        raise ValueError('未知emotion/delivery，请使用配置列出的演绎选项')
    import math
    if isinstance(intensity,bool) or not isinstance(intensity,(int,float)) or not math.isfinite(intensity) or not 0 <= intensity <= 1:
        raise ValueError('intensity必须是0–1有限数值')
    fields={'text':text}
    if instruction and (not isinstance(instruction,str) or len(instruction)>1200):
        raise ValueError('instruction最多1200字符')
    if model.startswith('fishaudio-s'):
        if instruction:
            raise ValueError('Fish不支持独立instruction；请用emotion/delivery，角色指导由Agent组织台词')
        tags = [EMOTIONS[emotion][1], DELIVERIES[delivery][1]]
        if model=='fishaudio-s1' and any(tags):
            raise ValueError('S1未验证演绎标签，请使用neutral/normal或选择S2系列')
        if not experimental and any(t and t not in DOCUMENTED_TAGS for t in tags):
            raise ValueError('该Fish情绪/发声标签仍属实验，请由管理员开启ALLOW_EXPERIMENTAL_ACTING')
        if intensity != .5:
            raise ValueError('Fish未提供可靠强度字段；请省略intensity（.5），避免假装精确控制')
        fields['text']=''.join(dict.fromkeys(t for t in tags if t))+text
    elif model.startswith('minimax-'):
        if emotion not in MINIMAX_EMOTIONS or delivery!='normal' or intensity!=.5 or instruction:
            raise ValueError('MiniMax仅支持基础emotion；不支持此发声方式/强度/导演指令，请使用指令型模型')
        fields['emotion']=emotion
    elif controls and controls.get('instruction'):
        fields['instruction']=f"情绪：{EMOTIONS[emotion][0]}；发声方式：{DELIVERIES[delivery][0]}；演绎程度：{intensity:.2f}（软提示，非精确量表）。只读台词，不读指令。{instruction}"
    else:
        if emotion!='neutral' or delivery!='normal' or intensity!=.5 or instruction:
            raise ValueError('当前模型未声明支持此演绎控制')
    return fields
