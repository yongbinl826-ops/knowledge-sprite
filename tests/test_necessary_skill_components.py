"""Offline necessary-component controls; retained verdicts are not new model runs."""
from copy import deepcopy
from pathlib import Path
import json

import pytest

from backend.app import teaching_match as match
from backend.app import teaching_review as review
from test_teaching_match import lesson, point, support, verdict

FIXTURE = Path(__file__).parent / "fixtures/phase3_necessary_components/retained_real_claims.json"
RETAINED = json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.mark.parametrize("record", RETAINED, ids=lambda row: row["resource"]["resource_id"])
def test_retained_true_source_does_not_establish_missing_skill_components(record):
    before = deepcopy(record)
    pair = match.prepare_pair(record["point"], record["resource"], record["evidence"])
    assert pair is not None
    saved = {"fingerprint": pair["fingerprint"], "supports": record["match"]["teaching_support"]}
    actual = match.validate_decision(record["point"], record["resource"], record["evidence"], saved)
    assert actual == {"fingerprint": pair["fingerprint"], "supports": []}
    assert record == before  # no reinterpretation or replacement of raw evidence


@pytest.mark.parametrize("skill,technology,body", [
    ("按极性正确连接 LED 与限流电阻", "Arduino", "本课讲解按极性连接 LED 与限流电阻。"),
    ("Arduino map 线性映射与整数截断处理", "Arduino", "本课讲解 Arduino map 的线性映射与整数截断。"),
    ("原生 JavaScript 按钮 click 事件绑定与回调", "JavaScript", "本课讲解按钮 click 事件绑定与回调。"),
    ("pandas 时间列解析与类型检查", "pandas", "本课讲解时间列解析与类型检查。"),
    ("LumaTable fold 分组归约与空值处理", "LumaTable", "本课讲解 fold 分组归约与空值处理。"),
])
def test_nearby_explicit_complete_source_can_teach_different_demo(skill, technology, body):
    p = point([skill], technology=technology, project_task="a completely different demonstration")
    r, e = lesson(body)
    pair = match.prepare_pair(p, r, e)
    assert match.validate_decision(p, r, e, verdict(pair)) == verdict(pair)


@pytest.mark.parametrize("skill,technology,body", [
    ("原生 JavaScript 按钮 click 事件绑定与回调", "JavaScript", "本课讲解按钮 onclick 事件绑定与回调。"),
    ("Arduino map 线性映射与整数截断处理", "Arduino", "本课讲解 mapping 线性映射与整数截断。"),
    ("按极性正确连接 LED 与限流电阻", "Arduino", "本课介绍 LED 与限流电阻，但没有接线说明。"),
    ("pandas 时间列解析与类型检查", "pandas", "本课讲解时间列解析。"),
    ("LumaTable fold 分组归约与空值处理", "LumaTable", "本课讲解 fold 分组归约。"),
])
def test_related_family_or_missing_method_is_unknown_not_invalid_source(skill, technology, body):
    p = point([skill], technology=technology); r, e = lesson(body)
    pair = match.prepare_pair(p, r, e)
    assert match.validate_decision(p, r, e, verdict(pair)) == {"fingerprint": pair["fingerprint"], "supports": []}


def test_component_missing_is_filtered_without_discarding_other_independent_support():
    p = point(["LumaTable fold 分组归约与空值处理", "LumaTable fold 分组归约"], technology="LumaTable")
    r, e = lesson("本课讲解 fold 分组归约。")
    pair = match.prepare_pair(p, r, e)
    actual = match.validate_decision(p, r, e, verdict(pair, [support(pair), support(pair, skill_index=1)]))
    assert actual["supports"] == [support(pair, skill_index=1)]
    forged = support(pair); forged["source_text_sha256"] = "0" * 64
    assert match.validate_decision(p, r, e, verdict(pair, [forged])) is None


def test_title_cannot_donate_qualifiers_to_a_generic_description():
    p = point(["LumaTable fold 分组归约与空值处理"], technology="LumaTable")
    r, e = lesson("本课介绍 fold 分组归约。", title="LumaTable fold 分组归约与空值处理")
    pair = match.prepare_pair(p, r, e)
    assert match.validate_decision(p, r, e, verdict(pair))["supports"] == []
    assert match.validate_decision(p, r, e, verdict(pair, [support(pair, basis="title")]))["supports"]


def test_different_catalog_part_cannot_donate_missing_compound_component():
    record = next(row for row in RETAINED if row["match"]["teaching_support"][0]["basis"] == "catalog")
    pair = match.prepare_pair(record["point"], record["resource"], record["evidence"])
    decision = verdict(pair, record["match"]["teaching_support"])
    assert match.validate_decision(record["point"], record["resource"], record["evidence"], decision)["supports"] == []
    pointers = match.topic_pointers(pair)
    pointer = next(p for p in pointers if p["quote"] == "1-25 模拟输出1 - analogWrite")
    assert pointer["scope"] == "topic_declared" and pointer["basis"] == "catalog"
    assert pointer["target_url"].endswith("/?p=26")
    assert pointer["missing_components"] == ["占空比控制输出"]
    assert pointer["source_text_sha256"] == record["match"]["teaching_support"][0]["source_text_sha256"]
    assert set(pointer) == {"knowledge_point_id", "resource_id", "skill_id", "skill", "evidence_id", "quote", "basis", "source_text_sha256", "source_url", "target_url", "scope", "missing_components"}
    assert "_private" not in json.dumps(pointers)


@pytest.mark.parametrize("mutation", ["fingerprint", "raw", "projection", "foreign-url"])
def test_catalog_pointer_rejects_changed_binding(mutation):
    record = next(row for row in RETAINED if row["match"]["teaching_support"][0]["basis"] == "catalog")
    pair = match.prepare_pair(record["point"], record["resource"], record["evidence"])
    eid = record["match"]["teaching_support"][0]["evidence_id"]
    if mutation == "fingerprint": pair["fingerprint"] = "0" * 64
    elif mutation == "raw": pair["_records"][eid] += " foreign"
    elif mutation == "projection": pair["_scope_records"][eid] += " foreign"
    else: pair["_binding"]["canonical"] = "https://other.example/lesson"
    assert match.topic_pointers(pair) == []


def test_body_only_pointer_and_owner_only_catalog_are_not_invented():
    r, e = lesson("This lesson teaches QuillFlow bounded queues.")
    pair = match.prepare_pair(point(), r, e)
    assert match.topic_pointers(pair) == []


def test_old_seal_cannot_revive_under_new_component_contract():
    r, e = lesson(); p = point(); pair = match.prepare_pair(p, r, e)
    sealed = review.sealed_decision(verdict(pair))
    sealed["_review_version"] = "teaching-claim-review-v2-method-input"
    assert review.validate_reviewed(p, r, e, sealed) is None


@pytest.mark.parametrize("skill,technology,body", [
    ("pandas 读取 CSV", "pandas", "This lesson teaches reading CSV files using pandas."),
    ("Arduino 使用 analogWrite", "Arduino", "This lesson demonstrates Arduino analogWrite output with a worked example."),
    ("JavaScript 绑定 click", "JavaScript", "This lesson demonstrates binding a click handler in JavaScript."),
    ("QuillFlow 初始化消息队列", "QuillFlow", "This lesson initializes a QuillFlow message queue with a worked example."),
])
def test_plain_action_sentence_is_not_forced_to_repeat_chinese_verbatim(skill, technology, body):
    p = point([skill], technology=technology); r, e = lesson(body)
    pair = match.prepare_pair(p, r, e)
    assert match.validate_decision(p, r, e, verdict(pair)) == verdict(pair)


def test_unmapped_cross_language_compound_stays_unknown_not_claimed_absent():
    p = point(["QuillFlow 队列读取与错误检查"], technology="QuillFlow")
    r, e = lesson("This lesson teaches reading queues and checking errors in QuillFlow.")
    pair = match.prepare_pair(p, r, e)
    assert match.validate_decision(p, r, e, verdict(pair)) == {"fingerprint": pair["fingerprint"], "supports": []}
    assert r["fetch_status"] == "fetched" and r["video_evidence_status"] == "page_verified"


def test_actual_business_demo_can_still_declare_its_narrow_own_method():
    from backend.app.learning_support import learning_skill_assessment
    from backend.app.models import SearchRequest
    from backend.app.ranking import rank_resource
    retained = json.loads((FIXTURE.parents[1] / "phase3_method_input/web_demo_title_card.json").read_text(encoding="utf-8"))
    p, r, e = deepcopy((retained["point"], retained["resource"], retained["evidence"]))
    p["learning_skills"] = ["JavaScript onclick 事件绑定"]
    request = SearchRequest.model_validate(retained["request"])
    pair = match.prepare_pair(p, r, e, request.student_level)
    # Explicitly narrower counterfactual, not a claim that the actual original
    # requested button/click/callback skill was established.
    core = verdict(pair, [support(pair, "事件绑定onclick", basis="title")])
    p["_teaching_decision"] = review.sealed_decision(core)
    assert learning_skill_assessment(p, r, e, request)["topic_evidence_status"] == "partial"
    assert rank_resource(p, r, e, request)["teaching_support"][0]["skill"] == p["learning_skills"][0]


def test_same_object_action_grammatical_inversion_is_not_a_missing_method():
    p = point(["pandas 时间列解析与类型检查"], technology="pandas")
    r, e = lesson("本课讲解解析时间列并检查类型。")
    pair = match.prepare_pair(p, r, e)
    assert match.validate_decision(p, r, e, verdict(pair)) == verdict(pair)


@pytest.mark.parametrize("body", ["本课解析时间列，不检查类型。", "本课讲解时间列解析，没有类型检查。", "本课讲解时间列解析，类型检查不包含。"])
def test_negated_required_facet_cannot_become_positive_by_grammatical_inversion(body):
    p = point(["pandas 时间列解析与类型检查"], technology="pandas")
    r, e = lesson(body); pair = match.prepare_pair(p, r, e)
    result = match.validate_decision(p, r, e, verdict(pair)) if pair else None
    assert result is None or result["supports"] == []


def test_quote_cannot_crop_component_negation_from_same_own_field():
    p = point(["pandas 时间列解析与类型检查"], technology="pandas")
    r, e = lesson("时间列解析与类型检查不包含在本课讲解中。")
    pair = match.prepare_pair(p, r, e)
    result = match.validate_decision(p, r, e, verdict(pair, [support(pair, "时间列解析与类型检查")])) if pair else None
    assert result is None or result["supports"] == []


def test_actual_date_code_is_preserved_but_unmapped_chinese_compound_is_unknown():
    row = json.loads(FIXTURE.with_name("retained_date_code_source.json").read_text(encoding="utf-8"))
    pair = match.prepare_pair(row["point"], row["resource"], row["evidence"])
    quote = "df[&#39;datetime&#39;] = pd.to_datetime(df[&#39;date&#39;]) print(df) print(df.info())"
    assert len(row["resource"]["description"]) == 2496
    assert quote in row["resource"]["description"]
    assert any(quote in segment for source in pair["observations"] for segment in source["segments"])
    claim = support(pair, quote)
    # This test records a conservative false-negative boundary. The source is
    # genuinely specific; without an API dictionary the new gate cannot prove
    # the Chinese compound from these function names, and MUST NOT call the
    # existing {} failure sentinel a valid model rejection.
    assert match.validate_decision(row["point"], row["resource"], row["evidence"], verdict(pair, [claim]))["supports"] == []


@pytest.mark.parametrize("skill,body,expected", [
    ("pandas 从内存对象读取 CSV", "pandas 读取磁盘CSV到内存对象", False),
    ("pandas 从内存对象读取 CSV", "Read disk CSV into a file-like object using pandas.", False),
    ("pandas 从内存对象读取 CSV", "Read CSV from a file-like object using pandas.", True),
    ("pandas 写入内存对象", "从内存对象读取 CSV 并写入本地磁盘。", False),
    ("pandas 写入内存对象", "从本地读取 CSV 并写入内存对象。", True),
])
def test_explicit_input_and_output_medium_cannot_exchange_directions(skill, body, expected):
    assert match._method_input_supported(skill, body) is expected


def test_actual_5354_character_movement_notes_include_requested_bare_method_window():
    row = json.loads(FIXTURE.with_name("retained_movement_bare_method.json").read_text(encoding="utf-8"))
    before = deepcopy(row)
    pair = match.prepare_pair(row["point"], row["resource"], row["evidence"], "intermediate")
    assert len(row["resource"]["video_topic_summary"]) == 5354
    source = next(s for s in pair["observations"] if s["basis"] == "lesson_notes")
    assert any("pygame.key.get_pressed()" in segment for segment in source["segments"])
    assert sum(map(len, source["segments"])) + len(source["segments"]) - 1 <= 1800
    assert len(pair["observations"]) <= 8
    assert sum(sum(map(len, s["segments"])) + len(s["segments"]) - 1 for s in pair["observations"]) <= 6000
    assert source["source_text_sha256"] == match._hash(row["resource"]["video_topic_summary"])
    assert match.literal_decision(pair)["supports"] == []  # recall is not approval
    assert row == before


@pytest.mark.parametrize("method", ["flush_queue", "flushQueue", "fold"])
def test_unseen_target_identifier_selects_late_local_source_window(method):
    body = "QuillFlow background material. " * 150 + f"\nThis lesson demonstrates QuillFlow {method} with a worked example."
    p = point([f"QuillFlow {method} 队列操作"])
    r, e = lesson(body)
    pair = match.prepare_pair(p, r, e)
    source = next(s for s in pair["observations"] if s["basis"] == "description")
    assert any(method in segment for segment in source["segments"])
    assert source["source_text_sha256"] == match._hash(body)


def test_late_identifier_keeps_negative_heading_scope_and_cannot_borrow_similar_name():
    p = point(["QuillFlow flush_queue"])
    body = "Prerequisites:\n" + "Background material. " * 150 + "\nQuillFlow flush_queue with a worked example."
    r, e = lesson(body); pair = match.prepare_pair(p, r, e)
    assert any("Prerequisites:" in segment for segment in match._segments(body, body, p["learning_skills"]))
    if pair is not None:  # whole-source scope may already reject the source
        claim = support(pair, "QuillFlow flush_queue with a worked example.")
        assert match.validate_decision(p, r, e, verdict(pair, [claim])) is None
    r, e = lesson("Background material. " * 150 + "\nQuillFlow unseen_flush_queueish is a different method.")
    pair = match.prepare_pair(p, r, e)
    source = next(s for s in pair["observations"] if s["basis"] == "description")
    assert not any("unseen_flush_queueish" in segment for segment in source["segments"])


@pytest.mark.parametrize("path,expected", [
    ("QuillFlow.runtime.flush_queue", True), ("foreign.flush_queue", False),
    ("foo.QuillFlow.runtime.flush_queue", False), ("QuillFlowWrapper.flush_queue", False),
    ("QuillFlow.runtime.flush_queueish", False),
])
def test_bare_method_qualified_spelling_requires_exact_declared_namespace(path, expected):
    p = point(["QuillFlow flush_queue"]); r, e = lesson(f"This lesson demonstrates {path} with a worked example.")
    pair = match.prepare_pair(p, r, e)
    actual = match.validate_decision(p, r, e, verdict(pair))
    assert bool(actual and actual["supports"]) is expected
