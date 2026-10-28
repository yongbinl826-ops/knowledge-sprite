"""Offline single-pass projection tests, not a real-model semantic evaluation."""
import json
from dataclasses import replace
from pathlib import Path

import pytest

from backend.app import project_analysis as analysis_module
from backend.app.project_analysis import learning_quality_issues
from backend.app.project_models import AnalysisDocument, ProjectInput
from tests.test_project_analysis import settings


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "analysis_method_traceability.json"
CASES = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["cases"]
BAD_PAIRS = [c for c in CASES if c["kind"] == "retained_real_synthetic_plan_pair"]
ALLOWED = [c for c in CASES if c["kind"] == "unseen_offline_positive"]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_local_fixture_has_current_schema_and_does_not_add_a_broad_heuristic(case):
    project = ProjectInput.model_validate(case["project"])
    before = AnalysisDocument.model_validate(case["before"], context={"fresh_generation": True})
    # These semantic examples are intentionally valid structurally. A prompt
    # revision cannot turn this assertion into proof of semantic correctness.
    assert learning_quality_issues(project, before) == []
    if case["after"]:
        after = AnalysisDocument.model_validate(case["after"], context={"fresh_generation": True})
        assert learning_quality_issues(project, after) == []
        assert before.model_dump() != after.model_dump()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", BAD_PAIRS, ids=lambda c: c["id"])
async def test_historical_method_examples_are_projected_without_claiming_semantic_approval(case, monkeypatch):
    from tests.professional_contract_support import projected_once
    # These retained examples may still have semantic defects. Reading/projecting
    # them is deliberately not a new semantic approval or a promise of review.
    def forbidden(*_args, **_kwargs):
        pytest.fail("Single-pass generation must not run semantic/name review")
    monkeypatch.setattr(analysis_module, "_local_quality_issues", forbidden)
    project = ProjectInput.model_validate(case["project"])
    result, calls = await projected_once(case["before"], project,
        replace(settings(), project_semantic_review_enabled=True))
    assert len(calls) == 1
    assert [point.name for point in result.knowledge_points] == [point["name"] for point in case["before"]["knowledge_points"]]
    assert calls[0]["messages"][0]["content"] == analysis_module.GENERATION_PROMPT
    assert "functions" not in result.model_dump()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ALLOWED, ids=lambda c: c["id"])
async def test_legacy_reuse_examples_keep_graph_and_background_without_filled_new_targets(case, monkeypatch):
    from tests.professional_contract_support import projected_once
    def forbidden(*_args, **_kwargs):
        pytest.fail("Single-pass generation must not run semantic/name review")
    monkeypatch.setattr(analysis_module, "_local_quality_issues", forbidden)
    result, calls = await projected_once(case["before"], ProjectInput.model_validate(case["project"]),
        replace(settings(), project_semantic_review_enabled=True))
    assert len(calls) == 1
    assert [point.name for point in result.knowledge_points] == [point["name"] for point in case["before"]["knowledge_points"]]
    assert all(k.selection == "learn" for k in result.knowledge_points)
    assert all("prerequisite_ids" not in p for p in result.model_dump()["knowledge_points"])


def test_active_prompt_selects_relevant_terms_without_compulsory_method_traceability():
    from tests.professional_contract_support import assert_simple_generation_schema
    assert analysis_module.ANALYSIS_PROMPT_VERSION == "project-analysis-v9-textbook-single-generation"
    prompt = analysis_module.SYSTEM_PROMPT
    assert "Honor its technologies and constraints" in prompt
    assert "Do not add a separate review" in prompt
    assert "Do not output graphs, learning order" in prompt
    assert "not a prerequisite graph" in prompt
    assert "learner profiles, review fields or additional wrappers" in prompt
    assert analysis_module.ANALYSIS_MAX_MODEL_CALLS == 1
    assert_simple_generation_schema()


def test_actual_missing_method_pair_is_one_field_completion_not_scope_or_grammar_rewrite():
    case = next(c for c in BAD_PAIRS if c["id"] == "actual_state_render_missing")
    before = json.loads(json.dumps(case["before"]))
    after = case["after"]
    old_skills = before["knowledge_points"][1]["learning_skills"]
    new_skills = after["knowledge_points"][1]["learning_skills"]
    assert new_skills[:2] == old_skills and len(new_skills) == 4
    before["knowledge_points"][1]["learning_skills"] = new_skills
    assert before == after


def test_positive_reuse_cases_have_real_graph_or_background_basis():
    prior = next(c for c in ALLOWED if c["id"] == "declared_prior_skill_reuse_allowed")
    assert prior["before"]["knowledge_points"][1]["prerequisite_ids"] == ["k1"]
    assert prior["before"]["knowledge_points"][0]["learning_order"] < prior["before"]["knowledge_points"][1]["learning_order"]
    known = next(c for c in ALLOWED if c["id"] == "explicit_background_reuse_allowed")
    assert "已会JavaScript对象、函数、textContent与DOM集中渲染" in known["project"]["project_context"]
    assert known["before"]["knowledge_points"][0]["prerequisite_ids"] == []
    assert len(known["before"]["knowledge_points"][0]["learning_skills"]) == 2
