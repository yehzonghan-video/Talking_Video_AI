"""Transactional local storage; JSON interchange. No Streamlit dependency."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol
from core.storage.schemas import Backup, Draft, Project
from core.topics.topic_manager import Catalog


class StorageError(RuntimeError):
    pass


class Repository(Protocol):
    def list_projects(self) -> list[Project]: ...
    def get(self, project_id: str) -> Project | None: ...
    def save(self, project: Project) -> Project: ...
    def delete(self, project_id: str, expected_revision: int) -> None: ...
    def used(self) -> set[str]: ...
    def save_draft(self, draft_id: str, draft: Draft) -> None: ...
    def load_draft(self, draft_id: str) -> Draft | None: ...
    def delete_draft(self, draft_id: str) -> None: ...
    def list_drafts(self) -> list[tuple[str, Draft]]: ...
    def merge(self, backup: Backup) -> tuple[int, int]: ...


class SQLiteRepository:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, revision INTEGER NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS used (combination_id TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS drafts (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            """)

    @contextmanager
    def connection(self):
        db = None
        try:
            db = sqlite3.connect(self.path, timeout=10)
            with db:
                yield db
        except sqlite3.Error as exc:
            raise StorageError("本機資料無法讀寫，請檢查資料夾權限或磁碟空間；請先下載內容備份。") from exc
        finally:
            if db is not None:
                db.close()

    def list_projects(self) -> list[Project]:
        with self.connection() as db:
            rows = db.execute("SELECT payload FROM projects").fetchall()
        return sorted((Project.model_validate_json(r[0]) for r in rows), key=lambda p: p.updated_at, reverse=True)

    def get(self, project_id: str) -> Project | None:
        with self.connection() as db:
            row = db.execute("SELECT payload FROM projects WHERE id=?", (project_id,)).fetchone()
        return Project.model_validate_json(row[0]) if row else None

    def save(self, project: Project) -> Project:
        project = Project.model_validate(project.model_dump())
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT revision FROM projects WHERE id=?", (project.id,)).fetchone()
            if (row is None and project.revision != 0) or (row is not None and row[0] != project.revision):
                raise StorageError("這份腳本已在其他視窗修改或刪除。請先匯出目前草稿，重新開啟資料庫中的腳本後再編輯。")
            saved = project.model_copy(update={"revision": project.revision + 1})
            db.execute("INSERT OR REPLACE INTO projects VALUES (?,?,?)", (saved.id, saved.revision, saved.model_dump_json()))
            db.execute("INSERT OR IGNORE INTO used VALUES (?)", (saved.combination_id,))
        return saved

    def delete(self, project_id: str, expected_revision: int) -> None:
        with self.connection() as db:
            cursor = db.execute("DELETE FROM projects WHERE id=? AND revision=?", (project_id, expected_revision))
            if cursor.rowcount != 1:
                raise StorageError("腳本已變更，請重新整理後再確認刪除。")

    def used(self) -> set[str]:
        with self.connection() as db:
            return {r[0] for r in db.execute("SELECT combination_id FROM used")}

    def save_draft(self, draft_id: str, draft: Draft) -> None:
        with self.connection() as db:
            db.execute("INSERT OR REPLACE INTO drafts VALUES (?,?)", (draft_id, draft.model_dump_json()))

    def load_draft(self, draft_id: str) -> Draft | None:
        with self.connection() as db:
            row = db.execute("SELECT payload FROM drafts WHERE id=?", (draft_id,)).fetchone()
        return Draft.model_validate_json(row[0]) if row else None

    def delete_draft(self, draft_id: str) -> None:
        with self.connection() as db:
            db.execute("DELETE FROM drafts WHERE id=?", (draft_id,))

    def list_drafts(self) -> list[tuple[str, Draft]]:
        with self.connection() as db:
            rows = db.execute("SELECT id,payload FROM drafts ORDER BY rowid DESC").fetchall()
        return [(r[0], Draft.model_validate_json(r[1])) for r in rows]

    def merge(self, backup: Backup) -> tuple[int, int]:
        """Merge a fully validated backup atomically; keep existing script IDs."""
        imported = skipped = 0
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            for p in backup.projects:
                if db.execute("SELECT 1 FROM projects WHERE id=?", (p.id,)).fetchone():
                    skipped += 1
                    continue
                saved = p.model_copy(update={"revision": max(1, p.revision)})
                db.execute("INSERT INTO projects VALUES (?,?,?)", (saved.id, saved.revision, saved.model_dump_json()))
                db.execute("INSERT OR IGNORE INTO used VALUES (?)", (saved.combination_id,))
                imported += 1
            db.executemany("INSERT OR IGNORE INTO used VALUES (?)", [(c,) for c in backup.used_combinations])
        return imported, skipped


def export_backup(repo: Repository, projects: list[Project] | None = None) -> str:
    return Backup(projects=repo.list_projects() if projects is None else projects,
                  used_combinations=sorted(repo.used()) if projects is None else [p.combination_id for p in projects]).model_dump_json(indent=2)


def parse_backup(content: str | bytes, catalog: Catalog) -> Backup:
    if len(content) > 20_000_000:
        raise ValueError("備份超過20 MB，請分批匯入。")
    backup = Backup.model_validate_json(content)
    ids = [p.id for p in backup.projects]
    if len(ids) != len(set(ids)):
        raise ValueError("備份中有重複的腳本 ID。")
    for p in backup.projects:
        if catalog.combo_id(p.selection) != p.combination_id:
            raise ValueError("腳本的 ABC 組合 ID 與分類不一致。")
    for combo in backup.used_combinations:
        parts = combo.split("-")
        if len(parts) != 3:
            raise ValueError("已使用組合格式錯誤。")
        catalog.validate(dict(zip("abc", parts)))
    return backup


def import_backup(repo: Repository, content: str | bytes, catalog: Catalog) -> tuple[int, int]:
    backup = parse_backup(content, catalog)  # Validate everything before any mutation.
    return repo.merge(backup)


def export_txt(project: Project) -> str:
    return f"{project.title}\n\n{project.script}\n\n目標長度：{project.duration}秒\n製作狀態：{project.status}\n選題：{project.combination_id}\n版本：V{project.versions[-1].number}\n"
