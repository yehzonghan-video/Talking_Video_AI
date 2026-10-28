"""Validated, reusable delivery for explicit editor output actions."""
from uuid import uuid4
from core.subtitles.service import delivery_cues, delivery_signature
from core.subtitles.formats import srt
from core.subtitles.mapping import time_map
from core.video.renderer import render
from core.video.errors import VideoError
from core.video.diagnostics import record


def export_mp4(project, manager, assets):
    signature = delivery_signature(project)
    if (project.output_key and project.output_signature == signature
            and project.output_timeline == project.timelines[-1].number
            and assets.path(project.id, project.output_key).exists()
            and assets.path(project.id, project.output_key).stat().st_size > 0):
        record('output_reused', exists=True, bytes=assets.path(project.id, project.output_key).stat().st_size)
        return project
    options = {}
    if project.subtitles and project.subtitles.enabled:
        options = {'subtitles': delivery_cues(project), 'subtitle_style': project.subtitles.style}
    key = f'output-v{project.timelines[-1].number}-{uuid4().hex[:8]}.mp4'
    render(assets.source(project), assets.path(project.id, key), project.timelines[-1], project.media, project.source_sha256, **options)
    updated = project.model_copy(deep=True)
    updated.output_key, updated.output_timeline, updated.export_status = key, project.timelines[-1].number, '已輸出'
    updated.output_signature = signature
    saved = manager.save(updated)
    record('output_reference_saved', exists=assets.path(saved.id, key).exists(), bytes=assets.path(saved.id, key).stat().st_size)
    return saved


def export_srt(project):
    cues = delivery_cues(project)
    if not cues:
        raise VideoError('目前沒有可匯出的已對齊字幕；可為無法對齊的逐字稿指定時間。')
    return srt(cues, time_map(project.timelines[-1])[-1].output_end)
