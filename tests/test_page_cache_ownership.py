"""Offline page-cache ownership tests: real service methods, plain-memory stores."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from backend.app.extractor import MetadataExtractor
from backend.app.grounded_related import prepare_pair
from backend.app.models import Candidate, Query, SearchRequest
from backend.app.service import JobService

STAMP = "2026-10-21T12:16:13.593438+00:00"
OLD = "2026-10-21T10:43:03.723666+00:00"
URL = "https://www.bilibili.com/video/BV1Ab4y1W7xT/"
POINT = {"knowledge_point_id": "p1", "text": "文件下载", "technology": "Streamlit"}
FRESH = {"hit": False, "cached_at": None, "stale": False}
SEARCH_CACHES = [FRESH, {"hit": True, "cached_at": OLD, "stale": False}, {"hit": True, "cached_at": OLD, "stale": True}]

class MemoryOnlyStore:
    def __init__(self): self.rows = []; self.resources = {}; self.page_writes = []
    def add_evidence(self, job_id, rid, pid, row): self.rows.append((rid, deepcopy(row)))
    def evidence(self, job_id, rid): return [deepcopy(row) for key, row in self.rows if key == rid]
    def save_resource(self, job_id, resource): self.resources[resource["resource_id"]] = deepcopy(resource)
    def cache_set(self, *args): self.page_writes.append(deepcopy(args))

class FixedPayloadFetcher:
    def __init__(self, payload): self.payload = deepcopy(payload); self.calls = 0
    async def enrich(self, candidate): self.calls += 1; return deepcopy(self.payload)

def own_page():
    data = {"videoData": {"bvid": "BV1Ab4y1W7xT", "title": "Streamlit 文件下载 st.download_button", "desc": "Streamlit 文件下载方法教学", "pages": [{"cid": 1, "page": 1, "part": "st.download_button 文件下载", "duration": 120}]}}
    html = "<html><body><script>window.__INITIAL_STATE__=" + json.dumps(data, ensure_ascii=False) + ";</script></body></html>"
    return MetadataExtractor().extract(html, URL, STAMP)

def setup(search_cache, payload=None, url=URL):
    service = JobService.__new__(JobService)  # Never constructs real Store/providers/services.
    service.store = MemoryOnlyStore(); service.settings = SimpleNamespace(max_detail_pages=10)
    service.course_library = None; service.fetcher = FixedPayloadFetcher(payload if payload is not None else own_page())
    service._page_cache_ttl = lambda value: 60
    service._save = lambda job: None; service._warn = lambda *args: None
    service._rank = lambda *args: None; service._refresh_gap_coverage = lambda *args: None
    request = SearchRequest(knowledge_points=[POINT["text"]], topic_technologies={POINT["text"]: "Streamlit"})
    job = {"job_id": "offline-memory", "progress": {"cache_hits": 0, "details_cached": 0, "details_attempted": 0, "details_completed": 0, "catalog_pages_attempted": 0, "catalog_pages_completed": 0}}
    state = {"request": request, "points": [deepcopy(POINT)], "resources": {}, "candidates": {}, "candidate_groups": {"p1": []}, "reserved": 0, "network_slots": asyncio.Semaphore(1)}
    candidate = Candidate(id="search-1", url=url, title="Search-only hint", snippet="Search-only snippet", source="offline-memory", query=POINT["text"])
    query = Query(knowledge_point_id="p1", query=POINT["text"])
    service._record_search_candidates(job, state, query, [candidate], deepcopy(search_cache))
    rid = next(iter(state["resources"]))
    return service, job, state, rid, candidate, query

def execute(service, job, state, rid, cached=None):
    asyncio.run(service._enrich_one(job, state, rid, "offline-cache-key", cached))
    return state["resources"][rid], service.store.evidence(job["job_id"], rid)

@pytest.mark.parametrize("search_cache", SEARCH_CACHES)
def test_fresh_page_owns_resource_cache_and_preserves_original_search_evidence(search_cache):
    service, job, state, rid, *_ = setup(search_cache)
    before = service.store.evidence(job["job_id"], rid)
    resource, evidence = execute(service, job, state, rid)
    assert resource["cache"] == FRESH and resource["fetch_status"] == "fetched"
    assert resource["video_evidence_status"] == "page_verified" and service.fetcher.calls == 1
    assert [row for row in evidence if row["kind"] == "search"] == before
    assert all(row["cache"] == FRESH for row in evidence if row["kind"] != "search")
    assert prepare_pair(POINT, resource, evidence, state["request"]) is not None

@pytest.mark.parametrize("search_cache", [FRESH, SEARCH_CACHES[-1]])
@pytest.mark.parametrize("page_stale", [False, True])
def test_page_cache_status_not_search_cache_controls_admission(search_cache, page_stale):
    service, job, state, rid, *_ = setup(search_cache)
    before = service.store.evidence(job["job_id"], rid)
    page_cache = {"hit": True, "cached_at": OLD, "stale": page_stale}
    resource, evidence = execute(service, job, state, rid, {"data": own_page(), "cache": page_cache})
    assert resource["cache"] == page_cache and service.fetcher.calls == 0
    assert job["progress"]["details_cached"] == 1 and job["progress"]["details_attempted"] == 0
    assert [row for row in evidence if row["kind"] == "search"] == before
    assert all(row["cache"] == page_cache for row in evidence if row["kind"] != "search")
    assert (prepare_pair(POINT, resource, evidence, state["request"]) is None) == page_stale

@pytest.mark.parametrize("later_cache", SEARCH_CACHES)
def test_later_search_does_not_overwrite_page_cache_or_page_evidence(later_cache):
    service, job, state, rid, candidate, query = setup(SEARCH_CACHES[-1])
    resource, evidence = execute(service, job, state, rid)
    page_before = [row for row in evidence if row["kind"] != "search"]
    service._record_search_candidates(job, state, query, [candidate], deepcopy(later_cache))
    after = service.store.evidence(job["job_id"], rid)
    assert state["resources"][rid]["cache"] == FRESH
    assert [row for row in after if row["kind"] != "search"] == page_before
    assert [row for row in after if row["kind"] == "search"][-1]["cache"] == later_cache
    assert prepare_pair(POINT, state["resources"][rid], after, state["request"]) is not None

@pytest.mark.parametrize("status", ["javascript_required", "fetch_error"])
def test_new_failed_fetch_is_not_promoted_to_verified_page(status):
    service, job, state, rid, *_ = setup(SEARCH_CACHES[-1], {"fetch_status": status, "fetched_at": STAMP, "evidence": []})
    resource, evidence = execute(service, job, state, rid)
    assert resource["cache"] == FRESH and resource["fetch_status"] == status
    assert resource["video_evidence_status"] == "search_discovered"
    assert prepare_pair(POINT, resource, evidence, state["request"]) is None

def test_stale_search_residue_has_real_guard_effect_in_memory_control():
    service, job, state, rid, *_ = setup(FRESH)
    resource, evidence = execute(service, job, state, rid)
    assert prepare_pair(POINT, resource, evidence, state["request"]) is not None
    control = deepcopy(resource); control["cache"] = deepcopy(SEARCH_CACHES[-1])
    assert prepare_pair(POINT, control, evidence, state["request"]) is None
    assert all(row["cache"] == FRESH for row in evidence if row["kind"] != "search")

def test_retained_actual_canvas_own_page_corrects_only_cache_ownership():
    fixture = json.loads((Path(__file__).parent/"fixtures/canvas-v5-own-page-search-cache-with-trace.json").read_text(encoding="utf8"))
    original = fixture["resource"]
    identity = original["field_provenance"]["video_evidence_status"]["evidence_id"]
    identity_row = next(row for row in fixture["evidence"] if row["evidence_id"] == identity)
    assert original["cache"]["hit"] is True and original["cache"]["cached_at"] < fixture["job_created_at"]
    assert original["fetched_at"] >= fixture["job_created_at"] and identity_row["cache"] == FRESH
    assert any(e["event"] == "bilibili_locale_received" and original["canonical_url"].rstrip("/").split("/")[-1] in e.get("url", "") for e in fixture["fetch_trace"]["events"])
    payload = deepcopy(original); payload["evidence"] = [deepcopy(row) for row in fixture["evidence"] if row["kind"] != "search"]
    service, job, state, rid, *_ = setup(original["cache"], payload, original["canonical_url"])
    resource, evidence = execute(service, job, state, rid)
    assert resource["cache"] == FRESH
    for field in ("fetched_at", "fetch_status", "video_evidence_status", "title", "description", "canonical_url"):
        assert resource[field] == original[field]
    assert len(resource["chapters"]) == len(original["chapters"])
    assert all(row["cache"] == FRESH for row in evidence if row["kind"] != "search")
