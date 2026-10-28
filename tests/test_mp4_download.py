from pathlib import Path
import pytest
from streamlit.runtime.media_file_manager import MediaFileManager
from streamlit.runtime.memory_media_file_storage import MemoryMediaFileStorage
from streamlit.runtime.media_file_storage import MediaFileStorageError
from tests.test_subtitles import caption_project
from tests.test_video_media import media_files


def test_real_sdk_deferred_download_orphan_reproduced_and_eager_reference_survives(monkeypatch):
    from streamlit.runtime import media_file_manager as module
    monkeypatch.setattr(module, '_get_session_id', lambda: 'session')
    store = MemoryMediaFileStorage('/media')
    manager = MediaFileManager(store)
    deferred = manager.add_deferred(lambda: b'video-test', 'video/mp4', 'download', '影片.mp4')
    url = manager.execute_deferred(deferred)
    manager.remove_orphaned_files()
    manager.remove_orphaned_files()
    with pytest.raises(MediaFileStorageError):
        store.get_file(Path(url).name)
    stable = manager.add(b'video-test', 'video/mp4', 'download', file_name='影片.mp4', is_for_static_download=True)
    manager.remove_orphaned_files()
    manager.remove_orphaned_files()
    assert store.get_file(Path(stable).name).content == b'video-test'


def test_download_uses_stable_mp4_bytes_mime_filename_and_survives_rerun(caption_project, monkeypatch):
    from ui import downloads
    p, _, assets = caption_project
    p.output_key = 'output-v1-test.mp4'
    assets.path(p.id, p.output_key).write_bytes(b'completed-video')
    calls = []
    monkeypatch.setattr(downloads.st, 'session_state', {})
    monkeypatch.setattr(downloads.st, 'download_button', lambda *a, **kw: calls.append(kw))
    downloads.mp4_download(p, assets)
    assets.temporary_cleanup(p.id)
    downloads.mp4_download(p, assets)
    assert len(calls) == 2 and all(c['data'] == b'completed-video' for c in calls)
    assert calls[0]['mime'] == 'video/mp4' and calls[0]['file_name'].endswith('_粗剪.mp4')
    assert calls[0]['on_click'] == 'ignore' and not callable(calls[0]['data'])
