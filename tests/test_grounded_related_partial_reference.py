"""Offline transport checks of partial related references, not model accuracy."""
import pytest

from backend.app import grounded_related as grounded
from test_grounded_related_review import case, reviewed


@pytest.mark.parametrize("topic,technology,title,description", [
    ("操作历史栈与撤销/重做游标", "JavaScript", "JavaScript undo history",
     "JavaScript: maintain a history stack and undo the last action."),
    ("CSV 文件导出与下载", "Streamlit", "Streamlit download buttons",
     "Streamlit download buttons provide a download action for CSV files."),
])
def test_reviewed_specific_contribution_projects_without_claiming_complete_topic(
        monkeypatch, topic, technology, title, description):
    args = case(topic=topic, technology=technology, title=title, description=description)
    pair = grounded.prepare_pair(*args)
    sealed, calls = reviewed(monkeypatch, pair)
    assert sealed and len(calls) == 2
    assert calls[0]["pairs"][0]["topic"] == topic
    assert calls[1]["claims"][0]["topic"] == topic
    result = grounded.project_reference(*args, sealed)
    assert result["reference"]["source_quote"] == description
    assert result["reference"]["exact_teaching_verified"] is False
    assert result["reference"]["technical_context"] == "observed"
    assert result["reference"]["evidence_ids"] == ["own-description"]


def test_partial_reference_does_not_erase_an_explicit_api(monkeypatch):
    args = case(topic="read_csv() 读取与导出数据", technology="Python",
        title="Python spreadsheet data", description="Python: read_excel() reads spreadsheet data.")
    pair = grounded.prepare_pair(*args)
    sealed, calls = reviewed(monkeypatch, pair)
    assert sealed is None
    assert len(calls) == 1  # An exact quote with the wrong API never reaches review.


def test_partial_reference_does_not_erase_an_explicit_technology():
    args = case(topic="事件注册与分发", technology="Python",
        title="JavaScript event registration", description="JavaScript event registration and handlers.")
    assert grounded.prepare_pair(*args) is None


def test_conflicting_object_context_stays_out_of_model_observations():
    args = case(topic="数据库规范化与范式设计", technology="Python", title="Python 视频课程",
        description="Python pose database normalization set for motion matching.")
    pair = grounded.prepare_pair(*args)
    assert pair
    assert "own-description" not in {source["evidence_id"] for source in pair["sources"]}


def test_independent_rejection_of_adjacent_subject_stays_unknown(monkeypatch):
    args = case(topic="HTTP 请求与重试策略", technology="Python", title="Python request data",
        description="Python: pretty-print recorded request headers for a debugging report.")
    pair = grounded.prepare_pair(*args)
    sealed, calls = reviewed(monkeypatch, pair, accepted=False)
    assert sealed is None and len(calls) == 2
    assert calls[1]["claims"][0]["topic"] == args[0]["text"]
