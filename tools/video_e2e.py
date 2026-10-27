"""Real-video local acceptance CLI. Never sends video, script, or audio to Gemini."""
import argparse
import json
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.storage.schemas import Project, Version
from core.video.assets import LocalAssets, sha256
from core.video.uploader import create_project
from core.video.project_manager import VideoProjectManager
from core.video.service import analyze, confirm_timeline
from core.video.renderer import render
from core.transcription.provider import FasterWhisperProvider
from core.video.errors import VideoError


def main():
    parser = argparse.ArgumentParser(description='本機真實影片：上傳、聲學辨識、保守粗剪、輸出 MP4；不呼叫 Gemini。')
    parser.add_argument('--video', type=Path, required=True)
    parser.add_argument('--script', type=Path, required=True, help='UTF-8逐字稿TXT')
    parser.add_argument('--model', default='small')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'artifacts' / 'video-e2e')
    args = parser.parse_args()
    run_dir = args.output_dir.resolve() / uuid4().hex[:12]
    run_dir.mkdir(parents=True)
    script_text = args.script.read_text(encoding='utf-8-sig').strip()
    script = Project(combination_id='A01-B01-C01', selection=dict(a='A01', b='B01', c='C01'),
        title=args.video.stem, script=script_text, versions=[Version(number=1, title=args.video.stem, script=script_text, duration=45, note='真實影片驗收快照')])
    manager, assets = VideoProjectManager(run_dir / 'project.db'), LocalAssets(run_dir / 'media')
    def progress(stage, fraction): print(stage, f'{fraction:.0%}', flush=True)
    with args.video.open('rb') as upload:
        project = create_project(script, upload, args.video.name, assets, manager, progress)
    asr = FasterWhisperProvider(args.model, ROOT / 'models' / 'whisper')
    project = analyze(project, manager, assets, asr, progress=progress)
    project = confirm_timeline(project, manager, project.suggestions, '本機驗收：僅套用安全停頓縮短，重講保留供人工確認')
    output = run_dir / '粗剪驗收.mp4'
    render(assets.source(project), output, project.timelines[-1], project.media, project.source_sha256, progress=progress)
    (run_dir / '剪輯專案.json').write_text(project.model_dump_json(indent=2), encoding='utf-8')
    print(json.dumps({'output': str(output), 'source_unchanged': sha256(args.video) == project.source_sha256,
                      'transcribed_segments': len(project.transcript.segments), 'review_items': sum(d.requires_review for d in project.suggestions)}, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except (VideoError, ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
