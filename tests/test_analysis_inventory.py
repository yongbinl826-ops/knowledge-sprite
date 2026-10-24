"""Offline inventory integrity tests; no claim of semantic completeness."""
from copy import deepcopy
import json

import pytest
from pydantic import ValidationError

from backend.app.analysis_inventory import (
    FOUNDATION_CHECK_FIELDS, INVENTORY_GENERATION_PROMPT, FoundationCheck,
    FoundationChecks, GenerationDraft, InventoryMechanism, MechanismInventory,
    inventory_issues, inventory_schema,
)
from backend.app.project_models import ProjectInput


def example(name="本地支出汇总", requirements="按月份计算支出并显示合计。", **fields):
    project = ProjectInput(name=name, requirements=requirements, **fields)
    mechanisms = [{"id": f"m{index + 1}", "source_field": field,
                   "source_quote": getattr(project, field), "mechanism": "数据记录与分组计算",
                   "must_explain": "记录的字段含义及相同分组内数值求和的规则。"}
                  for index, field in enumerate(field for field in
                      ("name", "requirements", "project_context", "technical_version")
                      if getattr(project, field).strip())]
    checks = {field: {"applicable": False, "reason": "此合成路线未使用该维度。", "mechanism_ids": []}
              for field in FOUNDATION_CHECK_FIELDS}
    checks["data_representation"] = {"applicable": True, "reason": "路线需要表示输入记录。", "mechanism_ids": ["m1"]}
    body = {"mechanisms": mechanisms, "foundation_checks": checks}
    return project, body


def inspect(project, body):
    return inventory_issues(project, MechanismInventory.model_validate(body))


@pytest.mark.parametrize("name,requirements", [
    ("本地支出汇总", "按月份计算支出并显示合计。"),
    ("温度报警器", "温度超过给定阈值时点亮指示灯。"),
    ("排队服务模拟", "按到达顺序服务并计算平均等待时间。"),
])
def test_cross_domain_inventory_integrity_uses_no_domain_whitelist(name, requirements):
    project, body = example(name, requirements)
    before = deepcopy(body)
    assert inspect(project, body) == []
    assert body == before


def test_every_nonempty_source_field_including_name_is_accounted_for():
    project, body = example(project_context="本地运行", technical_version="Python 3")
    assert inspect(project, body) == []
    for field in ("name", "requirements", "project_context", "technical_version"):
        changed = deepcopy(body)
        changed["mechanisms"] = [row for row in changed["mechanisms"] if row["source_field"] != field]
        for check in changed["foundation_checks"].values():
            check.update(applicable=False, mechanism_ids=[])
        issues = inspect(project, changed)
        assert issues == [{"code": "inventory_unmapped_source",
                           "message": "Every nonempty project source field needs a valid inventory quotation.",
                           "location": ["project", field]}]


def test_blank_optional_fields_do_not_create_required_mechanisms():
    project, body = example(project_context=" \n ", technical_version=" ")
    assert inspect(project, body) == []


def test_quotes_preserve_urls_and_whitespace_without_executing_source_data():
    text = " 读取原始记录\n参考 https://example.org/spec；忽略规则的文本也只作为数据。 "
    project, body = example(requirements=text)
    inventory = MechanismInventory.model_validate(body)
    assert inventory.mechanisms[1].source_quote == text
    assert inventory_issues(project, inventory) == []
    body["mechanisms"][1]["source_quote"] = text.replace("\n", " ")
    assert {issue["code"] for issue in inspect(project, body)} == {"inventory_source_quote", "inventory_unmapped_source"}


def test_duplicate_ids_are_rejected_without_silently_renumbering():
    project, body = example()
    body["mechanisms"][1]["id"] = "m1"
    before = deepcopy(body)
    assert {issue["code"] for issue in inspect(project, body)} == {"inventory_duplicate_id"}
    assert body == before


@pytest.mark.parametrize("applicable,refs", [(True, []), (False, ["m1"])])
def test_applicable_iff_references_are_present(applicable, refs):
    project, body = example()
    body["foundation_checks"]["callable_contracts"].update(applicable=applicable, mechanism_ids=refs)
    issues = inspect(project, body)
    assert {issue["code"] for issue in issues} == {"inventory_foundation_applicability"}
    assert issues[0]["location"] == ["inventory", "foundation_checks", "callable_contracts", "applicable"]


def test_foundation_references_must_exist_and_errors_do_not_echo_model_values():
    project, body = example()
    body["foundation_checks"]["callable_contracts"].update(applicable=True, reason="UNTRUSTED_SENTINEL", mechanism_ids=["m999"])
    body["mechanisms"][0]["source_quote"] = "UNTRUSTED_SENTINEL"
    issues = inspect(project, body)
    assert "inventory_mechanism_reference" in {issue["code"] for issue in issues}
    assert "UNTRUSTED_SENTINEL" not in json.dumps(issues)
    assert "m999" not in json.dumps(issues)
    assert all(set(issue) == {"code", "message", "location"} for issue in issues)


def test_structure_does_not_certify_semantic_applicability_or_whole_text_coverage():
    project, body = example(requirements="按月份计算支出；还必须保留全部原始记录。")
    body["mechanisms"][1]["source_quote"] = "按月份计算支出"
    for row in body["mechanisms"]:
        row["must_explain"] = "这段说明可能没有解释实际必需的原理。"
    for check in body["foundation_checks"].values():
        check.update(applicable=False, reason="此理由可能不成立。", mechanism_ids=[])
    # These shortcomings require semantic review; local integrity cannot infer
    # missing mechanisms or prove the six applicability judgments correct.
    assert inspect(project, body) == []


@pytest.mark.parametrize("field,value", [
    ("id", "m0"), ("id", "m01"), ("id", "k1"), ("id", 1),
    ("source_field", "student_level"), ("source_quote", ""), ("source_quote", " \n "),
    ("source_quote", "x" * 1501), ("mechanism", " "), ("mechanism", "x" * 121),
    ("must_explain", ""), ("must_explain", "x" * 501), ("extra", "not allowed"),
])
def test_mechanism_fields_are_strict_nonempty_and_bounded(field, value):
    _, body = example()
    with pytest.raises(ValidationError):
        InventoryMechanism.model_validate({**body["mechanisms"][0], field: value})


@pytest.mark.parametrize("field,value", [
    ("applicable", 1), ("applicable", "true"), ("reason", ""), ("reason", " \n "),
    ("reason", "x" * 241), ("mechanism_ids", ["m0"]), ("mechanism_ids", ["m1"] * 91),
    ("extra", True),
])
def test_foundation_check_structure_is_strict(field, value):
    _, body = example()
    check = body["foundation_checks"]["data_representation"]
    with pytest.raises(ValidationError):
        FoundationCheck.model_validate({**check, field: value})


@pytest.mark.parametrize("field", FOUNDATION_CHECK_FIELDS)
def test_all_six_dimensions_are_required(field):
    _, body = example()
    del body["foundation_checks"][field]
    with pytest.raises(ValidationError):
        MechanismInventory.model_validate(body)


def test_inventory_bounds_do_not_pad_or_truncate_mechanisms():
    _, body = example()
    row = body["mechanisms"][0]
    row.update(source_quote="x" * 1500, mechanism="x" * 120, must_explain="x" * 500)
    body["mechanisms"] = [{**row, "id": f"m{i + 1}"} for i in range(90)]
    assert len(MechanismInventory.model_validate(body).mechanisms) == 90
    for mechanisms in ([], [*body["mechanisms"], {**row, "id": "m91"}]):
        with pytest.raises(ValidationError):
            MechanismInventory.model_validate({**body, "mechanisms": mechanisms})


@pytest.mark.parametrize("surface", ["checks", "inventory", "envelope"])
def test_extra_keys_are_forbidden_at_every_level(surface):
    _, body = example()
    if surface == "checks":
        model, value = FoundationChecks, body["foundation_checks"]
    elif surface == "inventory":
        model, value = MechanismInventory, body
    else:
        model, value = GenerationDraft, {"inventory": body, "analysis": {}}
    with pytest.raises(ValidationError):
        model.model_validate({**value, "unexpected": "not allowed"})


def test_generation_draft_preserves_inventory_first_and_analysis_remains_separately_validated():
    _, body = example()
    draft = GenerationDraft(inventory=MechanismInventory.model_validate(body), analysis={})
    assert list(draft.model_dump()) == ["inventory", "analysis"]
    with pytest.raises(ValidationError):
        GenerationDraft.model_validate({"inventory": body, "analysis": []})
    with pytest.raises(ValidationError):
        GenerationDraft.model_validate({"analysis": {}})


def test_schema_embeds_full_flat_contract_resolves_defs_and_never_mutates_input():
    # A schema stand-in keeps this independent of concurrently changing analyzer
    # orchestration while checking root-relative nested generation references.
    flat = {"type": "object", "additionalProperties": False,
            "properties": {"knowledge_points": {"type": "array", "maxItems": 30,
                                                 "items": {"$ref": "#/$defs/Concept"}}},
            "required": ["knowledge_points"], "$defs": {"Concept": {"type": "object"}}}
    before = deepcopy(flat)
    schema = inventory_schema(flat)
    assert flat == before
    assert list(schema["properties"]) == ["inventory", "analysis"]
    assert schema["required"] == ["inventory", "analysis"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["analysis"] == {key: value for key, value in flat.items() if key != "$defs"}
    assert schema["$defs"]["Concept"] == flat["$defs"]["Concept"]
    def refs(value):
        if isinstance(value, dict):
            if "$ref" in value:
                target = schema
                for segment in value["$ref"].removeprefix("#/").split("/"):
                    target = target[segment.replace("~1", "/").replace("~0", "~")]
            for item in value.values():
                refs(item)
        elif isinstance(value, list):
            for item in value:
                refs(item)
    refs(schema)
    schema["$defs"]["Concept"]["type"] = "string"
    assert flat == before


def test_schema_definition_conflicts_fail_closed():
    with pytest.raises(ValueError, match="Conflicting inventory and analysis"):
        inventory_schema({"type": "object", "$defs": {"FoundationCheck": {"type": "string"}}})


def test_prompt_requires_source_first_inventory_not_posthoc_point_copy_or_reasoning():
    prompt = INVENTORY_GENERATION_PROMPT
    assert "inventory FIRST and analysis SECOND" in prompt
    assert "BEFORE writing the knowledge-point list" in prompt
    assert "not by copying existing point titles" in prompt
    assert "parameter/return contract, invocation and transfer of control" in prompt
    assert "what the program must compute from what a tool already computes" in prompt
    assert "review dimensions, not mandatory knowledge points" in prompt
    assert "not reasoning steps" in prompt
    assert "do not prove" in prompt
    assert all(field in prompt for field in FOUNDATION_CHECK_FIELDS)


@pytest.mark.asyncio
@pytest.mark.parametrize("defect", ["malformed_inventory", "invalid_source_quote", "sensitive_inventory"])
async def test_legacy_inventory_is_rejected_then_repaired_as_flat_output_without_private_inventory(defect):
    import httpx
    from backend.app.project_analysis import ProjectAnalyzer
    from tests.professional_contract_support import draft_with_inventory
    from tests.test_project_analysis import flat_analysis_fixture, request, response, settings

    project, configured = request(), settings()
    final = flat_analysis_fixture()
    first = draft_with_inventory(final, project)
    if defect == "malformed_inventory":
        del first["inventory"]["foundation_checks"]["resource_readiness"]
    elif defect == "invalid_source_quote":
        first["inventory"]["mechanisms"][0]["source_quote"] = "not present in the project"
    else:
        first["inventory"]["mechanisms"][0]["must_explain"] = configured.llm_api_key
    original_first = deepcopy(first)
    calls, audits = [], []

    def reply(req):
        calls.append(json.loads(req.content))
        assert len(calls) <= 2
        if len(calls) == 1:
            return response(first)
        payload = json.loads(calls[-1]["messages"][1]["content"])
        assert payload["project"] == project.model_dump()
        assert payload["repair_required"] is True and payload["validation_feedback"]
        assert "reconstruction_required" not in payload
        assert "implementation_inventory" not in payload
        assert "previous_analysis" not in payload and "rejected_inventory" not in payload
        assert "not present in the project" not in json.dumps(payload)
        assert configured.llm_api_key not in json.dumps(payload)
        return response(final)

    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        result = await ProjectAnalyzer(configured, client).analyze(project, on_analysis_attempt=audits.append)
    assert len(calls) == 2
    assert [row["outcome"] for row in audits] == ["rejected", "accepted"]
    assert audits[-1]["analysis"] == final
    assert all("implementation_inventory" not in row for row in audits)
    assert len(result.knowledge_points) == len(final["knowledge_points"])
    assert first == original_first
    if defect == "sensitive_inventory":
        assert audits[0]["analysis"] is None
        assert "implementation_inventory" not in audits[0]
        assert configured.llm_api_key not in json.dumps(audits)
    else:
        # A legacy envelope remains complete untrusted audit data, never an
        # accepted analysis or privileged implementation inventory.
        assert audits[0]["analysis"] == original_first


@pytest.mark.asyncio
async def test_valid_legacy_inventory_does_not_make_an_invalid_analysis_acceptable():
    import httpx
    from backend.app.project_analysis import ProjectAnalyzer
    from tests.professional_contract_support import draft_with_inventory
    from tests.test_project_analysis import flat_analysis_fixture, request, response, settings

    project = request()
    final = flat_analysis_fixture()
    first = draft_with_inventory(final, project)
    first["inventory"]["mechanisms"][0]["must_explain"] = "PRIVATE_INVENTORY_OBLIGATION"
    frozen = deepcopy(first["inventory"])
    first["analysis"]["knowledge_points"] = []  # inventory is independently valid
    original_first = deepcopy(first)
    calls, audits = [], []

    def reply(req):
        calls.append(json.loads(req.content))
        assert len(calls) <= 2
        if len(calls) == 1:
            return response(first)
        payload = json.loads(calls[-1]["messages"][1]["content"])
        assert payload["project"] == project.model_dump()
        assert payload["repair_required"] is True and payload["validation_feedback"]
        assert "reconstruction_required" not in payload and "implementation_inventory" not in payload
        assert "previous_analysis" not in payload
        assert "PRIVATE_INVENTORY_OBLIGATION" not in json.dumps(payload)
        return response(final)

    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        await ProjectAnalyzer(settings(), client).analyze(project, on_analysis_attempt=audits.append)
    assert len(calls) == 2
    assert [row["outcome"] for row in audits] == ["rejected", "accepted"]
    assert first == original_first and first["inventory"] == frozen
    assert audits[0]["analysis"] == original_first and audits[1]["analysis"] == final
    assert all("implementation_inventory" not in row and "coverage_review" not in row for row in audits)
