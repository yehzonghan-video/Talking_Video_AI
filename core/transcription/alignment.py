from core.video.schemas import Transcript
from core.video.errors import VideoError


def validate_transcript(transcript: Transcript, duration: float) -> None:
    if transcript.timing != 'acoustic-alignment':
        raise VideoError('辨識時間未經音訊對齊，不能作為自動剪輯依據。')
    seen, previous = set(), 0.0
    for s in transcript.segments:
        if s.id in seen or s.end > duration + .001 or s.start < previous - .001:
            raise VideoError('辨識片段的時間或識別碼無效。')
        seen.add(s.id)
        previous = s.end
        word_cursor = s.start
        for word in s.words:
            if word.start < s.start - .05 or word.end > s.end + .05 or word.start < word_cursor - .05:
                raise VideoError('詞語的對齊時間不在有效範圍。')
            word_cursor = word.end
