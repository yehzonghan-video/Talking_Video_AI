import random
from itertools import product
from core.topics.topic_manager import Catalog


class ExhaustedTopics(ValueError):
    pass


def candidates(catalog: Catalog, fixed: dict | None = None) -> list[dict]:
    fixed = fixed or {}
    if set(fixed) - set(catalog.groups):
        raise ValueError("固定維度不存在。")
    for dim, cid in fixed.items():
        if cid not in catalog.groups[dim]:
            raise ValueError("固定分類不存在。")
    return [dict(zip(catalog.groups, values)) for values in product(*[
        [fixed[d]] if d in fixed else list(group) for d, group in catalog.groups.items()
    ])]


def choose(catalog: Catalog, used: set[str], fixed: dict | None = None,
           allow_reuse: bool = False, rng=None) -> dict:
    pool = candidates(catalog, fixed)
    if fixed and len(fixed) == 3:
        return pool[0]
    unused = [c for c in pool if catalog.combo_id(c) not in used]
    if not unused and not allow_reuse:
        raise ExhaustedTopics("目前條件下的組合皆已使用，請勾選「允許重用已使用組合」後再抽取，或調整條件。")
    return (rng or random.SystemRandom()).choice(unused or pool)
