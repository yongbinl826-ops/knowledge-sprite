"""Shape-based family anchors cannot lend specific requested method evidence."""
from copy import deepcopy
import json

import pytest

from backend.app import teaching_match
from test_teaching_match import point, lesson


def catalog_pair(skill, title):
    p = point([skill]); r, e = lesson()
    chapter = {"title": title, "url": r["canonical_url"], "start_seconds": None,
               "end_seconds": None, "duration_seconds": None, "source": "own.catalog", "evidence_id": "own-chapter"}
    r["chapters"] = [chapter]
    e.append({"evidence_id": "own-chapter", "kind": "catalog", "field": "chapters.0", "source": "own.catalog",
              "url": r["canonical_url"], "text": json.dumps(chapter, ensure_ascii=False, sort_keys=True)})
    pair = teaching_match.prepare_pair(p, r, e)
    assert pair
    return p, r, e, pair


@pytest.mark.parametrize("family", ["DOM", "PWM", "CSV", "LED", "XYZ"])
def test_family_only_heading_does_not_admit_specific_method_target(family):
    p, r, e, pair = catalog_pair(f"QuillFlow {family} 对象查询与状态检查", f"{family} introduction")
    before = deepcopy((p, r, e, pair))
    assert teaching_match.topic_pointers(pair) == []
    assert (p, r, e, pair) == before


@pytest.mark.parametrize("skill,title", [("DOM", "DOM introduction"), ("QuillFlow PWM", "PWM"),
    ("KEYDOWN", "KEYDOWN"), ("INPUT_PULLUP", "INPUT_PULLUP"),
    ("QuillFlow INPUT_PULLUP 输入模式", "INPUT_PULLUP"),
    ("QuillFlow DOM 对象查询与状态检查", "DOM 对象查询"),
    ("QuillFlow selectNode 查询与状态检查", "selectNode")])
def test_actual_declared_acronym_or_nonfamily_specific_anchor_can_remain_pointer(skill, title):
    _, _, _, pair = catalog_pair(skill, title)
    pointers = teaching_match.topic_pointers(pair)
    assert len(pointers) == 1
    assert pointers[0]["quote"] == title
    assert pointers[0]["scope"] == "topic_declared"
    assert pointers[0]["basis"] == "catalog"
