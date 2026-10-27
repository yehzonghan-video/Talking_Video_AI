"""Local acoustic ASR. No Gemini media uploads or invented word timings."""
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Protocol, Callable
import wave
from core.video.schemas import Transcript, Segment, Word
from core.video.errors import VideoError

MODEL_LOCK = Lock()


class TranscriptionProvider(Protocol):
    model_name: str
    def transcribe(self, audio: Path, duration: float, progress: Callable | None = None) -> Transcript: ...


@lru_cache(maxsize=1)
def load_model(name: str, cache: str):
    from faster_whisper import WhisperModel
    from huggingface_hub.errors import LocalEntryNotFoundError
    options = dict(device='cpu', compute_type='int8', cpu_threads=4, download_root=cache)
    try:
        return WhisperModel(name, local_files_only=True, **options)
    except LocalEntryNotFoundError:
        return WhisperModel(name, **options)


def pcm_samples(audio: Path):
    """Accept the transcriber's explicit 16 kHz / mono / signed-16-bit contract."""
    import numpy as np
    with wave.open(str(audio), 'rb') as source:
        if (source.getframerate(), source.getnchannels(), source.getsampwidth()) != (16000, 1, 2):
            raise VideoError('辨識音訊必須先轉成16 kHz單聲道PCM，請重新執行影片分析。')
        return np.frombuffer(source.readframes(source.getnframes()), dtype='<i2').astype(np.float32) / 32768.0


class FasterWhisperProvider:
    def __init__(self, model_name: str = 'small', cache: Path | None = None):
        self.model_name = model_name
        self.cache = Path(cache or 'models/whisper').resolve()

    def transcribe(self, audio: Path, duration: float, progress=None) -> Transcript:
        try:
            from opencc import OpenCC
            converter = OpenCC('s2twp')
            with MODEL_LOCK:
                model = load_model(self.model_name, str(self.cache))
                # FFmpeg already decoded and aligned the audio. Passing PCM directly
                # avoids an additional PyAV decode and its version-specific APIs.
                segments, _ = model.transcribe(pcm_samples(audio), language='zh', beam_size=5, temperature=0,
                    word_timestamps=True, vad_filter=True, condition_on_previous_text=False,
                    hallucination_silence_threshold=1.0)
                results = []
                for segment in segments:
                    text = converter.convert(segment.text.strip())
                    words = [Word(start=max(0, w.start), end=min(duration, w.end), text=converter.convert(w.word))
                             for w in segment.words or [] if 0 <= w.start < w.end <= duration + .05]
                    if not text or segment.end <= segment.start or segment.start >= duration:
                        continue
                    results.append(Segment(id=f'seg_{len(results) + 1:04d}', start=max(0, segment.start),
                        end=min(duration, segment.end), text=text, confidence=None, words=words))
                    if progress:
                        progress('語音辨識', min(.9, segment.end / duration))
            return Transcript(provider='faster-whisper', model=self.model_name, timing='acoustic-alignment', segments=results)
        except ImportError as exc:
            raise VideoError('語音辨識套件尚未安裝，請先執行第二階段安裝程式。') from exc
        except Exception as exc:
            raise VideoError('語音辨識未完成。首次使用需下載模型；請檢查網路、模型設定與記憶體，原片及已完成的分析均保留。') from exc
