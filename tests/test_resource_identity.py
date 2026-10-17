"""Offline identity fixtures; no live discovery or page access."""
import pytest

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.models import Candidate, SearchRequest
from backend.app.service import JobService
from backend.app.url_utils import normalize_url


BILIBILI_VIDEO = "https://www.bilibili.com/video/BV1Nx411J7No/"


@pytest.mark.parametrize("part", ["", "?p=2"])
def test_bilibili_identity_merges_sharing_parameters_for_same_part(part):
    base = BILIBILI_VIDEO + part
    separator = "&" if part else "?"
    assert normalize_url(base + separator + "uid=first&utm_source=share&vd_source=one") == normalize_url(base)
    assert normalize_url(base + separator + "uid=second&spm_id_from=333.1") == normalize_url(base)


def test_bilibili_parts_and_nontracking_entry_fields_remain_distinct():
    first = BILIBILI_VIDEO + "?p=2&uid=first"
    second = BILIBILI_VIDEO + "?uid=second&p=3"
    assert normalize_url(first) != normalize_url(second)
    assert normalize_url(BILIBILI_VIDEO + "?p=2&course=a&chapter=3&term=2026&version=3&custom=keep&uid=first#lesson") == (
        BILIBILI_VIDEO + "?p=2&course=a&chapter=3&term=2026&version=3&custom=keep#lesson"
    )


@pytest.mark.parametrize("url", [
    "https://example.org/video/BV1Nx411J7No/?uid=first",
    "https://bilibili.com.evil.org/video/BV1Nx411J7No/?uid=first",
    "https://www.bilibili.com/course/BV1Nx411J7No/?uid=first",
    "https://www.bilibili.com/video/unknown/?uid=first",
    "https://b23.tv/example?uid=first",
])
def test_uid_is_not_globally_discarded(url):
    assert normalize_url(url) == url


@pytest.mark.asyncio
async def test_merged_bilibili_resource_retains_original_links_and_all_search_evidence():
    original_urls = [
        BILIBILI_VIDEO + "?p=2&uid=first&utm_source=share",
        BILIBILI_VIDEO + "?uid=second&p=2&vd_source=tracking",
        BILIBILI_VIDEO + "?p=3&uid=third&spm_id_from=333.1",
    ]

    class FixtureSearch:
        name = "identity-test-fixture"

        async def search(self, query, language, limit, domain_filters):
            return [Candidate(
                id=f"fixture-{index}", title="Python 列表与字典 入门视频教程",
                url=url, snippet="Python 列表与字典 入门视频教程", source=self.name, query=query,
            ) for index, url in enumerate(original_urls)]

    class NoPageAccess:
        async def enrich(self, candidate):
            raise AssertionError("This identity fixture must not fetch pages")

    store = Store(":memory:")
    try:
        svc = JobService(Settings(max_detail_pages=0), store, provider=FixtureSearch(), fetcher=NoPageAccess())
        job_id = svc.create(SearchRequest(knowledge_points=["Python 列表与字典"], preferred_platforms=[]))["job_id"]
        await svc.run(job_id)
        resources = list(store.resources(job_id).values())
        assert len(resources) == 2
        by_url = {resource["canonical_url"]: resource for resource in resources}
        part_two = by_url[BILIBILI_VIDEO + "?p=2"]
        part_three = by_url[BILIBILI_VIDEO + "?p=3"]
        assert part_two["url"] == original_urls[0]
        assert part_three["url"] == original_urls[2]

        result = svc.results(job_id)
        assert len(result["groups"][0]["items"]) == 2
        progress = store.get_job(job_id)["progress"]
        searches = progress["search_successes"]
        assert progress["details_attempted"] == 0
        evidence = store.evidence(job_id, part_two["resource_id"])
        assert len(evidence) == searches * 2
        assert {entry["url"] for entry in evidence} == set(original_urls[:2])
        assert all(entry["kind"] == "search" and entry["candidate_id"] for entry in evidence)
        assert len(store.evidence(job_id, part_three["resource_id"])) == searches
    finally:
        store.close()
