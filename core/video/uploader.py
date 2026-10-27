from pathlib import Path
from core.storage.schemas import identifier
from core.video.schemas import VideoProject
from core.video.assets import AssetStore, sha256
from core.video.media_probe import probe
from core.video.timeline import build_timeline
from core.video.errors import VideoError

MAX_UPLOAD = 500 * 1024 * 1024


def create_project(script, upload, name: str, assets: AssetStore, manager, progress=None):
    # The supplied name is display metadata only, never a filesystem location.
    suffix = Path(name.replace('\\', '/')).suffix.lower()
    project_id = identifier()
    source, digest = assets.write_upload(project_id, upload, suffix, MAX_UPLOAD)
    if progress:
        progress('讀取影片及驗證解碼', .2)
    try:
        media = probe(source, decode=True)
        project = VideoProject(id=project_id, script_id=script.id, title=script.title,
            script_snapshot=script.script, script_version=script.versions[-1].number,
            original_name=Path(name.replace('\\', '/')).name[:250], source_sha256=digest,
            source_suffix=suffix, media=media, timelines=[build_timeline(media.duration, [], 1, '原始時間軸：完整保留')])
        return manager.save(project)
    except Exception:
        source.unlink(missing_ok=True)  # Failed new upload only; no existing project is touched.
        raise


def reattach_source(project, upload, name: str, assets: AssetStore):
    if Path(name).suffix.lower() != project.source_suffix:
        raise VideoError('恢復原片的副檔名與專案不符。')
    target = assets.source(project)
    if target.exists():
        if sha256(target) != project.source_sha256:
            raise VideoError('現有原片驗證失敗，請由管理者檢查檔案；不會覆蓋。')
        return
    source, digest = assets.write_upload(project.id, upload, project.source_suffix, MAX_UPLOAD)
    try:
        if digest != project.source_sha256:
            raise VideoError('這支影片與專案原片的 SHA256 不一致，無法恢復。請選擇原本那支影片。')
        info = probe(source, decode=True)
        if abs(info.duration - project.media.duration) > .05:
            raise VideoError('影片長度與專案不一致。')
    except Exception:
        source.unlink(missing_ok=True)
        raise
