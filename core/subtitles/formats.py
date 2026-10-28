import html
from core.subtitles.mapping import validate_output
from core.subtitles.segmentation import width as text_width
from core.video.errors import VideoError


def timestamp(seconds, *, ass=False):
    units = round(seconds * (100 if ass else 1000))
    base = 100 if ass else 1000
    whole, fraction = divmod(units, base)
    minutes, second = divmod(whole, 60)
    hour, minute = divmod(minutes, 60)
    return f'{hour}:{minute:02d}:{second:02d}.{fraction:02d}' if ass else f'{hour:02d}:{minute:02d}:{second:02d},{fraction:03d}'


def srt(cues, duration):
    validate_output(cues, duration)
    return '\n\n'.join(f'{i}\n{timestamp(c.start)} --> {timestamp(c.end)}\n{html.escape(c.text, quote=False)}'
                        for i, c in enumerate(cues, 1)) + ('\n' if cues else '')


def ass_text(cue, emphasis):
    plain = cue.text.replace('\n', '')
    marked = set()
    if emphasis:
        for highlight in cue.highlights:
            start = 0
            while highlight and (index := plain.find(highlight, start)) >= 0:
                marked.update(range(index, index + len(highlight)))
                start = index + len(highlight)
    rendered, cursor, yellow = '', 0, False
    for char in cue.text:
        if char == '\n':
            rendered += r'\N'
            continue
        active = cursor in marked
        if active != yellow:
            rendered += r'{\c&H00FFFF&}' if active else r'{\c&HFFFFFF&}'
            yellow = active
        # ASS override syntax is generated only here, never accepted from users.
        rendered += {'\\': '＼', '{': '｛', '}': '｝'}.get(char, char)
        cursor += 1
    return rendered


def ass(cues, style, font, width, height, duration):
    validate_output(cues, duration)
    res_y = round(1080 * height / width)
    margin = round(res_y * style.bottom_percent / 100)
    header = f'''[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: {res_y}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font.family},{style.font_size},&H00FFFFFF,&H0000FFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,3,0,2,54,54,{margin},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    events = []
    for cue in cues:
        longest = max((text_width(line) for line in cue.text.splitlines()), default=1)
        size = min(style.font_size, int(972 / max(1, longest)))
        if size < 16:
            raise VideoError('字幕單行太長，請增加換行或分段後再輸出。')
        events.append(f'Dialogue: 0,{timestamp(cue.start, ass=True)},{timestamp(cue.end, ass=True)},Default,,0,0,0,,{{\\fs{size}}}{ass_text(cue, style.preset == "emphasis")}')
    return header + '\n'.join(events) + '\n'
