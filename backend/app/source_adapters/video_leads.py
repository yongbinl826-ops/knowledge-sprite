"""Bounded observed navigation leads, never metadata or recommendation facts."""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urljoin, urlsplit

from bs4 import BeautifulSoup

from ..url_utils import UnsafeURL, normalize_url


def _native_video_url(raw: str) -> tuple[str, str, str] | None:
    try:
        url = normalize_url(raw)
        parts = urlsplit(url)
        if (parts.scheme != "https" or parts.hostname not in {"www.bilibili.com", "bilibili.com"}
                or parts.port not in {None, 443} or parts.fragment):
            return None
        match = re.fullmatch(r"/video/(BV[0-9A-Za-z]{10}|av[0-9]+)/?", parts.path)
        if not match:
            return None
        query = parse_qsl(parts.query, keep_blank_values=True)
        if query and (len(query) != 1 or query[0][0] != "p" or not re.fullmatch(r"[1-9][0-9]*", query[0][1])):
            return None
        return url, match[1], query[0][1] if query else ""
    except (UnsafeURL, ValueError):
        return None


def observed_bilibili_video_leads(soup: BeautifulSoup, source_url: str) -> list[dict]:
    """Read only native anchor targets; caller must verify the source video.

    The first 500 raw anchors bound inspection, including rejected/hidden nodes.
    Titles label a navigation lead only and cannot prove its target's content.
    """
    source = _native_video_url(source_url)
    if source is None:
        return []
    leads = []
    seen = set()
    for anchor in soup.find_all("a", href=True, limit=500):
        if any(tag.name in {"script", "style", "template", "noscript"} or tag.has_attr("hidden")
               or tag.get("aria-hidden") == "true"
               or re.search(r"display\s*:\s*none|visibility\s*:\s*hidden", str(tag.get("style", "")), re.I)
               for tag in [anchor, *anchor.parents]):
            continue
        href = anchor.get("href")
        if (not isinstance(href, str) or not href.strip() or "\\" in href
                or any(ord(char) < 32 or ord(char) == 127 for char in href)):
            continue
        target = _native_video_url(urljoin(source[0], href))
        if target is None or target[1] == source[1]:
            continue
        # www/bare hosts and trailing slashes do not create distinct videos.
        identity = target[1:]
        if identity in seen:
            continue
        raw_text = anchor.get_text(" ", strip=True)
        title = " ".join(raw_text.split()) if raw_text else " ".join(str(anchor.get("title") or "").split())
        if not title or len(title) > 300:
            continue
        seen.add(identity)
        leads.append({"url": target[0], "title": title, "source_url": source[0]})
        if len(leads) >= 24:
            break
    return leads
