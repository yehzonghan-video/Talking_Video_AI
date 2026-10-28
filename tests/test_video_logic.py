import json
import pytest
from core.video.schemas import Interval, Decision, Transcript, Segment, AnalysisSettings, MediaInfo, VideoProject
from core.video.timeline import build_timeline, merge_intervals, validate_timeline, filename
from core.video.errors import VideoError
from core.video.project_manager import VideoProjectManager
from core.video.service import confirm_timeline, restore_timeline, apply_automatic_timeline
from core.video.assets import LocalAssets
from core.transcription.alignment import validate_transcript
from core.editing.script_matcher import match_script
from core.editing.repetition_detector import detect_repetitions
from core.editing.edit_planner import local_plan, semantic_plan, SemanticPlan
from core.ai.provider import AIError


def transcript(*texts):
    return Transcript(provider='test-acoustic', model='test', timing='acoustic-alignment', segments=[
        Segment(id=f's{i}', start=i * 3.0, end=i * 3.0 + 2, text=t) for i, t in enumerate(texts)])


def project():
    media = MediaInfo(duration=20, width=320, height=240, display_width=320, display_height=240, fps=30,
        size=1000, format_name='mov,mp4', video_codec='h264', audio_codec='aac')
    return VideoProject(script_id='script1', title='測試影片', script_snapshot='先確認預算。', script_version=1,
        original_name='test.mp4', source_sha256='a' * 64, source_suffix='.mp4', media=media,
        timelines=[build_timeline(20, [], 1, '原片')])


@pytest.mark.parametrize('start,end', [(-1, 2), (2, 1), (1, 1), (float('nan'), 4), (0, float('inf'))])
def test_invalid_timestamps(start, end):
    with pytest.raises(ValueError): Interval(start=start, end=end)


def test_merge_overlaps_and_keep_complement():
    cuts = [Decision(start=2, end=5, kind='manual', reason='人工', selected=True, confirmed=True),
            Decision(start=4, end=7, kind='manual', reason='人工', selected=True, confirmed=True)]
    t = build_timeline(10, cuts, 2, '合併')
    assert [(s.start, s.end) for s in t.keep_segments] == [(0, 2), (7, 10)]
    validate_timeline(t)


def test_empty_or_entire_removal_forbidden():
    with pytest.raises(VideoError): build_timeline(10, [Decision(start=0, end=10, kind='manual', reason='全部', selected=True, confirmed=True)], 2, '刪除')
    with pytest.raises(VideoError): build_timeline(10, [Decision(start=0, end=11, kind='manual', reason='越界')], 2, '錯誤')


def test_selected_cut_does_not_require_manual_review_to_build_timeline():
    d = Decision(start=1, end=4, kind='retake', reason='疑似重講')
    assert build_timeline(10, [d], 1, '保留').keep_segments == [Interval(start=0, end=10)]
    d.selected = True
    timeline = build_timeline(10, [d], 1, '自動粗剪')
    assert timeline.keep_segments == [Interval(start=0, end=1), Interval(start=4, end=10)]


def test_alignment_rejects_model_guessed_and_duplicate_ids():
    tr = transcript('一句話', '另一句')
    validate_transcript(tr, 10)
    tr.timing = 'unverified'
    with pytest.raises(VideoError): validate_transcript(tr, 10)
    tr.timing = 'acoustic-alignment'
    tr.segments[1].id = tr.segments[0].id
    with pytest.raises(VideoError): validate_transcript(tr, 10)


@pytest.mark.parametrize('texts', [
    ['這個浴室我們會先做', '這個浴室我們會先做防水工程'],
    ['裝潢之前要先確認生活需求', '然後再討論合適的預算分配', '裝潢之前要先確認生活需求', '然後再討論合適的預算分配'],
    ['裝潢之前先把預算確認好', '裝潢之前先把預算確認好', '裝潢之前先把預算確認好']])
def test_single_paragraph_and_multiple_retakes(texts):
    decisions = detect_repetitions(transcript(*texts))
    assert decisions and all(d.requires_review and not d.selected and d.confidence is None for d in decisions)


def test_emphasis_and_paraphrase_are_not_auto_deleted():
    tr = transcript('防水真的很重要，非常重要。', '我會建議大家裝潢之前，先把預算抓出來。')
    decisions, matches = local_plan('裝潢前一定要先確認預算。', tr, [], AnalysisSettings(), 10)
    assert not any(d.selected for d in decisions)
    assert matches[0].status in ('matched', 'needs_review')


def test_two_takes_keep_later_complete_script_matching_version():
    tr = transcript('這個空間我們做了三成', '這個空間我們做了三層收納設計')
    decisions, _ = local_plan('這個空間我們做了三層收納設計。', tr, [], AnalysisSettings(), 10)
    automatic = [item for item in decisions if item.selected]
    assert len(automatic) == 1
    assert automatic[0].segment_ids == ['s0'] and not automatic[0].requires_review
    timeline = build_timeline(10, decisions, 2, '自動粗剪')
    assert timeline.keep_segments[0].start == pytest.approx(2)


def test_three_takes_keep_last_complete_version_but_not_last_incomplete_attempt():
    complete = '裝潢之前一定要確認水電配置'
    tr = transcript('裝潢之前一定要', complete, '裝潢之前一定要確認')
    decisions, _ = local_plan(complete + '。', tr, [], AnalysisSettings(), 12)
    automatic = [item for item in decisions if item.selected]
    assert [item.segment_ids for item in automatic] == [['s0']]
    timeline = build_timeline(12, decisions, 2, '自動粗剪')
    assert any(part.start == pytest.approx(2) and part.end == pytest.approx(12) for part in timeline.keep_segments)


def test_intentional_emphasis_is_not_treated_as_retake():
    tr = transcript('收納真的很重要', '收納真的很重要')
    decisions, _ = local_plan('收納真的很重要。', tr, [], AnalysisSettings(), 8)
    assert not any(item.selected for item in decisions)


def test_analysis_result_directly_creates_automatic_timeline_without_overwriting_source():
    p = project()
    p.suggestions = [Decision(start=3, end=5, kind='silence', action='remove', reason='長停頓',
                              requires_review=False, selected=True)]
    updated, created = apply_automatic_timeline(p)
    assert created and len(updated.timelines) == 2
    assert updated.timelines[-1].keep_segments == [Interval(start=0, end=3), Interval(start=5, end=20)]
    assert p.timelines[-1].keep_segments == [Interval(start=0, end=20)]


def test_completed_recognition_analysis_persists_directly_exportable_automatic_cut(monkeypatch, tmp_path):
    from core.video import service as video_service
    from core.video.assets import sha256
    manager, assets = VideoProjectManager(tmp_path / 'automatic.db'), LocalAssets(tmp_path / 'media')
    p = project()
    source = assets.source(p)
    source.write_bytes(b'non-destructive-source')
    p.source_sha256 = sha256(source)
    p.transcript = transcript('第一句內容', '第二句內容')
    p.transcript.model = 'already-aligned'
    p = manager.save(p)
    monkeypatch.setattr(video_service, 'detect_silences', lambda *args: [Interval(start=8, end=11)])
    class ASR:
        model_name = 'already-aligned'
    saved = video_service.analyze(p, manager, assets, ASR(), settings=AnalysisSettings())
    assert len(saved.timelines) == 2
    assert any(item.selected for item in saved.timelines[-1].decisions)
    assert '可直接預覽或輸出 MP4' in saved.analysis_note


def test_no_usable_kept_segment_has_clear_error():
    with pytest.raises(VideoError, match='不能刪除全部影片'):
        build_timeline(5, [Decision(start=0, end=5, kind='manual', reason='錯誤範圍', selected=True)], 2, '無可用片段')


def test_long_silence_preserves_breath_short_silence_kept():
    tr = transcript('開頭要先整理需求', '下一句')
    silence = [Interval(start=6, end=9), Interval(start=2.1, end=2.4)]
    decisions, _ = local_plan('開頭要先整理需求。下一句。', tr, silence, AnalysisSettings(), 12)
    automatic = [d for d in decisions if d.kind == 'silence' and d.selected]
    assert len(automatic) == 1
    assert automatic[0].start == pytest.approx(6.2)
    assert automatic[0].end == pytest.approx(8.8)


def test_quiet_speech_overlap_is_not_auto_cut():
    decisions, _ = local_plan('一句', transcript('一句話'), [Interval(start=.5, end=2.5)], AnalysisSettings(), 10)
    assert decisions and all(d.requires_review and not d.selected for d in decisions)


def test_silence_candidate_shrinks_away_from_acoustic_edges():
    tr = Transcript(provider='test', model='test', timing='acoustic-alignment', segments=[
        Segment(id='s1', start=0, end=3.48, text='第一句'),
        Segment(id='s2', start=5.91, end=9.45, text='第二句')])
    decisions, _ = local_plan('第一句。第二句。', tr, [Interval(start=3.13488, end=6.36615)], AnalysisSettings(), 10)
    automatic = [d for d in decisions if d.kind == 'silence' and d.selected]
    assert len(automatic) == 1
    assert automatic[0].start >= 3.48 + .15 - 1e-8
    assert automatic[0].end <= 5.91 - .15 + 1e-8


def test_semantic_ids_only_and_paraphrase_preserved():
    class AI:
        def generate(self, instruction, payload, schema):
            assert not any('start' in s or 'end' in s for s in payload['segments'])
            return schema(suggestions=[], matches=[dict(script_index=0, segment_ids=['s0'], status='paraphrase', reason='語意相近')])
    suggestions, matches = semantic_plan(AI(), '裝潢前確認預算。', transcript('我會建議先把預算抓出來。'), 10, .15)
    assert not suggestions and matches[0].status == 'paraphrase'


def test_ai_invalid_ids_and_noncontiguous_ranges_rejected():
    class AI:
        def __init__(self, ids): self.ids = ids
        def generate(self, instruction, payload, schema):
            return schema(suggestions=[dict(segment_ids=self.ids, reason='重講', kind='retake')], matches=[])
    tr = transcript('第一句話', '第二句話', '第三句話')
    for ids in (['invented'], ['s0', 's2']):
        with pytest.raises(AIError): semantic_plan(AI(ids), '腳本', tr, 10, .15)


def test_timeline_persistence_restore_and_snapshot(tmp_path):
    manager = VideoProjectManager(tmp_path / 'data.db')
    p = manager.save(project())
    edit = Decision(start=2, end=4, kind='manual', reason='人工', selected=True, confirmed=True)
    p = confirm_timeline(p, manager, [edit])
    restored = manager.get(p.id)
    assert len(restored.timelines) == 2 and restored.script_snapshot == '先確認預算。'
    p = restore_timeline(restored, manager, 1)
    assert len(p.timelines) == 3 and p.timelines[-1].keep_segments == [Interval(start=0, end=20)]
    p = restore_timeline(p, manager, 2)
    assert len(p.timelines[-1].keep_segments) == 2


def test_backup_import_does_not_trust_paths_or_overwrite(tmp_path):
    manager = VideoProjectManager(tmp_path / 'data.db')
    p = manager.save(project())
    restored = manager.import_metadata(p.model_dump_json().encode())
    assert restored.id != p.id and restored.script_snapshot == p.script_snapshot
    assert restored.output_key is None
    invalid = p.model_dump()
    invalid['timelines'][0]['keep_segments'][0]['end'] = 12
    with pytest.raises(VideoError): manager.import_metadata(json.dumps(invalid).encode())


def test_manual_restore_retains_removed_segment():
    d = Decision(start=2, end=4, kind='manual', reason='人工', selected=True, confirmed=True)
    assert len(build_timeline(10, [d], 2, '刪除').keep_segments) == 2
    d.selected = False
    assert build_timeline(10, [d], 3, '還原').keep_segments == [Interval(start=0, end=10)]


def test_paths_and_windows_filename(tmp_path):
    assets = LocalAssets(tmp_path / 'media')
    from core.storage.schemas import identifier
    pid = identifier()
    for key in ('../source.mp4', 'C:\\source.mp4', '/source.mp4'):
        with pytest.raises(VideoError): assets.path(pid, key)
    assert filename('CON').startswith('_')
    assert not any(c in filename('測試:/?*影片') for c in ':/?*')


def test_temp_cleanup_preserves_source_and_final(tmp_path):
    assets = LocalAssets(tmp_path / 'media')
    p = project()
    for name in ('source.mp4', 'output-v1.mp4', 'temp-audio.wav', 'preview-1.mp4'):
        assets.path(p.id, name).write_bytes(b'test')
    assert assets.temporary_cleanup(p.id) == 2
    assert assets.source(p).exists() and assets.path(p.id, 'output-v1.mp4').exists()
