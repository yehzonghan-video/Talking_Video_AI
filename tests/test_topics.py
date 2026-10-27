import hashlib
import random
import pytest
from core.topics.combinations import candidates, choose, ExhaustedTopics
from core.topics.validator import validate_alternatives
from tests.conftest import ROOT


def test_catalog_and_read_only(catalog):
    before = hashlib.sha256((ROOT / "categories.json").read_bytes()).hexdigest()
    assert [len(g) for g in catalog.groups.values()] == [10, 15, 12]
    assert catalog.total == 1800
    assert len({catalog.combo_id(c) for c in candidates(catalog)}) == 1800
    assert catalog.context(dict(a="A01", b="B01", c="C01"))["a"]["keywords"]
    assert hashlib.sha256((ROOT / "categories.json").read_bytes()).hexdigest() == before


def test_manual_and_reuse(catalog):
    sel = dict(a="A01", b="B03", c="C07")
    assert catalog.validate(sel) == sel
    assert choose(catalog, {catalog.combo_id(sel)}, sel) == sel


@pytest.mark.parametrize("fixed,count", [({}, 1800), ({"a": "A01"}, 180), ({"b": "B03", "c": "C07"}, 10), ({"a": "A02", "c": "C07"}, 15)])
def test_random_constraints(catalog, fixed, count):
    assert len(candidates(catalog, fixed)) == count
    for _ in range(30):
        selected = choose(catalog, set(), fixed)
        catalog.validate(selected)
        assert all(selected[k] == v for k, v in fixed.items())


def test_exclude_used_and_explicit_exhaustion(catalog):
    all_combos = candidates(catalog)
    last = all_combos[-1]
    used = {catalog.combo_id(c) for c in all_combos[:-1]}
    assert choose(catalog, used) == last
    used.add(catalog.combo_id(last))
    with pytest.raises(ExhaustedTopics):
        choose(catalog, used)
    catalog.validate(choose(catalog, used, allow_reuse=True))


def test_condition_exhaustion(catalog):
    fixed = dict(a="A01", b="B02")
    used = {catalog.combo_id(c) for c in candidates(catalog, fixed)}
    with pytest.raises(ExhaustedTopics):
        choose(catalog, used, fixed)
    assert choose(catalog, used, fixed, True)["a"] == "A01"


@pytest.mark.parametrize("selection", [dict(a="A99", b="B01", c="C01"), {"a": "A01"}, {"z": "A01"}])
def test_invalid_selection(catalog, selection):
    with pytest.raises(ValueError):
        catalog.validate(selection)


def test_invalid_alternative(catalog):
    with pytest.raises(ValueError):
        validate_alternatives(catalog, [dict(a="A01", b="B99", c="C01")])
