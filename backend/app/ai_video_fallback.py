"""Bounded, untrusted discovery hints; only real sources can establish facts.

This module performs no network access and does not create search/page evidence.
Connect-time DNS and redirect checks remain the fetcher's responsibility.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from urllib.parse import parse_qsl, urlsplit

from pydantic import BaseModel, ConfigDict, Field

from .mooc_urls import course_identity_parts, public_course_url
from .url_utils import UnsafeURL, normalize_url, platform_for_url


MAX_VIDEO_HINT_POINTS = 5
MAX_VIDEO_HINTS_PER_POINT = 3
MAX_VIDEO_SEARCH_HINTS_PER_POINT = 2
VIDEO_HINT_TIMEOUT_SECONDS = 20
SUPPORTED_VIDEO_PLATFORMS = frozenset({"bilibili", "icourse163", "xuetangx"})


class VideoURLHint(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    point_id: str = Field(min_length=1, max_length=20)
    urls: list[str] = Field(max_length=MAX_VIDEO_HINTS_PER_POINT)


class VideoURLSuggestions(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    suggestions: list[VideoURLHint] = Field(max_length=MAX_VIDEO_HINT_POINTS)


class VideoDiscoveryHint(VideoURLHint):
    # An older compatible provider may omit queries. A missing field creates
    # no invented phrase and retains the previous direct-URL contract.
    queries: list[str] = Field(default_factory=list, max_length=MAX_VIDEO_SEARCH_HINTS_PER_POINT)


class VideoDiscoverySuggestions(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    suggestions: list[VideoDiscoveryHint] = Field(max_length=MAX_VIDEO_HINT_POINTS)


def normalize_empty_api_calls(value: str) -> str:
    """Drop only empty call notation in a search copy, retaining its API name.

    Arguments, nested calls and control characters are not rewritten. This is
    plain query text normalization; no expression is parsed or executed.
    """
    return re.sub(r"(?<=[A-Za-z0-9_])\([ ]*\)(?![A-Za-z0-9_()])", "", value)


def video_search_phrase(value: str) -> str | None:
    """Keep bounded plain search text, never model-provided engine operators.

    A course name here is merely a query lead. It must never be copied into
    resource titles, matching targets or source evidence as a factual claim.
    """
    if (not isinstance(value, str) or len(value) > 160
            or re.search(r"[\x00-\x1f\x7f]", value)):
        return None
    phrase = " ".join(normalize_empty_api_calls(value).split())
    if (not 2 <= len(phrase) <= 80
            or re.search(r"https?://|www\.|\b[\w-]+\.(?:com|org|net|cn|io)\b|"
                         r"[/\\<>:!@=\"();|`$]|(?:^|\s)-\S", phrase, re.I)):
        return None
    return phrase


def direct_video_url(value: str, preferred_platforms: Sequence[str]) -> str | None:
    """Accept only known public video/course entry routes on requested platforms.

    Acceptance is a URL syntax check, never confirmation that a resource exists,
    can play, or teaches the requested material. Shorteners and search pages are
    intentionally not direct resource entries.
    """
    if (not isinstance(value, str) or not value or len(value) > 2048
            or any(char.isspace() for char in value)):
        return None
    try:
        normalized = normalize_url(value)
        parts = urlsplit(normalized)
        if parts.scheme != "https" or parts.port not in {None, 443} or parts.fragment:
            return None
        platform = platform_for_url(normalized)
        if platform not in SUPPORTED_VIDEO_PLATFORMS or platform not in preferred_platforms:
            return None
        if platform == "bilibili":
            if (parts.hostname not in {"bilibili.com", "www.bilibili.com"}
                    or not re.fullmatch(r"/video/(?:BV[0-9A-Za-z]{10}|av[1-9][0-9]{0,19})/?", parts.path)
                    or parts.query and not re.fullmatch(r"p=[1-9][0-9]{0,5}", parts.query)):
                return None
            return normalized
        if platform == "icourse163":
            return public_course_url(normalized)
        if (parts.hostname in {"xuetangx.com", "www.xuetangx.com"}
                and re.fullmatch(r"/course/[A-Za-z0-9_-]{1,160}/?", parts.path)
                and not parts.query):
            return normalized
    except (UnsafeURL, TypeError, ValueError):
        pass
    return None


def _url_identity(url: str) -> tuple:
    """Dedupe known aliases without rewriting the model's actual course URL."""
    parts = urlsplit(url)
    platform = platform_for_url(url)
    if platform == "icourse163":
        identity = course_identity_parts(url)
        if identity:
            return platform, identity["course_id"], identity["term_id"]
    return platform, parts.path.rstrip("/"), tuple(sorted(parse_qsl(parts.query)))


def normalize_video_suggestions(body: dict, points: list[str], preferred_platforms: Sequence[str], *,
                                excluded_urls: Sequence[str] = ()) -> dict[str, list[str]]:
    """Bind model IDs to exact requested points and discard unusable URL hints."""
    result, _ = normalize_video_suggestions_with_diagnostics(
        body, points, preferred_platforms, excluded_urls=excluded_urls)
    return result


def empty_video_discovery_diagnostics(point_count: int, *, requested: bool = True,
                                      include_queries: bool = False) -> dict:
    """Only fixed labels and bounded counts; never preserve model/user text."""
    if not 0 <= point_count <= MAX_VIDEO_HINT_POINTS:
        raise ValueError("Video diagnostic point count must be bounded")

    def rejections():
        return {"empty": 0, "invalid": 0, "duplicate": 0, "already_seen": 0}

    diagnostic = {
        "schema_version": 1,
        "status": "normalized" if requested else "not_requested",
        "requested_points": point_count,
        "returned_points": 0,
        "missing_points": point_count if requested else 0,
        "empty_url_points": 0,
        "input_urls": 0,
        "accepted_urls": 0,
        "rejected_urls": rejections(),
        "points": [{"point_index": index, "returned": False,
                    "url_state": "missing" if requested else "not_requested",
                    "input_urls": 0, "accepted_urls": 0,
                    "rejected_urls": rejections()} for index in range(point_count)],
    }

    if include_queries:
        diagnostic["query_normalization"] = _empty_query_diagnostics(point_count, requested=requested)
    return diagnostic


def _empty_query_diagnostics(point_count: int, *, requested: bool = True) -> dict:
    def rejections():
        return {"empty": 0, "invalid": 0, "duplicate": 0}

    return {"schema_version": 1, "status": "normalized" if requested else "not_requested",
        "requested_points": point_count, "returned_query_fields": 0,
        "missing_points": point_count if requested else 0, "missing_query_fields": 0,
        "empty_query_points": 0, "input_queries": 0, "accepted_queries": 0,
        "rejected_queries": rejections(),
        "points": [{"point_index": index, "query_state": "missing_point" if requested else "not_requested",
                    "input_queries": 0, "accepted_queries": 0, "rejected_queries": rejections()}
                   for index in range(point_count)]}


def normalize_video_suggestions_with_diagnostics(
    body: dict, points: list[str], preferred_platforms: Sequence[str], *,
    excluded_urls: Sequence[str] = (),
) -> tuple[dict[str, list[str]], dict]:
    """Normalize once and count mutually exclusive URL outcomes per input row.

    Missing rows and empty arrays are point outcomes, not rejected URL items.
    Already-seen identities take precedence over duplicates within this answer.
    Strict schema failures still raise; zero counts never stand in for an unread
    or invalid model response. Diagnostics contain no input strings or URLs.
    """
    if len(points) > MAX_VIDEO_HINT_POINTS or len(set(points)) != len(points):
        raise ValueError("Video suggestion points must be unique and bounded")
    parsed = VideoURLSuggestions.model_validate(body)
    known = {f"kp_{index}": point for index, point in enumerate(points)}
    if (len({row.point_id for row in parsed.suggestions}) != len(parsed.suggestions)
            or any(row.point_id not in known for row in parsed.suggestions)):
        raise ValueError("Unknown or duplicate video suggestion point IDs")
    excluded = {
        _url_identity(url) for value in excluded_urls
        if (url := direct_video_url(value, preferred_platforms)) is not None
    }
    result = {point: [] for point in points}
    diagnostic = empty_video_discovery_diagnostics(len(points))
    for row in parsed.suggestions:
        point_index = int(row.point_id.removeprefix("kp_"))
        counts = diagnostic["points"][point_index]
        counts.update(returned=True, input_urls=len(row.urls))
        diagnostic["returned_points"] += 1
        diagnostic["missing_points"] -= 1
        diagnostic["input_urls"] += len(row.urls)
        if not row.urls:
            diagnostic["empty_url_points"] += 1
        seen = set()
        for value in row.urls:
            url = direct_video_url(value, preferred_platforms)
            if url is None:
                reason = "empty" if not value.strip() else "invalid"
            elif (identity := _url_identity(url)) in excluded:
                reason = "already_seen"
            elif identity in seen:
                reason = "duplicate"
            else:
                result[known[row.point_id]].append(url)
                seen.add(identity)
                counts["accepted_urls"] += 1
                diagnostic["accepted_urls"] += 1
                continue
            counts["rejected_urls"][reason] += 1
            diagnostic["rejected_urls"][reason] += 1
        counts["url_state"] = ("empty" if not row.urls else
                               "accepted" if counts["accepted_urls"] else "filtered")
    return result, diagnostic


def normalize_video_discovery(body: dict, points: list[str], preferred_platforms: Sequence[str], *,
                              excluded_urls: Sequence[str] = ()) -> dict[str, dict[str, list[str]]]:
    """Bind query/URL leads to exact points without accepting model source facts."""
    result, _ = normalize_video_discovery_with_diagnostics(
        body, points, preferred_platforms, excluded_urls=excluded_urls)
    return result


def normalize_video_discovery_with_diagnostics(
    body: dict, points: list[str], preferred_platforms: Sequence[str], *,
    excluded_urls: Sequence[str] = (),
) -> tuple[dict[str, dict[str, list[str]]], dict]:
    """Return hints plus bounded URL and query outcomes, never response text."""
    parsed = VideoDiscoverySuggestions.model_validate(body)
    urls, diagnostic = normalize_video_suggestions_with_diagnostics({"suggestions": [
        {"point_id": row.point_id, "urls": row.urls} for row in parsed.suggestions
    ]}, points, preferred_platforms, excluded_urls=excluded_urls)
    result = {point: {"urls": values, "queries": []} for point, values in urls.items()}
    queries = diagnostic["query_normalization"] = _empty_query_diagnostics(len(points))
    for row in parsed.suggestions:
        index = int(row.point_id.removeprefix("kp_"))
        point = points[index]
        counts = queries["points"][index]
        queries["missing_points"] -= 1
        if "queries" not in row.model_fields_set:
            counts["query_state"] = "missing_field"
            queries["missing_query_fields"] += 1
            continue
        queries["returned_query_fields"] += 1
        counts["input_queries"] = len(row.queries)
        queries["input_queries"] += len(row.queries)
        if not row.queries:
            queries["empty_query_points"] += 1
        seen = set()
        for value in row.queries:
            phrase = video_search_phrase(value)
            if phrase is None:
                reason = "empty" if not value.strip() else "invalid"
            elif phrase.casefold() in seen:
                reason = "duplicate"
            else:
                result[point]["queries"].append(phrase)
                seen.add(phrase.casefold())
                counts["accepted_queries"] += 1
                queries["accepted_queries"] += 1
                continue
            counts["rejected_queries"][reason] += 1
            queries["rejected_queries"][reason] += 1
        counts["query_state"] = ("empty" if not row.queries else
                                 "accepted" if counts["accepted_queries"] else "filtered")
    return result, diagnostic


def video_recovery_required_literals(text: str) -> list[str]:
    """Ordered original-point literals; no model interpretation or expansion.

    The caller supplies its already validated, bounded original point. This is
    not an owner classifier: identifiers present in the original stay required,
    including ones also present in the separate declared technology field.
    Empty API call notation does not affect these identifier matches.
    """
    return list(dict.fromkeys(re.findall(
        r"(?<![A-Za-z0-9_.+#-])(?:\.?[A-Za-z][A-Za-z0-9_.+#]*(?:-[A-Za-z0-9_.+#]+)*"
        r"|\d+[A-Za-z][A-Za-z0-9_.+#-]*|\d+(?:\.\d+)*)(?![A-Za-z0-9_.+#-])", text)))
