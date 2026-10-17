from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    knowledge_points: list[str] = Field(min_length=1, max_length=5)
    student_level: Literal["beginner", "intermediate", "advanced", "any"] = "beginner"
    language: Literal["zh", "en", "any"] = "zh"
    project_context: str = Field(default="", max_length=1000)
    technical_version: str = Field(default="", max_length=100)
    preferred_platforms: list[Literal["bilibili", "icourse163", "xuetangx"]] = Field(
        default_factory=lambda: ["bilibili", "icourse163", "xuetangx"], max_length=3
    )

    @field_validator("knowledge_points")
    @classmethod
    def clean_points(cls, values: list[str]) -> list[str]:
        cleaned = list(dict.fromkeys(" ".join(v.split()) for v in values))
        if any(not v or len(v) > 160 for v in cleaned):
            raise ValueError("知识点不能为空且不得超过160字符")
        return cleaned


class Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    url: str
    snippet: str = ""
    source: str
    query: str
    discovered_at: str = Field(default_factory=now)
    resource_type_hint: Literal["video", "course", "playlist", "unknown"] = "unknown"
    source_engines: list[str] = Field(default_factory=list)
    type_source: str | None = None


class Query(BaseModel):
    knowledge_point_id: str
    query: str
    domain_filters: list[str] = Field(default_factory=list)


class Resource(BaseModel):
    model_config = ConfigDict(extra="ignore")
    resource_id: str
    title: str
    url: str
    canonical_url: str
    platform: str = "general"
    resource_type: Literal["video", "course", "playlist", "unknown"] = "unknown"
    video_evidence_status: Literal["search_discovered", "page_verified", "none"] = "none"
    author: str | None = None
    description: str | None = None
    language: str | None = None
    duration_seconds: int | None = None
    published_at: str | None = None
    discovered_at: str
    fetched_at: str | None = None
    fetch_status: str = "not_fetched"
    metadata_evidence_level: Literal["search", "page", "catalog"] = "search"
    requires_login: bool | None = None
    requires_payment: bool | None = None
    requires_enrollment: bool | None = None
    chapters: list = Field(default_factory=list)
    catalog_kind: str | None = None
    catalog_fetch_status: str | None = None
    field_provenance: dict = Field(default_factory=dict)
    cache: dict = Field(default_factory=lambda: {"hit": False, "cached_at": None, "stale": False})
    playback_verified: bool = False
