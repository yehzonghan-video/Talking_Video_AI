import io
import json
from pathlib import Path
import wave
import math
import pytest
from core.video.ffmpeg import run
from core.video.media_probe import probe
from core.video.assets import LocalAssets, sha256
from core.video.project_manager import VideoProjectManager
from core.video.uploader import create_project, reattach_source
from core.video.schemas import Decision, AnalysisSettings, Transcript, Segment
from core.video.timeline import build_timeline
from core.video.renderer import render
from core.video.silence_detector import detect_silences
from core.video.service import analyze, confirm_timeline
from core.video.errors import VideoError
from core.workflow import project_from_draft
from core.ai.provider import AIError


@pytest.fixture(scope='module')
def media_files(tmp_path_factory):
    folder = tmp_path_factory.mktemp('real_media')
    audio = r'aevalsrc=if(between(t\,0.1\,1.5)+between(t\,4\,6.8)\,0.2*sin(2*PI*440*t)\,0):s=48000:d=8'
    mp4 = folder / 'source.mp4'
    run('ffmpeg', ['-v', 'error', '-nostdin', '-f', 'lavfi', '-i', 'testsrc2=size=192x320:rate=30:duration=8',
        '-f', 'lavfi', '-i', audio, '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(mp4)])
    mov = folder / 'source.mov'
    run('ffmpeg', ['-v', 'error', '-nostdin', '-i', str(mp4), '-c', 'copy', str(mov)])
    silent = folder / 'no_audio.mp4'
    run('ffmpeg', ['-v', 'error', '-nostdin', '-i', str(mp4), '-an', '-c:v', 'copy', str(silent)])
    rotated = folder / 'rotate.mp4'
    run('ffmpeg', ['-v', 'error', '-nostdin', '-i', str(mp4), '-c', 'copy', '-metadata:s:v:0', 'rotate=90', str(rotated)])
    return dict(mp4=mp4, mov=mov, silent=silent, rotated=rotated)


@pytest.mark.parametrize('kind', ['mp4', 'mov'])
def test_mp4_mov_upload_bound_snapshot_and_original_preserved(media_files, kind, tmp_path, draft, catalog):
    source = media_files[kind]
    assets = LocalAssets(tmp_path / 'media')
    manager = VideoProjectManager(tmp_path / 'db.sqlite')
    script = project_from_draft(draft, catalog.combo_id(draft.selection))
    with source.open('rb') as upload:
        p = create_project(script, upload, '../../惡意路徑.' + kind, assets, manager)
    assert assets.source(p).is_relative_to(assets.root)
    assert assets.source(p).name == 'source.' + kind
    assert sha256(assets.source(p)) == sha256(source) == p.source_sha256
    script.script = '日後改稿'
    assert manager.get(p.id).script_snapshot == draft.script
    assert p.media.display_width == 192 and p.media.display_height == 320


def test_invalid_extension_corrupt_and_non_video(tmp_path, draft, catalog):
    assets, manager = LocalAssets(tmp_path / 'media'), VideoProjectManager(tmp_path / 'db.sqlite')
    script = project_from_draft(draft, catalog.combo_id(draft.selection))
    for name, content in [('file.exe', b'abc'), ('broken.mp4', b'not an mp4'), ('empty.mov', b'')]:
        with pytest.raises(VideoError): create_project(script, io.BytesIO(content), name, assets, manager)
    assert manager.list() == []
    png = tmp_path / 'image.mp4'
    run('ffmpeg', ['-v', 'error', '-f', 'lavfi', '-i', 'color=c=black:s=32x32', '-frames:v', '1', '-f', 'image2', '-vcodec', 'png', str(png)])
    with pytest.raises(VideoError): probe(png)


def test_upload_size_limit(tmp_path):
    from core.storage.schemas import identifier
    assets = LocalAssets(tmp_path)
    with pytest.raises(VideoError, match='限制'):
        assets.write_upload(identifier(), io.BytesIO(b'x' * 200), '.mp4', max_bytes=100)


def test_no_audio_detected_and_asr_refused(media_files):
    from core.transcription.transcriber import transcribe_video
    info = probe(media_files['silent'], decode=True)
    assert info.audio_codec is None
    p = type('Project', (), {'media': info})()
    with pytest.raises(VideoError, match='沒有音軌'): transcribe_video(p, None, None)


def test_silence_detection_is_waveform_based(media_files):
    silences = detect_silences(media_files['mp4'], 8, AnalysisSettings())
    long = [s for s in silences if s.end - s.start > 1.5]
    assert len(long) == 1
    assert long[0].start == pytest.approx(1.5, abs=.1)
    assert long[0].end == pytest.approx(4, abs=.1)


@pytest.mark.parametrize('kind', ['mp4', 'silent', 'rotated'])
def test_mp4_render_sync_orientation_no_original_overwrite(media_files, kind, tmp_path):
    source = media_files[kind]
    before = sha256(source)
    info = probe(source)
    decision = Decision(start=1.7, end=3.8, kind='manual', reason='人工確認停頓', selected=True, confirmed=True)
    timeline = build_timeline(info.duration, [decision], 2, '測試')
    output = tmp_path / f'output_{kind}.mp4'
    render(source, output, timeline, info, before)
    result = probe(output, decode=True)
    assert result.video_codec == 'h264' and result.audio_codec == 'aac'
    assert result.duration == pytest.approx(info.duration - 2.1, abs=.15)
    assert result.display_width / result.display_height == pytest.approx(info.display_width / info.display_height, abs=.02)
    raw = json.loads(run('ffprobe', ['-v', 'error', '-show_streams', '-of', 'json', str(output)]).stdout)
    streams = raw['streams']
    assert abs(float(streams[0]['duration']) - float(streams[1]['duration'])) < .12
    assert abs(float(streams[0].get('start_time', 0)) - float(streams[1].get('start_time', 0))) < .08
    assert sha256(source) == before
    with pytest.raises(VideoError): render(source, source, timeline, info, before)
    with pytest.raises(VideoError): render(source, output, timeline, info, before)


def test_preview_render_and_tampered_source_rejected(media_files, tmp_path):
    source = media_files['mp4']
    info = probe(source)
    t = build_timeline(info.duration, [], 1, '原片')
    preview = tmp_path / 'preview.mp4'
    render(source, preview, t, info, sha256(source), preview=True)
    assert probe(preview).display_height <= 640
    with pytest.raises(VideoError, match='原片內容已變更'):
        render(source, tmp_path / 'bad.mp4', t, info, '0' * 64)


def test_video_project_backup_reattach_hash_check(media_files, tmp_path, draft, catalog):
    manager, assets = VideoProjectManager(tmp_path / 'db.sqlite'), LocalAssets(tmp_path / 'media')
    script = project_from_draft(draft, catalog.combo_id(draft.selection))
    with media_files['mp4'].open('rb') as f:
        p = create_project(script, f, 'source.mp4', assets, manager)
    restored = manager.import_metadata(p.model_dump_json().encode())
    assert not assets.source(restored).exists()
    with pytest.raises(VideoError, match='SHA256'):
        reattach_source(restored, io.BytesIO(b'wrong'), 'source.mp4', assets)
    with media_files['mp4'].open('rb') as f:
        reattach_source(restored, f, 'source.mp4', assets)
    assert sha256(assets.source(restored)) == p.source_sha256


def test_pipeline_caches_asr_and_ai_failure_preserves_progress(media_files, tmp_path, draft, catalog):
    manager, assets = VideoProjectManager(tmp_path / 'db.sqlite'), LocalAssets(tmp_path / 'media')
    script = project_from_draft(draft, catalog.combo_id(draft.selection))
    with media_files['mp4'].open('rb') as f:
        p = create_project(script, f, 'source.mp4', assets, manager)
    class ASR:
        model_name = 'mock-acoustic'
        calls = 0
        def transcribe(self, audio, duration, progress):
            self.calls += 1
            assert audio.exists()
            return Transcript(provider='test', model=self.model_name, timing='acoustic-alignment', segments=[
                Segment(id='s1', start=.1, end=1.5, text='先確認預算。'), Segment(id='s2', start=4, end=6.8, text='先確認預算，再整理需求。')])
    asr = ASR()
    p = analyze(p, manager, assets, asr)
    assert p.transcript and asr.calls == 1
    cached = analyze(p, manager, assets, asr)
    assert asr.calls == 1 and cached.revision == p.revision
    class FailingAI:
        model = 'test-ai'
        def generate(self, *args): raise AIError('服務繁忙')
    p = analyze(p, manager, assets, asr, FailingAI(), force=True)
    assert '服務繁忙' in p.analysis_note and manager.get(p.id).transcript
    assert p.suggestions and asr.calls == 1
    assert not list(assets.project_dir(p.id).glob('temp-*.wav'))
