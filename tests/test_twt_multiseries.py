"""Actual retained directory/trace replay and bounded synthetic transport edges."""
from copy import deepcopy
import json
from pathlib import Path

import httpx
import pytest

from backend.app import techwithtim_catalog as catalog
from backend.app.config import Settings
from backend.app.db import Store
from backend.app.fetcher import FetchStopped, NETWORK_OBSERVER
from backend.app.models import SearchRequest
from backend.app.providers import SearchBudgetReached, SearchError, SearXNGProvider
from backend.app.service import JobService
from tests.test_techwithtim_catalog import make, card, ENTRY, SERIES, ORIGIN


FIXTURE = Path(__file__).parent / "fixtures/twt_multiseries/actual-directories.json"


class NoNetwork:
    async def fetch(self, *args, **kwargs):
        pytest.fail("Retained metadata replay must not make an external request")


def actual_provider():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    provider = catalog.TechWithTimCatalogProvider(Settings(), fetcher=NoNetwork())
    for document in data["documents"]:
        provider._put(document["source_url"], document)
    return provider, data


def actual_point(data, word):
    point = next(p for p in data["points"] if word in p["text"])
    attempt = next(a for a in data["attempts"] if a["knowledge_point_id"] == point["knowledge_point_id"])
    return point, attempt


@pytest.mark.asyncio
@pytest.mark.parametrize("word", ["状态机", "真实时间"])
async def test_actual_full_targets_select_two_observed_series_and_preserve_early_diversity(word):
    provider, data = actual_provider()
    point, attempt = actual_point(data, word)
    before = deepcopy(provider.memory_cache)
    rows = await provider.search(attempt["query"], "zh", 6, [], original_point=point["text"], learning_targets=point["learning_targets"])
    assert len(rows) == 6 and len(provider.last_discovery["indexes"]) == 3
    assert provider.memory_cache == before and not provider.last_requests
    assert len({r.discovery_evidence["parent_series_url"] for r in rows[:2]}) == 2
    if word == "状态机":
        assert rows[0].title == "Scoring & Health Bars"
        assert rows[0].discovery_evidence["heading_hint_matches"]
    else:
        assert any(r.title == "Tutorial #1" for r in rows[:2])
    assert [r.discovery_evidence["provider_result_index"] for r in rows] == list(range(6))
    assert all(r.resource_type_hint == "unknown" and not r.type_source for r in rows)
    assert all(r.discovery_evidence["confidence"] == "low" and r.discovery_evidence["independent_detail_required"] for r in rows)
    assert NETWORK_OBSERVER.get() is None


def test_zero_signal_diversity_is_source_position_based_not_demo_url_or_tool():
    cards = [{"url": f"https://www.techwithtim.net/tutorials/python-programming/opaque-{i}",
              "title": f"General series {i}", "snippet": "Python explanations"} for i in range(8)]
    plan = {"literal_terms": ["mystery"], "heading_hint_terms": []}
    assert [index for index, _ in catalog.series_probe_order(cards, plan)] == [0, 4]
    changed = deepcopy(cards)
    for item in changed:
        item["url"] = item["url"].replace("opaque", "clock-score")
    assert [index for index, _ in catalog.series_probe_order(changed, plan)] == [0, 4]
    cards[6]["snippet"] = "mystery explanation"
    assert [index for index, _ in catalog.series_probe_order(cards, plan)] == [6, 0]


def generic_documents(second_value=None):
    other = ENTRY + "/other-series"
    lesson = SERIES + "/unrelated-first"
    documents = {ENTRY: (card(SERIES, "General first", "No specific subject") + card(other, "General second", "No specific subject")).encode(),
                 SERIES: f'<div class="tutoriallayout__Lessons-test"><a href="{lesson}">A topic</a></div>'.encode(),
                 other: second_value if second_value is not None else f'<div class="tutoriallayout__Lessons-test"><a href="{other}/unrelated-second">Another topic</a></div>'.encode()}
    return documents, other, lesson


@pytest.mark.asyncio
async def test_third_index_budget_failure_keeps_only_first_observed_series_links():
    documents, other, lesson = generic_documents()
    provider, transport = make(documents)
    reservations = []
    async def reserve():
        if len(reservations) >= 3:
            raise SearchBudgetReached()
        reservations.append(1)
    provider.request_hook = reserve
    with pytest.raises(SearchBudgetReached) as failure:
        await provider.search("pygame unknown", "en", 6, [], original_point="pygame unknown")
    assert transport.calls == [ORIGIN + "/robots.txt", ENTRY, SERIES]
    assert [row.url for row in failure.value.partial_candidates] == [lesson]
    assert all(row.resource_type_hint == "unknown" for row in failure.value.partial_candidates)
    assert provider.last_discovery["budget_stopped"] and NETWORK_OBSERVER.get() is None


@pytest.mark.asyncio
async def test_second_series_timeout_preserves_first_without_retry():
    documents, other, lesson = generic_documents(FetchStopped("timeout", "synthetic timeout"))
    provider, transport = make(documents)
    rows = await provider.search("pygame unknown", "en", 6, [], original_point="pygame unknown")
    assert [row.url for row in rows] == [lesson]
    assert transport.calls == [ORIGIN + "/robots.txt", ENTRY, SERIES, other]
    assert provider.last_warnings and NETWORK_OBSERVER.get() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("refusal", [(403, b"", {}), b"<html><title>Verify you are human</title></html>"])
async def test_second_series_refusal_stops_source_without_rediscovery_or_alternate(refusal):
    documents, other, _ = generic_documents(refusal)
    provider, transport = make(documents)
    with pytest.raises(SearchError) as failure:
        await provider.search("pygame unknown", "en", 6, [], original_point="pygame unknown")
    assert failure.value.code == "access_denied"
    assert transport.calls == [ORIGIN + "/robots.txt", ENTRY, SERIES, other]
    assert provider.last_discovery["source_stopped"] and NETWORK_OBSERVER.get() is None
    with pytest.raises(SearchError):
        await provider.search("Python other", "en", 6, [], original_point="Python other")
    assert len(transport.calls) == 4


def test_priority_rejects_other_points_urls_nonpublic_and_bad_indices():
    point = {"knowledge_point_id": "p"}
    resource = {"canonical_url": SERIES + "/lesson"}
    row = {"kind": "search", "source": "techwithtim_catalog", "knowledge_point_id": "p", "url": resource["canonical_url"],
           "discovery_evidence": {"kind": "public_catalog_link", "independent_detail_required": True, "admission_result_index": 0}}
    assert JobService._public_catalog_probe_priority(point, resource, [row]) == 100
    for updates in [{"knowledge_point_id": "other"}, {"url": "https://attacker.example/a"}, {"source": "searxng"}]:
        assert JobService._public_catalog_probe_priority(point, resource, [dict(row, **updates)]) == 1
    for bad in [-1, 6, True, "0", None, 1e100]:
        mutated = deepcopy(row); mutated["discovery_evidence"]["admission_result_index"] = bad
        assert JobService._public_catalog_probe_priority(point, resource, [mutated]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("word", ["状态机", "真实时间"])
async def test_actual_directory_response_order_survives_ingestion_and_two_probe_dispatch(tmp_path, word):
    provider, data = actual_provider()
    point, attempt = actual_point(data, word)
    expected = await provider.search(attempt["query"], "zh", 6, [], original_point=point["text"], learning_targets=point["learning_targets"])
    fetched = []
    class NoTeaching:
        async def enrich(self, candidate):
            fetched.append(candidate["url"])
            return {"fetch_status": "fetched", "metadata_evidence_level": "page", "resource_type": "unknown", "video_evidence_status": "none", "evidence": []}
    settings = Settings(database_path=str(tmp_path / "isolated.sqlite3"), searxng_url="https://search.example", public_catalog_fallback=True,
                        search_min_interval_seconds=0, max_search_requests=12, max_detail_pages=40)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"results": []}))) as client:
        store = Store(settings.database_path)
        service = JobService(settings, store, provider=SearXNGProvider(settings, client), fetcher=NoTeaching())
        service.twt_catalog = provider
        try:
            request = SearchRequest(knowledge_points=[point["text"]], learning_targets={point["text"]: point["learning_targets"]})
            job_id = service.create(request)["job_id"]
            await service.run(job_id)
            assert fetched == [r.url for r in expected[:2]]
            assert len(fetched) == 2
            result = service.results(job_id)["groups"][0]
            assert not result["items"] and not result["partial_items"] and not result["review_items"]
            assert store.get_job(job_id)["progress"]["search_requests"] <= 12
            records = [e for r in store.resources(job_id).values() for e in store.evidence(job_id, r["resource_id"]) if e.get("source") == "techwithtim_catalog"]
            assert sorted(e["discovery_evidence"]["admission_result_index"] for e in records) == list(range(6))
            capability = service.capabilities()["public_catalog_discovery"]
            assert capability["max_indexes_per_query"] == 3 and capability["max_indexes_by_source"] == {"freecodecamp": 2, "techwithtim": 3}
        finally:
            store.close()


@pytest.mark.asyncio
async def test_tight_budget_reserves_robots_plus_three_twt_indexes_without_raising_global_limit(tmp_path):
    class FourRequestCatalog:
        name = "techwithtim_catalog"
        request_hook = dns_request_hook = budget_check_hook = None
        last_requests, last_dns_requests, last_warnings, last_discovery = [], [], [], {}
        @staticmethod
        def supports(point):
            return True
        async def search(self, *args, **kwargs):
            for _ in range(4):
                await self.request_hook()
            return []
    class NoDetails:
        async def enrich(self, *args, **kwargs):
            pytest.fail("No lesson candidate was discovered")
    settings = Settings(database_path=str(tmp_path / "tight.sqlite3"), searxng_url="https://search.example", public_catalog_fallback=True,
                        search_min_interval_seconds=0, max_search_requests=15, max_detail_pages=40,
                        searxng_video_engines=("primary",), searxng_fallback_engines=("backup",))
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"results": []}))) as client:
        store = Store(settings.database_path)
        service = JobService(settings, store, provider=SearXNGProvider(settings, client), fetcher=NoDetails())
        service.twt_catalog = FourRequestCatalog()
        try:
            job_id = service.create(SearchRequest(knowledge_points=[f"pygame 独立技能{i}" for i in range(4)]))["job_id"]
            await service.run(job_id)
            attempts = store.attempts(job_id)
            assert attempts[0]["priority_request_limit"] == 2  # floor((15 - 4 public requests) / 4 units)
            assert len({a["knowledge_point_id"] for a in attempts[:4]}) == 4
            assert all(a["provider"] == "searxng" for a in attempts[:4])
            assert any(a["provider"] == "techwithtim_catalog" for a in attempts)
            assert store.get_job(job_id)["progress"]["search_requests"] <= 15
        finally:
            store.close()
