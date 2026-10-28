"""Complete real-media path: analysis -> editor payload -> MP4 with pixels."""
import numpy as np
from PIL import Image
from core.video import service
from core.video.schemas import Transcript, Segment
from core.video.assets import sha256
from core.video.ffmpeg import run
from core.video.media_probe import probe
from core.video.export_service import export_mp4
from core.editor.service import document, save_document
from core.subtitles.service import delivery_cues
from tests.test_subtitles import caption_project
from tests.test_video_media import media_files
from tests.test_visual_editor import request


def test_analysis_direct_export_with_legacy_flags_and_latest_subtitle_pixels(caption_project, monkeypatch, tmp_path):
    project, manager, assets = caption_project
    source = assets.source(project)
    # Real black H264 with audio makes burned text objectively detectable.
    run('ffmpeg', ['-y', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=black:s=192x320:r=25:d=8',
        '-f', 'lavfi', '-i', 'sine=frequency=440:duration=8', '-c:v', 'libx264', '-preset', 'ultrafast',
        '-c:a', 'aac', '-shortest', str(source)])
    project.media, project.source_sha256 = probe(source), sha256(source)
    project.script_snapshot = '這個空間我們做了三層收納設計。'
    project.transcript = Transcript(provider='test', model='cached', timing='acoustic-alignment', segments=[
        Segment(id='old', start=.1, end=2, text='這個空間我們做了三成'),
        Segment(id='new', start=3, end=7, text=project.script_snapshot)])
    project = manager.save(project)
    monkeypatch.setattr(service, 'detect_silences', lambda *a: [])
    class ASR:
        model_name = 'cached'
        def transcribe(self, *a):
            raise AssertionError('Existing recognition must be reused')
    saved = service.analyze(project, manager, assets, ASR())
    assert saved.subtitles.enabled and saved.subtitles.text_source == 'script'
    doc = document(saved)
    assert doc['sources'] and any(c['selected'] and not c['confirmed'] for c in doc['cuts'])
    assert '三成' not in ''.join(c.text for c in delivery_cues(saved))
    assert delivery_cues(saved)[0].start < 3
    payload = request(saved)
    # Old drafts may retain false confirmation fields. Editing then exporting
    # must consume exactly this latest text/style, without another save action.
    for c in payload['captions']:
        c['confirmed'] = False
    payload['captions'][-1]['text'] = '繁體字幕已經更新'
    payload['captions'][-1]['highlights'] = ['字幕']
    payload['style'].update(preset='emphasis', font_size=72)
    saved = save_document(saved.id, manager, payload)
    burned = export_mp4(saved, manager, assets)
    from ui import downloads
    registered = []
    monkeypatch.setattr(downloads.st, 'session_state', {})
    monkeypatch.setattr(downloads.st, 'download_button', lambda *a, **kw: registered.append(kw))
    downloads.mp4_download(burned, assets)
    assert registered[0]['data'] == assets.path(burned.id, burned.output_key).read_bytes()
    assert registered[0]['mime'] == 'video/mp4'
    assert '已經更新' in delivery_cues(burned)[-1].text
    frame = tmp_path / 'burned.png'
    run('ffmpeg', ['-v', 'error', '-ss', '2', '-i', str(assets.path(burned.id, burned.output_key)), '-frames:v', '1', str(frame)])
    pixels = np.asarray(Image.open(frame).convert('RGB'))
    assert np.sum(np.all(pixels > 150, axis=2)) > 5
    assert np.sum((pixels[:, :, 0] > 130) & (pixels[:, :, 1] > 130) & (pixels[:, :, 2] < 100)) > 5
    burned.subtitles.enabled = False
    plain = export_mp4(manager.save(burned), manager, assets)
    run('ffmpeg', ['-v', 'error', '-ss', '2', '-i', str(assets.path(plain.id, plain.output_key)), '-frames:v', '1', str(tmp_path / 'plain.png')])
    assert np.asarray(Image.open(tmp_path / 'plain.png')).max() < 20
    before = manager.get(plain.id).revision
    assert service.prepare_delivery(manager.get(plain.id), manager).revision == before


def test_existing_analysis_gets_captions_once_preserves_manual_and_disabled(caption_project):
    project, manager, _ = caption_project
    ready = service.prepare_delivery(project, manager)
    assert ready.subtitles.enabled
    payload = request(ready)
    payload['captions'][0]['text'] = '人工字幕最高優先'
    payload['enabled'] = False
    saved = save_document(ready.id, manager, payload)
    again = service.prepare_delivery(saved, manager)
    assert again.revision == saved.revision
    assert not again.subtitles.enabled and again.subtitles.cues[0].text == '人工字幕最高優先'
