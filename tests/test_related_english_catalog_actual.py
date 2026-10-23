"""Previously missed real own chapters; source snapshot, never live search."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from backend.app.models import SearchRequest
from backend.app.related_recommendations import related_recommendation


ACTUAL = json.loads((Path(__file__).parent / "fixtures/streamlit-mixed-course-actual.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name,fields", [
    ("文件下载", {"chapters.5"}),
    ("表单输入", {"chapters.6", "chapters.7", "chapters.8"}),
])
def test_actual_own_english_chapters_are_related_without_borrowing_flet(name, fields):
    resource, evidence = deepcopy(ACTUAL["resource"]), deepcopy(ACTUAL["evidence"])
    point = {"knowledge_point_id": "tested-point", "text": name, "technology": "Streamlit"}
    request = SearchRequest(knowledge_points=[name], topic_technologies={name: "Streamlit"}, preferred_platforms=["bilibili"])
    # Exclude discovery observations: own page/catalog alone must suffice.
    evidence = [row for row in evidence if row["kind"] != "search"]
    result = related_recommendation(point, resource, evidence, request)
    assert result and result["reference"]["exact_teaching_verified"] is False
    cited = {row["field"] for row in result["evidence"] if row["kind"] == "catalog"}
    assert cited == fields
    assert result["reference"]["technical_context"] == "observed"


def test_mixed_course_flet_form_cannot_fill_streamlit_gap_after_own_chapters_removed():
    evidence = [row for row in ACTUAL["evidence"]
                if row["kind"] != "search" and row.get("field") not in {"chapters.6", "chapters.7", "chapters.8"}]
    point = {"knowledge_point_id": "tested-point", "text": "表单输入", "technology": "Streamlit"}
    request = SearchRequest(knowledge_points=[point["text"]], topic_technologies={point["text"]: "Streamlit"})
    assert related_recommendation(point, ACTUAL["resource"], evidence, request) is None
