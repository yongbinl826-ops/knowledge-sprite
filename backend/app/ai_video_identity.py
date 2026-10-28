"""Ground AI direct-video hints in independently fetched native page facts.

Acceptance proves observed resource identity and field provenance, not teaching
relevance or playback. The caller must classify the returned original-site text
against its knowledge points. Model titles, descriptions, covers and chapters
are never forwarded to the fetcher or copied into the result.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import math
import re
from collections.abc import Callable, Sequence
from typing import Awaitable
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from .ai_video_fallback import direct_video_url
from .mooc_urls import course_identity_parts
from .related_recommendations import bound_native_course_identity
from .url_utils import UnsafeURL, normalize_url, platform_for_url, safe_thumbnail_url
from .video_availability import _bound_page_video


_BILI_NATIVE_IDENTITIES = frozenset({
    "html.bilibili.__INITIAL_STATE__.videoData.bvid",
    "html.bilibili.video_pod.multip",
})
_NATIVE_GENERIC_FIELDS = frozenset({
    "html.title", "html.h1", "meta.og:title", "meta.og:description",
    "meta.description", "meta.og:image", "meta.og:image:secure_url",
    "jsonld.name", "jsonld.description", "jsonld.thumbnailUrl", "jsonld.image",
})
_GENERIC_ONLY = re.compile(
    r"bilibili|哔哩哔哩|中国大学mooc|中国大学慕课|慕课|学堂在线|xuetangx|"
    r"干杯|乾杯|首页|登录|注册|人机验证|安全验证|访问验证|验证中心|"
    r"页面不存在|视频不存在|视频已失效|页面无法访问|404|notfound|pagenotfound|login|homepage",
    re.I,
)


def _identity(value) -> tuple | None:
    """Same native course and selected part only; locale is not a new video."""
    if not isinstance(value, str):
        return None
    try:
        normalized = normalize_url(value)
        parsed = urlsplit(normalized)
        if parsed.scheme != "https" or parsed.port not in {None, 443}:
            return None
        if parsed.hostname in {"www.bilibili.com", "bilibili.com"}:
            path = re.fullmatch(r"/video/(BV[0-9A-Za-z]{10}|av[1-9][0-9]{0,19})/?", parsed.path)
            pairs = parse_qsl(parsed.query, keep_blank_values=True)
            if path and (not pairs or len(pairs) == 1 and pairs[0][0] == "p"
                         and re.fullmatch(r"[1-9][0-9]{0,5}", pairs[0][1])):
                return "bilibili", path[1], pairs[0][1] if pairs else None
            return None
        mooc = course_identity_parts(normalized)
        if mooc:
            return "icourse163", mooc["course_id"], mooc["term_id"]
        if parsed.hostname in {"www.xuetangx.com", "xuetangx.com"} and not parsed.query:
            match = re.fullmatch(r"/course/([A-Za-z0-9_-]{1,160})/?", parsed.path)
            if match:
                return "xuetangx", match[1]
    except (UnsafeURL, TypeError, ValueError):
        pass
    return None


def _text(value) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def _native_field(metadata: dict, field: str, identity: tuple, limit: int):
    """Require a same-resource original field and its matching page evidence."""
    value = metadata.get(field)
    provenance = metadata.get("field_provenance")
    origin = provenance.get(field) if isinstance(provenance, dict) else None
    if not isinstance(value, str) or not value.strip() or len(value) > limit or not isinstance(origin, dict):
        return None
    source = origin.get("source")
    if (not isinstance(source, str) or re.search(r"search|snippet|discovery|page_link", source, re.I)
            or not (source in _NATIVE_GENERIC_FIELDS or source.startswith("html." + identity[0] + "."))
            or _identity(origin.get("url")) != identity or not origin.get("evidence_id")):
        return None
    for evidence in metadata.get("evidence", []):
        if (not isinstance(evidence, dict) or evidence.get("kind") != "page"
                or evidence.get("field") != field or evidence.get("source") != source
                or evidence.get("evidence_id") != origin["evidence_id"]
                or _identity(evidence.get("url")) != identity
                or _text(evidence.get("text")) != _text(value)):
            continue
        observed = metadata.get("fetched_at")
        if observed and any(row.get("fetched_at") not in {None, observed} for row in (origin, evidence)):
            continue
        return _text(value), {**deepcopy(origin), "evidence": deepcopy(evidence)}
    return None


def _specific_title(title: str) -> bool:
    remaining = _GENERIC_ONLY.sub("", title.casefold())
    # Strip the decorative punctuation/kana in generic Bilibili shell titles.
    return bool(re.search(r"[a-z0-9\u4e00-\u9fff]", remaining))


def _reject(reason: str) -> dict:
    return {"status": "rejected", "reason": reason, "candidate": None, "provenance": None}


def ground_ai_video_metadata(suggestion: dict, metadata: dict, *, preferred_platforms: Sequence[str]) -> dict:
    """Project only independently observed native facts from a direct AI URL.

The returned candidate can describe a game or a coffee vlog. That factual
acceptance must not be mistaken for relevance to the requested learning point.
"""
    url = direct_video_url(suggestion.get("url") if isinstance(suggestion, dict) else None, preferred_platforms)
    identity = _identity(url)
    if not url or not identity:
        return _reject("invalid_direct_url")
    if not isinstance(metadata, dict):
        return _reject("invalid_metadata")
    status = metadata.get("fetch_status")
    if status != "fetched":
        known = {"captcha", "access_denied", "login_required", "not_found", "error_page", "javascript_required",
                 "timeout", "http_error", "unsafe_url", "unsupported_content", "rate_limited", "budget_limited"}
        return _reject(status if status in known else "fetch_not_verified")
    if metadata.get("requires_login") is True:
        return _reject("login_required")
    if metadata.get("requires_payment") is True:
        return _reject("explicitly_paid")
    if metadata.get("stale") or isinstance(metadata.get("cache"), dict) and metadata["cache"].get("stale"):
        return _reject("stale_metadata")
    if not metadata.get("resolved_url"):
        return _reject("missing_resolved_identity")
    for key in ("url", "canonical_url", "resolved_url"):
        if metadata.get(key) and _identity(metadata[key]) != identity:
            return _reject("resource_identity_mismatch")
    evidence = metadata.get("evidence")
    if not isinstance(evidence, list):
        return _reject("missing_native_evidence")
    fields = metadata.get("field_provenance") or {}
    if not isinstance(fields, dict):
        return _reject("missing_native_evidence")
    if identity[0] == "bilibili":
        media_origin = fields.get("video_evidence_status") or {}
        if (not isinstance(media_origin, dict) or media_origin.get("source") not in _BILI_NATIVE_IDENTITIES
                or not _bound_page_video(metadata, evidence)):
            return _reject("native_identity_unconfirmed")
    elif identity[0] == "icourse163":
        if not bound_native_course_identity(metadata, evidence):
            return _reject("native_identity_unconfirmed")
    else:
        # The current extractor has no same-course Xuetang identity adapter.
        # A generic Course JSON-LD node may describe a related recommendation.
        return _reject("native_identity_unconfirmed")
    title = _native_field(metadata, "title", identity, 600)
    if not title:
        return _reject("native_title_unconfirmed")
    if not _specific_title(title[0]):
        return _reject("generic_page_title")
    description = _native_field(metadata, "description", identity, 4000)
    image = _native_field(metadata, "thumbnail_url", identity, 2048)
    cover = safe_thumbnail_url(image[0], url) if image else None
    media_origin = fields["video_evidence_status"] if identity[0] == "bilibili" else fields["resource_type"]
    media_evidence = next(row for row in evidence if isinstance(row, dict)
                          and row.get("evidence_id") == media_origin["evidence_id"]
                          and row.get("kind") == "page")
    provenance = {"identity": list(identity), "source_url": metadata["resolved_url"],
                  "observed_at": metadata.get("fetched_at"), "title": title[1],
                  "media_identity": {**deepcopy(media_origin), "evidence": deepcopy(media_evidence)}}
    if description:
        provenance["description"] = description[1]
    if image and cover:
        provenance["thumbnail_url"] = image[1]
    candidate = {"id": "ai_native_" + hashlib.sha256(str(identity).encode()).hexdigest()[:24],
                 "title": title[0], "url": url, "snippet": description[0] if description else "",
                 "thumbnail_url": cover, "source": "ai_native_verified", "query": "",
                 "discovered_at": metadata.get("fetched_at"),
                 "requires_payment": False if metadata.get("requires_payment") is False else None,
                 "platform": platform_for_url(url), "video_evidence_status": "native_page_observed"}
    return {"status": "accepted", "reason": "native_metadata_verified", "candidate": candidate,
            "provenance": provenance}


async def fetch_ai_video_identity(suggestion: dict, *, fetcher, preferred_platforms: Sequence[str],
                                  timeout_seconds: float,
                                  catalog_budget_hook: Callable[[], Awaitable[bool]] | None = None) -> dict:
    """Use an injected policy-aware Fetcher under a bounded caller-owned budget.

The optional hook can admit the fetcher's one same-video locale request. The
caller should only supply it for Bilibili; MOOC chapter-page traversal is not
needed for title/description identity and is deliberately disabled here.
"""
    url = direct_video_url(suggestion.get("url") if isinstance(suggestion, dict) else None, preferred_platforms)
    if not url:
        return _reject("invalid_direct_url")
    if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds) or timeout_seconds <= 0):
        return _reject("invalid_timeout")
    fetch_url = url
    if platform_for_url(url) == "bilibili":
        # The native video route redirects its slashless form. Avoid that
        # redundant request without changing the suggested card URL, selected
        # part, or the strict original-video identity checks below.
        parts = urlsplit(url)
        fetch_url = urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/") + "/",
                               parts.query, parts.fragment))
    try:
        async with asyncio.timeout(timeout_seconds):
            metadata = await fetcher.enrich({"url": fetch_url},
                catalog_budget_hook=catalog_budget_hook if platform_for_url(url) == "bilibili" else None)
    except TimeoutError:
        return _reject("timeout")
    except Exception as exc:
        result = _reject("fetch_failed")
        result["error_type"] = type(exc).__name__
        return result
    return ground_ai_video_metadata(suggestion, metadata, preferred_platforms=preferred_platforms)
