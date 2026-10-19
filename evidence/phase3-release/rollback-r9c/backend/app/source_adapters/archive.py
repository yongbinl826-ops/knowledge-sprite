"""Internet Archive public details HTML; no player execution or media requests."""
from __future__ import annotations

import json
import math
import re
from urllib.parse import unquote, urljoin, urlsplit

from bs4 import BeautifulSoup

from ..url_utils import UnsafeURL, normalize_url
from .base import FieldFact, SourceFacts, clean_text


def duration_seconds(value) -> int | float | None:
    """Preserve finite positive playlist durations, including decimal strings."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        value = value.strip()
        if len(value) > 40 or not re.fullmatch(r"\d+(?:\.\d+)?", value):
            return None
        value = float(value)
    if not isinstance(value, (int, float)):
        return None
    try:
        return value if math.isfinite(value) and value > 0 else None
    except OverflowError:
        return None


def archive_video_playlist(soup: BeautifulSoup, url: str) -> list[dict]:
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
                # Media filenames are not chapter-page links, and a duration is
                # not a timeline offset. Keep the source page as the evidence link.
                chapters.append({"title": clean_text(item["title"], 300), "url": None, "source_url": url,
                                 "start_seconds": None, "end_seconds": None,
                                 "duration_seconds": duration_seconds(item.get("duration"))})
        if chapters:
            return chapters
    return []


class ArchiveAdapter:
    name = "archive_details"

    def matches(self, url: str) -> bool:
        parsed = urlsplit(url)
        return parsed.hostname in {"archive.org", "www.archive.org"} and re.fullmatch(r"/details/[^/]+/?", parsed.path) is not None

    def extract(self, soup: BeautifulSoup, url: str) -> SourceFacts:
        result = SourceFacts()
        for selector, field, source in (
            ('h1 [itemprop="name"]', "title", "html.archive.item_name"),
            ('#descript[itemprop="description"]', "description", "html.archive.description"),
            ('[itemprop="creator"]', "author", "html.archive.creator"),
        ):
            tag = soup.select_one(selector)
            if tag:
                value = clean_text(tag.get_text(" ", strip=True), 4000 if field == "description" else 500)
                result.fields.append(FieldFact(field, value, source))
                if field == "author" and value:
                    result.fields.append(FieldFact("author_role", "credited_creator", source, "itemprop=creator: " + value))
        chapters = archive_video_playlist(soup, url)
        if chapters:
            result.chapters = chapters
            result.catalog_source = "html.archive.play_av.playlist"
            result.catalog_kind = "video_playlist"
            result.fields.extend([
                FieldFact("resource_type", "playlist", result.catalog_source, "Public play-av HTML attributes identify a video player and its ordered playlist; media playback not tested"),
                FieldFact("video_evidence_status", "page_verified", result.catalog_source, "Public play-av args audio=false and playlist JSON contain video sources and item titles; no media requested"),
            ])
        return result
