"""Static, evidence-preserving metadata extraction. Page text is never executed."""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, datetime
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit

from bs4 import BeautifulSoup

from .url_utils import UnsafeURL, normalize_url


def clean_text(value: Any, limit: int = 4000) -> str | None:
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())[:limit]
    return value or None


def iso_duration(value: Any) -> int | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?", value)
    if not match or not any(match.groups()):
        return None
    days, hours, minutes, seconds = (float(part or 0) for part in match.groups())
    return int(days * 86400 + hours * 3600 + minutes * 60 + seconds)


def valid_date(value: Any) -> str | None:
    value = clean_text(value, 100)
    if not value:
        return None
    try:
        if len(value) == 10:
            date.fromisoformat(value)
        else:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value
    except ValueError:
        return None


def _person_name(value: Any) -> str | None:
    if isinstance(value, list):
        names = [_person_name(item) for item in value[:10]]
        return ", ".join(name for name in names if name) or None
    if isinstance(value, dict):
        return clean_text(value.get("name"), 250)
    return clean_text(value, 250)


def _json_nodes(value: Any, depth: int = 0):
    if depth > 12:
        return
    if isinstance(value, list):
        for item in value[:100]:
            yield from _json_nodes(item, depth + 1)
    elif isinstance(value, dict):
        yield value
        # Do not mistake arbitrary nested unrelated objects for this page's resource.
        for key in ("@graph", "mainEntity"):
            if key in value:
                yield from _json_nodes(value[key], depth + 1)


def _types(node: dict) -> set[str]:
    value = node.get("@type", [])
    values = {value} if isinstance(value, str) else {item for item in value if isinstance(item, str)} if isinstance(value, list) else set()
    return {re.sub(r"^https?://schema\.org/", "", item) for item in values}


def offset_seconds(value: Any) -> int | float | None:
    """Schema.org Clip offsets are numbers of seconds, never generated estimates."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    try:
        if not math.isfinite(value):
            return None
    except OverflowError:
        return None
    return value


def archive_video_playlist(soup: BeautifulSoup, url: str) -> list[dict]:
    """Read public HTML attributes only; never execute the player or fetch media."""
    parsed = urlsplit(url)
    match = re.fullmatch(r"/details/([^/]+)/?", parsed.path)
    if parsed.hostname not in {"archive.org", "www.archive.org"} or not match:
        return []
    identifier = unquote(match.group(1))
    for player in soup.select("play-av[args][playlist]")[:3]:
        raw_args, raw_playlist = player.get("args", ""), player.get("playlist", "")
        if len(raw_args) > 50_000 or len(raw_playlist) > 250_000:
            continue
        try:
            args, items = json.loads(raw_args), json.loads(raw_playlist)
        except (ValueError, TypeError, RecursionError):
            continue
        if not isinstance(args, dict) or args.get("audio") is not False or args.get("identifier") != identifier or not isinstance(items, list):
            continue
        chapters = []
        for item in items[:100]:
            if not isinstance(item, dict) or not clean_text(item.get("title"), 300):
                continue
            sources = item.get("sources")
            has_video_source = False
            for source in sources[:10] if isinstance(sources, list) else []:
                if not isinstance(source, dict) or not isinstance(source.get("type"), str) or source["type"] not in {"mp4", "ogg", "webm", "video/mp4", "video/ogg", "video/webm"} or not isinstance(source.get("file"), str):
                    continue
                try:
                    media = urlsplit(normalize_url(urljoin(url, source["file"])))
                except (UnsafeURL, ValueError):
                    continue
                if media.hostname == parsed.hostname and unquote(media.path).startswith("/download/" + identifier + "/"):
                    has_video_source = True
                    break
            if has_video_source:
                # The player gives media filenames, not chapter page links. Do not
                # invent /details/<id>/<file>, playback offsets, or download links.
                chapters.append({"title": clean_text(item["title"], 300), "url": None, "source_url": url,
                                 "start_seconds": None, "end_seconds": None})
        if chapters:
            return chapters
    return []


def detect_access_page(soup: BeautifulSoup, url: str) -> str | None:
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    headlines = [text.strip().lower() for text in [title] + [tag.get_text(" ", strip=True) for tag in soup.select("h1")[:2]]]
    prominent = " ".join(headlines)
    if re.search(r"verify (?:you are|that you are) human|security (?:check|verification)|just a moment", prominent) or any(
        re.fullmatch(r"(?:captcha|验证码|人机验证|安全验证|访问验证)(?:\s*[-|:：_–—]\s*.*|[.!。！]?)", heading)
        for heading in headlines
    ):
        return "captcha"
    if soup.select_one('iframe[src*="recaptcha"], iframe[src*="hcaptcha"], form[action*="captcha"], #challenge-form'):
        return "captcha"
    if re.search(r"access denied|request blocked|forbidden|访问受限|访问被拒绝|禁止访问", prominent):
        return "access_denied"
    if re.search(r"(?:^|\s)(?:404|410)(?:\s|$)|page not found|content (?:is )?(?:unavailable|removed)|页面不存在|页面已删除|内容已下架|课程已下架|链接已失效", prominent):
        return "not_found"
    if any(re.match(r"^(?:(?:error|错误)\s*)?(?:500|502|503|504)(?:\s|$)|^(?:bad gateway|service unavailable|internal server error|页面出错|系统繁忙|服务不可用|请求失败|出错了|出错啦)(?:\s|[-|:：_–—.!。！]|$)", heading) for heading in headlines):
        return "error_page"
    if re.search(r"请先?登录|登录后(?:继续|访问|查看)|sign in to continue|log in to continue", prominent):
        return "login_required"
    if any(re.fullmatch(r"(?:login|log in|sign in|登录|账号登录)(?:\s*[-|:：_–—]\s*.*)?", heading) for heading in headlines):
        return "login_required"
    if soup.select_one('input[type="password"]') and re.search(r"login|sign.?in|log.?in|登录", prominent):
        return "login_required"
    return None


class MetadataExtractor:
    def extract(self, html: str, url: str, fetched_at: str) -> dict:
        soup = BeautifulSoup(html, "html.parser")
        blocked = detect_access_page(soup, url)
        if blocked:
            return {"fetch_status": blocked, "video_evidence_status": "none", "requires_login": True if blocked == "login_required" else None}
        # Strip executable and invisible nodes before any visible text / catalog read.
        json_nodes: list[dict] = []
        for script in soup.select('script[type="application/ld+json"]')[:20]:
            raw = script.string or script.get_text()
            if len(raw) > 250_000:
                continue
            try:
                json_nodes.extend(_json_nodes(json.loads(raw)))
            except (ValueError, TypeError, RecursionError):
                continue
        primary = next((node for node in json_nodes if _types(node) & {"Course", "VideoObject", "LearningResource"}), None)
        metadata: dict[str, Any] = {
            "fetch_status": "fetched", "metadata_evidence_level": "page", "fetched_at": fetched_at,
            "field_provenance": {}, "evidence": [], "chapters": [],
        }

        def put(field: str, value: Any, source: str, excerpt: str | None = None):
            if value is None or value == "" or field in metadata and field not in {"chapters"}:
                return
            evidence_id = "ev_" + hashlib.sha256(f"{url}|{field}|{source}|{value}".encode()).hexdigest()[:20]
            metadata[field] = value
            metadata["field_provenance"][field] = {"evidence_id": evidence_id, "source": source, "url": url, "fetched_at": fetched_at}
            metadata["evidence"].append({"id": evidence_id, "evidence_id": evidence_id, "kind": "catalog" if field == "chapters" else "page",
                                         "url": url, "field": field, "source": source, "text": (excerpt or str(value))[:2000], "fetched_at": fetched_at})

        def put_catalog(chapters: list[dict], source: str, kind: str):
            if not chapters:
                return
            verified_chapters = []
            for index, chapter in enumerate(chapters[:100]):
                facts = {key: chapter.get(key) for key in ("title", "url", "start_seconds", "end_seconds")}
                if chapter.get("source_url"):
                    facts["source_url"] = chapter["source_url"]
                text = json.dumps(facts, ensure_ascii=False, sort_keys=True)
                evidence_id = "ev_" + hashlib.sha256(f"{url}|chapters.{index}|{source}|{text}".encode()).hexdigest()[:20]
                verified_chapters.append(dict(facts, source=source, evidence_id=evidence_id))
                metadata["evidence"].append({"id": evidence_id, "evidence_id": evidence_id, "kind": "catalog", "url": url,
                    "field": f"chapters.{index}", "source": source, "text": text, "fetched_at": fetched_at})
            put("chapters", verified_chapters, source)
            metadata["metadata_evidence_level"] = "catalog"
            metadata["catalog_kind"] = kind

        if primary:
            types = _types(primary)
            put("resource_type", "video" if "VideoObject" in types else "course" if "Course" in types else None, "jsonld.@type")
            if "VideoObject" in types:
                put("video_evidence_status", "page_verified", "jsonld.VideoObject", "Page JSON-LD identifies this resource as VideoObject; playback not tested")
            put("title", clean_text(primary.get("name"), 500), "jsonld.name")
            put("description", clean_text(primary.get("description")), "jsonld.description")
            put("author", _person_name(primary.get("author") or primary.get("instructor") or primary.get("creator")), "jsonld.author/instructor/creator")
            put("language", clean_text(primary.get("inLanguage"), 80), "jsonld.inLanguage")
            put("duration_seconds", iso_duration(primary.get("duration")), "jsonld.duration")
            put("published_at", valid_date(primary.get("datePublished") or primary.get("uploadDate")), "jsonld.datePublished/uploadDate")
            if primary.get("isAccessibleForFree") is True:
                put("requires_payment", False, "jsonld.isAccessibleForFree")
            offers = primary.get("offers")
            if isinstance(offers, dict) and offers.get("price") is not None:
                try:
                    price = float(offers["price"])
                    if price >= 0:
                        put("requires_payment", price > 0, "jsonld.offers.price")
                except (TypeError, ValueError):
                    pass
            # LearningResource also describes ordinary documentation. Only explicit
            # Course/VideoObject structure can promote hasPart into a course catalog.
            parts = (primary.get("hasPart") or primary.get("syllabusSections") or []) if types & {"Course", "VideoObject"} else []
            if isinstance(parts, dict):
                parts = [parts]
            chapters = []
            if isinstance(parts, list):
                for part in parts[:100]:
                    if not isinstance(part, dict) or not clean_text(part.get("name"), 300):
                        continue
                    chapter_url = None
                    if isinstance(part.get("url"), str):
                        try:
                            chapter_url = normalize_url(urljoin(url, part["url"]))
                        except UnsafeURL:
                            pass
                    start = offset_seconds(part.get("startOffset")) if "Clip" in _types(part) and "VideoObject" in types else None
                    end = offset_seconds(part.get("endOffset")) if "Clip" in _types(part) and "VideoObject" in types else None
                    if start is not None and end is not None and end < start:
                        end = None
                    chapters.append({"title": clean_text(part["name"], 300), "url": chapter_url,
                                     "start_seconds": start, "end_seconds": end})
            if chapters:
                put_catalog(chapters, "jsonld.hasPart.Clip" if "VideoObject" in types else "jsonld.hasPart/syllabusSections",
                            "video_chapters" if "VideoObject" in types else "course_outline")
        for attr, key, field in (("property", "og:title", "title"), ("property", "og:description", "description"),
                                 ("name", "description", "description"), ("name", "author", "author")):
            tag = soup.find("meta", attrs={attr: key})
            if tag:
                put(field, clean_text(tag.get("content"), 4000 if field == "description" else 500), "meta." + key)
        if soup.title:
            put("title", clean_text(soup.title.get_text(" ", strip=True), 500), "html.title")
        if soup.html:
            put("language", clean_text(soup.html.get("lang"), 80), "html.lang")
        og_type = soup.find("meta", attrs={"property": "og:type"})
        if og_type and str(og_type.get("content", "")).startswith("video"):
            put("resource_type", "video", "meta.og:type")
        for tag in soup.select("script, style, noscript, template, [hidden], [aria-hidden='true']"):
            if not tag.decomposed:
                tag.decompose()
        for tag in list(soup.select("[style]")):
            # Decomposing a hidden ancestor also clears descendants already in this
            # snapshot; BeautifulSoup sets their attrs to None after decompose().
            if tag.decomposed:
                continue
            if re.search(r"display\s*:\s*none|visibility\s*:\s*hidden", str(tag.get("style", "")), re.I):
                tag.decompose()
        parsed_url = urlsplit(url)
        archive_chapters = archive_video_playlist(soup, url) if not metadata["chapters"] else []
        if archive_chapters:
            put("resource_type", "playlist", "html.archive.play_av.playlist", "Public play-av HTML attributes identify a video player and its ordered playlist; media playback not tested")
            put_catalog(archive_chapters, "html.archive.play_av.playlist", "video_playlist")
            put("video_evidence_status", "page_verified", "html.archive.play_av.playlist", "Public play-av args audio=false and playlist JSON contain video sources and item titles; no media requested")
        is_mit_ocw = parsed_url.hostname in {"ocw.mit.edu", "www.ocw.mit.edu"} and parsed_url.path.startswith("/courses/")
        course_entry = re.fullmatch(r"(/courses/[^/]+)(?:/pages)?/?", parsed_url.path) if is_mit_ocw else None
        if course_entry and soup.select_one("#course-banner h1"):
            put("resource_type", "course", "html.mit_ocw.course_home", "Official OCW course homepage or pages overview with #course-banner h1 and same-course resource navigation")
            course_path = course_entry.group(1) + "/"
            for anchor in soup.select('a[href*="video_galleries/"]'):
                link_text = clean_text(anchor.get_text(" ", strip=True), 200)
                if not link_text or not re.search(r"video|lecture", link_text, re.I):
                    continue
                try:
                    linked = normalize_url(urljoin(url, str(anchor["href"])))
                except UnsafeURL:
                    continue
                linked_parts = urlsplit(linked)
                if linked_parts.scheme == parsed_url.scheme and linked_parts.netloc == parsed_url.netloc and linked_parts.path.startswith(course_path + "video_galleries/"):
                    # Internal directive is only a real public same-course href.
                    # Fetcher follows at most one and requires a reserved detail budget.
                    metadata["_catalog_followup"] = {"url": linked, "source_url": url, "link_text": link_text,
                                                     "source": "html.mit_ocw.course_navigation"}
                    break
        if is_mit_ocw and "/resources/" in parsed_url.path and soup.select_one(".video-page .video-player-wrapper video"):
            put("resource_type", "video", "html.mit_ocw.video_player", "Official OCW resource page contains .video-page .video-player-wrapper video; playback not tested")
            put("video_evidence_status", "page_verified", "html.mit_ocw.video_player", "Official OCW resource page contains .video-page .video-player-wrapper video; playback not tested")
        if is_mit_ocw and not metadata["chapters"]:
            # Verified against the real 2026 OCW public video-gallery HTML. This is
            # a scoped structural adapter, not a fixed collection of course results.
            content = soup.select_one("main#course-content-section")
            chapters = []
            if content and "/video_galleries/" in parsed_url.path:
                for card in content.select(".video-gallery-card")[:100]:
                    anchor = card.select_one("a.video-link[href]")
                    heading = card.select_one(".video-title")
                    if not anchor or not heading:
                        continue
                    title = clean_text(heading.get_text(" ", strip=True), 300)
                    try:
                        chapter_url = normalize_url(urljoin(url, str(anchor["href"])))
                    except UnsafeURL:
                        continue
                    if title and urlsplit(chapter_url).hostname == parsed_url.hostname:
                        chapters.append({"title": title, "url": chapter_url})
                if chapters:
                    put("resource_type", "playlist", "html.mit_ocw.video_gallery", "main#course-content-section contains video-gallery-card / a.video-link / video-title")
                    put_catalog(chapters, "html.mit_ocw.video_gallery", "video_playlist")
                    put("video_evidence_status", "page_verified", "html.mit_ocw.video_gallery", "main#course-content-section contains actual video-gallery-card / a.video-link / video-title entries")
        if not metadata["chapters"]:
            # Explicit course-outline containers only; a global navigation menu is not a catalog.
            outline = soup.select_one(".course-outline, .curriculum, .chapter-list, #course-outline, [data-course-outline]")
            chapters = []
            course_context = metadata.get("resource_type") in {"course", "video", "playlist"} or bool(
                re.search(r"\bcourse\b|课程", metadata.get("title", ""), re.I) and outline
                and not re.search(r"\bdocumentation\b|参考文档", metadata.get("title", ""), re.I))
            if outline and course_context:
                for anchor in outline.select("a[href]")[:100]:
                    title = clean_text(anchor.get_text(" ", strip=True), 300)
                    if not title:
                        continue
                    try:
                        chapter_url = normalize_url(urljoin(url, str(anchor["href"])))
                    except UnsafeURL:
                        continue
                    chapters.append({"title": title, "url": chapter_url})
            if chapters:
                if metadata.get("resource_type") is None:
                    put("resource_type", "course", "html.visible_course_outline", "Course title and explicit course-outline DOM with actual lesson links")
                put_catalog(chapters, "html.visible_course_outline", "course_outline")
        if not metadata.get("title") and soup.h1:
            put("title", clean_text(soup.h1.get_text(" ", strip=True), 500), "html.h1")
        visible = soup.get_text(" ", strip=True)
        if len(visible) < 80 and not metadata.get("description") and not primary:
            metadata["fetch_status"] = "javascript_required"
        metadata.setdefault("video_evidence_status", "none")
        return metadata
