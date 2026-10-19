"""Synthetic responses are isolated here and never imported by application code."""
import asyncio
import json
from dataclasses import replace
import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from backend.app.config import Settings
from backend.app.db import Store
from backend.app.llm import Expansion, OpenAICompatibleLLM
from backend.app.main import create_app
from backend.app.models import Candidate, SearchRequest, now
from backend.app.providers import SearXNGProvider, TavilyProvider, SearchError
from backend.app.queries import fair_queries, generate_queries
from backend.app.ranking import has_type_evidence, has_video_evidence, rank_resource, relevance, type_from_discovered_url, version_conflict
from backend.app.service import JobService
from backend.app.fetcher import Fetcher


class FakeSearch:
    name = "test-only"
    def __init__(self, fail_after=None, empty=False):
        self.calls = []
        self.fail_after, self.empty = fail_after, empty

    async def search(self, query, language, limit, domain_filters):
        self.calls.append((query, language, domain_filters))
        if self.fail_after is not None and len(self.calls) > self.fail_after:
            raise SearchError("search_timeout", "测试来源超时")
        if self.empty:
            return []
        return [Candidate(id=str(len(self.calls)), title="Python 列表与字典 HTML 表单校验 SQL 多表连接 入门视频教程", url="https://example.org/course/python?p=2&utm_source=test", snippet="列表 字典 表单 教程 SQL 多表连接", source="test-only", query=query,
                          resource_type_hint="video", type_source="search_template", source_engines=["test-engine"])]


class FakeFetcher:
    def __init__(self):
        self.calls = []
    async def enrich(self, candidate):
        self.calls.append(candidate)
        return {"fetch_status": "search_only_policy", "metadata_evidence_level": "search", "evidence": []}


class BrokenLLM:
    async def expand(self, *args):
        raise ValueError("SECRET must never leak")
    async def rerank(self, *args):
        raise ValueError("SECRET must never leak")


def service(tmp_path, provider=None, settings=None, llm=None):
    settings = settings or Settings(database_path=str(tmp_path / "test.sqlite3"), searxng_url="http://trusted-private:8080")
    return JobService(settings, Store(settings.database_path), provider=provider or FakeSearch(), fetcher=FakeFetcher(), llm=llm)


def test_request_validation_and_dedup():
    assert SearchRequest(knowledge_points=[" X ", "X"]).knowledge_points == ["X"]
    with pytest.raises(ValidationError):
        SearchRequest(knowledge_points=[" "])
    with pytest.raises(ValidationError):
        SearchRequest(knowledge_points=["A"], searxng_url="http://attacker")


def test_queries_arbitrary_point_open_and_targeted_preserve_version():
    req = SearchRequest(knowledge_points=["稀疏张量分块压缩"], technical_version="TensorFlow 2", preferred_platforms=["bilibili", "icourse163", "xuetangx"])
    queries = generate_queries("p", req.knowledge_points[0], req)
    assert len(queries) == 5
    assert sum(not q.domain_filters for q in queries) == 2
    assert all("稀疏张量分块压缩" in q.query and "TensorFlow 2" in q.query for q in queries)
    assert {q.domain_filters[0] for q in queries if q.domain_filters} == {"bilibili.com", "icourse163.org", "xuetangx.com"}


def test_query_round_robin():
    req = SearchRequest(knowledge_points=["a", "b", "c"])
    schedule = fair_queries([generate_queries(p, p, req) for p in req.knowledge_points])
    assert [q.knowledge_point_id for q in schedule[:6]] == ["a", "b", "c", "a", "b", "c"]


@pytest.mark.asyncio
async def test_searxng_documented_request_and_missing_fields():
    def respond(request):
        assert request.url.path == "/search"
        assert request.url.params["format"] == "json" and request.url.params["language"] == "zh-CN"
        return httpx.Response(200, json={"results": [{"title": "Python课程", "url": "https://www.bilibili.com/video/BV-test"}, {"title": "missing URL"}, {"title": "wrong site", "url": "https://example.org/c"}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        results = await SearXNGProvider(Settings(searxng_url="http://configured"), client).search("Python", "zh", 5, ["bilibili.com"])
    assert len(results) == 1 and results[0].snippet == ""


@pytest.mark.asyncio
async def test_tavily_opt_in_official_auth_and_payload():
    def respond(request):
        assert request.headers["authorization"] == "Bearer private-test-token"
        data = json.loads(request.content)
        assert data["include_answer"] is False and data["include_raw_content"] is False
        assert data["include_domains"] == ["icourse163.org"]
        assert data["language"] == "zh-cn" and data["filter_by_language"] is False
        assert data["search_depth"] == "basic" and data["auto_parameters"] is False
        assert "api_key" not in data
        return httpx.Response(200, json={"results": [{"title": "SQL课程", "url": "https://www.icourse163.org/course/SQL"}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        results = await TavilyProvider(Settings(tavily_api_key="private-test-token"), client).search("SQL", "zh", 5, ["icourse163.org"])
    assert len(results) == 1


@pytest.mark.asyncio
async def test_provider_timeout_bounded_retry_and_safe_error():
    calls = []
    def timeout(request):
        calls.append(request)
        raise httpx.ReadTimeout("secret internal endpoint", request=request)
    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
        provider = SearXNGProvider(Settings(searxng_url="http://internal-secret"), client)
        with pytest.raises(SearchError) as error:
            await provider.search("SQL", "zh", 5, [])
    assert len(calls) == 2
    assert "secret" not in str(error.value)


@pytest.mark.asyncio
async def test_429_pauses_source_without_retry():
    calls = []
    def throttled(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "120"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(throttled)) as client:
        provider = SearXNGProvider(Settings(searxng_url="http://configured"), client)
        for _ in range(2):
            with pytest.raises(SearchError) as exc:
                await provider.search("SQL", "zh", 5, [])
            assert exc.value.code == "rate_limited"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_searxng_upstream_partial_and_all_failed():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"results": [{"title": "SQL教程", "url": "https://example.org/course"}], "unresponsive_engines": [["brave", "too many requests"]]}))) as client:
        provider = SearXNGProvider(Settings(searxng_url="http://configured"), client)
        assert len(await provider.search("SQL", "zh", 5, [])) == 1
        assert provider.last_warnings[0]["engine"] == "brave"
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"results": [], "unresponsive_engines": [["google", "timeout"]]}))) as client:
        provider = SearXNGProvider(Settings(searxng_url="http://configured"), client)
        with pytest.raises(SearchError) as exc:
            await provider.search("SQL", "zh", 5, [])
        assert exc.value.code == "upstream_engine_failed"
        assert provider.last_status == "fault"
        store = Store(":memory:")
        svc = JobService(Settings(searxng_url="http://configured"), store, provider=provider, fetcher=FakeFetcher())
        assert svc.capabilities()["search"]["status"] == "fault"
        store.close()


@pytest.mark.asyncio
async def test_multimapping_dedupe_all_evidence_and_cache(tmp_path):
    svc = service(tmp_path)
    request = SearchRequest(knowledge_points=["Python 列表与字典", "HTML 表单校验"])
    first = svc.create(request)["job_id"]
    await svc.run(first)
    result = svc.results(first)
    assert result["status"] == "completed"
    assert all(len(group["items"]) == 1 for group in result["groups"])
    assert len(svc.store.resources(first)) == 1
    assert len(svc.store.matches(first)) == 2
    assert len(svc.store.evidence(first, result["groups"][0]["items"][0]["resource"]["resource_id"])) == 10
    assert all(e["candidate_id"] for e in result["groups"][0]["items"][0]["evidence"])
    assert result["groups"][0]["items"][0]["resource"]["canonical_url"].endswith("?p=2")
    second = svc.create(request)["job_id"]
    await svc.run(second)
    assert len(svc.provider.calls) == 10 and len(svc.fetcher.calls) == 1
    assert svc.store.get_job(second)["progress"]["cache_hits"] == 11
    assert svc.store.get_job(second)["progress"]["details_cached"] == 1
    assert svc.store.get_job(second)["progress"]["details_completed"] == 0
    assert all(a["cache_hit"] and a["cached_at"] for a in svc.results(second)["search_attempts"])


@pytest.mark.asyncio
async def test_partial_failure_and_no_fake_results(tmp_path):
    svc = service(tmp_path, FakeSearch(fail_after=1))
    job = svc.create(SearchRequest(knowledge_points=["SQL 多表连接"]))["job_id"]
    await svc.run(job)
    assert svc.store.get_job(job)["status"] == "partial"
    assert svc.results(job)["groups"][0]["items"]
    allfail = svc.create(SearchRequest(knowledge_points=["没有预设过的拓扑课程"]))["job_id"]
    await svc.run(allfail)
    assert svc.store.get_job(allfail)["status"] == "failed"
    assert not svc.results(allfail)["groups"][0]["items"]


@pytest.mark.asyncio
async def test_successful_zero_results_is_completed(tmp_path):
    svc = service(tmp_path, FakeSearch(empty=True))
    jid = svc.create(SearchRequest(knowledge_points=["未知知识点"]))["job_id"]
    await svc.run(jid)
    assert svc.results(jid)["status"] == "completed"
    assert not svc.results(jid)["groups"][0]["items"]


@pytest.mark.asyncio
async def test_fair_budget_and_llm_failure_fallback(tmp_path):
    settings = Settings(database_path=str(tmp_path / "test.sqlite3"), max_search_requests=2)
    svc = service(tmp_path, settings=settings, llm=BrokenLLM())
    jid = svc.create(SearchRequest(knowledge_points=["Python 列表", "HTML 表单"]))["job_id"]
    await svc.run(jid)
    job = svc.store.get_job(jid)
    assert job["status"] == "partial" and job["progress"]["search_requests"] == 2
    assert all(group["items"] for group in svc.results(jid)["groups"])
    assert "SECRET" not in json.dumps(job)
    assert any("回退" in warning for warning in job["warnings"])
    assert svc.capabilities()["llm"]["status"] == "fault"


def test_restart_marks_queued_and_running_interrupted(tmp_path):
    svc = service(tmp_path)
    jid = svc.create(SearchRequest(knowledge_points=["Python"]))["job_id"]
    job = svc.store.get_job(jid)
    job["status"] = "running"
    svc.store.save_job(job)
    svc.store.close()
    store = Store(str(tmp_path / "test.sqlite3"))
    store.recover()
    assert store.get_job(jid)["status"] == "interrupted"


def test_expired_cache_explicit_opt_in(tmp_path):
    store = Store(str(tmp_path / "cache.sqlite3"))
    store.cache_set("x", "search", ["actual response"], -1)
    assert store.cache_get("x") is None
    assert store.cache_get("x", allow_stale=True)["cache"]["stale"] is True


def test_llm_keywords_urls_extra_fields_forbidden():
    for data in ({"keywords": ["https://invented.example/video"]}, {"keywords": ["SQL"], "url": "https://evil.example"}):
        with pytest.raises(ValidationError):
            Expansion.model_validate(data)


@pytest.mark.asyncio
async def test_llm_rerank_rejects_new_url_unknown_id_and_evidence():
    payloads = [{"rankings": [{"candidate_id": "known", "rank": 1, "evidence_ids": ["e"], "url": "https://invented.example"}]},
                {"rankings": [{"candidate_id": "unknown", "rank": 1, "evidence_ids": []}]},
                {"rankings": [{"candidate_id": "known", "rank": 1, "evidence_ids": ["invented"]}]}]
    for payload in payloads:
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}]}))) as client:
            llm = OpenAICompatibleLLM(Settings(llm_model="test"), client)
            with pytest.raises(ValueError):
                await llm.rerank("SQL", [{"candidate_id": "known", "evidence_ids": ["e"]}])


def test_versions_not_mixed_and_reasons_cautious():
    assert version_conflict("Vue 3 表单", "", "Vue 2 表单教程")
    assert version_conflict("Vue 表单", "3", "Vue 2 表单教程")
    point = {"knowledge_point_id": "k", "text": "Python 字典"}
    resource = {"resource_id": "r", "url": "https://example.org/lesson", "title": "Python 字典视频教程", "metadata_evidence_level": "search", "description": "Python 字典",
                "resource_type": "video", "field_provenance": {"resource_type": {"evidence_id": "e", "source": "search_template"}}}
    evidence = [{"evidence_id": "e", "kind": "search", "title": "Python 字典视频教程", "snippet": "Python 字典", "type_source": "search_template", "resource_type_hint": "video"}]
    match = rank_resource(point, resource, evidence, SearchRequest(knowledge_points=[point["text"]]), require_type=False)
    assert "可能涉及" in match["recommendation_reason"]
    assert "description" not in match["coverage_basis"]


def test_prerequisite_only_live_discovery_regression():
    point = {"knowledge_point_id": "k", "text": "Python 列表与字典"}
    resource = {"resource_id": "r", "url": "https://www.icourse163.org/course/-1001871002",
                "title": "Python云端系统开发入门_北京理工大学_中国大学MOOC(慕课)",
                "metadata_evidence_level": "search", "resource_type": "course",
                "field_provenance": {"resource_type": {"evidence_id": "e", "source": "url_pattern"}}}
    evidence = [{"evidence_id": "e", "kind": "search", "title": resource["title"],
                 "snippet": "Python语言程序设计课程。具体地，学习者需要预先掌握Python的数字类型、字符串类型、分支、循环、函数、列表类型、字典类型、文件和第三方库使用等概念和编程方法。"}]
    request = SearchRequest(knowledge_points=[point["text"]])
    assert rank_resource(point, resource, evidence, request, require_type=False) is None
    # This isolates topic relevance; an actual recommendation also needs video evidence.
    assert rank_resource(point, dict(resource, title="Python列表与字典入门课程"), evidence, request, require_type=False) is not None
    for snippet in ("无需预先掌握Python列表与字典，本课程从零教学。", "无先修要求：Python列表与字典入门课程。",
                    "无需任何基础，本课程讲解Python列表与字典。"):
        evidence[0]["snippet"] = snippet
        assert rank_resource(point, resource, evidence, request, require_type=False) is not None


@pytest.mark.parametrize("point_text,title,expected", [
    ("Python", "Python3 tutorial", 1),
    ("Python", "Python3.13 tutorial", 1),
    ("Python3", "Python tutorial", 1),
    ("Python", "Python3tutorial", 0),
    ("Java", "JavaScript tutorial", 0),
    ("SQL", "NoSQL tutorial", 0),
    ("D3.js", "D3.js tutorial", 1),
    ("D3.js", "D3 tutorial", 0),
    ("C++", "C++17 tutorial", 1),
    ("C#", "C#12 tutorial", 1),
    ("C++", "C# tutorial", 0),
])
def test_complete_version_alias_preserves_technology_token_boundaries(point_text, title, expected):
    assert relevance(point_text, title) == expected
    resource = {"resource_id": "r", "url": "https://example.org/tutorial", "title": title,
                "metadata_evidence_level": "search", "resource_type": "video"}
    point = {"knowledge_point_id": "k", "text": point_text}
    assert (rank_resource(point, resource, [], SearchRequest(knowledge_points=[point_text]), require_type=False) is not None) is bool(expected)


@pytest.mark.parametrize("point_text,description,expected", [
    ("Python 列表与字典", "本课程讲解Python列表与字典，先修要求：基础算术。", True),
    ("Python lists and dictionaries", "This course teaches Python lists and dictionaries, prerequisites: basic arithmetic.", True),
    ("Python lists and dictionaries", "This course teaches Python lists and dictionaries, and prior knowledge of arithmetic is required.", True),
    ("Python 列表与字典", "先修要求：预先掌握Python列表与字典，本课程讲解云端系统开发。", False),
    ("Python lists and dictionaries", "Prerequisites: prior knowledge of Python lists and dictionaries, this course teaches cloud development.", False),
])
def test_teaching_and_prerequisite_clauses_in_one_description_are_independent(point_text, description, expected):
    resource = {"resource_id": "r", "url": "https://example.org/course", "title": "Introduction course",
                "metadata_evidence_level": "page", "resource_type": "course", "description": description,
                "field_provenance": {"description": {"source": "jsonld.description"}}}
    point = {"knowledge_point_id": "k", "text": point_text}
    assert (rank_resource(point, resource, [], SearchRequest(knowledge_points=[point_text]), require_type=False) is not None) is expected


def test_api_live_configuration_failure_no_secrets(tmp_path):
    settings = Settings(database_path=str(tmp_path / "api.sqlite3"))
    with TestClient(create_app(settings, fetcher=FakeFetcher()), base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        assert client.get("/health").json()["mode"] == "live"
        caps = client.get("/api/capabilities").json()
        assert caps["search"]["status"] == "unconfigured"
        platforms = {p["id"]: p for p in caps["platforms"]}
        assert platforms["bilibili"]["metadata"] == "site_policy_blocked"
        assert platforms["bilibili"]["policy_status"] == "explicit_permission_required"
        assert platforms["icourse163"]["metadata"] == "public_course_metadata_only"
        assert platforms["xuetangx"]["metadata"] == "site_policy_blocked"
        assert platforms["xuetangx"]["policy_status"] == "explicit_scraping_prohibition"
        assert platforms["xuetangx"]["source_url"] == "https://www.xuetangx.com/app/protocol"
        assert all(platforms[key]["source_url"].startswith("https://") and platforms[key]["reviewed_at"] for key in ("bilibili", "icourse163", "xuetangx"))
        response = client.post("/api/search-jobs", json={"knowledge_points": ["Python 字典"]})
        assert response.status_code == 202
        jid = response.json()["job_id"]
        import time
        for _ in range(50):
            job = client.get(f"/api/search-jobs/{jid}").json()
            if job["status"] in {"failed", "completed", "partial"}:
                break
            time.sleep(.01)
        assert job["status"] == "failed"
        assert job["errors"][0]["code"] == "configuration_error"
        assert client.get(f"/api/search-jobs/{jid}/results").json()["groups"][0]["items"] == []
        assert client.get("/api/search-jobs/missing").status_code == 404
        assert client.post("/api/search-jobs", json={"knowledge_points": []}).status_code == 422


@pytest.mark.asyncio
async def test_deadline_preserves_partial_results(tmp_path):
    class SlowFetch:
        async def enrich(self, candidate):
            await asyncio.sleep(3)
    svc = service(tmp_path, settings=Settings(database_path=str(tmp_path / "test.sqlite3"), deadline_seconds=.1))
    svc.fetcher = SlowFetch()
    jid = svc.create(SearchRequest(knowledge_points=["Python 字典"]))["job_id"]
    await svc.run(jid)
    assert svc.store.get_job(jid)["status"] == "partial"
    assert svc.results(jid)["groups"][0]["items"]
    assert any("已开始的详情补全" in warning for warning in svc.store.get_job(jid)["warnings"])


def test_documentation_keywords_or_forged_type_are_not_course_evidence():
    point = {"knowledge_point_id": "k", "text": "HTML 表单校验"}
    resource = {"resource_id": "r", "url": "https://developer.mozilla.org/zh-CN/docs/Learn/Forms/Form_validation",
                "title": "HTML 表单校验教程", "resource_type": "unknown", "metadata_evidence_level": "page", "fetch_status": "fetched"}
    evidence = [{"evidence_id": "s", "kind": "search", "title": resource["title"], "snippet": "HTML表单校验学习教程"}]
    request = SearchRequest(knowledge_points=[point["text"]])
    assert rank_resource(point, resource, evidence, request) is None
    assert rank_resource(point, resource, evidence, request, require_type=False) is not None
    forged = dict(resource, resource_type="course", field_provenance={"resource_type": {"evidence_id": "not-observed", "source": "jsonld.@type"}})
    assert not has_type_evidence(forged, evidence)
    assert rank_resource(point, forged, evidence, request) is None


@pytest.mark.parametrize("point_text,generic_title,specific_title", [
    ("SQL 多表连接", "SQL数据库完整入门课程", "SQL JOIN多表连接课程"),
    ("Python 列表与字典", "Python编程完整入门课程", "Python列表与字典课程"),
    ("SQL joins", "SQL programming course", "SQL joins course"),
])
def test_compound_points_require_specific_evidence_not_only_the_technology(point_text, generic_title, specific_title):
    point = {"knowledge_point_id": "k", "text": point_text}
    resource = {"resource_id": "r", "url": "https://example.org/video", "title": generic_title,
                "resource_type": "video", "metadata_evidence_level": "search",
                "field_provenance": {"resource_type": {"evidence_id": "e", "source": "search_template"}}}
    evidence = [{"evidence_id": "e", "kind": "search", "title": generic_title, "snippet": generic_title,
                 "type_source": "search_template", "resource_type_hint": "video"}]
    request = SearchRequest(knowledge_points=[point_text])
    assert rank_resource(point, resource, evidence, request, require_type=False) is None
    assert rank_resource(point, dict(resource, title=specific_title), evidence, request, require_type=False) is not None


def test_english_function_words_do_not_create_a_topic_match():
    point = {"knowledge_point_id": "k", "text": "Python lists and dictionaries"}
    resource = {"resource_id": "r", "url": "https://example.org/video", "title": "And the with course",
                "resource_type": "video", "metadata_evidence_level": "search",
                "field_provenance": {"resource_type": {"evidence_id": "e", "source": "search_template"}}}
    evidence = [{"evidence_id": "e", "kind": "search", "title": resource["title"], "snippet": "And the with tutorial",
                 "type_source": "search_template", "resource_type_hint": "video"}]
    request = SearchRequest(knowledge_points=[point["text"]])
    assert rank_resource(point, resource, evidence, request, require_type=False) is None
    assert rank_resource(point, dict(resource, title="Python lists and dictionaries tutorial"), evidence, request, require_type=False) is not None


@pytest.mark.parametrize("url,kind", [
    ("https://www.bilibili.com/video/BV1RJ411x7Yk?p=2", "video"),
    ("https://www.icourse163.org/course/BIT-1001871002", "course"),
    ("https://www.icourse163.org/course/-1001871002", "course"),
    ("https://www.xuetangx.com/course/course-id-123", "course"),
    ("https://www.bilibili.com/search?keyword=Python", "unknown"),
    ("https://www.icourse163.org/course/", "unknown"),
    ("https://docs.python.org/3/tutorial/", "unknown"),
    ("https://bilibili.com.attacker.example/video/BV1RJ411x7Yk", "unknown"),
])
def test_type_inference_is_limited_to_platform_entry_formats(url, kind):
    assert type_from_discovered_url(url) == kind


class UntypedSearch(FakeSearch):
    async def search(self, query, language, limit, domain_filters):
        items = await super().search(query, language, limit, domain_filters)
        return [c.model_copy(update={"resource_type_hint": "unknown", "type_source": None, "source_engines": []}) for c in items]


@pytest.mark.asyncio
async def test_unknown_candidates_stay_in_evidence_but_not_learning_results(tmp_path):
    svc = service(tmp_path, provider=UntypedSearch())
    jid = svc.create(SearchRequest(knowledge_points=["Python 列表与字典"]))["job_id"]
    await svc.run(jid)
    assert svc.results(jid)["status"] == "completed"
    assert svc.results(jid)["groups"][0]["items"] == []
    resources = svc.store.resources(jid)
    assert len(resources) == 1 and len(svc.fetcher.calls) == 1
    assert len(svc.store.evidence(jid, next(iter(resources)))) == 5
    assert any("缺少课程或视频类型依据" in warning for warning in svc.results(jid)["warnings"])


@pytest.mark.asyncio
async def test_unknown_promoted_only_after_page_type_and_catalog_ids_resolve(tmp_path):
    class CourseFetcher:
        async def enrich(self, candidate):
            return {"fetch_status": "fetched", "metadata_evidence_level": "catalog", "resource_type": "course",
                    "video_evidence_status": "page_verified", "catalog_kind": "video_playlist", "field_provenance": {
                        "resource_type": {"evidence_id": "type-original", "source": "jsonld.@type", "url": candidate["url"]},
                        "video_evidence_status": {"evidence_id": "video-original", "source": "dom.video_catalog"},
                        "chapters": {"evidence_id": "chapter-original", "source": "jsonld.hasPart"}},
                    "chapters": [{"title": "Python 列表与字典", "url": candidate["url"] + "#chapter-1",
                                  "start_seconds": None, "end_seconds": None, "source": "jsonld.hasPart", "evidence_id": "chapter-original"}],
                    "evidence": [{"evidence_id": "type-original", "kind": "page", "field": "resource_type", "source": "jsonld.@type", "text": "course", "url": candidate["url"]},
                                 {"evidence_id": "video-original", "kind": "page", "field": "video_evidence_status", "source": "dom.video_catalog", "text": "page_verified", "url": candidate["url"]},
                                 {"evidence_id": "chapter-original", "kind": "catalog", "field": "chapters.0", "source": "jsonld.hasPart", "text": "Python 列表与字典", "url": candidate["url"]}]}
    svc = service(tmp_path, provider=UntypedSearch())
    svc.fetcher = CourseFetcher()
    request = SearchRequest(knowledge_points=["Python 列表与字典", "HTML 表单校验"])
    for _ in range(2):  # Repeat through page cache to ensure IDs are remapped per job.
        jid = svc.create(request)["job_id"]
        await svc.run(jid)
        for group in svc.results(jid)["groups"]:
            item = group["items"][0]
            resource, evidence = item["resource"], item["evidence"]
            observed = {e["evidence_id"] for e in evidence}
            assert resource["resource_type"] == "course" and resource["metadata_evidence_level"] == "catalog"
            assert resource["catalog_kind"] == "video_playlist"
            assert resource["video_evidence_status"] == "page_verified"
            assert resource["field_provenance"]["video_evidence_status"]["evidence_id"] in observed
            assert resource["chapters"][0]["evidence_id"] in observed
            assert resource["chapters"][0]["evidence_id"] != "chapter-original"
            assert resource["field_provenance"]["resource_type"]["evidence_id"] in observed
            assert resource["field_provenance"]["chapters"]["evidence_id"] in observed


@pytest.mark.asyncio
@pytest.mark.parametrize("fetch_status", ["not_found", "error_page", "unsafe_url"])
async def test_confirmed_unusable_courses_are_removed_after_enrichment(tmp_path, fetch_status):
    class UnavailableFetcher:
        async def enrich(self, candidate):
            return {"fetch_status": fetch_status}
    svc = service(tmp_path)
    svc.fetcher = UnavailableFetcher()
    jid = svc.create(SearchRequest(knowledge_points=["Python 列表与字典"]))["job_id"]
    await svc.run(jid)
    assert not svc.results(jid)["groups"][0]["items"]
    assert next(iter(svc.store.resources(jid).values()))["fetch_status"] == fetch_status


@pytest.mark.asyncio
async def test_chapter_urls_dedup_fetch_once_without_losing_multimapping(tmp_path):
    class ChaptersSearch(FakeSearch):
        async def search(self, query, language, limit, domain_filters):
            first = (await super().search(query, language, limit, domain_filters))[0]
            return [first.model_copy(update={"url": f"https://example.org/course/python?p={p}&utm_source=test", "id": str(p)}) for p in (1, 2, 1)]
    svc = service(tmp_path, provider=ChaptersSearch())
    jid = svc.create(SearchRequest(knowledge_points=["Python 列表与字典", "HTML 表单校验"]))["job_id"]
    await svc.run(jid)
    assert len(svc.fetcher.calls) == 2
    assert len(svc.store.matches(jid)) == 4
    assert all(len(group["items"]) == 2 for group in svc.results(jid)["groups"])
    assert {r["canonical_url"] for r in svc.store.resources(jid).values()} == {"https://example.org/course/python?p=1", "https://example.org/course/python?p=2"}
    assert sum(len(svc.store.evidence(jid, rid)) for rid in svc.store.resources(jid)) == 30


@pytest.mark.asyncio
async def test_details_overlap_search_remain_fair_bounded_and_incremental(tmp_path):
    activity = {"active": 0, "peak": 0, "hosts": {}, "host_peak": {}, "starts": [], "query_count": 0}
    first_detail = asyncio.Event()
    continue_queries = asyncio.Event()
    def enter(host):
        activity["active"] += 1
        activity["peak"] = max(activity["peak"], activity["active"])
        activity["hosts"][host] = activity["hosts"].get(host, 0) + 1
        activity["host_peak"][host] = max(activity["host_peak"].get(host, 0), activity["hosts"][host])
    def leave(host):
        activity["active"] -= 1
        activity["hosts"][host] -= 1
    class DistributedSearch:
        async def search(self, query, language, limit, domain_filters):
            enter("search")
            try:
                activity["query_count"] += 1
                await asyncio.sleep(.01)
                if activity["query_count"] == 5:
                    await continue_queries.wait()
                topic, host = ("Python 列表", "python.example.org") if "Python" in query else ("HTML 表单", "html.example.org")
                return [Candidate(id=f"{host}-{i}", title=topic + "视频教程", url=f"https://{host}/course/{i}",
                    snippet=topic + "教学", query=query, source="test-only", resource_type_hint="video", type_source="search_template") for i in range(8)]
            finally:
                leave("search")
    class ConcurrentFetcher:
        async def enrich(self, candidate):
            from urllib.parse import urlsplit
            host = urlsplit(candidate["url"]).hostname
            enter(host)
            activity["starts"].append((host, activity["query_count"]))
            try:
                await asyncio.sleep(.025)
                first_detail.set()
                return {"fetch_status": "policy_unreviewed"}
            finally:
                leave(host)
    settings = Settings(database_path=str(tmp_path / "fair.sqlite3"), global_concurrency=3, max_detail_pages=4)
    svc = service(tmp_path, provider=DistributedSearch(), settings=settings)
    svc.fetcher = ConcurrentFetcher()
    jid = svc.create(SearchRequest(knowledge_points=["Python 列表", "HTML 表单"]))["job_id"]
    running = asyncio.create_task(svc.run(jid))
    await asyncio.wait_for(first_detail.wait(), 3)
    interim = svc.store.get_job(jid)
    assert interim["status"] == "running" and interim["progress"]["details_completed"] > 0
    assert all(group["items"] for group in svc.results(jid)["groups"])
    continue_queries.set()
    await running
    job = svc.store.get_job(jid)
    assert 1 < activity["peak"] <= 3 and all(value <= 1 for value in activity["host_peak"].values())
    assert activity["starts"][0][1] < activity["query_count"]
    assert [host for host, _ in activity["starts"]].count("python.example.org") == 2
    assert [host for host, _ in activity["starts"]].count("html.example.org") == 2
    assert job["progress"]["details_attempted"] == job["progress"]["details_completed"] == 4
    assert job["status"] == "partial" and activity["active"] == 0


@pytest.mark.asyncio
async def test_metadata_deadline_cancels_all_children_without_late_writes(tmp_path):
    class ManySearch(FakeSearch):
        async def search(self, *args):
            c = (await super().search(*args))[0]
            return [c.model_copy(update={"id": str(i), "url": f"https://host{i}.example.org/course"}) for i in range(8)]
    class CancelledFetcher:
        active = 0
        cancelled = 0
        async def enrich(self, candidate):
            self.active += 1
            try:
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                self.cancelled += 1
                raise
            finally:
                self.active -= 1
    svc = service(tmp_path, provider=ManySearch(), settings=Settings(database_path=str(tmp_path / "cancel.sqlite3"), deadline_seconds=.05, global_concurrency=3))
    svc.fetcher = CancelledFetcher()
    jid = svc.create(SearchRequest(knowledge_points=["Python 列表"]))["job_id"]
    await svc.run(jid)
    snapshot = svc.store.get_job(jid)
    assert snapshot["status"] == "partial" and snapshot["progress"]["details_attempted"] == 3
    assert svc.fetcher.active == 0 and svc.fetcher.cancelled == 3
    await asyncio.sleep(.03)
    assert svc.store.get_job(jid) == snapshot


@pytest.mark.asyncio
@pytest.mark.parametrize("budget,expected_catalog", [(1, 0), (2, 1)])
async def test_catalog_followup_shares_detail_budget_and_does_not_recount_cache(tmp_path, budget, expected_catalog):
    class HookFetcher(Fetcher):
        async def enrich(self, candidate, *, catalog_budget_hook=None):
            assert catalog_budget_hook is not None
            allowed = await catalog_budget_hook()
            return {"fetch_status": "fetched", "catalog_pages_completed": int(allowed),
                    "catalog_fetch_status": "fetched" if allowed else "budget_limited"}
    svc = service(tmp_path, settings=Settings(database_path=str(tmp_path / "catalog-budget.sqlite3"), max_detail_pages=budget))
    svc.fetcher = HookFetcher()
    request = SearchRequest(knowledge_points=["Python 列表"])
    jid = svc.create(request)["job_id"]
    await svc.run(jid)
    job = svc.store.get_job(jid)
    assert job["progress"]["details_attempted"] == job["progress"]["details_completed"] == 1
    assert job["progress"]["catalog_pages_attempted"] == job["progress"]["catalog_pages_completed"] == expected_catalog
    assert job["progress"]["details_attempted"] + job["progress"]["catalog_pages_attempted"] <= budget
    assert job["status"] == ("partial" if budget == 1 else "completed")
    second = svc.create(request)["job_id"]
    await svc.run(second)
    assert svc.store.get_job(second)["progress"]["details_cached"] == (0 if budget == 1 else 1)
    assert svc.store.get_job(second)["progress"]["catalog_pages_attempted"] == 0
    assert svc.store.get_job(second)["progress"]["catalog_pages_completed"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("expired", [False, True])
async def test_current_search_trace_is_separate_from_cache_history_and_denial_stops_job(tmp_path, expired):
    transport_calls = []
    blocked = False
    def respond(request):
        transport_calls.append(str(request.url))
        if blocked:
            return httpx.Response(401)
        return httpx.Response(200, json={"results": [{"title": "Python 列表视频课程", "url": "https://example.org/lecture", "content": "Python列表课程", "template": "videos.html", "engines": ["test-engine"]}]})
    settings = Settings(database_path=str(tmp_path / "trace.sqlite3"), searxng_url="http://trusted-search", search_min_interval_seconds=0,
                        allow_stale_cache=True, search_cache_ttl=-1 if expired else 3600)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        svc = service(tmp_path, settings=settings, provider=SearXNGProvider(settings, client))
        request = SearchRequest(knowledge_points=["Python 列表"], preferred_platforms=[])
        first = svc.create(request)["job_id"]
        await svc.run(first)
        assert len(transport_calls) == 2
        blocked = True
        second = svc.create(request)["job_id"]
        await svc.run(second)
        attempts = svc.store.attempts(second)
        assert attempts[0]["cache_hit"] is True
        assert attempts[0]["cache_origin_requests"][0]["http_status"] == 200
        assert attempts[0]["cache_origin_requests"][0]["filter_counts"] == {"accepted": 1}
        if expired:
            assert len(transport_calls) == 3 and len(attempts) == 1
            assert attempts[0]["provider_requests"][0]["http_status"] == 401
            assert attempts[0]["network_attempted"] is True and attempts[0]["status"] == "stale_cache"
            assert attempts[0]["error_code"] == "access_denied"
            assert any("已停止剩余查询" in warning for warning in svc.store.get_job(second)["warnings"])
            assert svc.store.get_job(second)["status"] == "partial"
        else:
            assert len(transport_calls) == 2 and len(attempts) == 2
            assert attempts[0]["provider_requests"] == [] and attempts[0]["network_attempted"] is False
        assert svc.results(second)["groups"][0]["items"]
