"""Reservation is an upper bound on all existing model branches, not spend."""
import importlib
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get("MOBILE_AUDIT_SOURCE_ROOT", ROOT)).resolve()
sys.path.insert(0, str(SOURCE))


@pytest.mark.parametrize("platforms", [[], ["bilibili"], ["bilibili", "icourse163"]])
@pytest.mark.parametrize("with_skills", [0, 1, 5])
def test_partial_skill_dictionary_reserves_expansion_for_other_points(platforms, with_skills):
    from backend.app.config import Settings
    from backend.app.mobile_tasks import MobileTasks, MobileTaskPayload
    settings = Settings(parallel_platform_search=True, teaching_match_enabled=True)
    points = ["Python topic " + str(index) for index in range(5)]
    payload = MobileTaskPayload.model_validate({"kind": "direct_search", "request": {
        "knowledge_points": points, "preferred_platforms": platforms,
        "learning_skills": {point: ["Python list indexing"] for point in points[:with_skills]}}})
    instance = MobileTasks.__new__(MobileTasks)  # Pure reservation method; not an incomplete live manager.
    instance.settings = settings
    costs = instance._costs(payload)
    rerank = len(points)
    expansions = len(points) - with_skills
    judge_and_review = settings.teaching_match_max_calls_per_job + 1 if with_skills else 0
    assert costs["model_calls"] >= rerank + expansions + judge_and_review
    assert costs["tasks"] == 1
    assert costs["search_requests"] <= settings.max_search_requests
    assert costs["detail_http"] >= costs["detail_pages"]
