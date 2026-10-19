"""Static source adapters return facts; the extractor owns provenance and policy."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from bs4 import BeautifulSoup


def clean_text(value: Any, limit: int = 4000) -> str | None:
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())[:limit]
    return value or None


@dataclass(frozen=True)
class FieldFact:
    field: str
    value: Any
    source: str
    excerpt: str | None = None


@dataclass
class SourceFacts:
    fields: list[FieldFact] = field(default_factory=list)
    chapters: list[dict] = field(default_factory=list)
    catalog_source: str | None = None
    catalog_kind: str | None = None
    catalog_followup: dict | None = None


class SourceAdapter(Protocol):
    name: str

    def matches(self, url: str) -> bool: ...

    def extract(self, soup: BeautifulSoup, url: str) -> SourceFacts: ...
