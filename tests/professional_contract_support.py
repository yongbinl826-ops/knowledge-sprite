"""Offline checks for v1 projection; these do not certify plan semantics."""
from copy import deepcopy
import json

import httpx

from backend.app.project_analysis import ProjectAnalyzer, generation_schema
from backend.app.project_models import AnalysisDocument
from tests.test_project_analysis import response


def assert_v1_projection(result, raw):
    """Known historical fields stay safe to read, but are not new targets."""
    expected = AnalysisDocument.model_validate(raw)
    expected.learner_profile = None
    for point in expected.knowledge_points:
        point.project_task = None
        point.concepts = []
        point.learning_skills = []
        point.practice_check = None
    assert result.model_dump() == expected.model_dump()


async def projected_once(raw, project, configured):
    before = deepcopy(raw)
    calls = []

    def respond(req):
        calls.append(json.loads(req.content))
        assert len(calls) == 1, "A valid v1 proposal must not invoke a critic or expanded-field repair"
        return response(raw)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await ProjectAnalyzer(configured, client).analyze(project)
    assert raw == before
    assert_v1_projection(result, raw)
    payload = json.loads(calls[0]["messages"][1]["content"])
    assert payload["project"] == project.model_dump()
    assert payload["output_schema"] == generation_schema()
    assert "validation_feedback" not in payload
    assert [c["max_tokens"] for c in calls] == [6000]
    return result, calls


def assert_simple_generation_schema():
    schema = generation_schema()
    assert schema["additionalProperties"] is False
    assert "learner_profile" not in schema["properties"]
    point = schema["$defs"]["ProjectKnowledgePoint"]
    assert point["additionalProperties"] is False
    assert {"id", "name", "description", "function_ids", "why_needed", "learning_goal",
            "necessity", "prerequisite_ids", "learning_order"} <= set(point["required"])
    assert point["properties"]["selection"]["default"] == "learn"
    assert not {"project_task", "concepts", "learning_skills", "practice_check"} & set(point["properties"])
    assert "technology" not in point["required"]
    assert point["properties"]["technology"]["maxLength"] == 80
    assert point["properties"]["technology"]["default"] == ""
