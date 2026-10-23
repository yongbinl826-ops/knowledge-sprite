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
BILIBILI_DESCRIPTION_LIMIT = 4000
BILIBILI_DESCRIPTION_BYTES = 16000
BILIBILI_DESCRIPTION_SOURCE = "html.bilibili.__INITIAL_STATE__.videoData.desc"
BILIBILI_DESCRIPTION_STATUS_SOURCE = BILIBILI_DESCRIPTION_SOURCE + ".limit"
DESCRIPTION_LIMIT_NOTICE = "来源视频简介未完整提取，当前仅保留可核对的标题与目录；请到平台查看完整介绍。"
UNAVAILABLE_NOTICE = "来源返回了视频不可见页面；是否删除、需要登录、地区限制或临时故障尚未确认，请到平台核实。"
_UNAVAILABLE_TITLE = re.compile(r"视频去哪了呢[？?]?(?:[_\s-]*哔哩哔哩(?:[_\s-]*bilibili)?)?", re.I)
_STATE_LIMIT = 4_000_000
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


def unconfirmed_unavailable_video_fact(soup: BeautifulSoup, url: str) -> FieldFact | None:
    """An exact unavailable landing is evidence of uncertainty, not deletion."""
    if not _video_url(url):
        return None
    state = _page_initial_state(soup)
    video = state.get("videoData") if isinstance(state, dict) else None
    if isinstance(video, dict) and video.get("bvid") == urlsplit(_video_url(url)).path.rstrip("/").rsplit("/", 1)[-1] and video.get("title"):
        return None
    titles = [soup.title.get_text(" ", strip=True)] if soup.title else []
    titles.extend(tag.get("content", "").strip() for tag in soup.select('meta[property="og:title"]')[:2])
    observed = next((title for title in titles if _UNAVAILABLE_TITLE.fullmatch(title)), None)
    if not observed:
        return None
    facts = {"observed_landing_title": observed, "classification": "unavailable_cause_unconfirmed",
             "not_a_deletion_or_access_cause_diagnosis": True}
    return FieldFact("fetch_status", "unavailable_unconfirmed", "html.bilibili.unavailable_landing",
                     json.dumps(facts, ensure_ascii=False, sort_keys=True))


def unavailable_video_projection(resource: dict, evidence: list[dict]) -> dict:
    """Repair old extracted landing metadata in a view, never its raw evidence.

    Historical caches did not retain HTML error payloads. Their exact landing
    title cannot prove removal, but must not be a normally fetched course title.
    Only a same-video search observation may restore a course name.
    """
    if resource.get("fetch_status") in {"not_found", "error_page", "unsafe_url", "login_required", "captcha", "access_denied"}:
        return resource
    page_url = _video_url(resource.get("canonical_url") or resource.get("url") or resource.get("resolved_url") or "")
    ambiguous = resource.get("fetch_status") == "unavailable_unconfirmed" or (
        page_url and resource.get("video_evidence_status") != "page_verified"
        and _UNAVAILABLE_TITLE.fullmatch(str(resource.get("title") or "").strip()))
    if not page_url or not ambiguous:
        return resource
    projected = dict(resource, fetch_status="unavailable_unconfirmed", access_notice=UNAVAILABLE_NOTICE)
    search = next((row for row in evidence if row.get("kind") == "search" and row.get("title")
                   and not _UNAVAILABLE_TITLE.fullmatch(str(row["title"]).strip())
                   and _video_url(row.get("url") or "") == page_url), None)
    projected["field_provenance"] = dict(resource.get("field_provenance") or {})
    if search:
        projected["title"] = search["title"]
        projected["field_provenance"]["title"] = {"source": "search", "evidence_id": search.get("evidence_id"),
            "url": search["url"], "note": "保留同一视频的原始搜索名称；当前页面不可见原因未确认。"}
        # A legacy generic og:type=video is not valid page evidence once the
        # page is unavailable. Retain only the independently observed same-BV
        # search entry identity, so it may appear in review without page proof.
        search_identity = {"source": "url_pattern", "evidence_id": search.get("evidence_id"), "url": search["url"]}
        projected["resource_type"] = "video"
        projected["video_evidence_status"] = "search_discovered"
        projected["field_provenance"]["resource_type"] = dict(search_identity)
        projected["field_provenance"]["video_evidence_status"] = dict(search_identity)
    elif _UNAVAILABLE_TITLE.fullmatch(str(resource.get("title") or "").strip()):
        projected["title"] = "来源视频页面暂不可见（原因未确认）"
        projected["field_provenance"].pop("title", None)
    return projected


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
    # The source's current charging flag is independent of legacy rights.pay:
    # an observed charging-exclusive video can still have rights.pay == 0 and
    # expose a free preview. Absence/false is not proof of unrestricted access.
    if video.get("is_upower_exclusive") is True:
        result.fields.append(FieldFact("requires_payment", True, source + ".is_upower_exclusive",
            json.dumps({"bvid": requested_bvid, "is_upower_exclusive": True},
                       ensure_ascii=False, sort_keys=True)))
    thumbnail = safe_thumbnail_url(video.get("pic"), page_url)
    if thumbnail:
        result.fields.append(FieldFact("thumbnail_url", thumbnail, source + ".pic"))
    raw_description = video.get("desc")
    description = " ".join(raw_description.split()) if isinstance(raw_description, str) else ""
    try:
        description_bytes = len(description.encode("utf-8"))
        description_status = "limit_exceeded" if (len(description) > BILIBILI_DESCRIPTION_LIMIT
            or description_bytes > BILIBILI_DESCRIPTION_BYTES) else None
    except UnicodeEncodeError:
        description_status = "invalid_encoding"
        description_bytes = None
    if description_status:
        # Never let a silent prefix omit a later qualification/negative clause.
        # This diagnostic contains counts/status only, no unbounded source text.
        result.fields.append(FieldFact("description_extraction_status", description_status,
            BILIBILI_DESCRIPTION_STATUS_SOURCE,
            f"Own video description omitted: {description_status}; normalized_characters={len(description)}; "
            f"utf8_bytes={description_bytes}; limits={BILIBILI_DESCRIPTION_LIMIT} characters/{BILIBILI_DESCRIPTION_BYTES} bytes"))
        result.fields.append(FieldFact("access_notice", DESCRIPTION_LIMIT_NOTICE, BILIBILI_DESCRIPTION_STATUS_SOURCE))
    elif description:
        result.fields.append(FieldFact("description", description, BILIBILI_DESCRIPTION_SOURCE))
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


def empty_ssr_locale_url(html: str, raw_url: str, resolved_url: str, extracted: dict) -> str | None:
    """One observed public HTML route, only for the platform's empty SSR shell."""
    def native(value):
        if not isinstance(value, str) or value != value.strip() or any(ord(c) < 32 for c in value):
            return None
        try:
            parts = urlsplit(value)
            if (parts.scheme != "https" or parts.netloc not in {"www.bilibili.com", "bilibili.com"}
                    or parts.fragment or not re.fullmatch(r"/video/BV[0-9A-Za-z]{10}/?", parts.path)
                    or parts.query and not re.fullmatch(r"p=[1-9][0-9]{0,5}", parts.query)):
                return None
            return parts
        except ValueError:
            return None
    try:
        normalized = normalize_url(raw_url, preserve_bilibili_locale=True)
    except UnsafeURL:
        return None
    original, current = native(normalized), native(resolved_url)
    # Preserve strict native p syntax even when known tracking is normalized away.
    if original is not None and original.query and original.query not in urlsplit(raw_url).query.split("&"):
        return None
    if (original is None or current is None or original.netloc != current.netloc
            or original.path.rstrip("/") != current.path.rstrip("/") or original.query != current.query):
        return None
    if (extracted.get("fetch_status") != "javascript_required"
            or extracted.get("video_evidence_status") not in {None, "none"}
            or extracted.get("chapters") or extracted.get("title") or extracted.get("description")
            or extracted.get("resource_type") not in {None, "unknown"}
            or any(extracted.get(key) is True for key in ("requires_login", "requires_payment", "requires_enrollment"))
            or set(extracted.get("field_provenance", {})) - {"language"}):
        return None
    soup = BeautifulSoup(html, "html.parser")
    shells = soup.select("div#video-page-app")
    if (not soup.title or soup.title.get_text(strip=True) or len(shells) != 1
            or shells[0].find(True) or shells[0].get_text(strip=True)
            or soup.select_one("#app > *, video, audio, iframe, form, script[type='application/ld+json']")):
        return None
    if any(_STATE_ASSIGNMENT_REFERENCE.search(tag.string or tag.get_text())
           for tag in soup.select("script:not([src])")):
        return None
    # Loading the shared CaptchaLoader SDK is normal bootstrap, not a challenge.
    visible = soup.get_text(" ", strip=True)
    if re.search(r"登录|登陆|验证码|安全验证|访问.{0,6}(?:限制|拒绝)|视频去哪|不存在|不可用|403|404|captcha|access denied|sign in|log in", visible, re.I):
        return None
    for tag in soup.select("script[src]"):
        try:
            bootstrap = urlsplit(tag.get("src", ""))
        except ValueError:
            continue
        if (bootstrap.hostname == "s1.hdslb.com"
                and re.fullmatch(r"/bfs/static/jinkela/video/video\.[0-9A-Za-z_-]+\.js", bootstrap.path)):
            return urlunsplit((current.scheme, current.netloc, "/zh-Hans" + current.path, current.query, ""))
    return None
