"""Strict public MOOC course routes, without inventing or rewriting aliases.

These routes admit anonymous metadata probes, never learning/media/API access.
The URL's course/term IDs must still be bound to the fetched page by extractors.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from .url_utils import UnsafeURL, normalize_url

_HOSTS = {"www.icourse163.org", "icourse163.org"}
_SLUG = re.compile(r"/course/(?:[A-Za-z0-9_][A-Za-z0-9_-]{0,127})?-([0-9]{1,20})/?")
_NUMBER = re.compile(r"[0-9]{1,20}")
_VENDOR = re.compile(r"[A-Za-z0-9_-]{1,128}")


def _course_route(value):
    if not isinstance(value, str) or value != value.strip():
        return None
    try:
        normalized = normalize_url(value)
        parts = urlsplit(value)
        if (parts.scheme != "https" or parts.hostname not in _HOSTS
                or parts.port not in {None, 443} or parts.fragment
                or parts.username is not None or parts.password is not None):
            return None
        slug = _SLUG.fullmatch(parts.path)
        detail = parts.path == "/course/detail.htm"
        if not slug and not detail:
            return None
        # Validate raw components before generic URL normalization can remove
        # tracking fields. Unknown, duplicated and encoded keys are not scope.
        query = {}
        for component in parts.query.split("&") if parts.query else []:
            key, separator, item = component.partition("=")
            if not separator or key in query or key not in {"cid", "tid", "outVendor"}:
                return None
            if not (_VENDOR.fullmatch(item) if key == "outVendor" else _NUMBER.fullmatch(item)):
                return None
            query[key] = item
        if detail and "cid" not in query or slug and "cid" in query:
            return None
        return normalized, {"course_id": query["cid"] if detail else slug[1],
                            "term_id": query.get("tid")}
    except (UnsafeURL, TypeError, ValueError):
        return None


def public_course_url(value: str) -> str | None:
    """Return the same accepted public URL; do not manufacture a slug alias."""
    parsed = _course_route(value)
    return parsed[0] if parsed else None


def course_identity_parts(value: str) -> dict[str, str | None] | None:
    """Return explicit numeric course/term IDs, not inferred page identity."""
    parsed = _course_route(value)
    return parsed[1] if parsed else None
