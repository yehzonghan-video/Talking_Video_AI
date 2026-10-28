import pytest
from core.subtitles.service import generate, save_preferences
from core.subtitles.schemas import SubtitleTrack, SourceCaption, Span
from core.video.schemas import Transcript, Segment, Word
from tests.test_video_ui import prepare, open_video
from tests.test_video_media import media_files
from tests.test_ui import by_label
from core.video.uploader import create_project
from core.workflow import project_from_draft


def test_caption_ui_generation_style_and_toggle_make_no_ai_or_asr_calls(monkeypatch, repo, catalog, fake, tmp_path, draft, media_files):
    manager, assets = prepare(monkeypatch, repo, catalog, fake, tmp_path)
    script = repo.save(project_from_draft(draft, catalog.combo_id(draft.selection)))
    with media_files['mp4'].open('rb') as stream:
        project = create_project(script, stream, 'source.mp4', assets, manager)
    project.transcript = Transcript(provider='test', model='small', timing='acoustic-alignment', segments=[
        Segment(id='s1', start=.1, end=1.5, text='確認預算。', words=[Word(start=.1, end=.8, text='確認'), Word(start=.8, end=1.5, text='預算。')])])
    manager.save(project)
    def forbidden(*args, **kwargs):
        raise AssertionError('Subtitles must not invoke ASR or Gemini')
    from core.transcription.provider import FasterWhisperProvider
    monkeypatch.setattr(FasterWhisperProvider, 'transcribe', forbidden)
    fake.generate = forbidden
    at = open_video()
    by_label(at.button, '由現有辨識產生字幕').click().run()
    assert not at.exception and manager.get(project.id).subtitles
    by_label(at.selectbox, '字幕樣式').set_value('重點字幕')
    by_label(at.slider, '字體大小').set_value(64)
    by_label(at.button, '保存字幕與樣式').click().run()
    assert not at.exception
    saved = manager.get(project.id)
    assert saved.subtitles.style.preset == 'emphasis' and saved.subtitles.style.font_size == 64
    by_label(at.checkbox, '輸出影片開啟字幕').uncheck().run()
    assert not at.exception and not manager.get(project.id).subtitles.enabled
    assert not assets.path(project.id, 'preview-1.mp4').exists()
    at.run()
    assert not at.exception


def test_unreviewed_caption_can_be_disabled_without_losing_edits(monkeypatch, repo, catalog, fake, tmp_path, draft, media_files):
    manager, assets = prepare(monkeypatch, repo, catalog, fake, tmp_path)
    script = repo.save(project_from_draft(draft, catalog.combo_id(draft.selection)))
    with media_files['mp4'].open('rb') as stream:
        project = create_project(script, stream, 'source.mp4', assets, manager)
    project.subtitles = SubtitleTrack(source_signature='0' * 64, cues=[SourceCaption(text='人工修字仍保留', spans=[Span(start=0, end=1)], review_reason='需確認')])
    manager.save(project)
    at = open_video()
    by_label(at.checkbox, '輸出影片開啟字幕').uncheck().run()
    saved = manager.get(project.id)
    assert not at.exception and not saved.subtitles.enabled
    assert saved.subtitles.cues[0].text == '人工修字仍保留' and saved.subtitles.cues[0].review_reason
