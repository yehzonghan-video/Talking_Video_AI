from uuid import uuid4
from core.video.assets import AssetStore
from core.video.ffmpeg import run
from core.video.errors import VideoError
from core.transcription.alignment import validate_transcript


def transcribe_video(project, assets: AssetStore, provider, progress=None):
    if not project.media.audio_codec:
        raise VideoError('影片沒有音軌，無法辨識口播；仍可使用人工剪輯與輸出。')
    audio = assets.path(project.id, 'temp-audio-' + uuid4().hex + '.wav')
    try:
        # Demux clock starts at the original video timeline. async fills initial audio offset.
        run('ffmpeg', ['-v', 'error', '-nostdin', '-copyts', '-start_at_zero', '-i', str(assets.source(project)),
            '-vn', '-map', '0:a:0', '-af', 'aresample=16000:async=1:first_pts=0,apad',
            '-ac', '1', '-ar', '16000', '-t', str(project.media.duration), '-c:a', 'pcm_s16le', str(audio)])
        transcript = provider.transcribe(audio, project.media.duration, progress)
        validate_transcript(transcript, project.media.duration)
        return transcript
    finally:
        audio.unlink(missing_ok=True)
