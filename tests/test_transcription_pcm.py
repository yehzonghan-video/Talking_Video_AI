from pathlib import Path
import wave
import pytest
import numpy as np
from core.transcription.provider import pcm_samples, FasterWhisperProvider
from core.video.errors import VideoError


def wav(path, rate=16000):
    with wave.open(str(path), 'wb') as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(np.array([0, 16384, -16384, 32767], dtype='<i2').tobytes())


def test_standard_pcm_has_known_scale_and_sample_count(tmp_path):
    audio = tmp_path / 'audio.wav'
    wav(audio)
    samples = pcm_samples(audio)
    assert samples.dtype == np.float32
    assert samples.tolist()[:3] == [0.0, .5, -.5]


def test_nonstandard_audio_rejected_instead_of_invented_timing(tmp_path):
    audio = tmp_path / 'audio.wav'
    wav(audio, 22050)
    with pytest.raises(VideoError, match='16 kHz'): pcm_samples(audio)


def test_asr_receives_waveform_not_another_decoder(monkeypatch, tmp_path):
    from core.transcription import provider
    audio = tmp_path / 'audio.wav'
    wav(audio)
    class Model:
        def transcribe(self, samples, **options):
            assert isinstance(samples, np.ndarray)
            assert options['word_timestamps'] and options['vad_filter']
            word = type('Word', (), dict(start=0, end=.5, word='预算'))()
            segment = type('Segment', (), dict(start=0, end=.5, text='预算', words=[word]))()
            return iter([segment]), None
    monkeypatch.setattr(provider, 'load_model', lambda *args: Model())
    result = FasterWhisperProvider('mock').transcribe(audio, 1)
    assert result.segments[0].text == '預算'
    assert result.segments[0].confidence is None
    assert result.timing == 'acoustic-alignment'
