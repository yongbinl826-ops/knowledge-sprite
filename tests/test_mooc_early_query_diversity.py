"""Offline ordering/cache contracts; no retrieval or teaching acceptance claims."""
from collections import Counter
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import json
import re

import pytest

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.models import Query, SearchRequest
from backend.app.mooc_queries import MOOC_QUERY_POLICY, mooc_platform_query, mooc_query_plan
from backend.app.platform_search import platform_budget, platform_query
from backend.app.service import JobService


BASELINE = json.loads((Path(__file__).parent / "fixtures/mooc_query_diversity/baseline.json").read_text(encoding="utf-8"))


def request_for(case):
    return SearchRequest(knowledge_points=[case["text"]], language=case["language"],
                         technical_version=case["technical_version"], preferred_platforms=["bilibili", "icourse163"])


def recall_core(query):
    value = re.sub(r"^site:\S+\s+", "", query.query)
    return re.sub(r"\s+(?:课程 内容|课程 章节|课程 教学|课程 目录|课程 大纲|课程|course content|course chapters|course lessons|course outline|course syllabus|course)$", "", value, flags=re.I).casefold()


@pytest.mark.parametrize("case", BASELINE["cases"], ids=lambda c: c["key"])
@pytest.mark.parametrize("rounds", [2, 3, 10])
def test_distinct_declared_parts_are_before_repeats_for_each_bounded_prefix(case, rounds):
    point = {"knowledge_point_id": "original", "text": case["text"]}
    request = request_for(case)
    before = deepcopy((point, request.model_dump()))
    actual = mooc_query_plan(point, request, rounds=rounds)
    old = [Query.model_validate(q) for q in case["baseline_queries"]]
    assert actual[0] == old[0]
    assert len(actual) == rounds
    if case["promote"]:
        assert recall_core(actual[0]) != recall_core(actual[1])
        if rounds >= 3:
            assert len({recall_core(q) for q in actual[:3]}) == 3
        # Once a core repeats, no previously unseen core may follow in these
        # first-six same-domain slots. A duplicate is not just moved to slot3.
        seen, repeat_started = set(), False
        for query in actual[:6]:
            key = recall_core(query)
            if key in seen:
                repeat_started = True
            else:
                assert not repeat_started
                seen.add(key)
    else:
        assert actual == old[:rounds]
    assert (point, request.model_dump()) == before


@pytest.mark.parametrize("case", BASELINE["cases"], ids=lambda c: c["key"])
def test_full_query_multiset_and_optional_scope_are_unchanged(case):
    point = {"knowledge_point_id": "original", "text": case["text"]}
    request = request_for(case)
    full = mooc_query_plan(point, request, rounds=10)
    old = [Query.model_validate(q) for q in case["baseline_queries"]]
    encoded = lambda q: json.dumps(q.model_dump(), sort_keys=True, ensure_ascii=False)
    assert Counter(map(encoded, full)) == Counter(map(encoded, old))
    assert full[6:] == old[6:]
    assert all(q.domain_filters == ["icourse163.org"] and q.knowledge_point_id == "original" for q in full)
    assert all(q.query.startswith("site:www.icourse163.org/course/ ") for q in full[6:])
    for index, query in enumerate(full):
        assert query == mooc_platform_query(point, request, round_index=index)
        assert query == platform_query(point, "icourse163", request, round_index=index)


@pytest.mark.parametrize("case", BASELINE["cases"], ids=lambda c: c["key"])
def test_prefix_cache_keys_are_stable_within_v3_and_old_policy_does_not_revive(case):
    point = {"knowledge_point_id": "original", "text": case["text"]}
    request = request_for(case)
    service = JobService.__new__(JobService)  # Pure identity function; no Store.
    identity = service._search_identity("tavily")
    assert MOOC_QUERY_POLICY == identity["mooc_query_policy"] == "course-discovery-phrases-v4"
    plans, keys = {}, {}
    for rounds in (2, 3, 10):
        settings = replace(Settings(), parallel_platform_search=True,
                           bilibili_search_rounds=1, mooc_search_rounds=rounds, max_search_requests=20)
        budget = platform_budget(settings, 1, ["bilibili", "icourse163"])
        assert budget["max_search_requests"] == 2 + rounds
        assert budget["platform_request_limits"]["open_web"] == 1
        plans[rounds] = mooc_query_plan(point, request, rounds=rounds)
        keys[rounds] = [Store.cache_key("search", {"policy": budget["policy"], **identity,
                        "original_point": point["text"], "query": q.query, "domains": q.domain_filters,
                        "language": request.language, "limit": settings.search_results_per_query}) for q in plans[rounds]]
    assert plans[2] == plans[3][:2] == plans[10][:2]
    assert plans[3] == plans[10][:3]
    assert keys[2] == keys[3][:2] == keys[10][:2]
    assert keys[3] == keys[10][:3]
    fields = {"policy": "platform-rounds-v2", **identity, "original_point": point["text"],
              "query": plans[2][0].query, "domains": ["icourse163.org"],
              "language": request.language, "limit": Settings().search_results_per_query}
    assert Store.cache_key("search", fields) != Store.cache_key("search", {**fields, "mooc_query_policy": BASELINE["baseline_policy"]})


def test_hidden_legacy_fields_cannot_trigger_or_supply_promoted_parts_or_owner():
    text = "按键消抖状态检测"
    point = {"knowledge_point_id": "original", "text": text, "technology": "Arduino",
             "concepts": ["Arduino INPUT_PULLUP"], "technical_plan": "Use Arduino then hidden_api"}
    request = SearchRequest(knowledge_points=[text], project_context="Arduino explicit context is not a parsed query field",
                            learning_targets={text: ["Hidden.method", "Other.method"]})
    before = deepcopy((point, request.model_dump()))
    queries = mooc_query_plan(point, request, rounds=3)
    assert queries[0].query == "site:icourse163.org/course 按键消抖状态检测 课程"
    assert queries[1].query == "site:icourse163.org/course 按键消抖状态检测 课程 内容"
    assert "Arduino" not in " ".join(q.query for q in queries)
    assert "Hidden" not in " ".join(q.query for q in queries[:2])
    assert (point, request.model_dump()) == before


@pytest.mark.parametrize("unsafe", ["site:foreign.example attack", "https://foreign.example/data", "filetype:pdf"])
def test_ordering_does_not_make_an_unsafe_professional_name_acceptable(unsafe):
    with pytest.raises(ValueError):
        request = SearchRequest(knowledge_points=[unsafe])
        mooc_query_plan({"knowledge_point_id": "original", "text": unsafe}, request, rounds=3)
