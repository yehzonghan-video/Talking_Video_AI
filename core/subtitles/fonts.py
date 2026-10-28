from functools import lru_cache
from pathlib import Path
from dataclasses import dataclass
import os
from core.video.errors import VideoError
from core.video.ffmpeg import run, binary


@dataclass(frozen=True)
class Font:
    path: Path
    family: str
    index: int
    codepoints: frozenset


@lru_cache(maxsize=8)
def read_font(path, modified):
    from fontTools.ttLib import TTFont, TTCollection
    path = Path(path)
    collection = TTCollection(path, lazy=True) if path.suffix.lower() in ('.ttc', '.otc') else None
    fonts = collection.fonts if collection else [TTFont(path, lazy=True)]
    try:
        indexes = sorted(range(len(fonts)), key=lambda i: ' TC' not in (fonts[i]['name'].getDebugName(16) or fonts[i]['name'].getDebugName(1) or ''))
        for index in indexes:
            font = fonts[index]
            cmap = font.getBestCmap() or {}
            if all(ord(c) in cmap for c in '繁體字幕室內設計裝潢'):
                family = font['name'].getDebugName(16) or font['name'].getDebugName(1)
                if family and not any(c in family for c in ',\r\n'):
                    return Font(path, family, index, frozenset(cmap))
    finally:
        if collection:
            collection.close()
        else:
            fonts[0].close()
    raise VideoError('字幕字型缺少繁體中文字形，請安裝 Noto Sans CJK TC；已停止燒錄以避免方框。')


def find_font(text=''):
    configured = os.environ.get('SUBTITLE_FONT_PATH')
    if configured:
        candidates = [Path(configured)]
    else:
        candidates = [Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc'),
            Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'),
            Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/msjhbd.ttc',
            Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/msjh.ttc']
    for path in candidates:
        if not path.is_file():
            continue
        try:
            font = read_font(str(path.resolve()), path.stat().st_mtime_ns)
        except VideoError:
            raise
        except Exception:
            raise VideoError('無法載入字幕字型或字型檢查套件，請由管理者確認 fonttools 與中文字型已安裝。') from None
        if any(ord(c) not in font.codepoints for c in text if not c.isspace()):
            raise VideoError('部分字幕字元不在目前字型中，請移除不支援的符號或改用完整中文字型。')
        return font
    raise VideoError('找不到繁體中文字幕字型。雲端請安裝 fonts-noto-cjk；本機可使用微軟正黑體，或設定 SUBTITLE_FONT_PATH。無字幕輸出仍可使用。')


@lru_cache(maxsize=4)
def check_libass(ffmpeg_path):
    filters = run('ffmpeg', ['-hide_banner', '-filters']).stdout
    if not any(' ass ' in line for line in filters.splitlines()):
        raise VideoError('目前 FFmpeg 沒有 libass 字幕燒錄功能，請安裝完整 FFmpeg；仍可下載 SRT 或輸出無字幕影片。')


def subtitle_capabilities(text=''):
    check_libass(binary('ffmpeg'))
    return find_font(text)
