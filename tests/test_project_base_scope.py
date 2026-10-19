"""Offline project merge boundary tests; no live source/model requests."""
from copy import deepcopy

from bs4 import BeautifulSoup
import pytest

from backend.app.models import SearchRequest
from tests.test_project_followup_matching import lesson
from tests.test_twt_recall_and_clock import extract, snake_html


from backend.app import ranking


def evaluate(point, resource, evidence, module=ranking):
    before = deepcopy((point, resource, evidence))
    result = module.rank_resource(point, resource, evidence, SearchRequest(knowledge_points=[point["text"]]))
    assert (point, resource, evidence) == before
    return result


@pytest.mark.parametrize("marker", ["TODO: ", "Next lesson: ", "Future lesson: ", "Coming soon: ",
                                    "Prerequisites: ", "本课不讲"])
def test_actual_own_snake_non_teaching_cannot_reenter_through_base_unit(monkeypatch, marker):
    soup = BeautifulSoup(snake_html(), "html.parser")
    demonstration = next(pre for pre in soup.find_all("pre")
        if pre.get_text().lstrip().startswith("def main():") and "clock.tick(10)" in pre.get_text())
    # Keep the actual adjacent explanation/function intact. Add a separate,
    # explicitly non-teaching own paragraph that the base matcher used to count.
    notice = soup.new_tag("p")
    notice.string = marker + "clock.tick 限帧。"
    demonstration.find_previous_sibling("p").insert_before(notice)
    resource = extract(monkeypatch, str(soup))
    assert "clock.tick(10)" in resource["video_topic_summary"]
    assert marker in resource["video_topic_summary"]
    point = {"knowledge_point_id": "timing", "text": "pygame 真实时间计时与限帧",
             "learning_targets": ["pygame.time.get_ticks 毫秒", "结束时间减开始时间", "clock.tick 限帧", "重置时更新时间基准"]}
    result = evaluate(point, resource, resource["evidence"])
    assert result is None or all(row["status"] == "unknown" for row in result["subtopic_coverage"])




@pytest.mark.parametrize("marker", ["TODO: ", "Next lesson: ", "Future lesson: ", "Coming soon: ",
                                    "Prerequisites: ", "本课不讲"])
def test_project_atomic_base_cannot_restore_a_rejected_confirmed_claim(marker):
    point = {"knowledge_point_id": "dedup", "text": "pandas 数据去重", "learning_targets": ["数据去重"]}
    resource, evidence = lesson("pandas 数据去重教程", description=marker + "pandas 数据去重。")
    assert evaluate(point, resource, evidence) is None


@pytest.mark.parametrize("tail", ["TODO: pandas 数据去重。", "Next lesson: pandas 数据去重。",
                                  "Prerequisites: pandas 数据去重。", "本课不讲pandas数据去重。"])
def test_related_non_teaching_tail_cannot_veto_own_teaching(tail):
    point = {"knowledge_point_id": "dedup", "text": "pandas 数据去重", "learning_targets": ["数据去重"]}
    resource, evidence = lesson("pandas 数据去重教程", description="本课讲pandas数据去重。相关视频：" + tail)
    result = evaluate(point, resource, evidence)
    assert result and result["topic_evidence_status"] == "supported"
    assert all(row["status"] == "supported" for row in result["subtopic_coverage"])


def test_only_affected_base_skill_is_retracted_independent_teaching_remains_partial():
    point = {"knowledge_point_id": "unit", "text": "pandas 数据去重与日期转换",
             "learning_targets": ["数据去重", "日期转换"]}
    resource, evidence = lesson("pandas 数据处理", description="本课讲pandas数据去重。TODO: pandas 日期转换。")
    result = evaluate(point, resource, evidence)
    assert result and result["topic_evidence_status"] == "partial"
    rows = {row["text"]: row for row in result["subtopic_coverage"]}
    assert rows["数据去重"]["status"] == "supported"
    assert rows["日期转换"]["status"] == "unknown" and rows["日期转换"]["evidence_ids"] == []


def test_untouched_actual_clock_remains_partial_and_all_other_requirements_unknown(monkeypatch):
    resource = extract(monkeypatch, snake_html())
    point = {"knowledge_point_id": "timing", "text": "pygame 真实时间计时与限帧",
             "learning_targets": ["pygame.time.get_ticks 毫秒", "结束时间减开始时间", "clock.tick 限帧", "重置时更新时间基准"]}
    result = evaluate(point, resource, resource["evidence"])
    assert result and result["topic_evidence_status"] == "partial"
    assert [row["text"] for row in result["subtopic_coverage"] if row["status"] == "supported"] == ["clock.tick 限帧"]




def test_genuine_scheduled_needs_review_is_preserved():
    point = {"knowledge_point_id": "upcoming", "text": "pandas 数据去重", "learning_targets": ["数据去重"]}
    resource, evidence = lesson("pandas 数据去重 upcoming live", description="预约直播，尚未开始。")
    result = evaluate(point, resource, evidence)
    assert result and result["topic_evidence_status"] == "needs_review"
    assert result["supporting_evidence_ids"] == []
    assert all(row["status"] == "unknown" for row in result["subtopic_coverage"])


@pytest.mark.parametrize("status", ["partial", "needs_review"])
def test_legacy_base_without_coverage_rows_is_accepted_without_key_error(monkeypatch, status):
    point = {"knowledge_point_id": "legacy", "text": "pandas 数据去重", "learning_targets": ["数据去重"]}
    resource, evidence = lesson("pandas CSV读取教程")
    base = {"topic_evidence_status": status, "supporting_evidence_ids": [], "topic_evidence_reasons": []}
    monkeypatch.setattr(ranking, "assess_topic_evidence", lambda *args: deepcopy(base))
    result = ranking._assess_confirmed_targets(point, resource, evidence)
    assert result and result["topic_evidence_status"] == status
    assert result["supporting_evidence_ids"] == []
