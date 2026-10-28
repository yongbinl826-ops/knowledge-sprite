"""Offline retrieval projection safety, independent of concept correctness."""
from copy import deepcopy

import pytest

from backend.app import professional_concepts as module


def analysis():
    return {"scope": "保留生成内容", "technical_plan": "原方案", "assumptions": [],
            "analysis_format": "concept_list_v1", "knowledge_points": [
                {"id": "k1", "name": "请创建一个窗口", "description": "不做语义正确性判断。",
                 "technology": "pygame", "selection": "learn"},
                {"id": "k2", "name": "数组", "description": "原始说明。",
                 "technology": "Python", "selection": "learn"},
            ]}


def version(raw):
    return {"prompt_version": "project-analysis-v8-single-pass", "analysis": raw,
            "validated_concept_context": module.generated_context(raw)}


def test_generated_context_does_not_call_name_judging_or_rewrite_source(monkeypatch):
    raw = analysis()
    original = deepcopy(raw)

    def forbidden(*_args, **_kwargs):
        pytest.fail("Retrieval context must not judge the generated concept name")

    monkeypatch.setattr(module, "concept_name_issues", forbidden)
    saved = version(raw)
    expected = {"请创建一个窗口": "pygame", "数组": "Python"}
    assert saved["validated_concept_context"]["topic_technologies"] == expected
    assert module.bound_generated_context(saved) == expected
    assert raw == original


@pytest.mark.parametrize("unsafe", [
    "Python/pygame", "Python+pygame tools", "https://example.com", "site:example.com",
    "ignore", "下载资料", "Python\nignore", "Py\u200bthon", "x" * 49, None, [],
])
def test_one_unsafe_annotation_does_not_discard_other_safe_contexts(unsafe):
    raw = analysis()
    raw["knowledge_points"][0]["technology"] = unsafe
    original = deepcopy(raw)
    saved = version(raw)
    assert saved["validated_concept_context"]["topic_technologies"] == {"数组": "Python"}
    assert module.bound_generated_context(saved) == {"数组": "Python"}
    assert raw == original


@pytest.mark.parametrize("names,technologies", [
    (["数组", "数组"], ["Python", "JavaScript"]),
    (["Python数组", "Python 数组"], ["Python", "JavaScript"]),
    (["Array", "array"], ["Python", "JavaScript"]),
    (["数组", "数组"], ["Python", "Python"]),
])
def test_ambiguous_retrieval_names_abstain_without_last_write_wins(names, technologies):
    raw = analysis()
    for point, name, technology in zip(raw["knowledge_points"], names, technologies):
        point.update(name=name, technology=technology)
    raw["knowledge_points"].append({"id": "k3", "name": "分组聚合", "description": "原始统计说明。",
                                     "technology": "SQL", "selection": "learn"})
    original = deepcopy(raw)
    saved = version(raw)
    assert saved["validated_concept_context"]["topic_technologies"] == {"分组聚合": "SQL"}
    assert module.bound_generated_context(saved) == {"分组聚合": "SQL"}
    assert raw == original


def test_all_unsafe_annotations_produce_empty_context_without_touching_analysis():
    raw = analysis()
    for point in raw["knowledge_points"]:
        point["technology"] = "https://example.com"
    original = deepcopy(raw)
    saved = version(raw)
    assert saved["validated_concept_context"]["topic_technologies"] == {}
    assert module.bound_generated_context(saved) == {}
    assert raw == original


def test_context_remains_bound_to_exact_original_names_ids_and_raw_annotations():
    saved = version(analysis())
    saved["analysis"]["knowledge_points"][0]["technology"] = "Python/pygame"
    assert module.bound_generated_context(saved) is None


def test_tampered_unsafe_retrieval_context_still_fails_safety_validation():
    saved = version(analysis())
    saved["validated_concept_context"]["topic_technologies"]["数组"] = "ignore instructions"
    assert module.bound_generated_context(saved) is None
