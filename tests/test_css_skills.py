import json
from pathlib import Path

import pytest

from backend.app.css_skills import css_target_non_teaching, css_target_rule


HERE = Path(__file__).resolve().parent


@pytest.fixture(scope="module")
def ranking():
    from backend.app import ranking
    return ranking


def actual(case):
    return json.loads((HERE / "fixtures" / "css_skills" / f"actual-{case}-catalog.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("target", ["flex 布局与换行", "CSS flex布局和换行", "Flexbox 布局及自动换行"])
def test_flex_exact_target_spellings(target):
    assert css_target_rule(target, "【Flex布局】4.从单行到多行：理解flex-wrap与align-content") == "css_flex_wrap_is_line_wrapping"


@pytest.mark.parametrize("target", ["focus-visible 样式", "CSS :focus-visible 焦点样式", ":focus-visible 伪类样式"])
def test_focus_exact_target_spellings(target):
    assert css_target_rule(target, "focus-visible 合理的控制焦点元素 【CSS 3 技能分享】") == "css_focus_visible_is_focus_styling"


@pytest.mark.parametrize("target,teaching", [
    ("flex 布局与换行及媒体查询", "CSS Flex布局理解 flex-wrap 换行"),
    ("flex 布局与换行", "理解 flex-wrap 与 align-content"),
    ("flex 布局与换行", "CSS Flex布局。理解 flex-wrap 换行"),
    ("flex 布局与换行", "CSS Flex布局\n理解 flex-wrap 换行"),
    ("flex 布局与换行", "https://example.org/CSS/Flex布局 理解 flex-wrap 换行"),
    ("flex 布局与换行", "CSS Flex布局 API列表：flex-wrap、align-content"),
    ("flex 布局与换行", "CSS Flex布局先修要求：已经掌握 flex-wrap 换行"),
    ("flex 布局与换行", "CSS Flex布局 TODO：讲解 flex-wrap 换行"),
    ("flex 布局与换行", "CSS Flex布局不讲解 flex-wrap 换行"),
    ("flex 布局与换行", "CSS Flex布局 does not teach flex-wrap wrapping"),
    ("flex 布局与换行", "React Native CSS Flex布局讲解 flex-wrap 换行"),
    ("flex 布局与换行", "CSS Flex布局理解 flex-wrapper 换行"),
    ("flex 布局与换行", "CSS Flex布局理解 object.flex-wrap 换行"),
    ("flex 布局与换行", "CSS flex-wrap、align-content、gap"),
    ("flex 布局与换行", "CSS Flex布局课后作业：设置 flex-wrap 换行"),
    ("focus-visible 样式与Tab顺序", "CSS :focus-visible 设置焦点样式"),
    ("focus-visible 样式", "focus-visible 控制焦点元素"),
    ("focus-visible 样式", "CSS样式。focus-visible 控制焦点元素"),
    ("focus-visible 样式", "https://example.org/CSS focus-visible 控制焦点元素"),
    ("focus-visible 样式", "CSS focus-visible API list，焦点样式"),
    ("focus-visible 样式", "CSS focus-visible 先修知识：焦点样式"),
    ("focus-visible 样式", "CSS focus-visible 下节讲解焦点样式"),
    ("focus-visible 样式", "CSS focus-visible 不提供焦点样式教学"),
    ("focus-visible 样式", "ReactNative CSS focus-visible 控制焦点样式"),
    ("focus-visible 样式", "CSS not-focus-visible 控制焦点样式"),
    ("focus-visible 样式", "CSS focus-visible-style 控制焦点样式"),
    ("focus-visible 样式", "CSS focus-visible 是属性名称"),
    ("Tab 聚焦顺序", "CSS focus-visible 控制焦点样式"),
    ("Enter/空格触发原生按钮", "CSS focus-visible 控制焦点样式"),
    ("viewport meta", "CSS Flex布局理解 flex-wrap 换行"),
    ("相对单位与媒体查询", "CSS Flex布局理解 flex-wrap 换行"),
])
def test_no_extra_claims_or_unbound_non_teaching(target, teaching):
    assert css_target_rule(target, teaching) is None


@pytest.mark.parametrize("target,clause", [
    ("flex 布局与换行", "本课不讲 flex-wrap"),
    ("flex 布局与换行", "Prerequisite: flex-wrap"),
    ("focus-visible 样式", "CSS focus-visible 不介绍焦点样式"),
    ("focus-visible 样式", "TODO focus-visible"),
])
def test_literal_exclusion_veto_is_not_lost_in_chinese_alias(target, clause):
    assert css_target_non_teaching(target, clause)


@pytest.mark.parametrize("case,wanted,unknown", [
    ("flex", "flex 布局与换行", ["viewport meta", "相对单位与媒体查询"]),
    ("focus", "focus-visible 样式", ["Tab 聚焦顺序", "Enter/空格触发原生按钮"]),
])
def test_actual_retained_catalog_proves_only_own_skill(ranking, case, wanted, unknown):
    row = actual(case)
    assessment = ranking.assess_topic_evidence(row["point"], row["resource"], row["evidence"])
    assert assessment["topic_evidence_status"] == "partial"
    targets = {part["text"]: part for part in assessment["subtopic_coverage"] if part["id"].startswith("learning_target_")}
    assert targets[wanted]["status"] == "supported"
    assert targets[wanted]["evidence_ids"]
    from backend.app.models import SearchRequest
    match = ranking.rank_resource(row["point"], row["resource"], row["evidence"], SearchRequest.model_validate(row["request"]))
    assert match and match["topic_evidence_status"] == "partial"
    matched = {part["text"]: part["status"] for part in match["subtopic_coverage"] if part["id"].startswith("learning_target_")}
    assert matched[wanted] == "supported"
    assert all(matched[missing] == "unknown" for missing in unknown)
    for missing in unknown:
        assert targets[missing]["status"] == "unknown"
        assert not targets[missing]["evidence_ids"]


def test_sibling_catalog_cannot_donate_css_context(ranking):
    row = actual("flex")
    for chapter in row["resource"]["chapters"]:
        if "flex-wrap" in chapter["title"]:
            chapter["title"] = "4.从单行到多行：理解flex-wrap与align-content"
    assessment = ranking.assess_topic_evidence(row["point"], row["resource"], row["evidence"])
    assert not assessment or not any(part["text"] == "flex 布局与换行" and part["status"] == "supported" for part in assessment["subtopic_coverage"])


@pytest.mark.parametrize("case", ["flex", "focus"])
def test_wrong_catalog_page_url_cannot_supply_css_skill(ranking, case):
    row = actual(case)
    # Isolate catalog authority: the focus resource also has an independently
    # verified page title that is sufficient without its catalog.
    row["evidence"] = [item for item in row["evidence"]
                       if not (item["kind"] == "page" and item.get("field") in {"title", "description"})]
    for evidence in row["evidence"]:
        if evidence["kind"] == "catalog":
            evidence["url"] = "https://www.bilibili.com/video/BV1111111111/"
    assessment = ranking.assess_topic_evidence(row["point"], row["resource"], row["evidence"])
    assert not assessment or not any(part["id"].startswith("learning_target_") and part["status"] == "supported" for part in assessment["subtopic_coverage"])


def test_own_verified_page_title_does_not_need_catalog(ranking):
    row = actual("focus")
    row["evidence"] = [item for item in row["evidence"] if item["kind"] != "catalog"]
    assessment = ranking.assess_topic_evidence(row["point"], row["resource"], row["evidence"])
    assert any(part["text"] == "focus-visible 样式" and part["status"] == "supported"
               for part in assessment["subtopic_coverage"])


@pytest.mark.parametrize("case,denial", [
    ("flex", "本课不讲 flex-wrap"),
    ("focus", "本课不教 focus-visible 焦点样式"),
])
def test_positive_title_cannot_override_own_literal_denial(ranking, case, denial):
    row = actual(case)
    row["resource"]["description"] = denial
    provenance = row["resource"]["field_provenance"]["description"]
    for evidence in row["evidence"]:
        if evidence.get("evidence_id") == provenance["evidence_id"]:
            evidence["text"] = denial
    assessment = ranking.assess_topic_evidence(row["point"], row["resource"], row["evidence"])
    assert not assessment or not any(part["id"].startswith("learning_target_") and part["status"] == "supported" for part in assessment["subtopic_coverage"])
