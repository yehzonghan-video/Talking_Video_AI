"""Read-only category catalog. No AI or UI dependencies."""
import json
from dataclasses import asdict, dataclass
from pathlib import Path

DIMENSIONS = {"a": "business_categories", "b": "target_audiences", "c": "problem_angles"}


@dataclass(frozen=True)
class Category:
    id: str
    name: str
    description: str
    keywords: tuple[str, ...]


class Catalog:
    def __init__(self, path: str | Path):
        raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        self.groups = {}
        for dim, field in DIMENSIONS.items():
            rows = raw.get(field)
            if not isinstance(rows, list) or not rows:
                raise ValueError(f"分類資料缺少有效的 {field}。")
            group = {}
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError("分類項目格式錯誤。")
                cid, name = row.get("id"), row.get("name")
                description, keywords = row.get("description", ""), row.get("keywords", [])
                if not isinstance(cid, str) or not cid.startswith(dim.upper()) or "-" in cid or not isinstance(name, str) or not name.strip() or cid in group:
                    raise ValueError("分類 ID 或名稱錯誤或重複。")
                if not isinstance(description, str) or not isinstance(keywords, list) or any(not isinstance(k, str) for k in keywords):
                    raise ValueError("分類說明或關鍵字格式錯誤。")
                group[cid] = Category(cid, name, description, tuple(keywords))
            self.groups[dim] = group

    def validate(self, selection: dict) -> dict[str, str]:
        if not isinstance(selection, dict) or set(selection) != set(DIMENSIONS):
            raise ValueError("請完整選擇三個分類。")
        for dim, cid in selection.items():
            if not isinstance(cid, str) or cid not in self.groups[dim]:
                raise ValueError("選題含有不存在的分類。")
        return dict(selection)

    def context(self, selection: dict) -> dict:
        return {dim: asdict(self.groups[dim][cid]) for dim, cid in self.validate(selection).items()}

    def combo_id(self, selection: dict) -> str:
        selected = self.validate(selection)
        return "-".join(selected[d] for d in DIMENSIONS)

    @property
    def total(self) -> int:
        result = 1
        for group in self.groups.values():
            result *= len(group)
        return result
