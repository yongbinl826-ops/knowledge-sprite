"""A published course's visible announcement, not a general news article.

No player, script, external API or media request is made by this adapter.
"""
from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup, Tag

from .base import FieldFact, SourceFacts, clean_text
from ..url_utils import UnsafeURL, normalize_url


VIDEO_SOURCE = "html.freecodecamp.course_announcement.video"
SUMMARY_SOURCE = "html.freecodecamp.course_announcement.summary"
SUMMARY_LIMIT = 1800  # The extractor retains the complete <=2000-char excerpt.
_CHANNEL = re.compile(r"freeCodeCamp(?:\.org)?\s+YouTube\s+channel", re.I)
_COURSE_DECLARATION = re.compile(r"\b(?:course|tutorial)\b", re.I)
_ANNOUNCEMENT = re.compile(r"\b(?:published|released|created|watch|learn|teaches?)\b", re.I)
_COVERAGE_MARKER = re.compile(
    r"^(?:Here are (?:the )?(?:(?:core|key|main) )?(?:concepts|topics|skills) covered(?: in this course)?|"
    r"You['’]ll learn [^:]{1,140} by [^:]{1,140}):$", re.I)
_PROJECT_MARKER = re.compile(r"^Below are the projects you will build\.$", re.I)
_PROJECT_SECTION = re.compile(r"^A Sneak Peek into the Course$", re.I)
_DIFFICULTY = re.compile(r"^(?:For Beginners|Intermediate Level|Advanced):$", re.I)
_PROJECT_TEACHING = re.compile(r"^(?:You will\b|Learn how\b|Dive into\b|Apply these\b|This project introduces\b|It combines\b)", re.I)
_PROJECT_LIMITATION = re.compile(r"\b(?:not|never|no|only|without|except|prerequisite\w*|already|required|assumes?|must know)\b", re.I)


def course_announcement_url(url: str) -> str | None:
    try:
        normalized = normalize_url(url)
        parsed = urlsplit(normalized)
    except (UnsafeURL, TypeError, ValueError):
        return None
    if (parsed.scheme != "https" or parsed.hostname not in {"freecodecamp.org", "www.freecodecamp.org"}
            or not re.fullmatch(r"/news/[a-z0-9][a-z0-9-]{1,180}/?", parsed.path)):
        return None
    return normalized


def _youtube_id(url: str, *, embed: bool) -> str | None:
    try:
        parsed = urlsplit(normalize_url(url))
    except (UnsafeURL, TypeError, ValueError):
        return None
    if parsed.scheme != "https" or parsed.port not in {None, 443} or parsed.fragment:
        return None
    if embed:
        if parsed.hostname not in {"www.youtube.com", "www.youtube-nocookie.com"}:
            return None
        match = re.fullmatch(r"/embed/([A-Za-z0-9_-]{11})", parsed.path)
        return match[1] if match and not parsed.query else None
    if parsed.hostname == "youtu.be":
        # The observed publisher's short watch link must still identify exactly
        # the same video as its iframe. No redirects or unknown parameters.
        match = re.fullmatch(r"/([A-Za-z0-9_-]{11})", parsed.path)
        return match[1] if match and not parsed.query else None
    if parsed.hostname != "www.youtube.com" or parsed.path != "/watch":
        return None
    query = parse_qs(parsed.query, keep_blank_values=True)
    identifiers = query.get("v", [])
    return identifiers[0] if set(query) == {"v"} and len(identifiers) == 1 and re.fullmatch(r"[A-Za-z0-9_-]{11}", identifiers[0]) else None


def _visible(tag: Tag) -> bool:
    for ancestor in [tag, *tag.parents]:
        if (ancestor.name in {"script", "style", "template", "noscript"} or ancestor.has_attr("hidden")
                or ancestor.get("aria-hidden") == "true"
                or re.search(r"display\s*:\s*none|visibility\s*:\s*hidden", str(ancestor.get("style", "")), re.I)):
            return False
    return not (tag.name == "iframe" and (str(tag.get("height")) == "0" or str(tag.get("width")) == "0"))


def _project_text(tag: Tag) -> str:
    return " ".join("".join(str(node) for node in tag.strings
                            if isinstance(node.parent, Tag) and _visible(node.parent)).split())


class FreeCodeCampCourseAdapter:
    name = "freecodecamp_course_announcement"

    def matches(self, url: str) -> bool:
        return course_announcement_url(url) is not None

    def extract(self, soup: BeautifulSoup, url: str) -> SourceFacts:
        result = SourceFacts()
        if not self.matches(url):
            return result
        articles = soup.select("article.post-full")
        if len(articles) != 1:
            return result
        article = articles[0]
        headings, contents = article.select("h1.post-full-title"), article.select("section.post-content")
        if len(headings) != 1 or len(contents) != 1:
            return result
        title = clean_text(headings[0].get_text(" ", strip=True), 500)
        content = contents[0]
        if not title or not _visible(headings[0]) or not _visible(content):
            return result
        frames = [(frame, _youtube_id(frame.get("src", ""), embed=True))
                  for frame in content.select("iframe[src]")[:5] if _visible(frame)]
        frames = [(frame, identity) for frame, identity in frames if identity]
        identities = {identity for _, identity in frames}
        if len(identities) != 1:
            return result
        identity = next(iter(identities))
        frame = frames[0][0]
        watch = next((anchor for anchor in content.select("a[href]")[:100] if _visible(anchor)
                      and _youtube_id(anchor.get("href", ""), embed=False) == identity
                      and _CHANNEL.search(anchor.get_text(" ", strip=True))), None)
        if watch is None:
            return result
        blocks = [child for child in content.children if isinstance(child, Tag) and _visible(child)][:100]
        declaration = next((block for block in blocks if block.name == "p"
                            and _CHANNEL.search(block.get_text(" ", strip=True))
                            and _COURSE_DECLARATION.search(block.get_text(" ", strip=True))
                            and _ANNOUNCEMENT.search(block.get_text(" ", strip=True))
                            and len(block.get_text(" ", strip=True)) <= 600), None)
        if declaration is None:
            return result
        positions = {id(tag): index for index, tag in enumerate(content.descendants) if isinstance(tag, Tag)}
        if positions[id(declaration)] >= positions[id(frame)]:
            return result
        declaration_text = clean_text(declaration.get_text(" ", strip=True), 600)
        selected = [declaration_text]
        # The adjacent lists are explicitly announced as this course's learning
        # content. They are not a video timeline, so no chapters are invented.
        for block in blocks[blocks.index(declaration) + 1:]:
            if positions.get(id(block), 0) >= positions[id(frame)]:
                break
            if block.name != "p" or not _COVERAGE_MARKER.fullmatch(block.get_text(" ", strip=True)):
                continue
            listing = block.find_next_sibling()
            if not isinstance(listing, Tag) or listing.name not in {"ul", "ol"} or not _visible(listing):
                continue
            entries = listing.find_all("li", recursive=False)
            if not 1 <= len(entries) <= 30:
                continue
            for item in entries:
                value = clean_text(item.get_text(" ", strip=True), SUMMARY_LIMIT)
                if value and sum(map(len, selected)) + len(selected) + len(value) <= SUMMARY_LIMIT:
                    selected.append(value)
        # Another observed course shape announces projects in a named course
        # section, then uses difficulty headings and bold project labels. Keep
        # only complete publisher-written teaching sentences from that bounded
        # section, not author/CTA prose, the article's conclusion or code lists.
        section = None
        for index, block in enumerate(blocks):
            if positions.get(id(block), 0) <= positions[id(declaration)]:
                continue
            if positions.get(id(block), 0) >= positions[id(frame)]:
                break
            if block.name == "h2":
                section = block.get_text(" ", strip=True)
            if (block.name != "p" or not _PROJECT_MARKER.fullmatch(block.get_text(" ", strip=True))
                    or not _PROJECT_SECTION.fullmatch(section or "")):
                continue
            level_seen = False
            for item in blocks[index + 1:]:
                if positions.get(id(item), 0) >= positions[id(frame)] or item.name in {"h1", "h2"}:
                    break
                if item.name == "h3":
                    level_seen = bool(_DIFFICULTY.fullmatch(item.get_text(" ", strip=True)))
                    continue
                if not level_seen or item.name != "p" or item.find("a") or item.select_one("code,pre,iframe,aside,nav"):
                    continue
                label = item.find("strong", recursive=False)
                if label is None or not _visible(label):
                    continue
                label_text = clean_text(_project_text(label), 300)
                paragraph = _project_text(item)
                if not label_text or not paragraph.startswith(label_text) or len(paragraph) > 1000:
                    continue
                body = paragraph[len(label_text):].lstrip(" :")
                sentences = [s for s in re.split(r"(?<=[.!?])\s+", body)
                             if _PROJECT_TEACHING.search(s) or _PROJECT_LIMITATION.search(s)]
                value = "\n".join([label_text, *sentences])
                if sum(map(len, selected)) + len(selected) + len(value) <= SUMMARY_LIMIT:
                    selected.append(value)
            break
        summary = "\n".join(selected)
        binding = json.dumps({"course_title": title, "announcement": declaration_text, "video_id": identity,
                              "watch_url": watch["href"], "embed_url": frame["src"],
                              "basis": "visible same-course declaration, same-ID watch link and iframe; no player/media request"}, ensure_ascii=False, sort_keys=True)
        result.fields.extend([
            FieldFact("title", title, "html.freecodecamp.course_announcement.title"),
            FieldFact("resource_type", "video", VIDEO_SOURCE, binding),
            FieldFact("video_evidence_status", "page_verified", VIDEO_SOURCE, binding),
            FieldFact("video_topic_summary", summary, SUMMARY_SOURCE),
            FieldFact("description", summary, SUMMARY_SOURCE),
        ])
        return result


def bound_video_topic_summary(resource: dict, evidence: list[dict]) -> str | None:
    """Validate retained source proof before restricting topic matching to it."""
    if (not course_announcement_url(resource.get("url", "")) or resource.get("resource_type") != "video"
            or resource.get("video_evidence_status") != "page_verified"
            or resource.get("fetch_status") not in {"fetched", "success"}
            or resource.get("metadata_evidence_level") not in {"page", "catalog"}):
        return None
    summary = resource.get("video_topic_summary")
    if not isinstance(summary, str) or not 1 <= len(summary) <= SUMMARY_LIMIT:
        return None
    provenance = resource.get("field_provenance", {})
    records = {}
    try:
        targets = {normalize_url(resource[key]) for key in ("url", "canonical_url", "resolved_url") if resource.get(key)}
        for field, source in (("video_evidence_status", VIDEO_SOURCE), ("video_topic_summary", SUMMARY_SOURCE)):
            origin = provenance.get(field) or {}
            row = next((row for row in evidence if row.get("evidence_id") == origin.get("evidence_id")), None)
            if (origin.get("source") != source or not row or row.get("kind") != "page" or row.get("field") != field
                    or row.get("source") != source or normalize_url(row.get("url", "")) not in targets
                    or normalize_url(origin.get("url", "")) not in targets):
                return None
            records[field] = row
        binding = json.loads(records["video_evidence_status"]["text"])
    except (UnsafeURL, TypeError, ValueError, KeyError, RecursionError):
        return None
    if (not isinstance(binding, dict) or binding.get("course_title") != resource.get("title")
            or not _CHANNEL.search(str(binding.get("announcement", "")))
            or not _COURSE_DECLARATION.search(str(binding.get("announcement", "")))
            or not _ANNOUNCEMENT.search(str(binding.get("announcement", "")))
            or _youtube_id(binding.get("watch_url", ""), embed=False) != binding.get("video_id")
            or _youtube_id(binding.get("embed_url", ""), embed=True) != binding.get("video_id")
            or not binding.get("video_id") or records["video_topic_summary"].get("text") != summary):
        return None
    return summary
