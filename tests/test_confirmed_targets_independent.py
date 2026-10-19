"""Independent adversarial confirmed-target review; synthetic and retained HTML.

These tests assert evidence boundaries, not live search or playback success.
"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from backend.app.extractor import MetadataExtractor
from backend.app.models import SearchRequest
from backend.app.ranking import assess_topic_evidence, rank_resource
import pytest


URL = "https://www.bilibili.com/video/BV1ab411c7De"


@pytest.fixture(scope="module", autouse=True)
def record_reviewed_ranking_hash(record_testsuite_property):
    path = Path(__file__).resolve().parents[1] / "backend/app/ranking.py"
    record_testsuite_property("independent_review_ranking_sha256", sha256(path.read_bytes()).hexdigest())
    record_testsuite_property("independent_review_network_requests", 0)


def page(title, body=""):
    resource = {"resource_id": "r", "url": URL, "canonical_url": URL, "title": title,
                "description": body, "resource_type": "video", "video_evidence_status": "page_verified",
                "fetch_status": "fetched", "metadata_evidence_level": "page", "chapters": [], "field_provenance": {}}
    evidence = []
    for field, value, source in (("title", title, "html.title"), ("description", body, "html.description"),
                                 ("resource_type", "video", "meta.og:type"),
                                 ("video_evidence_status", "same video public metadata", "html.bilibili.__INITIAL_STATE__.videoData.bvid")):
        identifier = "page-" + field
        resource["field_provenance"][field] = {"evidence_id": identifier, "source": source, "url": URL}
        evidence.append({"evidence_id": identifier, "kind": "page", "field": field, "source": source, "url": URL, "text": value})
    return resource, evidence


def assessed(title, body, target, *, unit="pandas CSV reading"):
    resource, evidence = page(title, body)
    point = {"knowledge_point_id": "p", "text": unit, "learning_targets": [target]}
    before = deepcopy((point, resource, evidence))
    result = assess_topic_evidence(point, resource, evidence)
    assert (point, resource, evidence) == before
    return result


def target_status(result, index=1):
    return next((row["status"] for row in (result or {}).get("subtopic_coverage", [])
                 if row["id"] == f"learning_target_{index}"), "unknown")


@pytest.mark.parametrize("target", ["数据去重", "重复行删除", "复核日志", "删除行数统计", "无效行隔离"])
def test_chinese_target_cannot_borrow_the_library_name_from_an_unrelated_lesson(target):
    result = assessed("pandas CSV reading tutorial", "Learn pandas read_csv to load a CSV file.", target)
    assert target_status(result) == "unknown"


@pytest.mark.parametrize("body", [
    "drop_duplicates is not covered. Learn pandas read_csv instead.",
    "This lesson doesn't cover drop_duplicates. Learn pandas read_csv instead.",
    "This lesson excludes drop_duplicates and teaches read_csv.",
    "Prerequisites: pandas drop_duplicates. This lesson teaches pandas read_csv.",
    "API list: read_csv, drop_duplicates. This page is a symbol index.",
    "TODO: implement drop_duplicates in a future lesson. This video teaches read_csv.",
])
def test_title_tokens_cannot_override_non_teaching_or_prerequisite_body(body):
    result = assessed("pandas read_csv and drop_duplicates", body, "drop_duplicates")
    assert target_status(result) == "unknown"


@pytest.mark.parametrize("unit,title,body,target", [
    ("Matplotlib basic plots", "Matplotlib introduction", "Pillow rectangle drawing tutorial.", "rectangle drawing"),
    ("Arduino button input", "Arduino introduction", "Raspberry Pi GPIO input tutorial using Python.", "GPIO input"),
    ("pandas CSV reading", "pandas introduction", "DuckDB CSV reading tutorial.", "CSV reading"),
])
def test_foreign_tool_operation_cannot_borrow_enclosing_title_owner(unit, title, body, target):
    result = assessed(title, body, target, unit=unit)
    assert target_status(result) == "unknown"


def test_catalog_evidence_from_a_different_video_is_not_own_target_support():
    resource, evidence = page("pandas CSV reading tutorial", "Learn pandas read_csv.")
    resource["chapters"] = [{"title": "pandas drop_duplicates tutorial", "evidence_id": "foreign-catalog"}]
    evidence.append({"evidence_id": "foreign-catalog", "kind": "catalog", "field": "chapter", "source": "html.catalog",
                     "url": "https://www.bilibili.com/video/BV1other56789", "text": "pandas drop_duplicates tutorial"})
    point = {"knowledge_point_id": "p", "text": "pandas CSV reading", "learning_targets": ["drop_duplicates"]}
    result = assess_topic_evidence(point, resource, evidence)
    assert target_status(result) == "unknown"


def test_search_excerpt_never_attests_concept_but_actual_own_api_can():
    resource, evidence = page("pandas CSV reading tutorial", "Learn pandas read_csv to load CSV files.")
    evidence.append({"evidence_id": "search-poison", "kind": "search", "source": "public_catalog", "url": URL,
                     "knowledge_point_id": "p", "title": "pandas drop_duplicates tutorial", "snippet": "drop_duplicates"})
    point = {"knowledge_point_id": "p", "text": "pandas CSV reading", "learning_targets": ["read_csv", "drop_duplicates"]}
    result = assess_topic_evidence(point, resource, evidence)
    assert result and result["topic_evidence_status"] == "partial"
    assert target_status(result, 1) == "supported" and target_status(result, 2) == "unknown"
    assert "search-poison" not in next(r for r in result["subtopic_coverage"] if r["id"] == "learning_target_1")["evidence_ids"]


@pytest.mark.parametrize("name,url,unit,targets,forbidden", [
    ("techwithtim/scoring-health-bars.html", "https://www.techwithtim.net/tutorials/game-development-with-python/pygame-tutorial/scoring-health-bars",
     "pygame score display", ["pygame.key.get_pressed", "pygame.init", "K_SPACE restart"], [1, 2, 3]),
    ("freecodecamp/article-projects.html", "https://www.freecodecamp.org/news/learn-pandas-for-data-science/",
     "pandas data cleaning", ["pd.to_datetime", "trip_id 删除行数统计", "按出发小时分组计数"], [1, 2, 3]),
])
def test_retained_course_scoping_cannot_attest_sidebar_cumulative_code_or_project_intent(name, url, unit, targets, forbidden):
    html = (Path(__file__).parent / "fixtures" / name).read_text(encoding="utf-8")
    resource = MetadataExtractor().extract(html, url, "2026-10-18T00:00:00Z")
    resource.update(resource_id="real-retained", url=url, canonical_url=url)
    point = {"knowledge_point_id": "p", "text": unit, "learning_targets": targets}
    result = assess_topic_evidence(point, resource, resource["evidence"])
    assert all(target_status(result, index) == "unknown" for index in forbidden)


@pytest.mark.parametrize("unit,target,source", [
    ("pandas timestamp comparison", "end < start", "pandas example: end > start"),
    ("pandas timestamp comparison", "end <= start", "pandas example: end < start"),
    ("pandas timestamp comparison", "end == start", "pandas example: end <= start"),
    ("pandas duration validation", "duration >= 0", "pandas example: duration > 0"),
    ("JavaScript focus timer", "25/5分钟", "JavaScript 20/10分钟计时教程"),
    ("JavaScript focus timer", "25/5 minute timers", "JavaScript 20/10 minute timers tutorial"),
    ("Arduino button debounce", "稳定20–30ms去抖", "Arduino 稳定100ms去抖教程"),
    ("Arduino button debounce", "稳定20–30ms去抖", "Arduino 稳定20–50ms去抖教程"),
    ("JavaScript focus timer", "25/5分钟", "JavaScript 5/25分钟计时教程"),
    ("pandas timestamp comparison", "end < start", "pandas tutorial: end < starter"),
])
def test_confirmed_numeric_or_comparison_boundary_is_not_equivalent_to_another(unit, target, source):
    result = assessed(unit + " tutorial", source, target, unit=unit)
    assert target_status(result) == "unknown"


@pytest.mark.parametrize("unit,target,source", [
    ("pandas timestamp comparison", "end < start", "pandas tutorial: end < start"),
    ("pandas timestamp comparison", "end < start", "pandas tutorial: end<start"),
    ("pandas duration validation", "duration >= 0", "pandas tutorial: duration >= 0"),
    ("JavaScript focus timer", "25/5 minute timers", "JavaScript 25/5 minute timers tutorial"),
    ("Arduino button debounce", "稳定20–30ms去抖", "Arduino 稳定20-30ms去抖教程"),
])
def test_exact_owned_numeric_comparison_teaching_is_not_rejected_as_an_unknown_number(unit, target, source):
    result = assessed(unit + " tutorial", source, target, unit=unit)
    assert target_status(result) == "supported"


def test_supported_target_cites_only_its_valid_same_page_field_ids():
    resource, evidence = page("pandas CSV reading tutorial", "Learn pandas read_csv to read CSV files.")
    title_row = next(e for e in evidence if e["field"] == "title")
    title_row["url"] = "https://www.bilibili.com/video/BV1MK4y1g77P"
    point = {"knowledge_point_id": "p", "text": "pandas CSV reading", "learning_targets": ["read_csv"]}
    result = assess_topic_evidence(point, resource, evidence)
    row = next(r for r in result["subtopic_coverage"] if r["id"] == "learning_target_1")
    assert row["status"] == "supported"
    assert "page-title" not in row["evidence_ids"]
    assert "page-description" in row["evidence_ids"]


@pytest.mark.parametrize("name,url,unit,targets,supported,unknown,whole_expected", [
    ("techwithtim/scoring-health-bars.html", "https://www.techwithtim.net/tutorials/game-development-with-python/pygame-tutorial/scoring-health-bars",
     "pygame score display", ["pygame.font.SysFont", "pygame.init"], [1], [2], "supported"),
    ("freecodecamp/article-projects.html", "https://www.freecodecamp.org/news/learn-pandas-for-data-science/",
     "pandas customer data audit", ["duplicate values", "grouping operations", "to_datetime"], [1, 2], [3], "unknown"),
])
def test_retained_own_lesson_concepts_remain_useful_without_completing_business_requirements(name, url, unit, targets, supported, unknown, whole_expected):
    html = (Path(__file__).parent / "fixtures" / name).read_text(encoding="utf-8")
    resource = MetadataExtractor().extract(html, url, "2026-10-18T00:00:00Z")
    resource.update(resource_id="real-confirmed", url=url, canonical_url=url)
    point = {"knowledge_point_id": "p", "text": unit, "learning_targets": targets}
    result = assess_topic_evidence(point, resource, resource["evidence"])
    assert result and result["topic_evidence_status"] == "partial"
    assert all(target_status(result, i) == "supported" for i in supported)
    assert all(target_status(result, i) == "unknown" for i in unknown)
    assert result["subtopic_coverage"][0]["status"] == whole_expected
    if unit == "pygame score display":
        # This generic topic is explicitly taught by this lesson's own notes.
        # It does not attest initialization from the excluded cumulative code.
        assert "display this score to the screen" in resource["video_topic_summary"]
        assert 'font.render("Score: " + str(score)' in resource["video_topic_summary"]
        assert "pygame.init" not in resource["video_topic_summary"]
