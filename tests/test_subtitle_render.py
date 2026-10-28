from pathlib import Path
import pytest
from PIL import Image
from core.subtitles.schemas import SubtitleTrack, SourceCaption, Span, CaptionStyle
from core.subtitles.mapping import map_captions
from core.subtitles.fonts import find_font, subtitle_capabilities, check_libass
from core.subtitles.formats import ass
from core.subtitles.burn import preview_frame
from core.video.ffmpeg import run
from core.video.media_probe import probe
from core.video.assets import sha256
from core.video.renderer import render
from core.video.timeline import build_timeline
from core.video.schemas import Decision
from core.video.errors import VideoError
from tests.test_subtitles import caption_project
from tests.test_video_media import media_files


@pytest.fixture(params=[(192, 320), (320, 192)])
def black_video(request, tmp_path):
    w, h = request.param
    source = tmp_path / 'source.mp4'
    run('ffmpeg', ['-v', 'error', '-f', 'lavfi', '-i', f'color=c=black:s={w}x{h}:r=25:d=3',
        '-f', 'lavfi', '-i', 'sine=frequency=440:duration=3', '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'aac', '-shortest', str(source)])
    return source


def test_real_mp4_burn_traditional_yellow_outline_and_plain_output(black_video, tmp_path):
    source = black_video
    before, media = sha256(source), probe(source)
    timeline = build_timeline(media.duration, [Decision(start=1, end=2, kind='manual', reason='刪除重講', selected=True, confirmed=True)], 2, 'test')
    track = SubtitleTrack(source_signature='0' * 64, cues=[
        SourceCaption(spans=[Span(start=.1, end=.9)], text='繁體字幕\n室內設計', highlights=['室內設計']),
        SourceCaption(spans=[Span(start=1.1, end=1.9)], text='此段必須刪掉'),
        SourceCaption(spans=[Span(start=2.1, end=2.9)], text='預算先確認')])
    cues = map_captions(track, timeline)
    assert '刪掉' not in ''.join(c.text for c in cues)
    assert cues[-1].start == pytest.approx(1.1)
    burned, plain = tmp_path / 'burned.mp4', tmp_path / 'plain.mp4'
    render(source, burned, timeline, media, before, subtitles=cues, subtitle_style=CaptionStyle(preset='emphasis', font_size=72))
    render(source, plain, timeline, media, before)
    frame = tmp_path / 'frame.png'
    run('ffmpeg', ['-v', 'error', '-ss', '0.5', '-i', str(burned), '-frames:v', '1', str(frame)])
    import numpy as np
    pixels = np.asarray(Image.open(frame).convert('RGB')).reshape(-1, 3).tolist()
    assert sum(r > 130 and g > 130 and b < 100 for r, g, b in pixels) > 5
    assert sum(min(r, g, b) > 150 for r, g, b in pixels) > 5
    plain_frame = tmp_path / 'plain.png'
    run('ffmpeg', ['-v', 'error', '-ss', '0.5', '-i', str(plain), '-frames:v', '1', str(plain_frame)])
    assert np.asarray(Image.open(plain_frame).convert('RGB')).max() < 20
    info = probe(burned, decode=True)
    assert info.duration == pytest.approx(2, abs=.15)
    assert info.display_width / info.display_height == pytest.approx(media.display_width / media.display_height)
    assert abs(info.audio_duration - info.video_duration) < .15
    assert sha256(source) == before
    assert not list(tmp_path.glob('temp-*'))


def test_chinese_font_has_real_glyphs_and_ass_style():
    font = find_font('繁體字幕室內設計')
    assert all(ord(c) in font.codepoints for c in '繁體字幕室內設計')


def test_font_missing_is_clear_and_does_not_affect_plain_output(monkeypatch, tmp_path):
    monkeypatch.setenv('SUBTITLE_FONT_PATH', str(tmp_path / 'missing.ttf'))
    with pytest.raises(VideoError, match='找不到繁體'):
        find_font()


def test_latin_font_is_rejected_instead_of_tofu(monkeypatch):
    path = Path('C:/Windows/Fonts/arial.ttf')
    if not path.exists():
        path = Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
    assert path.exists(), 'Test host must supply a Latin font for the missing-glyph test'
    monkeypatch.setenv('SUBTITLE_FONT_PATH', str(path))
    with pytest.raises(VideoError, match='缺少繁體'):
        find_font()


def test_ffmpeg_without_libass_and_missing_ffmpeg(monkeypatch):
    from core.subtitles import fonts
    from types import SimpleNamespace
    monkeypatch.setattr(fonts, 'run', lambda *a, **kw: SimpleNamespace(stdout=' ... scale V->V scale'))
    with pytest.raises(VideoError, match='libass'):
        check_libass('missing-filter-test-build')
    def absent(name):
        raise VideoError('尚未安裝 ffmpeg')
    monkeypatch.setattr(fonts, 'binary', absent)
    with pytest.raises(VideoError, match='ffmpeg'):
        subtitle_capabilities()


def test_single_frame_preview_and_cache_use_output_to_source_mapping(caption_project):
    from core.subtitles.service import generate, delivery_cues
    project, manager, assets = caption_project
    project = generate(project, manager)
    cues = delivery_cues(project)
    output = assets.path(project.id, 'preview-caption-test.png')
    preview_frame(project, assets, cues[0], cues, CaptionStyle(), output)
    assert Image.open(output).height == 640
    modified = output.stat().st_mtime_ns
    preview_frame(project, assets, cues[0], cues, CaptionStyle(), output)
    assert output.stat().st_mtime_ns == modified
    assert not list(assets.project_dir(project.id).glob('temp-sub-*'))
