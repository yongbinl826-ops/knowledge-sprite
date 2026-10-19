"""Only explicit own software/tool type declarations can veto neutral pointers."""
from pathlib import Path
from copy import deepcopy
import json

import pytest

from backend.app import teaching_match
from test_topic_pointer_acronym_scope import catalog_pair

ACTUAL = json.loads((Path(__file__).parent / "fixtures/phase3_pointer_owner/retained_pong_state_pointers.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("index,retained", [(0, True), (1, False)])
def test_actual_sysblock_untyped_and_fpga_explicit_chip_are_distinguished(index, retained):
    before = deepcopy(ACTUAL)
    item = ACTUAL["entries"][index]
    pair = teaching_match.prepare_pair(ACTUAL["point"], item["resource"], item["evidence"], ACTUAL["student_level"])
    pointers = teaching_match.topic_pointers(pair)
    assert bool(pointers) is retained
    if retained:
        assert pointers == [item["pointer"]]
        assert pointers[0]["missing_components"] == ["游戏状态机设计"]
    assert ACTUAL == before


def own_pair(body, *, skill="状态机设计与转移", title="状态机设计与转移"):
    p, r, e, _ = catalog_pair(skill, title)
    p["technology"] = "pygame"
    p["text"] = "pygame state machine unit"
    r["description"] = body
    next(row for row in e if row.get("field") == "description")["text"] = body
    return p, r, e, teaching_match.prepare_pair(p, r, e)


@pytest.mark.parametrize("body", [
    "FSM tutorial. We explain states and transitions with a diagram.",
    "基于FSM的状态机概念课程，介绍状态图和转移。",
    "State-machine tutorial: states and transitions.",
    "Python programming with Pygame demonstrates state transitions.",
    "Python programming language with Pygame demonstrates state transitions.",
    "Software architecture examples explain state diagrams.",
    "本课不使用FPGA芯片实现状态转换。",
    "本课并非GraphForge软件的使用教程。",
    "Compare FPGA芯片 with state diagrams as background only.",
    "Comparing FPGA芯片 with state diagrams as background only.",
    "A comparison of FPGA芯片 with state diagrams as background only.",
    "FPGA芯片仅用于对比说明。",
])
def test_neutral_concepts_and_own_language_with_framework_are_not_rejected(body):
    _, _, _, pair = own_pair(body)
    assert pair and teaching_match.topic_pointers(pair)


@pytest.mark.parametrize("body", [
    "本课使用AuroraChip芯片和CopperFlow软件实现状态转换。",
    "Rust programming language implements the state machine.",
    "本课使用QuillDesigner框架组织状态机。",
    "本课采用开发工具GraphForge构建状态图。",
])
def test_unseen_explicit_foreign_tool_declaration_vetoes_pointer_only(body):
    p, r, e, pair = own_pair(body)
    assert pair is not None  # identity/teaching eligibility was not rewritten
    assert teaching_match.topic_pointers(pair) == []
    assert p["learning_skills"] == ["状态机设计与转移"]


@pytest.mark.parametrize("owner,body", [
    ("Python", "Python programming language explains state transitions."),
    ("C++", "C++编程语言讲解状态机设计与转移。"),
    ("Quill-Forge", "Quill-Forge软件提供状态机图。"),
])
def test_skill_explicit_owner_overrides_unit_framework(owner, body):
    _, _, _, pair = own_pair(body, skill=owner + " 状态机设计与转移")
    assert pair and teaching_match.topic_pointers(pair)


def test_foreign_url_and_other_catalog_part_cannot_supply_tool_declaration():
    p, r, e, _ = own_pair("A tool-neutral state machine concept lesson.")
    r["chapters"].append({**r["chapters"][0], "title": "ForeignChip芯片开发", "evidence_id": "other-chapter"})
    e.append({**e[-1], "evidence_id": "other-chapter", "field": "chapters.1", "text": json.dumps(r["chapters"][1], ensure_ascii=False)})
    pair = teaching_match.prepare_pair(p, r, e)
    assert pair and any(p["quote"] == "状态机设计与转移" for p in teaching_match.topic_pointers(pair))


def test_parent_language_relation_is_not_invented_across_separate_clauses():
    # Deliberate conservative boundary, not a claim Python and pygame conflict.
    _, _, _, pair = own_pair("Python programming language is introduced. Pygame examples follow.")
    assert pair and teaching_match.topic_pointers(pair) == []
