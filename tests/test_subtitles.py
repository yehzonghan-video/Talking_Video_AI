import math
import pytest
from pydantic import ValidationError
from core.subtitles.schemas import SubtitleTrack, SourceCaption, Span, CaptionStyle
from core.subtitles.segmentation import from_transcript, wrap, lexical
from core.subtitles.mapping import time_map, map_captions, output_to_source, validate_output
from core.subtitles.service import generate, save_edits, delivery_cues, delivery_signature
from core.subtitles.formats import srt, ass, ass_text
from core.video.schemas import Transcript, Segment, Word, Decision
from core.video.timeline import build_timeline
from core.video.errors import VideoError
from core.video.project_manager import VideoProjectManager
from core.video.assets import LocalAssets
from core.video.uploader import create_project
from core.video.service import confirm_timeline, restore_timeline
from core.workflow import project_from_draft
from tests.test_video_media import media_files


def transcript():
    texts = ['先确认实际需求。', '这段讲错重讲。', '室内设计先安排预算。']
    return Transcript(provider='test', model='mock', timing='acoustic-alignment', segments=[
        Segment(id=f's{i}', start=i * 5 + .1, end=i * 5 + 4, text=text,
            words=[Word(start=i * 5 + .1 + j * .35, end=i * 5 + .4 + j * .35, text=c) for j, c in enumerate(text)])
        for i, text in enumerate(texts)])


def track():
    return SubtitleTrack(source_signature='0' * 64, cues=from_transcript(transcript()))


def cut_timeline():
    return build_timeline(15, [Decision(start=5, end=10, kind='manual', reason='刪除口誤', selected=True, confirmed=True)], 2, 'test')


@pytest.fixture
def caption_project(media_files, tmp_path, draft, catalog):
    manager, assets = VideoProjectManager(tmp_path / 'subtitle.db'), LocalAssets(tmp_path / 'media')
    with media_files['mp4'].open('rb') as upload:
        project = create_project(project_from_draft(draft, catalog.combo_id(draft.selection)), upload, 'test.mp4', assets, manager)
    project.transcript = Transcript(provider='test', model='mock', timing='acoustic-alignment', segments=[
        Segment(id='s1', start=.1, end=1.5, text='先确认需求。', words=[
            Word(start=.1, end=.4, text='先'), Word(start=.4, end=.8, text='确认'), Word(start=.8, end=1.5, text='需求。')]),
        Segment(id='s2', start=4, end=6.8, text='再安排预算。', words=[
            Word(start=4, end=4.4, text='再'), Word(start=4.4, end=5.4, text='安排'), Word(start=5.4, end=6.8, text='预算。')])])
    project = manager.save(project)
    return project, manager, assets


def editable(cues):
    return [dict(id=c.id, start=c.start, end=c.end, text=c.text, highlights=c.highlights, confirmed=True) for c in cues]


def test_traditional_generation_has_only_spoken_content_and_readable_lines():
    cues = track().cues
    assert '確認' in ''.join(c.text for c in cues) and '室內' in ''.join(c.text for c in cues)
    assert lexical(''.join(c.text for c in cues)) == lexical(''.join(s.text for s in transcript().segments))
    assert all(1 <= len(c.text.splitlines()) <= 2 for c in cues)
    assert all(c.spans[0].end > c.spans[0].start for c in cues)


def test_linguistic_wrap_preserves_words_and_punctuation():
    text = '這個空間的室內設計需要先確認預算，再安排收納空間。'
    wrapped = wrap(text)
    assert wrapped.replace('\n', '') == text
    assert '室內\n設計' not in wrapped and '預\n算' not in wrapped


def test_long_segment_without_words_is_not_given_fake_character_times():
    tr = Transcript(provider='legacy', model='small', timing='acoustic-alignment', segments=[
        Segment(id='s', start=1, end=14, text='這是一段很長的實際口播內容但是沒有任何詞語時間所以不能猜測分段時間')])
    cues = from_transcript(tr)
    assert len(cues) == 1 and not cues[0].atoms and cues[0].review_reason
    assert (cues[0].spans[0].start, cues[0].spans[0].end) == (1, 14)


def test_original_output_mapping_removes_retake_and_shifts_correct_speech():
    mapping = time_map(cut_timeline())
    assert [(m.source_start, m.source_end, m.output_start, m.output_end) for m in mapping] == [(0, 5, 0, 5), (10, 15, 5, 10)]
    cues = map_captions(track(), cut_timeline())
    assert '講錯' not in ''.join(c.text for c in cues)
    assert cues[-1].start == pytest.approx(5.1)
    assert output_to_source(4, 6, cut_timeline()) == [Span(start=4, end=5), Span(start=10, end=11)]


def test_cutting_automatic_caption_filters_deleted_words():
    tr = SubtitleTrack(source_signature='0' * 64, cues=[SourceCaption(text='一二三四', spans=[Span(start=0, end=4)],
        atoms=[dict(start=i, end=i + .9, text=c) for i, c in enumerate('一二三四')])])
    timeline = build_timeline(4, [Decision(start=1, end=3, kind='manual', reason='test', selected=True, confirmed=True)], 2, 'test')
    cues = map_captions(tr, timeline)
    assert ''.join(c.text for c in cues) == '一四'
    assert cues[-1].start == 1


def test_partial_word_cut_requires_review():
    tr = SubtitleTrack(source_signature='0' * 64, cues=[SourceCaption(text='預算', spans=[Span(start=0, end=2)],
        atoms=[dict(start=0, end=2, text='預算')])])
    timeline = build_timeline(3, [Decision(start=1, end=2, kind='manual', reason='test', selected=True, confirmed=True)], 2, 'test')
    cues = map_captions(tr, timeline)
    assert cues and cues[0].needs_review
    validate_output(cues, 2, require_reviewed=True)  # Legacy flag is advisory.


def test_manual_caption_cut_is_retained_and_low_confidence_does_not_block_delivery():
    tr = SubtitleTrack(source_signature='0' * 64, cues=[SourceCaption(text='人工修好的實際口播', spans=[Span(start=4, end=12)], manual=True)])
    cue = map_captions(tr, cut_timeline())[0]
    assert cue.text == '人工修好的實際口播' and cue.needs_review
    assert (cue.start, cue.end) == (4, 7)
    validate_output([cue], 10)


@pytest.mark.parametrize('start,end', [(-1, 2), (2, 1), (0, math.nan), (0, math.inf), (0, 11)])
def test_invalid_output_times_rejected(start, end):
    with pytest.raises((ValidationError, VideoError)):
        output_to_source(start, end, cut_timeline())


def test_generate_edit_backup_restore_and_cache_without_ai_or_asr(caption_project):
    project, manager, _ = caption_project
    project = generate(project, manager)
    again = generate(project, manager)
    assert again.revision == project.revision
    cues = delivery_cues(project)
    rows = editable(cues)
    rows[0]['text'] = '先確認空間需求。'
    rows[0]['highlights'] = '空間需求'
    project = save_edits(project, manager, rows, CaptionStyle(preset='emphasis'), True)
    assert delivery_cues(manager.get(project.id))[0].text == '先確認空間需求。'
    restored = manager.import_metadata(project.model_dump_json().encode())
    assert restored.subtitles == project.subtitles and restored.id != project.id
    assert project.script_snapshot == manager.get(project.id).script_snapshot


def test_manual_split_and_merge_using_output_coordinates(caption_project):
    project, manager, _ = caption_project
    project = generate(project, manager)
    rows = [dict(start=.1, end=.8, text='先確認', highlights=[], confirmed=True),
            dict(start=.8, end=1.5, text='需求。', highlights=[], confirmed=True)]
    saved = save_edits(project, manager, rows, CaptionStyle(), True)
    assert [c.text for c in delivery_cues(saved)] == ['先確認', '需求。']
    merged = save_edits(saved, manager, [dict(start=.1, end=1.5, text='先確認需求。')], CaptionStyle(), True)
    assert len(delivery_cues(merged)) == 1


def test_manual_edits_survive_cut_change_and_review(caption_project):
    project, manager, _ = caption_project
    project = generate(project, manager)
    rows = editable(delivery_cues(project))
    rows[1]['text'] = '再安排實際預算。'
    project = save_edits(project, manager, rows, CaptionStyle(), True)
    project = confirm_timeline(project, manager, [Decision(start=4, end=5, kind='manual', reason='test', selected=True, confirmed=True)])
    assert project.subtitles.cues[-1].text == '再安排實際預算。'
    assert delivery_cues(project)[-1].text == '再安排實際預算。'
    mapped = map_captions(project.subtitles, project.timelines[-1])
    rows = editable(mapped)
    rows[-1]['text'] = '實際預算。'
    project = save_edits(project, manager, rows, CaptionStyle(), True)
    assert delivery_cues(project)[-1].start == 4


def test_restore_cut_restores_hidden_acoustic_captions(caption_project):
    project, manager, _ = caption_project
    project = generate(project, manager)
    project = confirm_timeline(project, manager, [Decision(start=3, end=7, kind='manual', reason='test', selected=True, confirmed=True)])
    project = save_edits(project, manager, editable(delivery_cues(project)), CaptionStyle(), True)
    project = restore_timeline(project, manager, 1)
    assert '預算' in ''.join(c.text for c in delivery_cues(project))


def test_invalid_highlight_overlap_and_blank_are_not_saved(caption_project):
    project, manager, _ = caption_project
    project = generate(project, manager)
    rows = editable(delivery_cues(project))
    rows[0]['highlights'] = '沒有說的話'
    with pytest.raises(VideoError, match='已有'):
        save_edits(project, manager, rows, CaptionStyle(), True)
    rows[0]['highlights'] = ''
    rows[1]['start'] = .2
    with pytest.raises(VideoError, match='重疊'):
        save_edits(project, manager, rows, CaptionStyle(), True)
    assert manager.get(project.id).revision == project.revision


def test_srt_and_ass_use_mapped_time_and_safe_highlight():
    cues = map_captions(track(), cut_timeline())
    text = srt(cues, 10)
    assert '00:00:05,100' in text and '講錯' not in text and '室內' in text
    cue = cues[0].model_copy(update={'text': r'預算{\pos(0,0)}', 'highlights': ['預算']})
    rendered = ass_text(cue, True)
    assert r'{\c&H00FFFF&}' in rendered and r'{\pos' not in rendered
    basic = ass_text(cue, False)
    assert '00FFFF' not in basic


def test_export_signature_changes_with_style_text_enable_and_cut(caption_project):
    project, manager, _ = caption_project
    original = delivery_signature(project)
    project = generate(project, manager)
    generated = delivery_signature(project)
    assert generated != original
    project.subtitles.style.font_size += 1
    assert delivery_signature(project) != generated
    project.subtitles.enabled = False
    assert delivery_signature(project) == original


def test_old_phase_two_backup_defaults_to_no_subtitles(caption_project):
    project, manager, _ = caption_project
    raw = project.model_dump()
    raw.pop('subtitles')
    raw.pop('output_signature')
    from core.video.schemas import VideoProject
    legacy = VideoProject.model_validate(raw)
    assert legacy.subtitles is None and manager.save(legacy).subtitles is None


def test_supplement_reuses_good_times_and_only_transcribes_missing_long_segment(caption_project):
    from core.subtitles.alignment import supplement
    project, manager, assets = caption_project
    project.transcript.segments[1].text = '再確認實際生活需求之後安排預算並且確認所有工程的項目與報價'
    project.transcript.segments[1].words = []
    before = project.transcript.model_dump_json()
    class ASR:
        calls = 0
        def transcribe(self, audio, duration):
            self.calls += 1
            assert duration == pytest.approx(2.8)
            return Transcript(provider='test', model='mock', timing='acoustic-alignment', segments=[
                Segment(id='new', start=0, end=duration, text='再確認需求', words=[Word(start=0, end=duration, text='再確認需求')])])
    asr = ASR()
    aligned = supplement(project, assets, asr)
    assert asr.calls == 1 and aligned.segments[0] == project.transcript.segments[0]
    assert aligned.segments[1].words[0].start == 4
    assert project.transcript.model_dump_json() == before
    assert not list(assets.project_dir(project.id).glob('temp-sub-align-*'))


def test_supplement_is_noop_when_existing_word_times_are_usable(caption_project):
    from core.subtitles.alignment import supplement
    project, manager, assets = caption_project
    class ASR:
        def transcribe(self, *args):
            raise AssertionError('No repeat ASR allowed')
    assert supplement(project, assets, ASR()) == project.transcript


def test_edit_one_split_fragment_then_restore_does_not_duplicate_captions(caption_project):
    project, manager, _ = caption_project
    project = generate(project, manager)
    project = confirm_timeline(project, manager, [Decision(start=4.4, end=5.4, kind='manual', reason='test', selected=True, confirmed=True)])
    rows = editable(delivery_cues(project))
    rows[1]['text'] = '先'
    project = save_edits(project, manager, rows, CaptionStyle(), True)
    project = restore_timeline(project, manager, 1)
    cues = delivery_cues(project)
    assert ''.join(c.text for c in cues).count('預算') == 1
    assert any(c.text == '先' for c in cues)


def test_failed_supplement_preserves_saved_subtitles_and_original_transcript(caption_project):
    from core.subtitles.alignment import supplement
    project, manager, assets = caption_project
    project.transcript.segments[1].text = '這是一段很長但是沒有詞語時間的口播需要確認時間與字幕分段'
    project.transcript.segments[1].words = []
    project = manager.save(project)
    project = generate(project, manager)
    before = manager.get(project.id).model_dump_json()
    class ASR:
        def transcribe(self, *args):
            raise VideoError('補充辨識失敗')
    with pytest.raises(VideoError, match='補充辨識失敗'):
        supplement(project, assets, ASR())
    assert manager.get(project.id).model_dump_json() == before
    assert not list(assets.project_dir(project.id).glob('temp-sub-align-*'))
