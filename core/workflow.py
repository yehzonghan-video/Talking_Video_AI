"""Pure editing operations: proposals do not change confirmed versions."""
from core.storage.schemas import Draft, Version, ChatTurn, Pending, Project, now


class WorkflowError(ValueError):
    pass


def checkpoint(draft: Draft, note: str) -> None:
    if not draft.title.strip() or not draft.script.strip():
        raise WorkflowError("請先填入標題與逐字稿。")
    if draft.versions:
        last = draft.versions[-1]
        if (last.title, last.script, last.duration) == (draft.title, draft.script, draft.duration):
            return
    draft.versions.append(Version(number=len(draft.versions) + 1, title=draft.title,
        script=draft.script, duration=draft.duration, note=note[:2000]))


def propose(draft: Draft, script: str, request: str, explanation: str) -> None:
    if draft.pending:
        raise WorkflowError("請先套用或取消目前的修改提案。")
    pending = Pending(base_title=draft.title, base_script=draft.script, base_duration=draft.duration,
                      script=script, request=request, explanation=explanation)
    checkpoint(draft, "修改前內容")
    draft.pending = pending
    draft.history.append(ChatTurn(request=request, proposal=script, explanation=explanation, outcome="待確認"))


def accept(draft: Draft) -> None:
    p = draft.pending
    if p is None:
        raise WorkflowError("沒有待確認的提案。")
    if (p.base_title, p.base_script, p.base_duration) != (draft.title, draft.script, draft.duration):
        raise WorkflowError("目前內容已變更，請取消提案後重新提出修改，避免覆蓋你的編輯。")
    draft.script = p.script
    checkpoint(draft, p.request)
    draft.history[-1].outcome = "已套用"
    draft.pending = None


def cancel(draft: Draft) -> None:
    if draft.pending:
        draft.history[-1].outcome = "已取消"
        draft.pending = None


def restore(draft: Draft, number: int) -> None:
    if draft.pending:
        raise WorkflowError("請先處理目前提案。")
    target = next((v for v in draft.versions if v.number == number), None)
    if not target:
        raise WorkflowError("找不到指定版本。")
    checkpoint(draft, "恢復前的手動內容")
    draft.title, draft.script, draft.duration = target.title, target.script, target.duration
    checkpoint(draft, f"恢復 V{number}")


def project_from_draft(draft: Draft, combination_id: str) -> Project:
    if draft.pending:
        raise WorkflowError("請先套用或取消修改提案，再儲存腳本。")
    if draft.selection is None:
        raise WorkflowError("請先選定 ABC 分類。")
    checkpoint(draft, "儲存手動編輯")
    return Project(id=draft.project_id, combination_id=combination_id, selection=draft.selection,
        title=draft.title, script=draft.script, duration=draft.duration, status=draft.status,
        created_at=draft.created_at, updated_at=now(), versions=draft.versions,
        history=draft.history, revision=draft.saved_revision)


def open_project(project: Project) -> Draft:
    return Draft(project_id=project.id, selection=project.selection, title=project.title,
        script=project.script, duration=project.duration, status=project.status,
        created_at=project.created_at, versions=[v.model_copy(deep=True) for v in project.versions],
        history=[t.model_copy(deep=True) for t in project.history], saved_revision=project.revision)
