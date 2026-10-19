"""Offline regressions: scarce detail fetches prefer already evidenced topics.

Synthetic URLs and responses are test fixtures only; no fixture enters runtime.
"""
from copy import deepcopy

import pytest

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.models import Candidate, Resource, SearchRequest
from backend.app.ranking import rank_resource
from backend.app.service import JobService


POINT = "Python 本地文件路径处理"
LEXICAL = "python教程-读取本地文件并打印-绝对路径-相对路径"
PARTIAL = "Python案例技巧51：文件路径处理"


class OfflineSearch:
    name = "offline_fixture"
    def __init__(self, titles):
        self.titles = titles
    async def search(self, query, language, limit, domain_filters):
        return [Candidate(id=f"source-{index}", title=title,
            url=f"https://courses.example.org/video/{index}", source=self.name, query=query,
            resource_type_hint="video", type_source="search_template") for index, title in enumerate(self.titles)]


class RecordingFetch:
    def __init__(self):
        self.calls = []
    async def enrich(self, candidate):
        self.calls.append(candidate)
        # A policy outcome must not be promoted to a successful fetch.
        return {"fetch_status": "search_only_policy", "metadata_evidence_level": "search", "evidence": []}


def setup(tmp_path, titles, *, point=POINT, detail_budget=1):
    settings = Settings(database_path=str(tmp_path / "details.sqlite3"), max_search_requests=1,
        max_detail_pages=detail_budget, deadline_seconds=5, search_min_interval_seconds=0,
        global_concurrency=1, official_sitemap_fallback=False)
    store = Store(settings.database_path)
    fetcher = RecordingFetch()
    jobs = JobService(settings, store, provider=OfflineSearch(titles), fetcher=fetcher)
    request = SearchRequest(knowledge_points=[point], preferred_platforms=[])
    job_id = jobs.create(request)["job_id"]
    job = store.get_job(job_id)
    resources, candidate_groups = {}, {job["knowledge_points"][0]["knowledge_point_id"]: []}
    point_id = next(iter(candidate_groups))
    for index, title in enumerate(titles):
        rid, eid, url = f"r{index}", f"ev-{index}", f"https://courses.example.org/video/{index}"
        evidence = {"evidence_id": eid, "kind": "search", "source": "offline_fixture", "url": url,
            "knowledge_point_id": point_id, "title": title, "snippet": "",
            "resource_type_hint": "video", "type_source": "search_template"}
        provenance = {"evidence_id": eid, "source": "search_template", "url": url}
        resource = Resource(resource_id=rid, title=title, url=url, canonical_url=url,
            discovered_at="2026-10-18T00:00:00Z", resource_type="video", video_evidence_status="search_discovered",
            field_provenance={"title": {"evidence_id": eid, "source": "search"},
                "resource_type": provenance, "video_evidence_status": provenance}).model_dump()
        store.save_resource(job_id, resource)
        store.add_evidence(job_id, rid, point_id, evidence)
        resources[rid] = resource
        candidate_groups[point_id].append(rid)
    state = {"points": job["knowledge_points"], "resources": resources, "candidate_groups": candidate_groups,
        "started": set(), "request": request}
    return store, jobs, fetcher, job, state


def test_lower_scored_real_partial_gets_detail_priority_over_lexical_only_candidate(tmp_path):
    store, jobs, _, job, state = setup(tmp_path, [LEXICAL, PARTIAL])
    try:
        point = state["points"][0]
        scores = [rank_resource(point, state["resources"][rid], store.evidence(job["job_id"], rid, point["knowledge_point_id"]), state["request"], require_type=False)
                  for rid in ("r0", "r1")]
        assert scores[0]["ranking_score"] > scores[1]["ranking_score"]
        assert scores[0].get("topic_evidence_status") is None
        assert scores[1]["topic_evidence_status"] == "partial"
        before = deepcopy(state["resources"])
        assert jobs._detail_queues(job, state)[point["knowledge_point_id"]] == ["r1", "r0"]
        assert state["resources"] == before
        assert rank_resource(point, state["resources"]["r0"], store.evidence(job["job_id"], "r0"), state["request"]) is None
    finally:
        store.close()


@pytest.mark.asyncio
async def test_one_detail_budget_fetches_the_partial_candidate_without_upgrading_policy_status(tmp_path):
    settings = Settings(database_path=str(tmp_path / "run.sqlite3"), max_search_requests=1,
        max_detail_pages=1, deadline_seconds=5, global_concurrency=1, official_sitemap_fallback=False)
    store = Store(settings.database_path)
    fetcher = RecordingFetch()
    jobs = JobService(settings, store, provider=OfflineSearch([LEXICAL, PARTIAL]), fetcher=fetcher)
    try:
        job_id = jobs.create(SearchRequest(knowledge_points=[POINT], preferred_platforms=[]))["job_id"]
        await jobs.run(job_id)
        job, resources = store.get_job(job_id), list(store.resources(job_id).values())
        assert len(fetcher.calls) == job["progress"]["details_attempted"] == 1
        assert fetcher.calls[0]["title"] == PARTIAL
        selected = next(resource for resource in resources if resource["title"] == PARTIAL)
        assert selected["fetch_status"] == "search_only_policy"
        group = jobs.results(job_id)["groups"][0]
        assert not group["items"] and group["total_partial_matches"] == 1
        assert group["partial_items"][0]["resource"]["fetch_status"] == "search_only_policy"
    finally:
        store.close()


@pytest.mark.parametrize("point,titles", [
    ("pandas 分科平均分、最高分与及格率统计", ["【全42集】Pandas数据分析从入门到实战"]),
    ("pandas DataFrame 列选择与列名处理", ["【57集完整版】Pandas数据分析零基础全套教程"]),
])
def test_queue_does_not_admit_generic_series_for_more_fetches(tmp_path, point, titles):
    store, jobs, _, job, state = setup(tmp_path, titles, point=point)
    try:
        assert not jobs._detail_queues(job, state)[job["knowledge_points"][0]["knowledge_point_id"]]
    finally:
        store.close()


def test_lexical_only_candidates_keep_existing_admission_without_evidence_priority(tmp_path):
    titles = ["Java 文件路径处理视频教程", "Python 在线远程文件路径处理教程", PARTIAL]
    store, jobs, _, job, state = setup(tmp_path, titles)
    try:
        point = state["points"][0]
        queue = jobs._detail_queues(job, state)[point["knowledge_point_id"]]
        # This change only orders the existing provisional fetch candidates.
        # It must not turn their relaxed lexical admission into a display match.
        assert queue[0] == "r2"
        assert set(queue) == {"r0", "r1", "r2"}
        for rid in ("r0", "r1"):
            assert rank_resource(point, state["resources"][rid], store.evidence(job["job_id"], rid), state["request"]) is None
    finally:
        store.close()


def test_started_candidates_are_not_dispatched_twice(tmp_path):
    store, jobs, _, job, state = setup(tmp_path, [LEXICAL, PARTIAL])
    try:
        state["started"].add("r1")
        assert jobs._detail_queues(job, state)[job["knowledge_points"][0]["knowledge_point_id"]] == ["r0"]
    finally:
        store.close()


@pytest.mark.parametrize("evidence_ids", [[], ["missing"], ["ev-0"], ["ev-1", "missing"]])
def test_unbacked_or_other_resource_support_ids_do_not_receive_priority(tmp_path, monkeypatch, evidence_ids):
    store, jobs, _, job, state = setup(tmp_path, [LEXICAL, PARTIAL])
    def fixture_rank(point, resource, evidence, request, **kwargs):
        if resource["resource_id"] == "r0":
            return {"ranking_score": 80}
        return {"ranking_score": 40, "topic_evidence_status": "partial", "supporting_evidence_ids": evidence_ids}
    monkeypatch.setattr("backend.app.service.rank_resource", fixture_rank)
    try:
        assert jobs._detail_queues(job, state)[job["knowledge_points"][0]["knowledge_point_id"]] == ["r0", "r1"]
    finally:
        store.close()
