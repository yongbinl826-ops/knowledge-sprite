from __future__ import annotations
import re

from datetime import datetime, timezone
import json
from typing import Annotated, Literal
import unicodedata
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator
from .url_utils import safe_thumbnail_url


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


MAX_LEARNING_TARGETS_PER_POINT = 8
MAX_LEARNING_TARGET_CHARS = 120
MAX_LEARNING_TARGET_BYTES = 20_000
LearningTarget = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=MAX_LEARNING_TARGET_CHARS)]
LearningTargetList = Annotated[list[LearningTarget], Field(strict=True, min_length=1, max_length=MAX_LEARNING_TARGETS_PER_POINT)]
LearningSkillList = Annotated[list[LearningTarget], Field(strict=True, min_length=1, max_length=6)]


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
    # Confirmed, per-unit requirements, never evidence of external teaching.
    # Empty defaults preserve manual requests and persisted pre-contract jobs.
    learning_targets: dict[str, LearningTargetList] = Field(default_factory=dict, max_length=5)
    # Transferable teaching goals are distinct from the project's exact practice
    # requirements. Older/manual jobs may omit them without being rewritten.
    learning_skills: dict[str, LearningSkillList] = Field(default_factory=dict, max_length=5)

    @field_validator("knowledge_points")
    @classmethod
    def clean_points(cls, values: list[str]) -> list[str]:
        cleaned = list(dict.fromkeys(" ".join(v.split()) for v in values))
        if any(not v or len(v) > 160 for v in cleaned):
            raise ValueError("知识点不能为空且不得超过160字符")
        return cleaned

    @model_validator(mode="after")
    def bound_learning_targets(self):
        if not (set(self.learning_targets) | set(self.learning_skills)) <= set(self.knowledge_points):
            raise ValueError("学习目标必须绑定当前知识点的确切名称")
        for point, targets in [*self.learning_targets.items(), *self.learning_skills.items()]:
            if any(unicodedata.category(character) in {"Cc", "Cf", "Cs"} for character in point):
                raise ValueError("学习目标名称不得包含控制字符")
            normalized = []
            for text in targets:
                if not text.strip() or any(unicodedata.category(character) in {"Cc", "Cf", "Cs"} for character in text):
                    raise ValueError("学习目标不能为空或包含控制字符")
                normalized.append(" ".join(unicodedata.normalize("NFKC", text).casefold().split()))
            if len(normalized) != len(set(normalized)):
                raise ValueError("同一知识点的学习目标不得重复")
        if len(json.dumps(self.learning_targets, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > MAX_LEARNING_TARGET_BYTES:
            raise ValueError("学习目标总 UTF-8 大小超过限制")
        if len(json.dumps(self.learning_skills, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > MAX_LEARNING_TARGET_BYTES:
            raise ValueError("学习技能总 UTF-8 大小超过限制")
        if any(re.search(r"https?://|www\.|\b(?:site|filetype|inurl):", skill, re.I)
               for skills in self.learning_skills.values() for skill in skills):
            raise ValueError("学习技能应为技能名称，不得包含网址或搜索指令")
        return self


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
    discovery_evidence: dict | None = None
    thumbnail_url: str | None = None
    thumbnail_source: str | None = None

    @field_validator("thumbnail_url", mode="before")
    @classmethod
    def clean_thumbnail(cls, value):
        return safe_thumbnail_url(value)


class Query(BaseModel):
    knowledge_point_id: str
    query: str
    domain_filters: list[str] = Field(default_factory=list)


class CourseIdentity(BaseModel):
    """Observed, source-scoped grouping; never global semantic course deduplication."""
    model_config = ConfigDict(extra="forbid")
    status: Literal["identified", "partial", "unknown"] = "unknown"
    family_id: str | None = None
    offering_id: str | None = None
    lesson_id: str | None = None
    family_url: str | None = None
    offering_url: str | None = None
    role: Literal["course", "catalog", "lesson", "video", "unknown"] = "unknown"
    basis: Literal["recognized_url", "page_course", "page_is_part_of", "unknown"] = "unknown"
    source_url: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    unknown_reason: str | None = "缺少可核对的同来源课程归属依据"


class TopicEvidenceReason(BaseModel):
    code: str
    message: str
    evidence_ids: list[str] = Field(default_factory=list)


class SubtopicCoverage(BaseModel):
    id: str
    text: str
    status: Literal["supported", "unknown"] = "unknown"
    evidence_ids: list[str] = Field(default_factory=list)
    reason: str = "当前资源自身的观察未证明这一子项"


class TopicEvidenceAssessment(BaseModel):
    """Topic support is independent of page access, playback and course identity."""
    topic_evidence_status: Literal["supported", "partial", "needs_review"]
    topic_evidence_reasons: list[TopicEvidenceReason] = Field(default_factory=list)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    subtopic_coverage: list[SubtopicCoverage] = Field(default_factory=list)


class Resource(BaseModel):
    model_config = ConfigDict(extra="ignore")
    resource_id: str
    title: str
    url: str
    canonical_url: str
    resolved_url: str | None = None
    platform: str = "general"
    resource_type: Literal["video", "course", "playlist", "unknown"] = "unknown"
    video_evidence_status: Literal["search_discovered", "page_verified", "none"] = "none"
    author: str | None = None
    author_role: Literal["course_instructors", "video_instructors", "credited_creator"] | None = None
    parent_course_url: str | None = None
    course_identity: CourseIdentity = Field(default_factory=CourseIdentity)
    description: str | None = None
    video_topic_summary: str | None = Field(default=None, max_length=12000)
    thumbnail_url: str | None = None
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
    access_notice: str | None = None
    chapters: list = Field(default_factory=list)
    catalog_kind: str | None = None
    catalog_fetch_status: str | None = None
    render_diagnostics: dict | None = None
    field_provenance: dict = Field(default_factory=dict)
    cache: dict = Field(default_factory=lambda: {"hit": False, "cached_at": None, "stale": False})
    playback_verified: bool = False

    @field_validator("thumbnail_url", mode="before")
    @classmethod
    def clean_thumbnail(cls, value):
        return safe_thumbnail_url(value)
