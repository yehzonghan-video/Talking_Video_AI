"""Install a verified Windows build linked by ffmpeg.org; no system changes."""
import hashlib
from pathlib import Path
import shutil
import subprocess
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
URL = 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip'


def main():
    folder = ROOT / 'tools' / 'ffmpeg'
    folder.mkdir(parents=True, exist_ok=True)
    existing = [folder / 'bin' / name for name in ('ffmpeg.exe', 'ffprobe.exe')]
    if all(p.is_file() for p in existing):
        for executable in existing:
            subprocess.run([str(executable), '-version'], check=True, capture_output=True, timeout=15)
        filters = subprocess.run([str(existing[0]), '-hide_banner', '-filters'], check=True, capture_output=True, text=True, timeout=15)
        if any(' ass ' in line for line in filters.stdout.splitlines()):
            print('Existing project FFmpeg / FFprobe and libass subtitles are ready. No download needed.', flush=True)
            return
        print('Existing FFmpeg has no libass subtitle filter; upgrading the project copy only.', flush=True)
    archive = ROOT / '.tmp' / 'ffmpeg-essentials.zip'
    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive.exists():
        with urllib.request.urlopen(URL + '.sha256', timeout=60) as response:
            cached_expected = response.read().decode().split()[0].lower()
        with archive.open('rb') as cached:
            cached_actual = hashlib.file_digest(cached, 'sha256').hexdigest()
        if cached_actual != cached_expected:
            archive.unlink()  # Only this installer's named, incomplete cache file.
    if not archive.exists():
        print('Downloading FFmpeg and FFprobe from gyan.dev...', flush=True)
        with urllib.request.urlopen(URL, timeout=60) as response, archive.open('wb') as target:
            shutil.copyfileobj(response, target)
    with urllib.request.urlopen(URL + '.sha256', timeout=60) as response:
        expected = response.read().decode().split()[0].lower()
    with archive.open('rb') as cached:
        actual = hashlib.file_digest(cached, 'sha256').hexdigest()
    if actual != expected:
        raise RuntimeError('FFmpeg archive checksum does not match. Remove .tmp/ffmpeg-essentials.zip and retry.')
    with zipfile.ZipFile(archive) as zipped:
        for item in zipped.namelist():
            name = Path(item).name
            if name in ('ffmpeg.exe', 'ffprobe.exe', 'LICENSE', 'README.txt'):
                destination = folder / ('bin' if name.endswith('.exe') else '') / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                with zipped.open(item) as source, destination.open('wb') as target:
                    shutil.copyfileobj(source, target)
    print('FFmpeg / FFprobe installed in tools/ffmpeg/bin. SHA256 verified.', flush=True)


if __name__ == '__main__':
    main()
