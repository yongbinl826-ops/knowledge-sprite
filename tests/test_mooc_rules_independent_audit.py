"""Independent offline admission audit for structured MOOC outline changes."""
from copy import deepcopy
import json

import httpx
import pytest

from backend.app.config import Settings
from backend.app.extractor import MetadataExtractor
from backend.app.models import now
from backend.app.mooc_relevance import assess_mooc_relevance
from test_mooc_structured_outline import URL, synthetic


@pytest.fixture(autouse=True)
def forbid_external_access(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Audit must not use network or environment credentials")
    monkeypatch.setattr(Settings, "from_env", forbidden)
    monkeypatch.setattr(httpx.Client, "send", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)


def observation(point, rows, *, title="计算机技术课程", outline=""):
    html = synthetic(rows, outline=outline).replace('"Own course"', json.dumps(title, ensure_ascii=False))
    html = html.replace("<body>", "<body><div id='j-rectxt'>spContent=本课程提供公开课程简介和章节大纲。</div>")
    resource = MetadataExtractor().extract(html, URL, now())
    evidence = resource.pop("evidence")
    resource.update(url=URL, canonical_url=URL, platform="icourse163")
    selected = {"knowledge_point_id": "audit", "text": point}
    evidence.append({"evidence_id": "audit_search", "kind": "search", "url": URL,
                     "title": title, "snippet": point, "knowledge_point_id": "audit"})
    return selected, resource, evidence


@pytest.mark.parametrize("point,parent,plan", [
    ("pandas 数据分组与聚合", "pandas 数据分析", "数据分组;;;聚合"),
    ("SQL 多表连接与分组查询", "SQL 查询", "内连接;;;分组查询"),
    ("HTML 表单与网页结构", "HTML 基础", "表单;;;网页文档基本结构"),
])
def test_bound_dto_parent_can_supply_only_its_childrens_missing_owner(point, parent, plan):
    selected, resource, evidence = observation(point, [{"name": parent, "plan": plan}])
    result = assess_mooc_relevance(selected, resource, evidence)
    assert result["display_eligible"]
    parent_id = resource["chapters"][0]["evidence_id"]
    assert all(row["context_evidence_ids"] == [parent_id] for row in result["matched_chapters"])


@pytest.mark.parametrize("foreign", ["XML", "XHTML", "JSON", "Markdown"])
def test_foreign_document_structure_cannot_inherit_html_owner(foreign):
    selected, resource, evidence = observation("HTML 表单与网页结构",
        [{"name": "HTML基础", "plan": "HTML表单;;;" + foreign + "文档基本结构"}], title="HTML网页设计")
    result = assess_mooc_relevance(selected, resource, evidence)
    assert not result["display_eligible"]
    assert all(row["title"] != foreign + "文档基本结构" for row in result["matched_chapters"])


@pytest.mark.parametrize("rows,title", [
    ([{"name": "pandas数据分析", "plan": "数据分组"}], "数据分析课程"),
    ([{"name": "pandas简介"}, {"name": "NumPy数据处理", "plan": "数据分组;;;聚合"}], "数据分析课程"),
    ([{"name": "NumPy数据处理", "plan": "数据分组;;;聚合"}], "pandas数据分析"),
    ([{"name": "预备知识：pandas", "plan": "数据分组;;;聚合"}], "数据分析课程"),
    ([{"name": "pandas数据分析", "goals": "数据分组和聚合", "plan": "安装"}], "数据分析课程"),
])
def test_partial_foreign_prerequisite_and_goal_text_cannot_fill_missing_chapters(rows, title):
    selected, resource, evidence = observation("pandas 数据分组与聚合", rows, title=title)
    assert not assess_mooc_relevance(selected, resource, evidence)["display_eligible"]


def test_legacy_paragraph_order_is_not_a_module_relationship():
    selected, resource, evidence = observation("pandas 数据分组与聚合", [], title="Python数据分析",
        outline="<p>pandas基础</p><p>数据分组</p><p>聚合</p>")
    assert not assess_mooc_relevance(selected, resource, evidence)["display_eligible"]


@pytest.mark.parametrize("missing", ["aggregate", "parent", "child"])
def test_dto_hierarchy_requires_original_hash_identity_for_aggregate_parent_and_child(missing):
    selected, resource, evidence = observation("pandas 数据分组与聚合",
        [{"name": "pandas基础", "plan": "数据分组;;;聚合"}])
    field = {"aggregate": "chapters", "parent": "chapters.0", "child": "chapters.1"}[missing]
    next(row for row in evidence if row.get("field") == field).pop("id")
    assert not assess_mooc_relevance(selected, resource, evidence)["display_eligible"]


def test_altered_parent_cannot_bypass_hash_binding_by_removing_original_ids():
    selected, resource, evidence = observation("pandas 数据分组与聚合",
        [{"name": "NumPy基础", "plan": "数据分组;;;聚合"}])
    assert not assess_mooc_relevance(selected, resource, evidence)["display_eligible"]
    resource, evidence = deepcopy(resource), deepcopy(evidence)
    parent = resource["chapters"][0]
    parent["title"] = "pandas基础"
    row = next(row for row in evidence if row.get("field") == "chapters.0")
    row["text"] = json.dumps({k: v for k, v in parent.items() if k not in {"source", "evidence_id"}},
                             ensure_ascii=False, sort_keys=True)
    row.pop("id")
    next(row for row in evidence if row.get("field") == "chapters").pop("id")
    assert not assess_mooc_relevance(selected, resource, evidence)["display_eligible"]


def test_explicit_instruction_search_only_admits_probe_never_a_recommendation():
    point = {"knowledge_point_id": "audit", "text": "SQL 多表连接与分组查询"}
    resource = {"url": URL, "canonical_url": URL, "platform": "icourse163", "fetch_status": "not_fetched"}
    evidence = [{"evidence_id": "audit_search", "kind": "search", "url": URL,
                 "title": "数据库基础", "snippet": "本课程讲授SQL语言和数据库设计。", "knowledge_point_id": "audit"}]
    result = assess_mooc_relevance(point, resource, evidence)
    assert result["probe_eligible"] and result["probe_priority"] == 10
    assert not result["display_eligible"] and result["matched_chapters"] == []
