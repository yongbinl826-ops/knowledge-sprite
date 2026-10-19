"""Prompt delivery checks only; no claim that a real generation obeys them."""
import ast
from pathlib import Path

from backend.app import project_analysis as module
from tests.professional_contract_support import assert_simple_generation_schema


def test_names_describe_one_reusable_topic_without_duplicate_or_unrelated_bundles():
    assert module.ANALYSIS_PROMPT_VERSION == "project-analysis-v4.1-coherent-professional-terms"
    assert "Each name must identify one coherent reusable technical topic" in module.SYSTEM_PROMPT
    assert "Merge duplicate topics" in module.SYSTEM_PROMPT
    assert "do not join independent mechanisms with 'and' or '与'" in module.SYSTEM_PROMPT
    assert "Closely related aspects of one technique may remain together" in module.SYSTEM_PROMPT
    assert "not project-specific objects or story labels" in module.SYSTEM_PROMPT


def test_literal_query_name_is_self_contained_without_mandatory_technology_field():
    assert "point.name itself is used as the search query" in module.SYSTEM_PROMPT
    assert "ambiguous across technology stacks" in module.SYSTEM_PROMPT
    assert "include the actually chosen technology in the name" in module.SYSTEM_PROMPT
    assert "do not rely on the optional technology field, description or project context" in module.SYSTEM_PROMPT
    assert "Genuinely general technical methods need no tool prefix" in module.SYSTEM_PROMPT
    assert_simple_generation_schema()


def test_new_name_guidance_adds_no_critic_teaching_gate_or_extra_model_call():
    assert module.ANALYSIS_MAX_ATTEMPTS == module.ANALYSIS_MAX_MODEL_CALLS == 2
    assert "not dozens or a fixed minimum number" in module.SYSTEM_PROMPT
    assert "Do not output project_task, concepts, learning_skills, practice_check or learner_profile" in module.SYSTEM_PROMPT
    assert "or add a separate semantic-review report" in module.SYSTEM_PROMPT
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    analyzer = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ProjectAnalyzer")
    calls = [n for n in ast.walk(analyzer) if isinstance(n, ast.Call)]
    assert not any(isinstance(n.func, ast.Name) and n.func.id in {"learning_quality_issues", "review_analysis"} for n in calls)
