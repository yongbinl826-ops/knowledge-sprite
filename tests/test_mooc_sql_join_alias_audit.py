"""Strict relational-query aliases; synthetic own-page evidence, no network."""
from copy import deepcopy
import json

import httpx
import pytest

from backend.app.config import Settings
from backend.app.extractor import MetadataExtractor
from backend.app.models import now
from backend.app.mooc_relevance import assess_mooc_relevance
from test_mooc_structured_outline import URL, synthetic


POINT = {"knowledge_point_id": "sql-audit", "text": "SQL 多表连接与分组查询"}


@pytest.fixture(autouse=True)
def no_external_access(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("SQL alias audit must use local synthetic data only")
    monkeypatch.setattr(Settings, "from_env", forbidden)
    monkeypatch.setattr(httpx.Client, "send", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)


def own_course(rows, title="数据库原理与应用", url=URL):
    course_id = url.rsplit("-", 1)[1]
    markup = synthetic(rows, course_id=course_id).replace('"Own course"', json.dumps(title, ensure_ascii=False))
    markup = markup.replace("<body>", "<body><div id='j-rectxt'>spContent=本课程提供独立课程简介和公开教学大纲。</div>")
    resource = MetadataExtractor().extract(markup, url, now())
    evidence = resource.pop("evidence")
    resource.update(url=url, canonical_url=url, platform="icourse163")
    evidence.append({"evidence_id": "search-" + course_id, "kind": "search", "url": url,
                     "title": title, "snippet": POINT["text"], "knowledge_point_id": POINT["knowledge_point_id"]})
    return resource, evidence


@pytest.mark.parametrize("join", ["数据表连接查询", "SQL连接查询"])
@pytest.mark.parametrize("owner_source", ["module", "course", "chapter"])
def test_relational_query_aliases_need_an_explicit_own_sql_owner_and_grouping(join, owner_source):
    title = "SQL查询语言" if owner_source == "course" else "数据库课程"
    parent = "关系数据库标准语言 SQL" if owner_source == "module" else "查询单元"
    chapter = "SQL 教学：" + join if owner_source == "chapter" else join
    resource, evidence = own_course([{"name": parent, "plan": chapter + ";;;SQL分组查询"}], title)
    result = assess_mooc_relevance(POINT, resource, evidence)
    assert result["display_eligible"]
    assert {part["status"] for part in result["subtopics"]} == {"supported"}
    assert {row["source_url"] for row in result["matched_chapters"]} == {URL}


def test_bfu_style_relational_focus_and_difficulty_plan_is_bound_outline_not_goals():
    resource, evidence = own_course([{"name": "关系数据库标准语言-SQL语言", "goals": "安装与配置",
        "plan": "重点：掌握SQL语句创建数据表、数据表连接查询和子查询。;;;难点：SQL连接查询、SQL子查询和分组查询等。"}])
    result = assess_mooc_relevance(POINT, resource, evidence)
    assert result["display_eligible"]
    assert {row["index"] for row in result["matched_chapters"]} == {1, 2}
    assert all(row["outline_parent_index"] == 0 for row in result["matched_chapters"])


@pytest.mark.parametrize("join", [
    "SQL数据库连接配置", "SQL连接字符串", "SQL连接数据库", "SQL连接池", "SQL单表查询",
    "SQL子查询", "SQL数据库连接查询", "NoSQL连接查询", "NoSQL数据表连接查询",
    "SQL简介；NoSQL连接查询", "SQL简介；NoSQL数据表连接查询", "SQL基础与Python数据表连接查询",
    "预备知识：SQL连接查询", "本课程不讲SQL连接查询", "未来课程讲授数据表连接查询",
])
def test_connection_infrastructure_foreign_owners_and_non_teaching_do_not_prove_table_join(join):
    resource, evidence = own_course([{"name": "SQL查询", "plan": join + ";;;SQL分组查询"}], "SQL数据库课程")
    result = assess_mooc_relevance(POINT, resource, evidence)
    assert not result["display_eligible"]
    assert next(part for part in result["subtopics"] if part["text"] == "多表连接")["status"] == "not_observed"


@pytest.mark.parametrize("join", ["数据表连接查询", "SQL连接查询"])
def test_join_alias_without_grouping_remains_partial(join):
    resource, evidence = own_course([{"name": "SQL查询", "plan": join}])
    result = assess_mooc_relevance(POINT, resource, evidence)
    assert result["status"] == "outline_partial" and not result["display_eligible"]


def test_unowned_data_table_join_does_not_borrow_sql_from_its_grouping_sibling():
    resource, evidence = own_course([{"name": "数据库课程", "plan": "数据表连接查询;;;SQL分组查询"}])
    assert not assess_mooc_relevance(POINT, resource, evidence)["display_eligible"]


def test_alias_in_goals_search_or_course_overview_cannot_replace_missing_join_chapter():
    resource, evidence = own_course([{"name": "SQL查询", "goals": "掌握数据表连接查询和SQL连接查询",
                                     "plan": "SQL分组查询"}])
    assert not assess_mooc_relevance(POINT, resource, evidence)["display_eligible"]
    resource.update(fetch_status="not_fetched", chapters=[], metadata_evidence_level="search")
    evidence[-1]["snippet"] = "本课程讲授SQL连接查询与分组查询。"
    result = assess_mooc_relevance(POINT, resource, evidence)
    assert result["probe_eligible"] and not result["display_eligible"]


def test_join_and_grouping_from_different_course_pages_cannot_be_pooled():
    resource, evidence = own_course([{"name": "SQL查询", "plan": "数据表连接查询"}])
    other, other_evidence = own_course([{"name": "SQL查询", "plan": "SQL分组查询"}], url=URL.replace("123", "124"))
    assert not assess_mooc_relevance(POINT, resource, evidence)["display_eligible"]
    assert not assess_mooc_relevance(POINT, other, other_evidence)["display_eligible"]
    mixed = deepcopy(resource)
    mixed["chapters"].extend(deepcopy(other["chapters"]))
    assert not assess_mooc_relevance(POINT, mixed, [*evidence, *other_evidence])["display_eligible"]
