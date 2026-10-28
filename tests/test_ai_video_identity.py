"""Independent native identity grounding; every input is a local fixture."""
from copy import deepcopy
import asyncio
import json

import httpx
import pytest

from backend.app.ai_video_identity import fetch_ai_video_identity, ground_ai_video_metadata
from backend.app.extractor import MetadataExtractor


URL = "https://www.bilibili.com/video/BV1hE411k7Qn"
STAMP = "2026-10-28T04:00:00+00:00"
PLATFORMS = ["bilibili", "icourse163", "xuetangx"]
HINT = {"url": URL, "title": "ECharts 自适应教程", "snippet": "AI_ONLY_ECHARTS",
        "thumbnail_url": "https://i0.hdslb.com/bfs/archive/ai-cover.jpg",
        "chapters": [{"title": "AI_ONLY_CHAPTER"}]}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    async def forbidden(*_args, **_kwargs):
        pytest.fail("Native identity checks must not make external requests")
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)


def native_bili(*, title="韩国星巴克两杯饮品一个提拉米苏要多少钱？", description="记录咖啡店消费",
                page_url=URL, bvid="BV1hE411k7Qn", generic_title="ECharts 教程"):
    state = {"videoData": {"bvid": bvid, "title": title, "desc": description,
        "pic": "https://i0.hdslb.com/bfs/archive/original.jpg", "owner": {"name": "原作者"},
        "pages": [{"page": 1, "part": "章节不能成为知识点证据", "cid": 123}]}}
    html = ('<html><head><meta property="og:title" content="' + generic_title + '">'
            '<meta property="og:description" content="误导的泛OG ECharts 摘要">'
            '</head><body><script>window.__INITIAL_STATE__=' + json.dumps(state, ensure_ascii=False)
            + ';</script></body></html>')
    metadata = MetadataExtractor().extract(html, page_url, STAMP)
    return {**metadata, "url": URL, "canonical_url": URL, "resolved_url": page_url}


def grounded(metadata, hint=None):
    return ground_ai_video_metadata(hint or HINT, metadata, preferred_platforms=PLATFORMS)


def set_field(metadata, field, value, source, *, url=None, kind="page"):
    url = url or metadata["resolved_url"]
    identity = "fixture-" + field
    metadata[field] = value
    metadata.setdefault("field_provenance", {})[field] = {
        "evidence_id": identity, "source": source, "url": url, "fetched_at": STAMP}
    metadata.setdefault("evidence", []).append({"evidence_id": identity, "id": identity,
        "field": field, "source": source, "kind": kind, "text": value,
        "url": url, "fetched_at": STAMP})


def native_mooc(url="https://www.icourse163.org/course/detail.htm?cid=1452132255"):
    metadata = {"url": url, "canonical_url": url, "resolved_url": url,
                "fetch_status": "fetched", "fetched_at": STAMP,
                "metadata_evidence_level": "page", "field_provenance": {}, "evidence": []}
    set_field(metadata, "resource_type", "course", "html.icourse163.course_structure")
    set_field(metadata, "title", "网页制作与网站设计", "html.icourse163.course_title")
    set_field(metadata, "description", "讲解 HTML 与 CSS", "html.icourse163.course_description")
    return metadata


def test_real_original_title_replaces_ai_claim_without_certifying_topic_relevance():
    result = grounded(native_bili())
    assert result["status"] == "accepted"
    candidate = result["candidate"]
    assert candidate["title"] == "韩国星巴克两杯饮品一个提拉米苏要多少钱？"
    assert candidate["snippet"] == "记录咖啡店消费"
    assert candidate["thumbnail_url"] == "https://i0.hdslb.com/bfs/archive/original.jpg"
    assert candidate["source"] == "ai_native_verified"
    assert candidate["video_evidence_status"] == "native_page_observed"
    assert "chapters" not in candidate and "AI_ONLY" not in json.dumps(result)
    assert result["provenance"]["title"]["source"].endswith("videoData.title")


def test_other_bv_with_plausible_og_fields_does_not_prove_this_video():
    metadata = native_bili(bvid="BV1mE411J7n7")
    assert metadata.get("title") == "ECharts 教程"
    assert grounded(metadata)["reason"] == "native_identity_unconfirmed"


def test_generic_jsonld_video_object_does_not_replace_native_bv_identity():
    metadata = native_bili()
    set_field(metadata, "video_evidence_status", "page_verified", "jsonld.VideoObject")
    assert grounded(metadata)["reason"] == "native_identity_unconfirmed"


@pytest.mark.parametrize("source,kind", [("search", "search"), ("page_link", "page"),
                                        ("search", "page"), ("discovery.title", "page")])
def test_inherited_model_title_is_rejected_even_when_media_and_http_are_valid(source, kind):
    metadata = native_bili()
    set_field(metadata, "title", "ECharts 自适应教程", source, kind=kind)
    assert grounded(metadata)["reason"] == "native_title_unconfirmed"


@pytest.mark.parametrize("mutation", ["text", "source", "field", "id", "url", "stale"])
def test_title_evidence_must_match_the_field_and_resource(mutation):
    metadata = native_bili()
    proof = metadata["field_provenance"]["title"]
    row = next(item for item in metadata["evidence"] if item.get("evidence_id") == proof["evidence_id"])
    if mutation == "text":
        row["text"] = "其他文字"
    elif mutation == "source":
        row["source"] = "meta.og:title"
    elif mutation == "field":
        row["field"] = "description"
    elif mutation == "id":
        row["evidence_id"] = "wrong-proof"
    elif mutation == "url":
        row["url"] = "https://www.bilibili.com/video/BV1mE411J7n7"
    else:
        row["fetched_at"] = "2020-01-01T00:00:00+00:00"
    assert grounded(metadata)["reason"] == "native_title_unconfirmed"


@pytest.mark.parametrize("title", ["哔哩哔哩_bilibili", "哔哩哔哩 (゜-゜)つロ 干杯~ - bilibili",
                                   "中国大学MOOC 首页", "登录", "404 页面不存在"])
def test_generic_page_title_is_not_a_video_identity(title):
    assert grounded(native_bili(title=title))["reason"] == "generic_page_title"


def test_unproven_description_and_cover_are_omitted_without_ai_fallback():
    metadata = native_bili()
    set_field(metadata, "description", "AI_ONLY_ECHARTS", "search", kind="search")
    set_field(metadata, "thumbnail_url", HINT["thumbnail_url"], "search", kind="search")
    result = grounded(metadata)
    assert result["status"] == "accepted"
    assert result["candidate"]["snippet"] == ""
    assert result["candidate"]["thumbnail_url"] is None
    assert "description" not in result["provenance"]
    assert "AI_ONLY" not in json.dumps(result)


def test_overlong_native_description_is_not_replaced_by_generic_meta_or_ai_text():
    metadata = native_bili(description="真实描述" * 2000)
    assert metadata.get("description_extraction_status") == "limit_exceeded"
    result = grounded(metadata)
    assert result["status"] == "accepted" and result["candidate"]["snippet"] == ""


@pytest.mark.parametrize("field,url", [
    ("resolved_url", "https://www.bilibili.com/"),
    ("resolved_url", "https://www.bilibili.com/video/BV1mE411J7n7"),
    ("canonical_url", "https://www.bilibili.com/video/BV1mE411J7n7"),
    ("resolved_url", URL + "?p=2"),
])
def test_redirect_or_part_identity_change_is_rejected(field, url):
    metadata = native_bili()
    metadata[field] = url
    assert grounded(metadata)["reason"] == "resource_identity_mismatch"


def test_same_bv_locale_observation_is_allowed():
    result = grounded(native_bili(page_url=URL.replace("/video/", "/zh-Hans/video/")))
    assert result["status"] == "accepted"


@pytest.mark.parametrize("status", ["captcha", "login_required", "access_denied", "not_found",
                                    "http_error", "javascript_required", "timeout", "not_fetched"])
def test_unsuccessful_page_fetch_never_uses_retained_title(status):
    metadata = native_bili()
    metadata["fetch_status"] = status
    assert grounded(metadata)["status"] == "rejected"


@pytest.mark.parametrize("flag,reason", [("requires_payment", "explicitly_paid"),
                                       ("requires_login", "login_required"), ("stale", "stale_metadata")])
def test_access_and_stale_flags_remain_blocking(flag, reason):
    metadata = native_bili()
    metadata[flag] = True
    assert grounded(metadata)["reason"] == reason


def test_mooc_requires_bound_native_course_type_not_title_or_cover_alone():
    metadata = native_mooc()
    hint = {"url": metadata["url"], "title": "AI 假标题"}
    assert grounded(metadata, hint)["status"] == "accepted"
    metadata["field_provenance"].pop("resource_type")
    assert grounded(metadata, hint)["reason"] == "native_identity_unconfirmed"


def test_mooc_redirect_to_homepage_is_rejected():
    metadata = native_mooc()
    hint = {"url": metadata["url"]}
    metadata["resolved_url"] = "https://www.icourse163.org/"
    assert grounded(metadata, hint)["reason"] == "resource_identity_mismatch"


async def test_fetch_wrapper_passes_only_url_and_shared_locale_budget_hook():
    inputs = []
    async def budget():
        return True
    class Fetcher:
        async def enrich(self, candidate, *, catalog_budget_hook):
            inputs.append((deepcopy(candidate), catalog_budget_hook))
            return native_bili()
    result = await fetch_ai_video_identity(HINT, fetcher=Fetcher(), preferred_platforms=PLATFORMS,
                                          timeout_seconds=1, catalog_budget_hook=budget)
    assert result["status"] == "accepted"
    assert inputs == [({"url": URL + "/"}, budget)]
    assert result["candidate"]["url"] == URL


@pytest.mark.parametrize("original,fetch_url", [(URL + "?p=3", URL + "/?p=3"),
                                                (URL + "/", URL + "/")])
async def test_fetch_route_normalization_preserves_part_and_never_forwards_ai_text(original, fetch_url):
    inputs = []
    metadata = native_bili(page_url=fetch_url)
    metadata.update(url=fetch_url, canonical_url=fetch_url)
    class Fetcher:
        async def enrich(self, candidate, *, catalog_budget_hook):
            inputs.append(deepcopy(candidate))
            return metadata
    result = await fetch_ai_video_identity({**HINT, "url": original}, fetcher=Fetcher(),
        preferred_platforms=PLATFORMS, timeout_seconds=1)
    assert result["status"] == "accepted"
    assert inputs == [{"url": fetch_url}]
    assert result["candidate"]["url"] == original
    assert "AI_ONLY" not in json.dumps(inputs)


async def test_fetch_wrapper_disables_mooc_catalog_followup():
    metadata = native_mooc()
    seen = []
    class Fetcher:
        async def enrich(self, candidate, *, catalog_budget_hook):
            seen.append(catalog_budget_hook)
            return metadata
    result = await fetch_ai_video_identity({"url": metadata["url"]}, fetcher=Fetcher(),
        preferred_platforms=PLATFORMS, timeout_seconds=1, catalog_budget_hook=lambda: True)
    assert result["status"] == "accepted" and seen == [None]


async def test_fetch_wrapper_timeout_and_cancellation_leave_no_running_child():
    active = 0
    entered = asyncio.Event()
    class Fetcher:
        async def enrich(self, *_args, **_kwargs):
            nonlocal active
            active += 1
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                active -= 1
    assert (await fetch_ai_video_identity(HINT, fetcher=Fetcher(), preferred_platforms=PLATFORMS,
                                         timeout_seconds=.01))["reason"] == "timeout"
    assert active == 0
    entered.clear()
    task = asyncio.create_task(fetch_ai_video_identity(HINT, fetcher=Fetcher(),
        preferred_platforms=PLATFORMS, timeout_seconds=1))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert active == 0
