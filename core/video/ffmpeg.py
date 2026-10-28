"""Arguments only, never shell commands or model-generated filters."""
import os
from pathlib import Path
import shutil
import subprocess
from core.video.errors import VideoError
from core.video.diagnostics import record


def binary(name: str) -> str:
    configured = os.environ.get(name.upper() + '_PATH')
    if configured and Path(configured).is_file():
        return configured
    system = shutil.which(name)
    if system:
        return system
    bundled = Path(__file__).resolve().parents[2] / 'tools' / 'ffmpeg' / 'bin' / (name + ('.exe' if os.name == 'nt' else ''))
    if bundled.is_file():
        return str(bundled)
    raise VideoError(f'尚未安裝 {name}，請先執行第二階段安裝程式，或由管理者設定路徑。')


def run(name: str, args: list[str], timeout: int = 600, *, cwd: Path | None = None) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run([binary(name), *args], capture_output=True, encoding='utf-8', errors='replace',
                                timeout=timeout, shell=False, cwd=cwd,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    except subprocess.TimeoutExpired as exc:
        raise VideoError('影片處理超過時間限制，請縮短影片後重試；原始影片與已儲存時間軸均保留。') from exc
    except OSError as exc:
        raise VideoError('無法啟動影片處理工具，請檢查 FFmpeg 安裝。') from exc
    if result.returncode:
        # Record diagnostic categories from stderr, never the command, source
        # paths or subtitle text that FFmpeg can echo in its complete stderr.
        causes = [label for needle, label in [('no space left', 'disk_full'), ('cannot allocate memory', 'memory'),
            ('invalid data', 'invalid_media'), ('permission denied', 'permission'), ('no such file', 'missing_file')]
            if needle in result.stderr.lower()]
        record('media_tool_failed', tool=name, returncode=result.returncode, causes=causes)
        raise VideoError('影片處理失敗：檔案可能損壞、格式不支援，或磁碟空間不足。原始影片未變更。')
    return result
