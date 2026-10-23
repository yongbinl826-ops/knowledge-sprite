"""Actual catalog formatting must retain its object and splitting operation."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from backend.app.models import SearchRequest
from backend.app.related_concepts import reference_concept_denied, reference_concept_hints
from backend.app.related_recommendations import related_recommendation


POINT = {"knowledge_point_id": "text-split", "text": "文本分段", "technology": "Python"}
REQUEST = SearchRequest(knowledge_points=["文本分段"], topic_technologies={"文本分段": "Python"})


def actual_records():
    return json.loads((Path(__file__).parent / "fixtures/text-segmentation-catalog-actual.json").read_text(encoding="utf-8"))["records"]


@pytest.mark.parametrize("text", [
    "026.字符串_split()分割_join()合并_join()效率测试",
    "字符串 split() 分割", "文本：split()：分段", "字符串-分割", "文本 / 切分", "分割 字符串",
    "Python string splitting", "Joining and Splitting a String", "Python split strings by a delimiter",
    "Text Splitting Techniques-Recursive Character Text Splitter",
])
def test_object_and_explicit_operation_survive_catalog_delimiters(text):
    assert reference_concept_hints("文本分段", text) == ["文本分段"]


@pytest.mark.parametrize("text", [
    "Python 文本分类", "文本分析", "字符串分类", "文本_分类_split()示例", "字符串列表排序",
    "图像分割", "数据集划分 train_test_split()", "Splitting the Data for Training and Testing",
    "Joining strings", "split()方法", "text classification", "text splitters_other",
    "Splitting a stringbuilder object", "字符串_任意其他技术_分割", "文本与图像分割",
])
def test_classification_other_objects_and_unbound_api_do_not_become_splitting(text):
    assert reference_concept_hints("文本分段", text) == []


@pytest.mark.parametrize("text", [
    "不讲字符串_split()分割", "未涉及文本：split()：分段", "not covering string splitting",
    "Splitting a string is not covered", "text splitting is not taught",
])
def test_explicit_noncoverage_stays_excluded(text):
    assert reference_concept_denied("文本分段", text) is True
    assert reference_concept_hints("文本分段", text) == []


def test_actual_current_python_course_uses_its_exact_own_part_evidence():
    item = actual_records()[0]
    resource, evidence = item["resource"], item["evidence"]
    before = deepcopy(item)
    result = related_recommendation(POINT, resource, evidence, REQUEST)
    assert result and result["reference"]["exact_teaching_verified"] is False
    chapter = next(e for e in evidence if e.get("field") == "chapters.25")
    title = next(e for e in evidence if e.get("field") == "title")
    assert json.loads(chapter["text"])["title"] == "026.字符串_split()分割_join()合并_join()效率测试"
    assert {chapter["evidence_id"], title["evidence_id"]} <= set(result["reference"]["evidence_ids"])
    assert result["reference"]["basis"] == ["catalog"]
    assert before == item


@pytest.mark.parametrize("mode", ["foreign", "query", "missing-source", "wrong-language", "negative"])
def test_actual_catalog_cannot_borrow_query_foreign_or_wrong_language_facts(mode):
    item = actual_records()[0]
    resource, evidence = item["resource"], item["evidence"]
    chapter = next(e for e in evidence if e.get("field") == "chapters.25")
    if mode == "foreign":
        chapter["url"] = "https://example.org/other-course"
    elif mode == "query":
        chapter.update(kind="search", query=chapter["text"], text="", title="课程", snippet="")
    elif mode == "missing-source":
        chapter["source"] = ""
    elif mode == "negative":
        chapter["text"] = {"title": "不讲字符串_split()分割"}
    else:
        resource["title"] = "JavaScript programming course"
        resource["description"] = "JavaScript course"
        for e in evidence:
            if e.get("field") in {"title", "description"}:
                e["text"] = resource[e["field"]]
    assert related_recommendation(POINT, resource, evidence, REQUEST) is None


def test_actual_langchain_splitting_chapter_cannot_inherit_python_from_distant_graph_lesson():
    item = actual_records()[1]
    evidence = item["evidence"]
    split = next(e for e in evidence if e.get("field") == "chapters.19")
    graph = next(e for e in evidence if e.get("field") == "chapters.94")
    assert reference_concept_hints("文本分段", split["text"]) == ["文本分段"]
    assert "Python" in graph["text"]
    assert related_recommendation(POINT, item["resource"], evidence, REQUEST) is None
