import json
from concurrent.futures import ThreadPoolExecutor
import pytest
from core.storage.schemas import Draft, Project
from core.storage.project_manager import SQLiteRepository, StorageError, export_backup, export_txt, import_backup, parse_backup
from core.workflow import project_from_draft, open_project, propose


def test_draft_not_used_until_save(repo, draft, catalog):
    repo.save_draft("token", draft)
    assert repo.used() == set()
    assert repo.load_draft("token") == draft
    p = repo.save(project_from_draft(draft, catalog.combo_id(draft.selection)))
    assert p.revision == 1
    assert repo.used() == {p.combination_id}
    assert repo.get(p.id) == p


def test_same_combo_multiple_scripts(repo, draft, catalog):
    p1 = repo.save(project_from_draft(draft, catalog.combo_id(draft.selection)))
    d2 = Draft(selection=draft.selection, title="不同標題", script="不同內容")
    p2 = repo.save(project_from_draft(d2, p1.combination_id))
    assert p1.id != p2.id and len(repo.list_projects()) == 2
    assert len(repo.used()) == 1


def test_crud_concurrent_edits_and_delete(repo, draft, catalog):
    p = repo.save(project_from_draft(draft, catalog.combo_id(draft.selection)))
    editor = open_project(p)
    editor.script = "更新過的內容"
    newer = repo.save(project_from_draft(editor, p.combination_id))
    with pytest.raises(StorageError): repo.save(p)
    with pytest.raises(StorageError): repo.delete(p.id, p.revision)
    repo.delete(p.id, newer.revision)
    assert repo.get(p.id) is None
    assert p.combination_id in repo.used()
    with pytest.raises(StorageError): repo.save(newer)


def test_atomic_concurrent_save(repo, draft, catalog):
    p = repo.save(project_from_draft(draft, catalog.combo_id(draft.selection)))
    def save():
        try:
            repo.save(p)
            return True
        except StorageError:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: save(), range(2))) == [False, True]


def test_export_import_restore(repo, draft, catalog, tmp_path):
    p = repo.save(project_from_draft(draft, catalog.combo_id(draft.selection)))
    assert p.script in export_txt(p)
    content = export_backup(repo)
    restored = SQLiteRepository(tmp_path / "restore.db")
    assert import_backup(restored, content, catalog) == (1, 0)
    assert import_backup(restored, content, catalog) == (0, 1)
    assert restored.get(p.id).versions == p.versions
    assert restored.used() == repo.used()


def test_invalid_import_all_or_nothing(repo, draft, catalog):
    p = project_from_draft(draft, catalog.combo_id(draft.selection))
    raw = json.loads(export_backup(repo, [p]))
    broken = p.model_dump()
    broken["selection"]["a"] = "A99"
    from uuid import uuid4
    broken["id"] = str(uuid4())
    raw["projects"].append(broken)
    with pytest.raises(ValueError): import_backup(repo, json.dumps(raw), catalog)
    assert repo.list_projects() == [] and repo.used() == set()


def test_preview_persists_and_does_not_save(repo, draft):
    propose(draft, "新稿", "修改開頭", "已修改開頭")
    repo.save_draft("token", draft)
    restored = repo.load_draft("token")
    assert restored.pending.script == "新稿"
    assert restored.script == draft.script
    assert repo.used() == set()
    with pytest.raises(ValueError): project_from_draft(draft, "A01-B01-C03")


def test_deleted_combinations_survive_backup(repo, draft, catalog, tmp_path):
    p = repo.save(project_from_draft(draft, catalog.combo_id(draft.selection)))
    repo.delete(p.id, p.revision)
    target = SQLiteRepository(tmp_path / "restore.db")
    import_backup(target, export_backup(repo), catalog)
    assert target.used() == {p.combination_id} and target.list_projects() == []
