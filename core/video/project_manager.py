from pathlib import Path
from core.storage.project_manager import SQLiteRepository, StorageError
from core.storage.schemas import now, identifier
from core.video.schemas import VideoProject
from core.video.timeline import validate_timeline
from core.transcription.alignment import validate_transcript
from core.editing.edit_validator import validate_decisions
from core.video.errors import VideoError


def validate_project(project: VideoProject):
    for timeline in project.timelines:
        if abs(timeline.duration - project.media.duration) > .001:
            raise VideoError('時間軸長度與原始影片不一致。')
        validate_timeline(timeline)
        validate_decisions(timeline.decisions, project.media.duration, project.transcript)
    if project.transcript:
        validate_transcript(project.transcript, project.media.duration)
    validate_decisions(project.suggestions, project.media.duration, project.transcript)
    if any(s.end > project.media.duration for s in project.silences):
        raise VideoError('停頓時間超出影片長度。')
    if project.subtitles:
        for cue in project.subtitles.cues:
            if any(s.end > project.media.duration for s in cue.spans):
                raise VideoError('字幕原始時間超出影片長度。')
            if any(b.start < a.end for a, b in zip(cue.spans, cue.spans[1:])):
                raise VideoError('字幕來源片段必須依原片時間排序且不能重疊。')
            if any(not any(a.start >= s.start - .001 and a.end <= s.end + .001 for s in cue.spans) for a in cue.atoms):
                raise VideoError('字幕詞語時間超出來源區間。')


class VideoProjectManager:
    """Adds one table to the existing SQLite DB; phase-one schema stays unchanged."""
    def __init__(self, database: str | Path):
        self.backend = SQLiteRepository(database)
        with self.backend.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS video_projects (id TEXT PRIMARY KEY, revision INTEGER NOT NULL, payload TEXT NOT NULL)')

    def list(self) -> list[VideoProject]:
        with self.backend.connection() as db:
            rows = db.execute('SELECT payload FROM video_projects').fetchall()
        return sorted([VideoProject.model_validate_json(r[0]) for r in rows], key=lambda p: p.updated_at, reverse=True)

    def get(self, project_id: str) -> VideoProject:
        with self.backend.connection() as db:
            row = db.execute('SELECT payload FROM video_projects WHERE id=?', (project_id,)).fetchone()
        if not row:
            raise VideoError('找不到剪輯專案，請從專案清單重新選擇。')
        return VideoProject.model_validate_json(row[0])

    def save(self, project: VideoProject) -> VideoProject:
        project = VideoProject.model_validate(project.model_dump())
        validate_project(project)
        with self.backend.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT revision FROM video_projects WHERE id=?', (project.id,)).fetchone()
            if (row is None and project.revision != 0) or (row is not None and row[0] != project.revision):
                raise StorageError('剪輯專案已在其他視窗變更，請先下載目前資料，再重新開啟專案。')
            saved = project.model_copy(update={'revision': project.revision + 1, 'updated_at': now()})
            db.execute('INSERT OR REPLACE INTO video_projects VALUES (?,?,?)', (saved.id, saved.revision, saved.model_dump_json()))
        return saved

    def import_metadata(self, content: bytes) -> VideoProject:
        if len(content) > 20_000_000:
            raise VideoError('專案 JSON 超過20 MB。')
        project = VideoProject.model_validate_json(content)
        validate_project(project)
        # Never trust imported filesystem paths or overwrite an existing project.
        project.id = identifier()
        project.revision = 0
        project.output_key, project.output_timeline, project.export_status = None, None, '未輸出'
        project.output_signature = ''
        return self.save(project)
