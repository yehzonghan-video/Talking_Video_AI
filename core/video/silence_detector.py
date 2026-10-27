import re
from core.video.ffmpeg import run
from core.video.schemas import Interval, AnalysisSettings


def parse_silences(log: str, duration: float) -> list[Interval]:
    results, start = [], None
    for event, value in re.findall(r'silence_(start|end):\s*(-?\d+(?:\.\d+)?)', log):
        value = min(duration, max(0, float(value)))
        if event == 'start':
            start = value
        elif start is not None:
            if value > start:
                results.append(Interval(start=start, end=value))
            start = None
    if start is not None and start < duration:
        results.append(Interval(start=start, end=duration))
    return results


def detect_silences(source, duration: float, settings: AnalysisSettings) -> list[Interval]:
    result = run('ffmpeg', ['-hide_banner', '-nostdin', '-copyts', '-start_at_zero', '-i', str(source),
        '-vn', '-map', '0:a:0', '-af', f'aresample=48000:async=1:first_pts=0,silencedetect=noise={settings.noise_db}dB:d=0.5:mono=0',
        '-f', 'null', '-'])
    return parse_silences(result.stderr, duration)
