"""Query selection only: original targets and all admission checks stay intact."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from backend.app.models import SearchRequest
from backend.app.queries import video_recovery_search_phrases_with_diagnostics as plan


@pytest.mark.parametrize("topic,owner,hints", [
    ("状态管理与生命周期推断", "Rust", ["Rust state management lifetime inference", "Rust state management borrow lifetimes"]),
    ("文本分段与去重", "Python", ["Python text splitting deduplication", "Python text segmentation duplicate removal"]),
    ("表单输入校验与提交控制", "Streamlit", ["Streamlit form input validation submission", "Streamlit form inputs submit control"]),
    ("HashMap 遍历与文件下载", "Rust", ["Rust HashMap iteration file download", "Rust HashMap traversal download files"]),
])
@pytest.mark.parametrize("reverse", [False, True])
def test_two_complete_valid_leads_displace_partial_translation(topic, owner, hints, reverse):
    req=SearchRequest(knowledge_points=[topic],topic_technologies={topic:owner})
    before=deepcopy(req.model_dump())
    values=list(reversed(hints)) if reverse else hints
    phrases,diag=plan(topic,req,values)
    assert phrases[0] == owner+" "+topic
    assert set(phrases[1:]) == set(hints)
    assert len(phrases)==3 and diag["accepted_hints"]==2
    assert diag["phrase_kinds"]==["original","model","model"]
    assert req.model_dump()==before


@pytest.mark.parametrize("topic,owner,hint", [
    ("借用检查与生命周期推断","Rust","Rust 借用检查 生命周期推断"),
    ("文本分段以及去重","Python","Python 文本分段 去重"),
    ("表单输入校验与提交控制","Streamlit","Streamlit 表单输入校验 提交控制"),
    ("借用检查与生命周期推断","Rust","Rust 借用检查、生命周期推断"),
])
def test_connector_only_restatement_is_duplicate(topic,owner,hint):
    req=SearchRequest(knowledge_points=[topic],topic_technologies={topic:owner})
    phrases,diag=plan(topic,req,[hint])
    assert phrases[0]==owner+" "+topic
    assert hint not in phrases and diag["accepted_hints"]==0
    assert diag["rejected_hints"]["duplicate"]==1


def test_chinese_query_is_not_mixed_merely_due_to_its_declared_owner():
    topic="文件下载与权限核对"
    hint="Python 文件下载 权限核对 教学实现"
    req=SearchRequest(knowledge_points=[topic],topic_technologies={topic:"Python"})
    phrases,diag=plan(topic,req,[hint,"Python file download permission validation"])
    assert hint in phrases and "Python file download permission validation" in phrases
    assert diag["accepted_hints"]==2


@pytest.mark.parametrize("hint", ["Streamlit st.form form_submit_button", "Streamlit form validation and submission"])
def test_scope_does_not_relax_existing_operation_checks_or_add_aliases(hint):
    topic="表单输入校验与提交控制"
    req=SearchRequest(knowledge_points=[topic],topic_technologies={topic:"Streamlit"})
    _,diag=plan(topic,req,[hint])
    assert diag["accepted_hints"]==0
    assert diag["rejected_hints"]["operation_not_preserved"]==1


@pytest.mark.parametrize("topic,owner,hint,reason", [
    ("文件下载","C++","C file download","missing_literal"),
    ("PointerEvent 指针捕获与触摸处理","JavaScript","JavaScript pointer capture touch handling","missing_literal"),
    ("CSV转JSON与字段映射","Python","Python JSON to CSV mapping","operation_not_preserved"),
    ("文件下载","Rust","Rust file download site:example.org","invalid_syntax_or_length"),
])
def test_original_safety_owner_api_and_direction_checks_remain(topic,owner,hint,reason):
    req=SearchRequest(knowledge_points=[topic],topic_technologies={topic:owner})
    before=deepcopy(req.model_dump())
    phrases,diag=plan(topic,req,[hint])
    assert diag["accepted_hints"]==0 and diag["rejected_hints"][reason]==1
    assert len(phrases)<=3 and req.model_dump()==before


@pytest.mark.parametrize("row",json.loads((Path(__file__).parent/"fixtures/query_slot_priority/canvas-v4-observed.json").read_text(encoding="utf8")))
def test_actual_canvas_v4_recovery_outputs_keep_english_and_original_api(row):
    req=SearchRequest.model_validate(row["request"])
    before=deepcopy(req.model_dump())
    topic=row["point"]["text"]
    phrases,diag=plan(topic,req,row["replay_hints"])
    english=[hint for hint in row["replay_hints"] if not any("\u4e00"<=c<="\u9fff" for c in hint)]
    assert english and all(hint in phrases for hint in english)
    assert len(phrases)<=3 and req.model_dump()==before
    if "Canvas.toBlob" in topic:
        assert all("Canvas.toBlob" in phrase for phrase in phrases)
    if topic.startswith("Pointer"):
        assert all("Pointer" in phrase for phrase in phrases)
    assert diag["input_hints"]==diag["accepted_hints"]+sum(diag["rejected_hints"].values())
