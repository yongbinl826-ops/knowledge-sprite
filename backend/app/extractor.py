"""Static, evidence-preserving metadata extraction. Page text is never executed."""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, datetime
from typing import Any
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from .url_utils import UnsafeURL, normalize_url, safe_thumbnail_url
from .source_adapters import extract_source_facts
from .source_adapters.freecodecamp import SUMMARY_SOURCE as FCC_SUMMARY_SOURCE
from .source_adapters.techwithtim import SUMMARY_SOURCE as TWT_SUMMARY_SOURCE, SUMMARY_LIMIT as TWT_SUMMARY_LIMIT
from .source_adapters.base import clean_text
from .source_adapters.video_leads import observed_bilibili_video_leads
from .source_adapters.archive import archive_video_playlist  # Compatibility for existing imports.
from .source_adapters.icourse163 import MOOC_CATALOG_LIMIT, MOOC_STRUCT_SOURCE, extract_embedded_course_facts
from .source_adapters.kaoyan import extract_embedded_kaoyan_facts
from .source_adapters.bilibili import BILIBILI_DESCRIPTION_LIMIT, BILIBILI_DESCRIPTION_SOURCE, BILIBILI_DESCRIPTION_STATUS_SOURCE, BILIBILI_CATALOG_LIMIT, UNAVAILABLE_NOTICE, extract_embedded_video_facts, unavailable_video_fact, unconfirmed_unavailable_video_fact


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


def _image_references(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key in ("contentUrl", "url"):
            if isinstance(value.get(key), str):
                yield value[key]
    elif isinstance(value, list):
        for item in value[:10]:
            if isinstance(item, (str, dict)):
                yield from _image_references(item)


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
        # Seal same-BV localized facts under the existing canonical identity.
        # The fetcher keeps the exact response route separately as resolved_url.
        if urlsplit(url).path.startswith("/zh-Hans/video/"):
            canonical = normalize_url(url)
            if urlsplit(canonical).path.startswith("/video/"):
                url = canonical
        soup = BeautifulSoup(html, "html.parser")
        unavailable = unavailable_video_fact(soup, url)
        if unavailable:
            evidence_id = "ev_" + hashlib.sha256(f"{url}|{unavailable.source}|{unavailable.excerpt}".encode()).hexdigest()[:20]
            return {"fetch_status": "not_found", "video_evidence_status": "none", "requires_login": None,
                "fetched_at": fetched_at, "metadata_evidence_level": "page", "chapters": [],
                "field_provenance": {"fetch_status": {"evidence_id": evidence_id, "source": unavailable.source,
                    "url": url, "fetched_at": fetched_at}},
                "evidence": [{"id": evidence_id, "evidence_id": evidence_id, "kind": "page", "url": url,
                    "field": "fetch_status", "source": unavailable.source, "text": unavailable.excerpt,
                    "fetched_at": fetched_at}]}
        blocked = detect_access_page(soup, url)
        if blocked:
            return {"fetch_status": blocked, "video_evidence_status": "none", "requires_login": True if blocked == "login_required" else None}
        uncertain = unconfirmed_unavailable_video_fact(soup, url)
        if uncertain:
            evidence_id = "ev_" + hashlib.sha256(f"{url}|{uncertain.source}|{uncertain.excerpt}".encode()).hexdigest()[:20]
            return {"fetch_status": uncertain.value, "video_evidence_status": "none", "access_notice": UNAVAILABLE_NOTICE,
                "fetched_at": fetched_at, "metadata_evidence_level": "page", "chapters": [],
                "field_provenance": {"fetch_status": {"evidence_id": evidence_id, "source": uncertain.source,
                    "url": url, "fetched_at": fetched_at}},
                "evidence": [{"id": evidence_id, "evidence_id": evidence_id, "kind": "page", "url": url,
                    "field": "fetch_status", "source": uncertain.source, "text": uncertain.excerpt,
                    "fetched_at": fetched_at}]}
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

        bili_description_limited = False

        def put(field: str, value: Any, source: str, excerpt: str | None = None):
            if field == "description" and bili_description_limited:
                return
            if value is None or value == "" or field in metadata and field not in {"chapters"}:
                return
            evidence_id = "ev_" + hashlib.sha256(f"{url}|{field}|{source}|{value}".encode()).hexdigest()[:20]
            metadata[field] = value
            metadata["field_provenance"][field] = {"evidence_id": evidence_id, "source": source, "url": url, "fetched_at": fetched_at}
            metadata["evidence"].append({"id": evidence_id, "evidence_id": evidence_id, "kind": "catalog" if field == "chapters" else "page",
                                         "url": url, "field": field, "source": source,
                                         "text": (excerpt or str(value))[:TWT_SUMMARY_LIMIT if field == "video_topic_summary" and source == TWT_SUMMARY_SOURCE
                                             else BILIBILI_DESCRIPTION_LIMIT if field == "description" and source == BILIBILI_DESCRIPTION_SOURCE else 2000],
                                         "fetched_at": fetched_at})

        def put_catalog(chapters: list[dict], source: str, kind: str):
            if not chapters or metadata.get("catalog_fetch_status") in {"catalog_limit_exceeded", "catalog_payload_invalid"}:
                return
            mooc_source = source.startswith("html.icourse163.")
            bilibili_source = source.startswith("html.bilibili.")
            item_limit = MOOC_CATALOG_LIMIT if mooc_source else BILIBILI_CATALOG_LIMIT if bilibili_source else 100
            if (mooc_source or bilibili_source) and len(chapters) > item_limit:
                put("catalog_fetch_status", "catalog_limit_exceeded", source + ".limit",
                    f"Public course outline contains {len(chapters)} entries, exceeding the {item_limit}-entry limit; no truncated catalog is displayed")
                return
            verified_chapters = []
            for index, chapter in enumerate(chapters[:item_limit]):
                facts = {key: chapter.get(key) for key in ("title", "url", "start_seconds", "end_seconds")}
                if chapter.get("source_url"):
                    facts["source_url"] = chapter["source_url"]
                if "duration_seconds" in chapter:
                    facts["duration_seconds"] = chapter["duration_seconds"]
                if "page_number" in chapter:
                    facts["page_number"] = chapter["page_number"]
                parent = chapter.get("outline_parent_index")
                if (source == MOOC_STRUCT_SOURCE and type(parent) is int and 0 <= parent < index
                        and facts.get("source_url") == url
                        and verified_chapters[parent].get("source_url") == url
                        and "outline_parent_index" not in chapters[parent]):
                    facts["outline_parent_index"] = parent
                text = json.dumps(facts, ensure_ascii=False, sort_keys=True)
                evidence_id = "ev_" + hashlib.sha256(f"{url}|chapters.{index}|{source}|{text}".encode()).hexdigest()[:20]
                verified_chapters.append(dict(facts, source=source, evidence_id=evidence_id))
                metadata["evidence"].append({"id": evidence_id, "evidence_id": evidence_id, "kind": "catalog", "url": url,
                    "field": f"chapters.{index}", "source": source, "text": text, "fetched_at": fetched_at})
            put("chapters", verified_chapters, source)
            metadata["metadata_evidence_level"] = "catalog"
            metadata["catalog_kind"] = kind

        embedded_video_facts = extract_embedded_video_facts(soup, url)
        # Preserve observed navigation separately, before DOM cleanup changes
        # anchor positions. Same-BV identity is required before collecting any.
        video_leads = observed_bilibili_video_leads(soup, url) if any(
            fact.field == "video_evidence_status" and fact.value == "page_verified"
            for fact in embedded_video_facts.fields) else []
        bili_description_limited = any(fact.field == "description_extraction_status"
            and fact.source == BILIBILI_DESCRIPTION_STATUS_SOURCE
            and fact.value in {"limit_exceeded", "invalid_encoding"} for fact in embedded_video_facts.fields)
        # On a verified BV page, its own videoData is the resource identity.
        # Generic JSON-LD elsewhere on that page may describe related content.
        if embedded_video_facts.fields:
            primary = None
        if primary:
            types = _types(primary)
            put("resource_type", "video" if "VideoObject" in types else "course" if "Course" in types else None, "jsonld.@type")
            # A typed, same-origin parent relation is evidence of affiliation,
            # not a directive to fetch another page or merge cross-site mirrors.
            parent_nodes = primary.get("isPartOf", [])
            if isinstance(parent_nodes, dict):
                parent_nodes = [parent_nodes]
            parent_urls = []
            if isinstance(parent_nodes, list):
                current = urlsplit(url)
                for parent in parent_nodes[:20]:
                    if not isinstance(parent, dict) or "Course" not in _types(parent):
                        continue
                    raw_parent = parent.get("url") or parent.get("@id")
                    if not isinstance(raw_parent, str):
                        continue
                    try:
                        parent_url = normalize_url(urljoin(url, raw_parent))
                    except UnsafeURL:
                        continue
                    parsed_parent = urlsplit(parent_url)
                    if (parsed_parent.scheme, parsed_parent.netloc) == (current.scheme, current.netloc):
                        parent_urls.append(parent_url)
            unique_parents = list(dict.fromkeys(parent_urls))
            if len(unique_parents) == 1:
                put("parent_course_url", unique_parents[0], "jsonld.isPartOf.Course",
                    json.dumps({"@type": "Course", "url": unique_parents[0]}, ensure_ascii=False))
            if "VideoObject" in types:
                put("video_evidence_status", "page_verified", "jsonld.VideoObject", "Page JSON-LD identifies this resource as VideoObject; playback not tested")
            put("title", clean_text(primary.get("name"), 500), "jsonld.name")
            for image_field in ("thumbnailUrl", "image"):
                for reference in _image_references(primary.get(image_field)):
                    put("thumbnail_url", safe_thumbnail_url(reference, url), "jsonld." + image_field)
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
                    # Named attachments, related videos and articles are not
                    # timeline chapters. Only an explicit Clip has that meaning.
                    if "VideoObject" in types and "Clip" not in _types(part):
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
        # MOOC publishes its public curriculum as a literal value in the same
        # HTTP document. Read that narrowly typed payload before removing script
        # nodes; this never executes code or follows an API/media URL.
        embedded_facts = extract_embedded_course_facts(soup, url)
        embedded_facts.fields.extend(extract_embedded_kaoyan_facts(soup, url).fields)
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
        source_facts = extract_source_facts(soup, url)
        source_facts.fields.extend(embedded_facts.fields)
        source_facts.fields.extend(embedded_video_facts.fields)
        if not source_facts.chapters and embedded_facts.chapters:
            source_facts.chapters = embedded_facts.chapters
            source_facts.catalog_source = embedded_facts.catalog_source
            source_facts.catalog_kind = embedded_facts.catalog_kind
        # Same-BV pages supplies explicit page numbers and the complete bounded
        # selector. Prefer it to a DOM viewport's potentially shorter preview.
        if embedded_video_facts.chapters:
            source_facts.chapters = embedded_video_facts.chapters
            source_facts.catalog_source = embedded_video_facts.catalog_source
            source_facts.catalog_kind = embedded_video_facts.catalog_kind
        # Resource-specific visible text takes precedence over generic site OG
        # text, while explicit JSON-LD fields retain their established priority.
        for fact in source_facts.fields:
            if fact.field in {"title", "description", "author", "thumbnail_url"}:
                if (fact.field == "thumbnail_url" and fact.source == "html.icourse163.course_cover"
                        and safe_thumbnail_url(fact.value, url)
                        and metadata.get("field_provenance", {}).get("thumbnail_url", {}).get("source", "").startswith("jsonld.")):
                    # The observed native course-cover container is stronger
                    # than a generic JSON-LD node that may describe a related
                    # course. Keep its old evidence record, but bind the field
                    # to the actual course cover, including when URLs coincide.
                    metadata.pop("thumbnail_url", None)
                    metadata["field_provenance"].pop("thumbnail_url", None)
                put(fact.field, fact.value, fact.source, fact.excerpt)
        for tag in soup.select('meta[property="og:image"], meta[property="og:image:secure_url"]')[:10]:
            put("thumbnail_url", safe_thumbnail_url(tag.get("content"), url), "meta." + str(tag.get("property")))
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
        for fact in source_facts.fields:
            if fact.field not in {"title", "description", "author", "thumbnail_url"}:
                # A higher-priority JSON-LD author must not inherit a different
                # author's DOM role merely because the same page has both.
                if fact.field == "author_role" and metadata["field_provenance"].get("author", {}).get("source") != fact.source:
                    continue
                put(fact.field, fact.value, fact.source, fact.excerpt)
        if source_facts.chapters and not metadata["chapters"]:
            put_catalog(source_facts.chapters, source_facts.catalog_source, source_facts.catalog_kind)
        if source_facts.catalog_followup:
            metadata["_catalog_followup"] = source_facts.catalog_followup
        fcc_video_announcement = metadata["field_provenance"].get("video_topic_summary", {}).get("source") in {FCC_SUMMARY_SOURCE, TWT_SUMMARY_SOURCE}
        if not metadata["chapters"] and not fcc_video_announcement and metadata.get("catalog_fetch_status") not in {"catalog_limit_exceeded", "catalog_payload_invalid"}:
            # Explicit course-outline containers only; a global navigation menu is not a catalog.
            outline = soup.select_one(".course-outline, .curriculum, .chapter-list, #course-outline, [data-course-outline]")
            chapters = []
            # A title containing "course" and a CSS class do not distinguish a
            # real course from notes, articles, or documentation. Require the
            # independently extracted resource structure before reading links.
            course_context = metadata.get("resource_type") in {"course", "video", "playlist"}
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
                put_catalog(chapters, "html.visible_course_outline", "course_outline")
        if not metadata.get("title") and soup.h1:
            put("title", clean_text(soup.h1.get_text(" ", strip=True), 500), "html.h1")
        # An oversized/invalid source catalog is an all-source failure for this page.
        # JSON-LD may have been read before the embedded limit was observed, or
        # visible DOM may contain only a short preview. Neither may resurrect a
        # partial catalog after the complete public payload exceeded the bound.
        if (metadata.get("catalog_fetch_status") in {"catalog_limit_exceeded", "catalog_payload_invalid"}
                and metadata["field_provenance"].get("catalog_fetch_status", {}).get("source", "").startswith(("html.icourse163.", "html.bilibili."))):
            metadata["chapters"] = []
            metadata.pop("catalog_kind", None)
            metadata.pop("_catalog_followup", None)
            metadata["field_provenance"].pop("chapters", None)
            metadata["evidence"] = [row for row in metadata["evidence"] if row.get("kind") != "catalog"]
            metadata["metadata_evidence_level"] = "page"
        visible = soup.get_text(" ", strip=True)
        native_course_cover = metadata.get("field_provenance", {}).get("thumbnail_url", {}).get("source") == "html.icourse163.course_cover"
        if (len(visible) < 80 and not metadata.get("description") and not primary
                and not embedded_video_facts.fields and not native_course_cover):
            metadata["fetch_status"] = "javascript_required"
        metadata.setdefault("video_evidence_status", "none")
        if video_leads and metadata.get("fetch_status") == "fetched" and metadata["video_evidence_status"] == "page_verified":
            metadata["_video_leads"] = video_leads
        return metadata
