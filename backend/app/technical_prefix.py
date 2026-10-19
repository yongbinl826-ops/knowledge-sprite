"""Exact leading technical identifiers at whitespace or ASCII→CJK boundaries.

This grammar never maps a prefix/suffix/foreign namespace to a known library.
Normalization is for canonical project search names, not student display text.
"""
from __future__ import annotations

import re


_LEADING = re.compile(r"^\s*(?P<owner>[A-Za-z][A-Za-z0-9_.+#-]*)(?P<separator>\s+|(?=[\u4e00-\u9fff]))(?P<body>.*)$")


def leading_technical_owner(text: str) -> str | None:
    match = _LEADING.fullmatch(text) if isinstance(text, str) else None
    return match["owner"] if match else None


def canonical_search_name(text: str) -> str:
    value = " ".join(text.split())
    match = _LEADING.fullmatch(value)
    if match and not match["separator"]:
        value = match["owner"] + " " + match["body"]
    return value
