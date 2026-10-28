"""Explicit offline flat proposals; retained historical fixtures are never rewritten."""
from copy import deepcopy
import json

import httpx

from backend.app.project_analysis import ProjectAnalyzer, generation_schema, semantic_review_settings, SYSTEM_PROMPT


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


def draft_with_inventory(proposal, project):
    """Synthetic mechanism inventory; no semantic or foundation-completeness claim."""
    original = project.model_dump() if hasattr(project, "model_dump") else project
    fields = [field for field in ("name", "requirements", "project_context", "technical_version")
              if original.get(field)]
    primary = "requirements" if "requirements" in fields else fields[0]
    mechanisms = [{"id": f"m{index + 1}", "source_field": primary,
                   "source_quote": original[primary][:1500], "mechanism": f"离线合成机制 {index + 1}",
                   "must_explain": str(point.get("description", "离线合成说明"))[:500] or "离线合成说明"}
                  for index, point in enumerate(proposal["knowledge_points"])]
    # Fixed IDs keep non-primary source references stable when a final mock merges points.
    mechanisms.extend({"id": f"m{101 + index}", "source_field": field,
                       "source_quote": original[field][:1500], "mechanism": "离线合成来源对应",
                       "must_explain": "只用于离线结构测试的来源引用，不证明语义覆盖。"}
                      for index, field in enumerate(fields) if field != primary)
    inventory = {"mechanisms": mechanisms, "foundation_checks": {
        field: {"applicable": False, "reason": "离线合成夹具明确不评估实际基础适用性。", "mechanism_ids": []}
        for field in ("data_representation", "data_transformation", "callable_contracts",
                      "control_flow", "resource_readiness", "lifecycle_changes")}}
    return {"inventory": inventory, "analysis": deepcopy(proposal)}


def coverage_completion(proposal, project, inventory=None):
    """Synthetic exact quotes; a supplied inventory preserves the first mock's IDs.

    Without one, include a reconstruction for invalid/absent-first-draft tests.
    Mapping/merging fixtures are not evidence that descriptions teach mechanisms.
    """
    frozen = deepcopy(inventory) if inventory is not None else draft_with_inventory(proposal, project)["inventory"]
    if hasattr(frozen, "model_dump"):
        frozen = frozen.model_dump()
    points = proposal["knowledge_points"]
    rows, mapped = [], set()
    for mechanism in frozen["mechanisms"]:
        ordinal = int(mechanism["id"][1:]) - 1
        index = min(ordinal, len(points) - 1) if ordinal < 100 else 0
        rows.append({"mechanism_id": mechanism["id"], "source_field": mechanism["source_field"],
                     "source_quote": mechanism["source_quote"], "mechanism": mechanism["mechanism"],
                     "taught_by": [{"point_index": index, "description_quote": points[index]["description"][:800]}]})
        mapped.add(index)
    for index in range(len(points)):
        if index not in mapped:
            source = frozen["mechanisms"][0]
            rows.append({"mechanism_id": "", "source_field": source["source_field"],
                         "source_quote": source["source_quote"], "mechanism": "离线合成补充机制",
                         "taught_by": [{"point_index": index, "description_quote": points[index]["description"][:800]}]})
    result = {"analysis": deepcopy(proposal), "coverage": rows, "unresolved": []}
    if inventory is None:
        result["reconstructed_inventory"] = frozen
    return result


def semantic_review_pass(analysis=None, inventory=None):
    """Synthetic exact-reference review, never evidence of semantic correctness.

    The no-argument form deliberately has no evidence and is only suitable for
    tests of incomplete reports. Successful orchestrator fixtures must supply
    the actual candidate and inventory from their review request.
    """
    if analysis is None and inventory is None:
        return {"passed": True, "issues": []}
    assert analysis is not None and inventory is not None
    if hasattr(analysis, "model_dump"):
        analysis = analysis.model_dump()
    if hasattr(inventory, "model_dump"):
        inventory = inventory.model_dump()
    points = analysis["knowledge_points"]
    checks = []
    for mechanism in inventory["mechanisms"]:
        ordinal = int(mechanism["id"][1:]) - 1
        index = min(ordinal, len(points) - 1) if ordinal < 100 else 0
        checks.append({
            "mechanism_id": mechanism["id"],
            "expected_contract": mechanism["must_explain"][:240],
            "location": ["knowledge_points", index, "description"],
            "description_quote": points[index]["description"][:400],
            "verdict": "covered", "issue_ids": [],
        })
    route_field = "technical_plan" if analysis.get("technical_plan") else "scope"
    return {"passed": True, "issues": [], "mechanism_checks": checks,
            "route_check": {"expected_contract": "离线结构夹具中的路径引用，不证明实际语义正确。",
                            "location": [route_field], "description_quote": analysis[route_field][:400],
                            "verdict": "covered", "issue_ids": []}}


def semantic_review_pass_for_payload(payload):
    """Use the exact final candidate of an explicitly passing review fixture."""
    return semantic_review_pass(payload["analysis"], payload["implementation_inventory"])


def is_semantic_review_payload(payload):
    properties = payload.get("output_schema", {}).get("properties", {})
    return "passed" in properties and "issues" in properties


def successful_analysis_response(payload, proposal, project):
    """Route an explicitly valid fixture by phase; never repairs invalid responses."""
    if payload.get("repair_format") == "name_patch":
        original = payload["previous_analysis"]["knowledge_points"]
        repaired = proposal["knowledge_points"]
        assert len(original) == len(repaired), "A name-only fixture cannot change point count"
        return {"name_repairs": [
            {"index": index, "original_name": original[index]["name"], "name": repaired[index]["name"]}
            for index in payload["allowed_indices"]
            if repaired[index]["name"] != original[index]["name"]
        ]}
    properties = payload.get("output_schema", {}).get("properties", {})
    if "knowledge_points" in properties:
        return deepcopy(proposal)
    if is_semantic_review_payload(payload):
        return semantic_review_pass_for_payload(payload)
    if "resolutions" in properties:
        raise AssertionError("A passing fixture must not request semantic correction")
    if "inventory" in properties:
        return draft_with_inventory(proposal, project)
    if "coverage" in properties:
        return coverage_completion(proposal, project, payload.get("implementation_inventory"))
    raise AssertionError("Unexpected analysis fixture phase")


def unchanged_quality_correction(payload):
    """Explicit negative fixture: leave known local-quality defects unrepaired."""
    assert "resolutions" in payload["output_schema"]["properties"]
    return {**coverage_completion(payload["previous_analysis"], payload["project"],
                                  payload["implementation_inventory"]), "resolutions": []}


def unrepaired_quality_response(payload, proposal, project):
    """Explicit negative fixture; leave local-quality defects unrepaired."""
    if payload.get("repair_format") == "name_patch":
        points = payload["previous_analysis"]["knowledge_points"]
        return {"name_repairs": [
            {"index": index, "original_name": points[index]["name"], "name": points[index]["name"]}
            for index in payload["required_indices"]
        ]}
    if "resolutions" in payload.get("output_schema", {}).get("properties", {}):
        return unchanged_quality_correction(payload)
    return successful_analysis_response(payload, proposal, project)


async def projected_once(raw, project, configured, *, concept_names=None):
    """Compact generation fixture; historical source objects stay untouched."""
    from tests.test_project_analysis import response
    before = deepcopy(raw)
    proposal = flat_proposal(concept_proposal(raw, concept_names) if concept_names is not None else raw)
    calls = []

    def respond(req):
        calls.append(json.loads(req.content))
        assert len(calls) == 1, "A valid flat proposal must not request extra rounds"
        payload = json.loads(calls[-1]["messages"][1]["content"])
        return response(successful_analysis_response(payload, proposal, project))

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await ProjectAnalyzer(configured, client).analyze(project)
    assert raw == before
    assert_v1_projection(result, proposal)
    payload = json.loads(calls[0]["messages"][1]["content"])
    assert payload["project"] == project.model_dump()
    assert payload["output_schema"] == generation_schema()
    assert "validation_feedback" not in payload
    assert len(calls) == 1
    assert calls[0]["messages"][0]["content"] == SYSTEM_PROMPT
    from backend.app.project_analysis import project_analysis_settings
    assert [c["max_tokens"] for c in calls] == [project_analysis_settings(configured).llm_max_output_tokens]
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
