"""Offline execution/ownership/budget regressions for the actual discovery service."""
import asyncio
from copy import deepcopy

import pytest

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.models import Candidate, SearchRequest
from tests.test_video_readiness import record

from backend.app import service as stage


class ObservedService(stage.JobService):
    async def _search_queries(self, job, schedule, state):
        self.observed_state = state
        return await super()._search_queries(job, schedule, state)


class EmptyProvider:
    name = "offline"
    request_hook = None

    def __init__(self, calls, *, public=False, candidates=False):
        self.calls, self.public, self.candidates = calls, public, candidates
        self.last_requests, self.last_dns_requests, self.last_warnings, self.last_discovery = [], [], [], {}
        if public:
            self.name = "public_catalog"
        self.service = None
        self.public_snapshots = []

    async def search(self, query, language, limit, domain_filters, **kwargs):
        # Production providers reset this per-call trace before budget hooks.
        self.last_requests, self.last_dns_requests, self.last_warnings, self.last_discovery = [], [], [], {}
        if self.request_hook:
            await self.request_hook()
        if self.public:
            self.public_snapshots.append(deepcopy(self.service.observed_state.get("gap_query_history", {})))
        self.calls.append({"query": query, "public": self.public, "domains": list(domain_filters)})
        self.last_requests = [{"provider": self.name, "status": "completed", "candidate_count": 0}]
        if not self.candidates:
            return []
        number = len(self.calls)
        return [Candidate(id=f"c{number}-{i}", title="Matplotlib complete video course",
                          url=f"https://videos.example.org/course/{number}/{i}", source="offline",
                          query=query, resource_type_hint="video", type_source="search_template") for i in range(6)]


class NoTeachingPage:
    def __init__(self):
        self.calls = []

    async def enrich(self, candidate):
        self.calls.append(candidate["url"])
        return {"fetch_status": "fetched", "metadata_evidence_level": "page"}


@pytest.mark.asyncio
@pytest.mark.parametrize("search_budget,public_position", [(3, 1), (6, 2)])
async def test_real_public_second_or_third_round_does_not_consume_unexecuted_gap(tmp_path, search_budget, public_position):
    calls, provider = [], None
    provider = EmptyProvider(calls)
    public = EmptyProvider(calls, public=True)
    settings = Settings(database_path=str(tmp_path / "scheduler.sqlite3"), max_search_requests=search_budget,
                        max_detail_pages=0, search_min_interval_seconds=0)
    store = Store(settings.database_path)
    service = ObservedService(settings, store, provider=provider, fetcher=NoTeachingPage())
    service.public_catalog, public.service = public, service
    topic = "Matplotlib 误差棒绘制与对数坐标设置"
    request = SearchRequest(knowledge_points=[topic], learning_targets={topic: ["errorbar 参数", "set_yscale 对数坐标"]})
    try:
        job_id = service.create(request)["job_id"]
        await service.run(job_id)
        assert next(i for i, call in enumerate(calls) if call["public"]) == public_position
        preceding = {call["query"] for call in calls[:public_position] if not call["public"]}
        assert all(set(history) <= preceding for snapshot in public.public_snapshots for history in snapshot.values())
        actual_primary = {call["query"] for call in calls if not call["public"]}
        histories = service.observed_state.get("gap_query_history", {})
        assert histories and all(history <= actual_primary for history in histories.values())
        assert len(calls) <= search_budget
        assert store.get_job(job_id)["progress"]["details_attempted"] == 0
    finally:
        store.close()


def probe_fixture(*, confirmed=True, atomic=False, started=2):
    topic = "Matplotlib 误差棒绘制" if atomic else "Matplotlib 误差棒绘制与对数坐标设置"
    point = {"knowledge_point_id": "p", "text": topic}
    if confirmed:
        point["learning_targets"] = ["errorbar 参数"]
    resource, evidence = record("Matplotlib complete video course")
    evidence[0]["query"] = "executed-gap"
    state = {"gap_query_history": {"p": {"executed-gap"}},
             "gap_probes_started": {"p": {f"done-{i}" for i in range(started)}}}
    return point, resource, evidence, state


@pytest.mark.parametrize("started,accepted", [(0, True), (1, True), (2, True), (3, True), (4, False)])
def test_confirmed_actual_gap_probe_is_bounded_at_four(started, accepted):
    args = probe_fixture(started=started)
    assert stage.JobService._gap_catalog_probe(*args) is accepted


@pytest.mark.parametrize("mutation", ["wrong-point", "unexecuted-query", "wrong-tool", "tool-prefix-lookalike", "no-type", "no-video"])
def test_extra_gap_probe_requires_own_executed_query_explicit_tool_and_video_identity(mutation):
    point, resource, evidence, state = probe_fixture(atomic=True)
    if mutation == "wrong-point": evidence[0]["knowledge_point_id"] = "other"
    if mutation == "unexecuted-query": evidence[0]["query"] = "never-executed"
    if mutation == "wrong-tool": evidence[0]["title"] = "Pandas complete video course"
    if mutation == "tool-prefix-lookalike": evidence[0]["title"] = "MatplotlibWrapper complete video course"
    if mutation == "no-type": resource["resource_type"] = "unknown"
    if mutation == "no-video": resource["video_evidence_status"] = "none"
    assert not stage.JobService._gap_catalog_probe(point, resource, evidence, state)


def test_only_confirmed_atomic_unit_can_supply_explicit_namespace_and_other_point_cap_is_irrelevant():
    point, resource, evidence, state = probe_fixture(atomic=True)
    state["gap_probes_started"]["other"] = {str(i) for i in range(40)}
    assert stage.JobService._gap_catalog_probe(point, resource, evidence, state)
    point.pop("learning_targets")
    state["gap_probes_started"]["p"] = set()
    assert not stage.JobService._gap_catalog_probe(point, resource, evidence, state)


def test_manual_gap_and_primary_probes_retain_two_limit_even_with_confirmed_targets():
    point, resource, evidence, state = probe_fixture(confirmed=False, started=1)
    assert stage.JobService._gap_catalog_probe(point, resource, evidence, state)
    state["gap_probes_started"]["p"].add("second")
    assert not stage.JobService._gap_catalog_probe(point, resource, evidence, state)
    point["learning_targets"] = ["errorbar 参数"]
    assert stage.JobService._gap_catalog_probe(point, resource, evidence, state)
    assert not stage.JobService._targeted_catalog_probe(point, resource, evidence, state)


@pytest.mark.asyncio
@pytest.mark.parametrize("confirmed,search_budget,detail_budget,expected", [(True, 3, 40, 4), (False, 3, 40, 2),
                                                                                     (True, 1, 40, 2), (True, 3, 1, 1)])
async def test_actual_detail_scheduler_adds_only_gap_capacity_and_never_raises_total_budget(tmp_path, confirmed, search_budget, detail_budget, expected):
    calls = []
    provider, fetcher = EmptyProvider(calls, candidates=True), NoTeachingPage()
    settings = Settings(database_path=str(tmp_path / "details.sqlite3"), max_search_requests=search_budget,
                        max_detail_pages=detail_budget, global_concurrency=1, search_min_interval_seconds=0)
    store = Store(settings.database_path)
    service = ObservedService(settings, store, provider=provider, fetcher=fetcher)
    topic = "Matplotlib 误差棒绘制与对数坐标设置"
    request = SearchRequest(knowledge_points=[topic], preferred_platforms=[],
                            learning_targets={topic: ["errorbar 参数"]} if confirmed else {})
    try:
        job_id = service.create(request)["job_id"]
        await service.run(job_id)
        job = store.get_job(job_id)
        assert len(fetcher.calls) == expected
        assert job["progress"]["details_attempted"] == expected <= detail_budget
        assert service.observed_state["reserved"] <= detail_budget
        assert job["budgets"]["max_detail_pages"] == settings.max_detail_pages == detail_budget
        assert not service.results(job_id)["groups"][0]["items"]
        assert not service.results(job_id)["groups"][0]["partial_items"]
    finally:
        store.close()
