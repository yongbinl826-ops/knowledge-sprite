"""Only the currently bound observed heading can identify its own teaching owner."""
from copy import deepcopy
from pathlib import Path
import json
import pytest
from backend.app import teaching_match
from test_topic_pointer_owner import own_pair

ACTUAL = json.loads((Path(__file__).parent / "fixtures/phase3_pointer_owner/retained_dashboard_auxiliary.json").read_text(encoding="utf-8"))


def test_actual_requested_owner_chapter_retains_pointer_despite_auxiliary_data_tool():
    before = deepcopy(ACTUAL)
    item = ACTUAL["entry"]
    pair = teaching_match.prepare_pair(ACTUAL["point"], item["resource"], item["evidence"], ACTUAL["student_level"])
    assert pair
    assert teaching_match.topic_pointers(pair) == [item["pointer"]]
    assert ACTUAL == before


@pytest.mark.parametrize("body", [
    "Test data was generated with CopperForge software.",
    "示例数据通过QuillForge工具生成。",
    "另用AuroraChip芯片作为辅助输入设备。",
])
def test_current_requested_owner_heading_is_not_vetoed_by_auxiliary_tool(body):
    _, _, _, pair = own_pair(body, title="pygame 状态机设计与转移")
    assert pair and teaching_match.topic_pointers(pair)


def test_parent_title_cannot_donate_owner_to_foreign_current_heading():
    p, r, e, _ = own_pair("本课采用QuillForge软件构建状态图。", title="QuillForge软件 状态机设计与转移")
    r["title"] = "pygame 状态机设计与转移系列"
    next(row for row in e if row.get("field") == "title")["text"] = r["title"]
    pair = teaching_match.prepare_pair(p, r, e)
    assert pair and teaching_match.topic_pointers(pair) == []


def test_other_chapter_cannot_donate_requested_owner():
    p, r, e, _ = own_pair("本课采用QuillForge软件构建状态图。")
    r["chapters"].append({**r["chapters"][0], "title": "pygame 状态机设计与转移", "evidence_id": "other"})
    e.append({**e[-1], "evidence_id": "other", "field": "chapters.1", "text": json.dumps(r["chapters"][1],ensure_ascii=False)})
    pair = teaching_match.prepare_pair(p, r, e)
    assert pair
    pointers = teaching_match.topic_pointers(pair)
    assert not any(x["quote"] == "状态机设计与转移" for x in pointers)


def test_negative_owner_mention_in_current_heading_is_not_permission():
    _, _, _, pair = own_pair("本课采用QuillForge软件构建状态图。", title="不使用pygame 状态机设计与转移")
    assert pair and teaching_match.topic_pointers(pair) == []


def test_url_only_owner_mention_cannot_donate_context():
    _, _, _, pair = own_pair("本课采用QuillForge软件构建状态图。 https://example.com/pygame")
    assert pair and teaching_match.topic_pointers(pair) == []
