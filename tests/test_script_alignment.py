import pytest
from core.subtitles.script_alignment import align_script
from core.subtitles.schemas import SubtitleTrack
from core.subtitles.mapping import map_captions
from core.subtitles.formats import srt
from core.subtitles.service import generate, resolve_unaligned
from core.video.schemas import Transcript, Segment, Word, Decision
from core.video.timeline import build_timeline
from tests.test_subtitles import caption_project
from tests.test_video_media import media_files


def speech(*texts):
    return Transcript(provider='test', model='test', timing='acoustic-alignment', segments=[
        Segment(id=f's{i}', start=i * 5 + .1, end=i * 5 + 4, text=text,
            words=[Word(text=c, start=i * 5 + .1 + j * .2, end=i * 5 + .3 + j * .2) for j, c in enumerate(text)])
        for i, text in enumerate(texts)])


def test_homophone_script_punctuation_and_asr_is_timing_only():
    script = '三層收納。'
    cues, missing = align_script(script, speech('三成收納。'), build_timeline(5, [], 1, '原片'))
    track = SubtitleTrack(cues=cues, source_signature='0'*64, text_source='script')
    final = map_captions(track, build_timeline(5, [], 1, '原片'))
    assert ''.join(c.text for c in final) == script
    assert not missing and '三成' not in srt(final, 5)


def test_script_sentence_boundaries_ignore_asr_sentences():
    script = '第一，確認水電。\n第二，確認防水。'
    tr = speech('第一確認水電第二確認防水')
    cues, missing = align_script(script, tr, build_timeline(5, [], 1, '原片'))
    assert [c.text for c in cues] == ['第一，確認水電。', '第二，確認防水。']
    assert not missing and cues[0].spans[-1].end <= cues[1].spans[0].start + .001


def test_missing_script_and_extra_speech_are_not_inserted():
    script = '先確認水電。\n陽台要安裝安全玻璃。\n再檢查防水。'
    cues, missing = align_script(script, speech('先確認水電。', '這是額外的話。', '再檢查防水。'), build_timeline(15, [], 1, '原片'))
    assert missing == ['陽台要安裝安全玻璃。']
    assert ''.join(c.text for c in cues) == '先確認水電。再檢查防水。'


def test_removed_retake_aligns_to_retained_last_version():
    tr = speech('三成收納。', '三成收納。')
    timeline = build_timeline(10, [Decision(start=0, end=5, kind='retake', reason='重講', selected=True)], 2, '自動粗剪')
    cues, missing = align_script('三層收納。', tr, timeline)
    final = map_captions(SubtitleTrack(cues=cues, source_signature='0'*64), timeline)
    assert not missing and len(final) == 1 and final[0].start == pytest.approx(.1)
    assert final[0].text == '三層收納。'


def test_unaligned_can_be_omitted_or_timed_without_blocking_valid_output(caption_project):
    p, manager, _ = caption_project
    p.script_snapshot += '\n陽台要安裝安全玻璃。'
    p = generate(p, manager)
    assert p.subtitles.unaligned
    p = resolve_unaligned(p, manager, 0)
    assert not p.subtitles.unaligned


def test_old_asr_captions_migrate_but_manual_edits_survive(caption_project):
    from core.subtitles.schemas import SourceCaption, Span
    p, manager, _ = caption_project
    p.subtitles = SubtitleTrack(source_signature='0'*64, cues=[
        SourceCaption(text='人工修字', spans=[Span(start=.1, end=1.5)], manual=True),
        SourceCaption(text='ASR錯字', spans=[Span(start=4, end=6.8)])])
    saved = generate(p, manager)
    assert saved.subtitles.text_source == 'script'
    assert [c.text for c in saved.subtitles.cues] == ['人工修字', '再安排預算。']
    assert generate(saved, manager).revision == saved.revision
