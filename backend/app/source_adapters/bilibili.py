"""Read an observed Bilibili multipart selector, without playing or fetching media."""
from __future__ import annotations

import json
import math
import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from ..url_utils import UnsafeURL, normalize_url, safe_thumbnail_url
from .base import FieldFact, SourceFacts, clean_text


BILIBILI_CATALOG_LIMIT = 1000
_STATE_LIMIT = 2_000_000
_STATE_ASSIGNMENT = re.compile(r"\A\s*window\s*\.\s*__INITIAL_STATE__\s*=\s*")
_STATE_ASSIGNMENT_REFERENCE = re.compile(
    r'''(?<![\w$.])(?:window\s*\.\s*__INITIAL_STATE__|window\s*\[\s*["']__INITIAL_STATE__["']\s*\]|__INITIAL_STATE__)\s*=(?!=|>)'''
)


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_json_constant(value):
    raise ValueError("non-JSON numeric constant")


def _initial_state(script: str) -> dict | None:
    """Read one JSON assignment in HTTP HTML, never interpret JavaScript.

    The assignment must begin the inline script. A literal in a comment, string,
    function or conditional cannot be mistaken for an executed page assignment.
    The site's following script-cleanup code is ignored, not evaluated; a second
    reference to the same state in that tail is rejected as ambiguous.
    """
    if len(script) > _STATE_LIMIT:
        return None
    match = _STATE_ASSIGNMENT.match(script)
    if not match:
        return None
    try:
        decoder = json.JSONDecoder(object_pairs_hook=_unique_json_object, parse_constant=_reject_json_constant)
        value, end = decoder.raw_decode(script, match.end())
    except (ValueError, TypeError, RecursionError):
        return None
    tail = script[end:].lstrip()
    if not isinstance(value, dict) or not tail.startswith(";") or "__INITIAL_STATE__" in tail:
        return None
    return value


def _page_initial_state(soup: BeautifulSoup) -> dict | None:
    payloads = []
    for script in soup.select("script:not([src])")[:80]:
        content = script.string or script.get_text()
        # Later player/bootstrap code reads the state without reassigning it.
        if not _STATE_ASSIGNMENT_REFERENCE.search(content):
            continue
        payload = _initial_state(content)
        if payload is None:
            return None
        payloads.append(payload)
    return payloads[0] if len(payloads) == 1 else None


def unavailable_video_fact(soup: BeautifulSoup, url: str) -> FieldFact | None:
    """Classify the observed Bilibili soft-404 page, not a missing catalog.

    The visible error panel and same-BV embedded 404 must agree. Ordinary video
    pages with no parts, descriptions mentioning deletion, or hidden error
    templates are insufficient. The 404 is a payload code, not an HTTP status.
    """
    page_url = _video_url(url)
    if not page_url:
        return None
    requested_bvid = urlsplit(page_url).path.rstrip("/").rsplit("/", 1)[-1]
    state = _page_initial_state(soup)
    if (not state or not re.fullmatch(r"BV[0-9A-Za-z]{10}", requested_bvid)
            or state.get("bvid") != requested_bvid):
        return None
    error = state.get("error")
    if not isinstance(error, dict) or type(error.get("code")) is not int or error["code"] != 404:
        return None
    video = state.get("videoData")
    if isinstance(video, dict) and (video.get("bvid") or video.get("pages")):
        return None
    notice = soup.select_one("#mirror-vdcon.error-page .error-panel .error-text")
    if not notice:
        return None
    for tag in [notice, *notice.parents]:
        if (tag.name in {"script", "style", "template", "noscript"} or tag.has_attr("hidden")
                or tag.get("aria-hidden") == "true"
                or re.search(r"display\s*:\s*none|visibility\s*:\s*hidden", str(tag.get("style", "")), re.I)):
            return None
    message = clean_text(notice.get_text(" ", strip=True), 300)
    if not message or not re.fullmatch(r"(?:啊叻[？?])?视频不见了[？?]?", message):
        return None
    facts = {"bvid": requested_bvid, "payload_error_code": 404,
             "payload_true_code": error.get("trueCode"),
             "payload_message": clean_text(error.get("message"), 300), "visible_notice": message,
             "status_basis": "HTML content; HTTP transport status is recorded separately"}
    return FieldFact("fetch_status", "not_found", "html.bilibili.unavailable_video",
                     json.dumps(facts, ensure_ascii=False, sort_keys=True))


def extract_embedded_video_facts(soup: BeautifulSoup, url: str) -> SourceFacts:
    """Read same-BV videoData.pages from the returned public page itself.

    This adapter has no network client. It does not fetch interfaces, execute
    page code, read media URLs, or traverse recommendations/collection items.
    """
    result = SourceFacts()
    page_url = _video_url(url)
    if not page_url:
        return result
    parsed = urlsplit(page_url)
    requested_bvid = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    if not re.fullmatch(r"BV[0-9A-Za-z]{10}", requested_bvid):
        return result
    state = _page_initial_state(soup)
    if state is None:
        return result
    video = state.get("videoData")
    if not isinstance(video, dict) or video.get("bvid") != requested_bvid:
        return result
    source = "html.bilibili.__INITIAL_STATE__.videoData"
    title = clean_text(video.get("title"), 500)
    if not title:
        return result
    result.fields.extend([
        FieldFact("title", title, source + ".title"),
        FieldFact("resource_type", "video", source + ".bvid",
                  f"Public video HTML contains videoData.bvid={requested_bvid} matching the requested BV identifier"),
        FieldFact("video_evidence_status", "page_verified", source + ".bvid",
                  "Observed same-BV video metadata in the returned public HTML; playback was not tested and no media was requested"),
    ])
    thumbnail = safe_thumbnail_url(video.get("pic"), page_url)
    if thumbnail:
        result.fields.append(FieldFact("thumbnail_url", thumbnail, source + ".pic"))
    description = clean_text(video.get("desc"))
    if description:
        result.fields.append(FieldFact("description", description, source + ".desc"))
    owner = video.get("owner")
    author = clean_text(owner.get("name"), 250) if isinstance(owner, dict) else None
    if author:
        result.fields.append(FieldFact("author", author, source + ".owner.name"))
    pages = video.get("pages")
    if pages is None or pages == []:
        return result
    if not isinstance(pages, list):
        result.fields.append(FieldFact("catalog_fetch_status", "catalog_payload_invalid", source + ".pages",
                                      "videoData.pages is not an array; no catalog is displayed"))
        return result
    if len(pages) > BILIBILI_CATALOG_LIMIT:
        result.fields.append(FieldFact("catalog_fetch_status", "catalog_limit_exceeded", source + ".pages.limit",
            f"Public video payload contains {len(pages)} entries, exceeding the {BILIBILI_CATALOG_LIMIT}-entry limit; no truncated catalog is displayed"))
        return result
    seen = set()
    chapters = []
    for row in pages:
        page = row.get("page") if isinstance(row, dict) else None
        part = clean_text(row.get("part"), 300) if isinstance(row, dict) else None
        if (type(page) is not int or page <= 0 or page in seen or not part
                or row.get("bvid", requested_bvid) != requested_bvid):
            result.fields.append(FieldFact("catalog_fetch_status", "catalog_payload_invalid", source + ".pages",
                "A part has an invalid/duplicate page number, missing title, or mismatched BV; no partial catalog is displayed"))
            return result
        seen.add(page)
        duration = row.get("duration")
        try:
            valid_duration = type(duration) in {int, float} and duration > 0 and math.isfinite(duration)
        except OverflowError:
            valid_duration = False
        if not valid_duration:
            duration = None
        chapters.append({
            "title": part, "page_number": page,
            "url": urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/") + "/", f"p={page}", "")),
            "source_url": page_url, "start_seconds": None, "end_seconds": None,
            "duration_seconds": duration,
        })
    result.chapters = chapters
    result.catalog_source = source + ".pages"
    result.catalog_kind = "video_parts"
    return result


def _video_url(url: str) -> str | None:
    try:
        normalized = normalize_url(url)
        parsed = urlsplit(normalized)
    except (UnsafeURL, ValueError):
        return None
    if parsed.hostname not in {"bilibili.com", "www.bilibili.com"}:
        return None
    if not re.fullmatch(r"/video/(?:BV[0-9A-Za-z]{10}|av\d+)/?", parsed.path):
        return None
    return normalized


def part_duration_seconds(value: str | None) -> int | None:
    """The visible MM:SS / H:MM:SS is a part duration, never an offset."""
    value = clean_text(value, 20)
    if not value or not re.fullmatch(r"\d{1,3}:[0-5]\d(?::[0-5]\d)?", value):
        return None
    fields = [int(part) for part in value.split(":")]
    seconds = fields[0] * 60 + fields[1] if len(fields) == 2 else fields[0] * 3600 + fields[1] * 60 + fields[2]
    return seconds if seconds > 0 else None


class BilibiliAdapter:
    name = "bilibili_video_parts"

    def matches(self, url: str) -> bool:
        return _video_url(url) is not None

    def extract(self, soup: BeautifulSoup, url: str) -> SourceFacts:
        result = SourceFacts()
        page_url = _video_url(url)
        if not page_url:
            return result
        heading = soup.select_one("h1.video-title")
        title = clean_text(heading.get_text(" ", strip=True), 500) if heading else None
        if title:
            result.fields.append(FieldFact("title", title, "html.bilibili.video_title"))
        for pod in soup.select(".video-pod")[:3]:
            label = pod.select_one(".video-pod__header .title")
            if not label or clean_text(label.get_text(" ", strip=True), 100) != "视频选集":
                continue
            multip = pod.select_one(".video-pod__list.multip")
            if not multip:
                continue
            items = multip.select(":scope > .video-pod__item")
            if len(items) > BILIBILI_CATALOG_LIMIT:
                result.fields.append(FieldFact("catalog_fetch_status", "catalog_limit_exceeded", "html.bilibili.video_pod.multip.limit",
                    f"Visible multipart selector contains {len(items)} entries, exceeding the {BILIBILI_CATALOG_LIMIT}-entry limit; no truncated catalog is displayed"))
                break
            for item in items:
                title_tag = item.select_one(".title-txt") or item.select_one(".title")
                part_title = clean_text(title_tag.get_text(" ", strip=True), 300) if title_tag else None
                if not part_title:
                    continue
                duration = item.select_one(".stats .duration")
                # A CID/data-key or the item's position is not a page URL. Only
                # an actual same-video link in the title can supply a URL.
                anchor = item if item.name == "a" and item.has_attr("href") else item.select_one("a.title[href], .title a[href]")
                part_url = None
                if anchor:
                    actual_url = _video_url(urljoin(page_url, str(anchor.get("href", ""))))
                    if actual_url and urlsplit(actual_url).path.rstrip("/") == urlsplit(page_url).path.rstrip("/"):
                        part_url = actual_url
                result.chapters.append({
                    "title": part_title, "url": part_url, "source_url": page_url,
                    "start_seconds": None, "end_seconds": None,
                    "duration_seconds": part_duration_seconds(duration.get_text(" ", strip=True) if duration else None),
                })
            if result.chapters:
                result.catalog_source = "html.bilibili.video_pod.multip"
                result.catalog_kind = "video_parts"
                result.fields.extend([
                    FieldFact("resource_type", "video", result.catalog_source,
                              "Bilibili video page has a visible 视频选集 multipart selector; parts are distinct videos, not timeline chapters"),
                    FieldFact("video_evidence_status", "page_verified", result.catalog_source,
                              "Observed video page structure and ordered multipart selector; playback was not tested and no media was requested"),
                ])
                break
        return result
