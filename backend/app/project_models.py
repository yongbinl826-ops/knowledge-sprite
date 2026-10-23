"""Project identities are version-scoped and distinct from search-job points."""
from __future__ import annotations

import re
import unicodedata
from typing import Annotated, ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_serializer, model_validator
from .professional_concepts import concept_name_issues, clean_topic_technology


MAX_PROJECT_FUNCTIONS = 12
MAX_PROJECT_KNOWLEDGE_POINTS = 24
MAX_PROJECT_REQUIREMENT_CHARS = 8000
Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")]
Selection = Literal["learn", "mastered", "skip"]
ReviewedTopicTechnologies = Annotated[dict[str, Annotated[str, StringConstraints(strict=True, min_length=1, max_length=48)]],
    Field(strict=True, max_length=MAX_PROJECT_KNOWLEDGE_POINTS)]


def normalized_name(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _has_url(value: str) -> bool:
    # Model analysis describes learning needs; links and chapter objects only
    # originate from the independently verified discovery pipeline. A bare
    # dotted technology name (ASP.NET, Socket.IO) is not itself a course URL.
    if re.search(r"[a-z][a-z0-9+.-]*://|www\.", value, re.I):
        return True
    for match in re.finditer(r"\b(?P<host>(?:[a-z0-9-]+\.)+(?:com|org|net|edu|cn|io|dev))\b(?P<path>[/\?])?", value, re.I):
        if match.group("host").casefold() in {"asp.net", "socket.io"} and not match.group("path"):
            continue
        return True
    return False


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ProjectInput(StrictModel):
    name: str = Field(min_length=1, max_length=160)
    requirements: str = Field(min_length=1, max_length=MAX_PROJECT_REQUIREMENT_CHARS)
    student_level: Literal["beginner", "intermediate", "advanced", "any"] = "beginner"
    language: Literal["zh", "en", "any"] = "zh"
    project_context: str = Field(default="", max_length=1000)
    technical_version: str = Field(default="", max_length=100)
    preferred_platforms: list[Literal["bilibili", "icourse163", "xuetangx"]] = Field(
        default_factory=lambda: ["bilibili", "icourse163", "xuetangx"], max_length=3
    )

    @field_validator("name", "requirements")
    @classmethod
    def nonempty_original(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("项目名称和功能需求不能为空")
        # Preserve the student's exact input, including line breaks and spaces.
        return value

    @field_validator("preferred_platforms")
    @classmethod
    def unique_platforms(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("平台偏好不能重复")
        return values


class AnalysisTextModel(StrictModel):
    allow_empty_analysis_fields: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="after")
    def safe_analysis_text(self) -> Self:
        for field, value in self.__dict__.items():
            if field in self.allow_empty_analysis_fields and value == "":
                continue
            strings = [value] if isinstance(value, str) else value if isinstance(value, list) else []
            for text in strings:
                if isinstance(text, str) and (not text.strip() or _has_url(text)):
                    raise ValueError("分析字段不能为空，且不得包含网址")
        return self


class ProjectFunction(AnalysisTextModel):
    id: Identifier
    name: str = Field(min_length=1, max_length=160)
    original_requirement: str = Field(min_length=1, max_length=1600)
    acceptance_criteria: str = Field(min_length=1, max_length=1000)
    no_new_learning_reason: str | None = Field(default=None, min_length=1, max_length=500)


class ProjectKnowledgePoint(AnalysisTextModel):
    allow_empty_analysis_fields: ClassVar[frozenset[str]] = frozenset({"technology", "why_needed", "learning_goal"})

    id: Identifier
    name: str = Field(min_length=1, max_length=160, description="One independently learnable professional concept; no project story, implementation checklist or chapter label.")
    description: str = Field(min_length=1, max_length=800)
    function_ids: list[Identifier] = Field(default_factory=list, max_length=MAX_PROJECT_FUNCTIONS)
    why_needed: str = Field(default="", min_length=1, max_length=800)
    learning_goal: str = Field(default="", min_length=1, max_length=800)
    # This is a student-editable retrieval target, never proof that a video
    # covers the selected tool. Both historical and newly generated points may
    # omit this optional field; omission does not invent a tool selection.
    technology: str = Field(default="", max_length=80, description="The specific language, tool or framework for this unit; empty only for a genuinely general concept. A retrieval target, not video coverage evidence.")
    # Optional defaults keep expanded historical analyses and student edits
    # readable. New professional-term generation does not request these fields;
    # reading history never fabricates missing details or migrates stored data.
    project_task: str | None = Field(default=None, min_length=1, max_length=800)
    concepts: list[Annotated[str, StringConstraints(min_length=1, max_length=120)]] = Field(default_factory=list, max_length=8)
    # Reusable teaching goals are separate from project-specific implementation
    # details and acceptance checks. Saved analyses do not acquire invented goals.
    learning_skills: list[Annotated[str, StringConstraints(min_length=1, max_length=120)]] = Field(
        default_factory=list, max_length=6,
        description="Specific transferable skills for teaching-material discovery; not project acceptance criteria or evidence that a source teaches them.",
    )
    practice_check: str | None = Field(default=None, min_length=1, max_length=800)
    necessity: Literal["required", "extension"] = "required"
    prerequisite_ids: list[Identifier] = Field(default_factory=list, max_length=MAX_PROJECT_KNOWLEDGE_POINTS - 1)
    learning_order: int | None = Field(default=None, ge=1, le=MAX_PROJECT_KNOWLEDGE_POINTS)
    selection: Selection = "learn"


    @field_validator("function_ids", "prerequisite_ids")
    @classmethod
    def unique_references(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("引用 ID 不能重复")
        return values

    @field_validator("concepts")
    @classmethod
    def unique_concepts(cls, values: list[str]) -> list[str]:
        if len({normalized_name(value) for value in values}) != len(values):
            raise ValueError("Concepts must be distinct within a learning unit")
        return values

    @field_validator("learning_skills")
    @classmethod
    def safe_distinct_learning_skills(cls, values: list[str]) -> list[str]:
        if any(re.search(r"[\x00-\x1f\x7f]", value) for value in values):
            raise ValueError("Learning skills must not contain control characters")
        if len({normalized_name(value) for value in values}) != len(values):
            raise ValueError("Learning skills must be distinct within a learning unit")
        return values


class LearnerProfile(AnalysisTextModel):
    student_level: Literal["beginner", "intermediate", "advanced", "any"]
    assumed_knowledge: list[Annotated[str, StringConstraints(min_length=1, max_length=300)]] = Field(min_length=1, max_length=6)
    adjustment_note: str = Field(min_length=1, max_length=500)


class AnalysisDocument(AnalysisTextModel):
    analysis_format: Literal["concept_list_v1"] | None = None
    scope: str = Field(min_length=1, max_length=1600)
    technical_plan: str = Field(min_length=1, max_length=2000)
    assumptions: list[Annotated[str, StringConstraints(min_length=1, max_length=500)]] = Field(max_length=8)
    learner_profile: LearnerProfile | None = None
    functions: list[ProjectFunction] = Field(default_factory=list, max_length=MAX_PROJECT_FUNCTIONS)
    knowledge_points: list[ProjectKnowledgePoint] = Field(max_length=MAX_PROJECT_KNOWLEDGE_POINTS)

    @model_serializer(mode="wrap")
    def serialize_analysis(self, handler):
        data = handler(self)
        if self.analysis_format != "concept_list_v1":
            # Existing analyses retain their original public shape. Reading or
            # editing history never adds a format marker or migrates its graph.
            data.pop("analysis_format", None)
            return data
        allowed = {"scope", "technical_plan", "assumptions", "analysis_format", "knowledge_points"}
        data = {key: value for key, value in data.items() if key in allowed}
        if "knowledge_points" in data:
            fields = {"id", "name", "description", "technology", "selection"}
            data["knowledge_points"] = [{key: value for key, value in point.items() if key in fields}
                                        for point in data["knowledge_points"]]
        return data

    def professional_concept_issues(self) -> list[dict]:
        """Explicit new-generation boundary; historical parsing stays compatible."""
        issues = []
        for index, point in enumerate(self.knowledge_points):
            for code, message in concept_name_issues(point.name):
                issues.append({"code": code, "point_id": point.id,
                    "location": ["knowledge_points", index, "name"], "message": message})
            try:
                clean_topic_technology(point.technology)
            except ValueError:
                issues.append({"code": "invalid_topic_technology", "point_id": point.id,
                    "location": ["knowledge_points", index, "technology"],
                    "message": "Use only the actual short language/tool name; no instructions, URLs or project details."})
        return issues[:24]


    @model_validator(mode="after")
    def check_project_graph(self) -> Self:
        function_ids = [function.id for function in self.functions]
        point_ids = [point.id for point in self.knowledge_points]
        if len(function_ids) != len(set(function_ids)):
            raise ValueError("功能 ID 必须唯一")
        if len(point_ids) != len(set(point_ids)):
            raise ValueError("知识点 ID 必须唯一")
        names = [normalized_name(point.name) for point in self.knowledge_points]
        if len(names) != len(set(names)):
            raise ValueError("知识点名称不能重复；多个功能应共享同一知识点")
        if self.analysis_format == "concept_list_v1":
            if self.functions or self.learner_profile is not None:
                raise ValueError("简明知识点分析不包含功能图或学习者画像")
            allowed = {"id", "name", "description", "technology", "selection"}
            if any(point.model_fields_set - allowed for point in self.knowledge_points):
                raise ValueError("简明知识点只包含名称、说明、技术背景和系统维护的标识与选择")
            return self
        if not self.functions:
            raise ValueError("历史项目分析必须保留功能列表")
        functions, points = set(function_ids), {point.id: point for point in self.knowledge_points}
        covered_functions: set[str] = set()
        for point in self.knowledge_points:
            if not set(point.function_ids) <= functions:
                raise ValueError("知识点引用了不存在的功能")
            if not set(point.prerequisite_ids) <= points.keys():
                raise ValueError("前置知识点引用不存在")
            if point.id in point.prerequisite_ids:
                raise ValueError("知识点不能以前置关系引用自身")
            covered_functions.update(point.function_ids)

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(point_id: str) -> None:
            if point_id in visiting:
                raise ValueError("前置知识点不能形成循环")
            if point_id in visited:
                return
            visiting.add(point_id)
            for prerequisite_id in points[point_id].prerequisite_ids:
                visit(prerequisite_id)
            visiting.remove(point_id)
            visited.add(point_id)

        for point_id in points:
            visit(point_id)
        # Retained for historical compatibility and stable system presentation.
        # The student selects concepts, not their learning order. Click order
        # neither rewrites this field nor creates a hidden prerequisite gate.
        for function in self.functions:
            if function.id not in covered_functions and not function.no_new_learning_reason:
                raise ValueError("每个功能必须关联知识点，或明确说明不需要新增学习的原因")

        # A point without a direct feature use must actually lead to a point
        # that implements a feature; an isolated chain of prerequisites fails.
        useful: set[str] = set()

        def mark_useful(point_id: str) -> None:
            if point_id in useful:
                return
            useful.add(point_id)
            for prerequisite_id in points[point_id].prerequisite_ids:
                mark_useful(prerequisite_id)

        for point in self.knowledge_points:
            if point.function_ids:
                mark_useful(point.id)
        if set(point_ids) - useful:
            raise ValueError("知识点必须服务于项目功能，或是其他功能知识点的必要前置")
        return self
