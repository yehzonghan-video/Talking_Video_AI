"""Explicit pipeline steps, durable checkpoints, no UI or hidden API reruns."""
import hashlib
from core.ai.provider import AIError
from core.video.assets import sha256
from core.video.schemas import AnalysisSettings, Timeline
from core.video.timeline import build_timeline
from core.video.silence_detector import detect_silences
from core.transcription.transcriber import transcribe_video
from core.editing.edit_planner import local_plan, semantic_plan
from core.video.errors import VideoError


def analyze(project, manager, assets, asr, ai=None, settings=None, force=False, progress=None):
    settings = settings or AnalysisSettings()
    update = progress or (lambda *args: None)
    update('讀取影片', .02)
    source = assets.source(project)
    if not source.exists() or sha256(source) != project.source_sha256:
        raise VideoError('原片遺失或已變更，請先恢復原片。')
    signature = hashlib.sha256((project.source_sha256 + settings.model_dump_json() + asr.model_name +
                                str(getattr(ai, 'model', 'local-only'))).encode()).hexdigest()
    if project.analysis_signature == signature and not force:
        update('已讀取先前的分析結果，沒有重複呼叫', 1.0)
        return project
    project = project.model_copy(deep=True)
    if project.transcript is None or project.transcript.model != asr.model_name:
        update('語音辨識：第一次使用需下載模型，之後可重複使用', .08)
        project.transcript = transcribe_video(project, assets, asr, update)
        project = manager.save(project)  # ASR survives a later network failure.
    update('腳本比對', .45)
    if not project.transcript.segments:
        raise VideoError('沒有辨識到可用語音，已保留原片；請確認音量或使用人工剪輯。')
    update('停頓分析', .55)
    silences = detect_silences(source, project.media.duration, settings)
    update('重講分析', .65)
    suggestions, matches = local_plan(project.script_snapshot, project.transcript, silences, settings, project.media.duration)
    project.silences, project.suggestions, project.matches = silences, suggestions, matches
    project.settings = settings
    project.analysis_note = '完成本機聲學與文字分析；語音刪除仍需逐項確認。'
    project = manager.save(project)
    if ai:
        update('產生 AI 語意剪輯建議', .78)
        try:
            extra, semantic_matches = semantic_plan(ai, project.script_snapshot, project.transcript, project.media.duration, settings.padding)
            # Semantic judgments replace duplicate lexical suggestions, retaining silence suggestions.
            if extra:
                project.suggestions = [s for s in suggestions if s.kind == 'silence'] + extra
            by_index = {m.script_index: m for m in matches}
            by_index.update({m.script_index: m for m in semantic_matches})
            project.matches = [by_index[i] for i in sorted(by_index)]
            project.analysis_note = '完成本機時間分析及 AI 語意比對；所有語音刪除預設保留，請逐項確認。'
        except AIError as exc:
            project.analysis_note = str(exc) + ' 已保留本機停頓、重講分析，可先人工確認。'
            # Do not cache a failed semantic call as a successful analysis.
            project.analysis_signature = ''
            return manager.save(project)
    project.analysis_signature = signature
    update('剪輯建議已完成，請確認時間軸', 1.0)
    return manager.save(project)


def confirm_timeline(project, manager, decisions, note='人工確認剪輯'):
    project = project.model_copy(deep=True)
    timeline = build_timeline(project.media.duration, decisions, len(project.timelines) + 1, note)
    project.timelines.append(timeline)
    project.output_key, project.output_timeline, project.export_status = None, None, '未輸出'
    return manager.save(project)


def restore_timeline(project, manager, number):
    target = next((t for t in project.timelines if t.number == number), None)
    if target is None:
        raise VideoError('找不到指定剪輯版本。')
    return confirm_timeline(project, manager, target.decisions, f'恢復剪輯 V{number}')
