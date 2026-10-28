"""Offline name-patch boundaries, not evidence of model quality or latency."""
from copy import deepcopy

import pytest

from backend.app.analysis_name_repair import (
    NAME_REPAIR_PROMPT, NameRepairNeedsContent, apply_name_repairs, name_repair_schema,
)


def candidate():
    return {
        "scope": "跨领域名称修正测试", "technical_plan": "保留原有机制与用途", "assumptions": [],
        "knowledge_points": [
            {"name": "物体运动更新", "description": "合力决定质量一定时的加速度。", "technology": ""},
            {"name": "读取分组结果", "description": "按键分组后对各组计算统计量。", "technology": "SQL"},
            {"name": "调色和着色步骤", "description": "明度表达颜色的明暗程度。"},
            {"name": "二维坐标系", "description": "用两个坐标确定平面位置。"},
        ],
        "retained_metadata": {"nested": ["unchanged", {"value": True}]},
    }


def patch(index=0, name="牛顿第二定律", original=None):
    original = candidate() if original is None else original
    return {"index": index, "original_name": original["knowledge_points"][index]["name"], "name": name}


def test_valid_multidomain_patch_only_changes_authorized_names_and_returns_deep_copy():
    original = candidate()
    response = {"name_repairs": [patch(), patch(1, "分组聚合"), patch(2, "色彩明度")]}
    before, response_before = deepcopy(original), deepcopy(response)
    result = apply_name_repairs(original, response, {0, 1, 2}, {0, 1})
    expected = deepcopy(original)
    for index, name in enumerate(("牛顿第二定律", "分组聚合", "色彩明度")):
        expected["knowledge_points"][index]["name"] = name
    assert result == expected
    assert original == before and response == response_before
    result["retained_metadata"]["nested"][1]["value"] = False
    result["knowledge_points"][3]["description"] = "detached"
    assert original == before


def test_optional_empty_patch_preserves_every_field():
    original = candidate()
    result = apply_name_repairs(original, {"name_repairs": []}, {0}, set())
    assert result == original and result is not original


def test_exact_content_repair_abstention_raises_without_mutation():
    original = candidate()
    before = deepcopy(original)
    with pytest.raises(NameRepairNeedsContent):
        apply_name_repairs(original, {"status": "needs_content_repair"}, {0}, {0})
    assert original == before


@pytest.mark.parametrize("response", [
    {}, [], None, {"name_repairs": {}}, {"name_repairs": ()},
    {"name_repairs": [], "description": "overwrite"},
    {"status": "needs_content_repair", "name_repairs": []},
    {"status": "needs_content_repair", "reason": "untrusted text"},
    {"status": "accepted"}, {"knowledge_points": []},
])
def test_wrong_envelopes_or_extra_fields_are_rejected(response):
    with pytest.raises(ValueError) as exc:
        apply_name_repairs(candidate(), response, {0}, set())
    assert not isinstance(exc.value, NameRepairNeedsContent)


@pytest.mark.parametrize("index", [True, False, 0.0, "0", -1, 4, 30, None])
def test_indices_are_strict_integers_in_range(index):
    repair = {**patch(), "index": index}
    with pytest.raises(ValueError):
        apply_name_repairs(candidate(), {"name_repairs": [repair]}, {0}, set())


@pytest.mark.parametrize("repair", [
    {"index": 0, "name": "牛顿第二定律"},
    {**patch(), "description": "replace the mechanism"},
    {**patch(), "technology": "Python"},
    {**patch(), "selection": "skip"},
    {**patch(), "id": "k2"},
    {**patch(), "original_name": "wrong candidate"},
    {**patch(), "original_name": None},
    "rename index zero",
])
def test_patch_cannot_change_fields_or_target_a_different_candidate(repair):
    with pytest.raises(ValueError):
        apply_name_repairs(candidate(), {"name_repairs": [repair]}, {0}, {0})


@pytest.mark.parametrize("name", [
    None, True, 7, [], {}, "", "   ", "a" * 81,
    "概念\x00", "概念\n名称", "概念\u200b", "概念\u202e", "概念\ud800",
    "https://example.com", "example.com", "第1章力学", "请创建一个物体",
])
def test_repaired_names_use_the_project_text_and_name_contract(name):
    with pytest.raises(ValueError):
        apply_name_repairs(candidate(), {"name_repairs": [patch(name=name)]}, {0}, {0})


def test_duplicate_indices_are_rejected_even_if_replacements_agree():
    with pytest.raises(ValueError):
        apply_name_repairs(candidate(), {"name_repairs": [patch(), patch()]}, {0}, {0})


def test_unauthorized_or_missing_required_indices_are_rejected():
    with pytest.raises(ValueError):
        apply_name_repairs(candidate(), {"name_repairs": [patch(1, "分组聚合")]}, {0}, set())
    with pytest.raises(ValueError):
        apply_name_repairs(candidate(), {"name_repairs": [patch()]}, {0, 1}, {0, 1})


@pytest.mark.parametrize("name", ["物体运动更新", "  物体运动更新  "])
def test_required_name_cannot_remain_unchanged_or_change_only_spacing(name):
    with pytest.raises(ValueError):
        apply_name_repairs(candidate(), {"name_repairs": [patch(name=name)]}, {0}, {0})


def test_patch_must_not_create_duplicate_concept_names_in_the_same_technology():
    original = candidate()
    original["knowledge_points"][0]["technology"] = "Physics"
    original["knowledge_points"][3]["technology"] = "Physics"
    with pytest.raises(ValueError):
        apply_name_repairs(original, {"name_repairs": [patch(name="二维坐标系")]}, {0}, {0})


def test_equal_standard_names_in_different_technologies_do_not_block_an_unrelated_repair():
    original = candidate()
    original["knowledge_points"][1].update(name="数组", technology="Python")
    original["knowledge_points"][2].update(name="数组", technology="JavaScript")
    result = apply_name_repairs(original, {"name_repairs": [patch()]}, {0}, {0})
    assert result["knowledge_points"][1:] == original["knowledge_points"][1:]
    assert result["knowledge_points"][0]["name"] == "牛顿第二定律"


def test_new_equal_names_across_explicit_technologies_are_not_duplicates():
    original = candidate()
    original["knowledge_points"][0]["technology"] = "Python"
    original["knowledge_points"][1].update(name="数组", technology="JavaScript")
    result = apply_name_repairs(original, {"name_repairs": [patch(name="数组")]}, {0}, {0})
    assert result["knowledge_points"][0]["name"] == result["knowledge_points"][1]["name"]


def test_unrelated_existing_duplicate_does_not_block_a_name_only_patch():
    original = candidate()
    original["knowledge_points"][1].update(name="数组", technology="Python")
    original["knowledge_points"][2].update(name="数组", technology="Python")
    result = apply_name_repairs(original, {"name_repairs": [patch()]}, {0}, {0})
    assert result["knowledge_points"][1:] == original["knowledge_points"][1:]


def test_context_prefix_normalization_uses_the_existing_duplicate_policy():
    original = candidate()
    original["knowledge_points"][0]["technology"] = "Python"
    original["knowledge_points"][1].update(name="Python 数组", technology="Python")
    with pytest.raises(ValueError):
        apply_name_repairs(original, {"name_repairs": [patch(name="数组")]}, {0}, {0})


def test_merging_existing_duplicate_groups_still_introduces_new_duplicate_pairs():
    original = candidate()
    for index, point in enumerate(original["knowledge_points"]):
        point.update(name="数组" if index < 2 else "字典", technology="Python")
    response = {"name_repairs": [patch(2, "数组", original), patch(3, "数组", original)]}
    with pytest.raises(ValueError):
        apply_name_repairs(original, response, {2, 3}, {2, 3})


@pytest.mark.parametrize("allowed,required", [
    ({True}, set()), ({-1}, set()), ({4}, set()), ({0}, {1}),
    ({0}, {False}), ([0], set()), ({0}, [0]),
])
def test_caller_coordinates_are_validated_before_use(allowed, required):
    with pytest.raises(ValueError):
        apply_name_repairs(candidate(), {"name_repairs": []}, allowed, required)


def test_failed_later_patch_never_partially_mutates_the_original():
    original = candidate()
    before = deepcopy(original)
    with pytest.raises(ValueError):
        apply_name_repairs(original, {"name_repairs": [patch(), patch(1, "https://example.com")]}, {0, 1}, {0})
    assert original == before


def test_patch_limit_and_original_count_are_bounded_without_truncation():
    with pytest.raises(ValueError):
        apply_name_repairs(candidate(), {"name_repairs": [patch()] * 31}, {0}, {0})
    original = candidate()
    original["knowledge_points"] *= 8
    with pytest.raises(ValueError):
        apply_name_repairs(original, {"name_repairs": []}, set(), set())
    assert len(original["knowledge_points"]) == 32


def test_schema_is_strict_and_fresh_and_prompt_does_not_authorize_content_changes():
    schema = name_repair_schema()
    patch_schema, abstention = schema["oneOf"]
    assert patch_schema["additionalProperties"] is False
    items = patch_schema["properties"]["name_repairs"]
    assert items["maxItems"] == 30
    assert items["items"]["additionalProperties"] is False
    assert set(items["items"]["required"]) == {"index", "original_name", "name"}
    assert abstention["additionalProperties"] is False
    assert abstention["properties"]["status"]["const"] == "needs_content_repair"
    items["maxItems"] = 100
    assert name_repair_schema()["oneOf"][0]["properties"]["name_repairs"]["maxItems"] == 30
    for instruction in ("untrusted data", "existing description", "required_indices", "needs_content_repair", "merging or splitting", "no permission to change the count"):
        assert instruction in NAME_REPAIR_PROMPT
