"""Prompt delivery checks only; no claim that a real generation obeys them."""
import ast
from pathlib import Path

from backend.app import project_analysis as module
from tests.professional_contract_support import assert_simple_generation_schema


def test_names_describe_one_reusable_topic_without_duplicate_or_unrelated_bundles():
    assert module.ANALYSIS_PROMPT_VERSION == "project-analysis-v9-textbook-single-generation"
    assert "one point teaches one reusable principle" in module.SYSTEM_PROMPT
    assert "combine its repeated project uses" in module.SYSTEM_PROMPT
    assert "Never split, merge or pad to reach a preferred count" in module.SYSTEM_PROMPT
    assert "Keep facets of the same principle together" in module.SYSTEM_PROMPT
    assert "Describe the mechanism first and its project use second" in module.SYSTEM_PROMPT


def test_canonical_name_and_explicit_context_are_separate_without_mandatory_extra_teaching_fields():
    assert "Each point contains only name, description and optional technology" in module.SYSTEM_PROMPT
    assert "technology is one short actual language/tool/framework identifier" in module.SYSTEM_PROMPT
    assert "or an empty string for a general concept" in module.SYSTEM_PROMPT
    assert "never join tools or put prose in it" in module.SYSTEM_PROMPT
    assert "Honor its technologies and constraints" in module.SYSTEM_PROMPT
    assert_simple_generation_schema()


def test_mechanism_first_protocol_reaches_prompt_and_schema_without_extra_output_fields():
    prompt = module.SYSTEM_PROMPT
    assert "Describe the mechanism first and its project use second" in prompt
    assert "separate genuinely independent principles" in prompt
    assert "combine its repeated project uses" in prompt
    assert "conditional checks, NOT a fixed syllabus" in prompt
    assert "Do not split by variable, field, parameter, API call or workflow step" in prompt
    fields = module.GeneratedConcept.model_fields
    assert "derived from the learning mechanism" in fields["name"].description
    assert "Mechanism first, application second" in fields["description"].description
    assert_simple_generation_schema()


def test_new_name_guidance_adds_no_critic_teaching_gate_or_extra_model_call():
    assert module.ANALYSIS_MAX_ATTEMPTS == 1 and module.ANALYSIS_MAX_MODEL_CALLS == 1
    assert "There is no target count or preferred range" in module.SYSTEM_PROMPT
    assert "Never split, merge or pad to reach a preferred count" in module.SYSTEM_PROMPT
    assert "Each point contains only name, description and optional technology" in module.SYSTEM_PROMPT
    assert "Do not add a separate review, naming critique, correction round" in module.SYSTEM_PROMPT
    assert "Internally check" not in str(module.generation_schema())
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    analyzer = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ProjectAnalyzer")
    calls = [n for n in ast.walk(analyzer) if isinstance(n, ast.Call)]
    assert not any(isinstance(n.func, ast.Name) and n.func.id in {"learning_quality_issues", "review_analysis"} for n in calls)
