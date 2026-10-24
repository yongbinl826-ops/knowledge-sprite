"""Prompt delivery checks only; no claim that a real generation obeys them."""
import ast
from pathlib import Path

from backend.app import project_analysis as module
from tests.professional_contract_support import assert_simple_generation_schema


def test_names_describe_one_reusable_topic_without_duplicate_or_unrelated_bundles():
    assert module.ANALYSIS_PROMPT_VERSION == "project-analysis-v5.22-program-state-description-checks"
    assert "one point represents one coherent reusable mechanism" in module.SYSTEM_PROMPT
    assert "Merge duplicate concepts" in module.SYSTEM_PROMPT
    assert "Never split or merge merely to reach a count" in module.SYSTEM_PROMPT
    assert "keep closely related facets of one mechanism together" in module.SYSTEM_PROMPT
    assert "Keep project details in this explanation" in module.SYSTEM_PROMPT


def test_canonical_name_and_explicit_context_are_separate_without_mandatory_extra_teaching_fields():
    assert "Keep canonical concept and technical context separate" in module.SYSTEM_PROMPT
    assert "Use the actual chosen ecosystem" in module.SYSTEM_PROMPT
    assert "when needed for accurate discovery" in module.SYSTEM_PROMPT
    assert "otherwise use an empty string" in module.SYSTEM_PROMPT
    assert "Do not join tools, instructions, URLs or prose" in module.SYSTEM_PROMPT
    assert_simple_generation_schema()


def test_mechanism_first_protocol_reaches_prompt_and_schema_without_extra_output_fields():
    prompt = module.SYSTEM_PROMPT
    assert "mechanism first, application second" in prompt
    assert "replacing project entities, fields and workflow stages with neutral placeholders" in prompt
    assert "retain all their project uses in one description" in prompt
    assert "不是任何项目的必选知识点或固定答案" in prompt
    assert "SHA-256" in prompt and "集合差集" in prompt and "发布与订阅模式" in prompt
    fields = module.GeneratedConcept.model_fields
    assert "derived from the learning mechanism" in fields["name"].description
    assert "Mechanism first, application second" in fields["description"].description
    assert_simple_generation_schema()


def test_new_name_guidance_adds_no_critic_teaching_gate_or_extra_model_call():
    assert module.ANALYSIS_MAX_ATTEMPTS == module.ANALYSIS_MAX_MODEL_CALLS == 2
    assert "no preferred count or target range" in module.SYSTEM_PROMPT
    assert "Never split or merge merely to reach a count" in module.SYSTEM_PROMPT
    assert "project_task, concepts, learning_skills, practice_check or learner_profile" in module.SYSTEM_PROMPT
    assert "Do not emit this review as extra fields" in module.SYSTEM_PROMPT
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    analyzer = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ProjectAnalyzer")
    calls = [n for n in ast.walk(analyzer) if isinstance(n, ast.Call)]
    assert not any(isinstance(n.func, ast.Name) and n.func.id in {"learning_quality_issues", "review_analysis"} for n in calls)
