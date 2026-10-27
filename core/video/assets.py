"""Local implementation of a replaceable media-object interface."""
import hashlib
from pathlib import Path
import re
from typing import Protocol, BinaryIO
from uuid import UUID, uuid4
from core.video.errors import VideoError


class AssetStore(Protocol):
    def project_dir(self, project_id: str) -> Path: ...
    def source(self, project) -> Path: ...
    def path(self, project_id: str, key: str) -> Path: ...


def sha256(path: Path) -> str:
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


class LocalAssets:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def project_dir(self, project_id: str) -> Path:
        try:
            safe_id = str(UUID(project_id))
        except ValueError as exc:
            raise VideoError('剪輯專案識別碼無效。') from exc
        folder = (self.root / safe_id).resolve()
        if not folder.is_relative_to(self.root):
            raise VideoError('儲存路徑無效。')
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def path(self, project_id: str, key: str) -> Path:
        if not re.fullmatch(r'[a-zA-Z0-9_.-]+', key) or key in ('.', '..'):
            raise VideoError('媒體檔案識別碼無效。')
        folder = self.project_dir(project_id)
        result = (folder / key).resolve()
        if not result.is_relative_to(folder):
            raise VideoError('媒體路徑超出專案範圍。')
        return result

    def source(self, project) -> Path:
        return self.path(project.id, 'source' + project.source_suffix)

    def temporary_cleanup(self, project_id: str) -> int:
        count = 0
        for path in self.project_dir(project_id).iterdir():
            if path.name.startswith(('temp-', 'preview-')) and path.is_file() and not path.is_symlink():
                path.unlink()
                count += 1
        return count

    def write_upload(self, project_id: str, stream: BinaryIO, suffix: str, max_bytes: int) -> tuple[Path, str]:
        if suffix not in ('.mp4', '.mov'):
            raise VideoError('請選擇 MP4 或 MOV 影片。')
        target = self.path(project_id, 'source' + suffix)
        temporary = self.path(project_id, 'temp-upload-' + uuid4().hex)
        if target.exists():
            raise VideoError('原始影片已存在，不允許覆蓋。')
        digest, size = hashlib.sha256(), 0
        try:
            with temporary.open('xb') as destination:
                while chunk := stream.read(1024 * 1024):
                    size += len(chunk)
                    if size > max_bytes:
                        raise VideoError(f'影片超過 {max_bytes // (1024 * 1024)} MB 上傳限制。')
                    destination.write(chunk)
                    digest.update(chunk)
            if not size:
                raise VideoError('上傳檔案是空的。')
            # Exclusive final creation prevents a second request from replacing the source.
            with target.open('xb') as output, temporary.open('rb') as source:
                import shutil
                shutil.copyfileobj(source, output)
            return target, digest.hexdigest()
        finally:
            temporary.unlink(missing_ok=True)
