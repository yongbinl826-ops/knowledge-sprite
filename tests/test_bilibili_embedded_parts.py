"""Synthetic parser boundaries; these offline tests do not prove live access."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from backend.app.extractor import MetadataExtractor
from backend.app.models import Resource
from backend.app.source_adapters.bilibili import BILIBILI_CATALOG_LIMIT


URL = "https://www.bilibili.com/video/BV1VZ4y1G7YB/"
SOURCE = "html.bilibili.__INITIAL_STATE__.videoData"


def payload():
    return {"videoData": {"bvid": "BV1VZ4y1G7YB", "title": "Python 列表和字典",
        "pic": "//i0.hdslb.com/bfs/archive/observed.jpg", "desc": "", "owner": {"name": "课程作者"},
        "pages": [{"cid": 93717282, "page": 3, "part": "Python 列表", "duration": 155},
                  {"cid": 93829297, "page": 7, "part": "Python 字典", "duration": 320}]}}


def markup(data=None, *, script=None, tail="", extra=""):
    if script is None:
        script = "window.__INITIAL_STATE__=" + json.dumps(payload() if data is None else data, ensure_ascii=False) + ";" + tail
    return "<html><head><title>Video page</title></head><body>" + extra + "<script>" + script + "</script></body></html>"


def extract(html, url=URL):
    return MetadataExtractor().extract(html, url, "offline-boundary")


def test_embedded_parts_preserve_explicit_page_numbers_not_cid_or_array_index():
    result = extract(markup(tail='(function(){var s=document.currentScript;s.parentNode.removeChild(s);}());'))
    assert result["fetch_status"] == "fetched"
    assert result["title"] == "Python 列表和字典"
    assert result["resource_type"] == "video"
    assert result["video_evidence_status"] == "page_verified"
    assert result["catalog_kind"] == "video_parts"
    assert result["thumbnail_url"] == "https://i0.hdslb.com/bfs/archive/observed.jpg"
    assert result["author"] == "课程作者"
    assert "duration_seconds" not in result  # Part durations are not a summed video duration.
    assert result["field_provenance"]["title"]["source"] == SOURCE + ".title"
    assert result["field_provenance"]["thumbnail_url"]["source"] == SOURCE + ".pic"
    assert [row["url"] for row in result["chapters"]] == [URL + "?p=3", URL + "?p=7"]
    assert [row["page_number"] for row in result["chapters"]] == [3, 7]
    evidence = {row["evidence_id"]: row for row in result["evidence"]}
    for index, chapter in enumerate(result["chapters"]):
        assert chapter["start_seconds"] is None and chapter["end_seconds"] is None
        record = evidence[chapter["evidence_id"]]
        assert record["field"] == f"chapters.{index}"
        assert record["source"] == SOURCE + ".pages" and record["url"] == URL
        facts = json.loads(record["text"])
        assert facts == {key: value for key, value in chapter.items() if key not in {"source", "evidence_id"}}


def test_fresh_real_http_response_ignores_later_player_reads_and_preserves_fifteen_parts():
    # Immutable HTTP body from this turn's real anonymous GET, not rendered DOM.
    path = Path(__file__).resolve().parents[1] / "tests/fixtures/public_catalog_replays/bilibili-local-use-20261017/probe-after-decompression/page.html"
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "163d94189805bfe6c25bc2e2b8bca301c30860cbb83870336757093e377fb388"
    html = raw.decode("utf-8")
    result = extract(html)
    soup = BeautifulSoup(html, "html.parser")
    scripts = [script.string or script.get_text() for script in soup.select("script:not([src])")]
    assignment = next(script for script in scripts if script.startswith("window.__INITIAL_STATE__="))
    state, _ = json.JSONDecoder().raw_decode(assignment[len("window.__INITIAL_STATE__="):])
    pages = state["videoData"]["pages"]
    assert state["videoData"]["bvid"] == "BV1VZ4y1G7YB"
    assert len(pages) == len(result["chapters"]) == 15
    assert sum("__INITIAL_STATE__" in script for script in scripts) == 4
    assert result["title"] == state["videoData"]["title"]
    assert "\ufffd" not in result["title"]
    for observed, chapter in zip(pages, result["chapters"]):
        assert chapter["title"] == observed["part"]
        assert chapter["page_number"] == observed["page"]
        assert chapter["duration_seconds"] == observed["duration"]
        assert chapter["url"] == URL + f'?p={observed["page"]}'
        assert chapter["source"] == SOURCE + ".pages"


def test_other_scripts_can_read_state_without_becoming_assignment_candidates():
    extra = '''<script>var vd = window.__INITIAL_STATE__ && window.__INITIAL_STATE__.videoData;</script>
      <script>if (window.__INITIAL_STATE__ == null) { console.log("no state"); }</script>'''
    result = extract(markup(extra=extra))
    assert len(result["chapters"]) == 2


@pytest.mark.parametrize("assignment", [
    'window["__INITIAL_STATE__"]={};', '__INITIAL_STATE__={};',
    'if (false) window.__INITIAL_STATE__={};', 'function f(){window.__INITIAL_STATE__={};}',
])
def test_other_ambiguous_assignments_are_not_treated_as_harmless_reads(assignment):
    result = extract(markup(extra="<script>" + assignment + "</script>"))
    assert result["chapters"] == []


@pytest.mark.parametrize("url", [
    "https://example.org/video/BV1VZ4y1G7YB/", "https://www.bilibili.com.evil.org/video/BV1VZ4y1G7YB/",
    "https://www.bilibili.com/read/cv123", "https://www.bilibili.com/video/BV1VZ4y1G7YA/",
    "https://www.bilibili.com/video/av123/", "https://user:password@www.bilibili.com/video/BV1VZ4y1G7YB/",
])
def test_embedded_state_requires_matching_video_identity_and_route(url):
    result = extract(markup(), url)
    assert result["chapters"] == [] and result["video_evidence_status"] == "none"


def test_requested_part_is_not_applied_to_every_returned_part():
    result = extract(markup(), URL + "?p=7")
    assert [row["url"] for row in result["chapters"]] == [URL + "?p=3", URL + "?p=7"]
    assert all(row["source_url"] == URL + "?p=7" for row in result["chapters"])


def test_recommendations_and_collection_episodes_do_not_enter_same_video_parts():
    data = payload()
    unrelated = {"bvid": "BV1VZ4y1G7YA", "pages": [{"page": 1, "part": "Unrelated video", "duration": 100}]}
    data["related"] = [unrelated]
    data["videoData"]["ugc_season"] = {"sections": [{"episodes": [unrelated]}]}
    result = extract(markup(data))
    assert [row["title"] for row in result["chapters"]] == ["Python 列表", "Python 字典"]


@pytest.mark.parametrize("damage", [
    "comment", "quoted", "conditional", "function", "call", "concat", "trailing_expression",
    "duplicate_key", "duplicate_script", "reassignment", "external_script", "missing_semicolon",
    "too_large", "nan", "missing_bvid", "missing_title", "nested_video_data",
])
def test_untrusted_or_ambiguous_script_does_not_become_metadata(damage):
    data = payload()
    script = "window.__INITIAL_STATE__=" + json.dumps(data) + ";"
    html = markup(script=script)
    if damage == "comment":
        html = markup(script="/*" + script + "*/")
    elif damage == "quoted":
        html = markup(script="var example=" + json.dumps(script) + ";")
    elif damage == "conditional":
        html = markup(script="if (false) " + script)
    elif damage == "function":
        html = markup(script="function f(){" + script + "}")
    elif damage == "call":
        html = markup(script="window.__INITIAL_STATE__=loadData();")
    elif damage == "concat":
        html = markup(script=script[:-1] + ' + "text";')
    elif damage == "trailing_expression":
        html = markup(script=script[:-1] + '.videoData;')
    elif damage == "duplicate_key":
        html = markup(script=script.replace('"videoData":', '"videoData": {}, "videoData":', 1))
    elif damage == "duplicate_script":
        html += "<script>" + script + "</script>"
    elif damage == "reassignment":
        html = markup(script=script + "window.__INITIAL_STATE__={};")
    elif damage == "external_script":
        html = html.replace("<script>", '<script src="https://example.org/payload.js">')
    elif damage == "missing_semicolon":
        html = markup(script=script[:-1])
    elif damage == "too_large":
        html = markup(script=" " * 4_000_001 + script)
    elif damage == "nan":
        html = markup(script=script.replace('"duration": 155', '"duration": NaN'))
    elif damage == "missing_bvid":
        del data["videoData"]["bvid"]
        html = markup(data)
    elif damage == "missing_title":
        del data["videoData"]["title"]
        html = markup(data)
    elif damage == "nested_video_data":
        html = markup({"related": data})
    result = extract(html)
    assert result["chapters"] == [] and result["video_evidence_status"] == "none"
    assert result.get("thumbnail_url") is None


@pytest.mark.parametrize("damage", ["duplicate_page", "missing_page", "string_page", "bool_page", "zero_page", "negative_page", "missing_part", "wrong_bvid", "not_object", "not_array"])
def test_invalid_part_does_not_silently_create_a_partial_catalog(damage):
    data = payload()
    row = data["videoData"]["pages"][1]
    if damage == "duplicate_page":
        row["page"] = 3
    elif damage == "missing_page":
        del row["page"]
    elif damage == "string_page":
        row["page"] = "7"
    elif damage == "bool_page":
        row["page"] = True
    elif damage == "zero_page":
        row["page"] = 0
    elif damage == "negative_page":
        row["page"] = -1
    elif damage == "missing_part":
        del row["part"]
    elif damage == "wrong_bvid":
        row["bvid"] = "BV1VZ4y1G7YA"
    elif damage == "not_object":
        data["videoData"]["pages"][1] = None
    elif damage == "not_array":
        data["videoData"]["pages"] = {}
    result = extract(markup(data))
    assert result["chapters"] == []
    assert result["catalog_fetch_status"] == "catalog_payload_invalid"
    assert result["metadata_evidence_level"] == "page"


@pytest.mark.parametrize("duration", [None, True, "155", -1, 0, 10 ** 400])
def test_invalid_duration_stays_unknown(duration):
    data = payload()
    data["videoData"]["pages"][0]["duration"] = duration
    result = extract(markup(data))
    assert len(result["chapters"]) == 2 and result["chapters"][0]["duration_seconds"] is None


@pytest.mark.parametrize("count", [122, BILIBILI_CATALOG_LIMIT, BILIBILI_CATALOG_LIMIT + 1])
def test_parts_limit_preserves_whole_catalog_or_marks_limit_and_clears_preview(count):
    data = payload()
    data["videoData"]["pages"] = [{"cid": 999999 + page, "page": page, "part": f"Part {page}", "duration": 30} for page in range(1, count + 1)]
    extra = '<div class="video-pod"><div class="video-pod__header"><span class="title">视频选集</span></div><div class="video-pod__list multip"><div class="video-pod__item"><span class="title-txt">Short DOM preview</span></div></div></div>'
    result = extract(markup(data, extra=extra))
    resource = Resource.model_validate(dict(result, resource_id="synthetic", url=URL, canonical_url=URL, discovered_at="offline-boundary"))
    if count <= BILIBILI_CATALOG_LIMIT:
        assert len(result["chapters"]) == len(resource.chapters) == count
        assert result["chapters"][-1]["url"] == URL + f"?p={count}"
        assert result["chapters"][-1]["title"] == f"Part {count}"
    else:
        assert result["chapters"] == resource.chapters == []
        assert result["catalog_fetch_status"] == "catalog_limit_exceeded"
        assert "catalog_kind" not in result
        assert not any(row["kind"] == "catalog" for row in result["evidence"])


def test_same_bv_payload_wins_over_unrelated_jsonld_on_page():
    unrelated = {"@type": "VideoObject", "name": "Another BV", "thumbnailUrl": "https://example.org/unrelated.jpg", "hasPart": [{"@type": "Clip", "name": "Unrelated chapter", "url": "https://example.org/clip"}]}
    result = extract(markup(extra='<script type="application/ld+json">' + json.dumps(unrelated) + '</script>'))
    assert result["title"] == "Python 列表和字典"
    assert result["thumbnail_url"].endswith("/observed.jpg")
    assert [row["title"] for row in result["chapters"]] == ["Python 列表", "Python 字典"]


@pytest.mark.parametrize("cover", ["javascript:alert(1)", "file:///private.png", "http://127.0.0.1/a.jpg", "http://user:secret@example.org/a.jpg"])
def test_unsafe_embedded_cover_is_not_promoted(cover):
    data = payload()
    data["videoData"]["pic"] = cover
    result = extract(markup(data))
    assert result.get("thumbnail_url") is None
    assert len(result["chapters"]) == 2


UNAVAILABLE_URL = "https://www.bilibili.com/video/BV1Dit1zYEJQ/"


def unavailable_html():
    path = Path(__file__).resolve().parents[1] / "tests/fixtures/public_catalog_replays/bilibili-local-use-20261017/unavailable-page/page.html"
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "8da75a630f4dc35ae99e756e62f31976bc52f98f8eb29815ca25d76d7cea6d9e"
    return raw.decode("utf-8")


def test_fresh_real_soft_404_is_content_not_found_despite_http_200():
    root = Path(__file__).resolve().parents[1] / "tests/fixtures/public_catalog_replays/bilibili-local-use-20261017/unavailable-page"
    response = json.loads((root / "page-response.json").read_text(encoding="utf-8"))
    assert response["status"] == 200
    result = extract(unavailable_html(), UNAVAILABLE_URL)
    assert result["fetch_status"] == "not_found"
    assert result["video_evidence_status"] == "none" and result["chapters"] == []
    assert "title" not in result and "description" not in result and "resource_type" not in result
    facts = json.loads(result["evidence"][0]["text"])
    assert facts["payload_error_code"] == 404 and facts["payload_true_code"] == 62002
    assert facts["payload_message"] == "稿件不可见" and facts["visible_notice"] == "啊叻？视频不见了？"
    assert "HTTP transport status is recorded separately" in facts["status_basis"]
    assert result["field_provenance"]["fetch_status"]["source"] == "html.bilibili.unavailable_video"


@pytest.mark.parametrize("damage", ["wrong_host", "other_route", "wrong_bv", "missing_payload", "missing_panel", "hidden_panel", "hidden_ancestor", "different_error", "valid_video_metadata"])
def test_soft_404_classification_requires_agreeing_same_bv_state_and_visible_error_panel(damage):
    soup = BeautifulSoup(unavailable_html(), "html.parser")
    url = UNAVAILABLE_URL
    script = next(script for script in soup.select("script:not([src])") if (script.string or "").startswith("window.__INITIAL_STATE__="))
    assignment = script.string
    prefix = "window.__INITIAL_STATE__="
    state, _ = json.JSONDecoder().raw_decode(assignment[len(prefix):])
    if damage == "wrong_host":
        url = url.replace("www.bilibili.com", "example.org")
    elif damage == "other_route":
        url = "https://www.bilibili.com/read/cv123"
    elif damage == "wrong_bv":
        state["bvid"] = "BV1VZ4y1G7YB"
    elif damage == "missing_payload":
        script.decompose()
    elif damage == "missing_panel":
        soup.select_one(".error-panel").decompose()
    elif damage == "hidden_panel":
        soup.select_one(".error-panel")["hidden"] = ""
    elif damage == "hidden_ancestor":
        soup.select_one("#mirror-vdcon")["style"] = "display: none"
    elif damage == "different_error":
        state["error"]["code"] = 500
    elif damage == "valid_video_metadata":
        state["videoData"] = {"bvid": "BV1Dit1zYEJQ", "title": "视频去哪了呢？教学案例", "pages": []}
    if damage != "missing_payload":
        script.string = prefix + json.dumps(state, ensure_ascii=False) + ";"
    result = extract(str(soup), url)
    assert result["fetch_status"] != "not_found"


def test_ordinary_video_without_catalog_or_with_error_words_is_not_soft_404():
    data = payload()
    data["videoData"]["pages"] = []
    data["videoData"]["desc"] = "本课解释视频去哪了呢，以及如何排查视频不见了的问题。"
    result = extract(markup(data))
    assert result["fetch_status"] == "fetched" and result["chapters"] == []
    assert result["video_evidence_status"] == "page_verified"


@pytest.mark.asyncio
async def test_soft_404_enrichment_preserves_search_title_and_content_evidence_without_claiming_http_404():
    from backend.app.fetcher import Fetcher, HTTPResult

    class ObservedResponseFetcher(Fetcher):
        async def fetch(self, url):
            assert url == UNAVAILABLE_URL
            return HTTPResult(200, {"content-type": "text/html; charset=utf-8"}, unavailable_html().encode("utf-8"), url)

    result = await ObservedResponseFetcher().enrich({"url": UNAVAILABLE_URL, "title": "Search-discovered Python course", "source": "offline_test"})
    assert result["fetch_status"] == "not_found"
    assert result["title"] == "Search-discovered Python course"
    assert result["chapters"] == [] and result["video_evidence_status"] == "none"
    assert any(row.get("field") == "fetch_status" and row["source"] == "html.bilibili.unavailable_video" for row in result["evidence"])
