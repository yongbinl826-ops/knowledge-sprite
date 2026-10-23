"""Explicit offline flat proposals; retained historical fixtures are never rewritten."""
from copy import deepcopy
import json

import httpx

from backend.app.project_analysis import ProjectAnalyzer, generation_schema, SYSTEM_PROMPT, NORMALIZATION_PROMPT
from backend.app.project_analysis import GeneratedConceptList


def flat_proposal(raw):
    """Build a NEW mock response from history, preserving meaning in description.

    Only call this at a fixture boundary. Invalid model-output tests must send
    their supplied fields unchanged so deprecated fields cannot pass by projection.
    """
    proposal = {key: deepcopy(raw[key]) for key in ("scope", "technical_plan", "assumptions")}
    proposal["knowledge_points"] = []
    for point in raw["knowledge_points"]:
        parts = []
        for key in ("description", "learning_goal", "why_needed"):
            value = point.get(key)
            if value and value not in parts:
                parts.append(value)
        concept = {"name": point["name"], "description": "；".join(parts)}
        if "technology" in point:
            concept["technology"] = point["technology"]
        proposal["knowledge_points"].append(concept)
    return proposal


def assert_v1_projection(result, raw):
    """Compatibility helper name; assert the new public concept-list result."""
    proposal = flat_proposal(raw)
    expected = {**proposal, "analysis_format": "concept_list_v1"}
    expected["knowledge_points"] = [
        {"id": f"k{index}", **point, "technology": point.get("technology", ""), "selection": "learn"}
        for index, point in enumerate(proposal["knowledge_points"], 1)
    ]
    assert result.model_dump() == expected


def concept_proposal(raw, names):
    """Explicit mock-only names; retained raw fixtures and all other fields stay intact."""
    assert set(names) == {point["id"] for point in raw["knowledge_points"]}
    proposal = deepcopy(raw)
    for point in proposal["knowledge_points"]:
        point["name"] = names[point["id"]]
    return proposal


async def projected_once(raw, project, configured, *, concept_names=None):
    """Keep the historical helper name while exercising both bounded stages."""
    from tests.test_project_analysis import response
    before = deepcopy(raw)
    proposal = flat_proposal(concept_proposal(raw, concept_names) if concept_names is not None else raw)
    calls = []

    def respond(req):
        calls.append(json.loads(req.content))
        assert len(calls) <= 2, "Generation and normalization must share the existing two-call limit"
        return response(proposal)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await ProjectAnalyzer(configured, client).analyze(project)
    assert raw == before
    assert_v1_projection(result, proposal)
    payload = json.loads(calls[0]["messages"][1]["content"])
    assert payload["project"] == project.model_dump()
    assert payload["output_schema"] == generation_schema()
    assert "validation_feedback" not in payload
    assert len(calls) == 2
    normalized = json.loads(calls[1]["messages"][1]["content"])
    assert normalized["project"] == project.model_dump()
    assert normalized["output_schema"] == generation_schema()
    assert normalized["normalization_required"] is True
    assert normalized["previous_analysis"] == GeneratedConceptList.model_validate(proposal).model_dump()
    assert not normalized.get("validation_feedback")
    assert calls[0]["messages"][0]["content"] == SYSTEM_PROMPT
    assert calls[1]["messages"][0]["content"] == NORMALIZATION_PROMPT
    assert [c["max_tokens"] for c in calls] == [6000, 12000]
    return result, calls


def assert_simple_generation_schema():
    schema = generation_schema()
    assert schema["additionalProperties"] is False
    assert "learner_profile" not in schema["properties"]
    assert set(schema["properties"]) == {"scope", "technical_plan", "assumptions", "knowledge_points"}
    point = schema["$defs"]["GeneratedConcept"]
    assert point["additionalProperties"] is False
    assert set(point["required"]) == {"name", "description"}
    assert set(point["properties"]) == {"name", "description", "technology"}
    assert not {"project_task", "concepts", "learning_skills", "practice_check"} & set(point["properties"])
    assert "technology" not in point["required"]
    assert point["properties"]["technology"]["maxLength"] == 48
    assert point["properties"]["technology"]["default"] == ""
