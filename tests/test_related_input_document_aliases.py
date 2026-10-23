"""General input/template terminology remains a bound related-reference hint."""
from copy import deepcopy

import pytest

from backend.app.related_recommendations import related_recommendation
from test_related_recommendations import candidate


FORM = ("表单输入", "Streamlit")
DOCUMENT = ("Word 文档模板填充", "python-docx")


def bound_page(point, technology, title, description=""):
    args = candidate(technology + "视频课程", name=point, technology=technology)
    _, resource, evidence, _ = args
    url = resource["canonical_url"]
    resource.update(title=title, fetch_status="fetched", metadata_evidence_level="page")
    evidence.append({"evidence_id": "own-title", "kind": "page", "field": "title",
                     "source": "html.title", "url": url, "text": title})
    if description:
        evidence.append({"evidence_id": "own-description", "kind": "page", "field": "description",
                         "source": "html.description", "url": url, "text": description})
    return args


@pytest.mark.parametrize("point,technology,title", [
    (*FORM, "Streamlit 输入类控件"),
    (*FORM, "Streamlit 常用控件-输入类"),
    (*FORM, "Streamlit 输入控件"),
    (*FORM, "Streamlit text_input"),
    (*FORM, "Streamlit st.text_input(label)"),
    (*FORM, "Streamlit form input widgets"),
    (*FORM, "Streamlit Email Form Using Python"),
    (*FORM, "Streamlit contact forms"),
    (*FORM, "Streamlit forms tutorial"),
    (*FORM, "Streamlit input widgets"),
    (*FORM, "Streamlit st.form"),
    (*DOCUMENT, "python-docx 更新docx模板文档"),
    (*DOCUMENT, "python-docx docx模板填充"),
    (*DOCUMENT, "python-docx 自动生成Word报告，自动填充数据"),
    (*DOCUMENT, "python-docx 模板填充"),
    (*DOCUMENT, "python-docx document template replacement"),
])
def test_bound_page_aliases_are_references_not_exact_teaching(point, technology, title):
    args = bound_page(point, technology, title)
    before = deepcopy(args[:3])
    result = related_recommendation(*args)
    assert result
    assert result["reference"]["basis"] == ["page"]
    assert result["reference"]["technical_context"] == "observed"
    assert result["reference"]["exact_teaching_verified"] is False
    assert "own-title" in result["reference"]["evidence_ids"]
    assert args[:3] == before


@pytest.mark.parametrize("point,technology,chapter", [
    (*FORM, "输入类控件"), (*FORM, "控件-输入类"), (*FORM, "text_input"),
    (*FORM, "Email Form Using Python"), (*FORM, "contact form"), (*FORM, "input widgets"),
    (*DOCUMENT, "更新docx模板文档"), (*DOCUMENT, "模板填充"), (*DOCUMENT, "template replacement"),
])
def test_owned_chapter_can_use_observed_own_course_technology(point, technology, chapter):
    args = bound_page(point, technology, technology + "视频课程")
    _, resource, evidence, _ = args
    evidence.append({"evidence_id": "own-chapter", "kind": "catalog", "field": "chapters.2",
        "source": "html.video.pages", "url": resource["canonical_url"], "text": {"title": chapter}})
    result = related_recommendation(*args)
    assert result and result["reference"]["basis"] == ["catalog"]
    assert {"own-title", "own-chapter"} <= set(result["reference"]["evidence_ids"])
    assert result["reference"]["exact_teaching_verified"] is False


@pytest.mark.parametrize("chapter", ["Email Form Using Flet", "Gradio contact form", "Dash input widgets",
                                    "Email Form Using Python", "contact form"])
def test_mixed_course_cannot_lend_streamlit_context_to_competing_chapter(chapter):
    args = bound_page(*FORM, "Python apps: Streamlit, Flet, Gradio, Dash")
    args[2].append({"evidence_id": "other-technology", "kind": "catalog", "field": "chapters.2",
        "source": "html.video.pages", "url": args[1]["canonical_url"], "text": {"title": chapter}})
    assert related_recommendation(*args) is None
    args[2].append({"evidence_id": "own-form", "kind": "catalog", "field": "chapters.7",
        "source": "html.video.pages", "url": args[1]["canonical_url"], "text": {"title": "Streamlit Email Form Using Python"}})
    result = related_recommendation(*args)
    assert result and "own-form" in result["reference"]["evidence_ids"]
    assert "other-technology" not in result["reference"]["evidence_ids"]


@pytest.mark.parametrize("point,technology,title", [
    (*FORM, "Streamlit 文件上传"), (*FORM, "Streamlit output widgets"),
    (*FORM, "Django 输入类控件"), (*FORM, "Streamlit myst.text_input_other"),
    (*FORM, "Streamlit 数据图表"),
    (*FORM, "Django contact form"), (*FORM, "Streamlit data formatting"),
    (*FORM, "Streamlit UI: form a team"), (*FORM, "Streamlit st.form_submit_button_other"),
    (*DOCUMENT, "python-docx 创建并保存文档"),
    (*DOCUMENT, "python-docx 文件复制与替换"),
    (*DOCUMENT, "Jinja2 HTML template replacement"),
    (*DOCUMENT, "Python template replacement"),
])
def test_generic_files_other_topics_and_missing_technology_are_not_promoted(point, technology, title):
    assert related_recommendation(*bound_page(point, technology, title)) is None


@pytest.mark.parametrize("point,technology,alias", [(*FORM, "输入类控件"), (*DOCUMENT, "更新docx模板文档")])
@pytest.mark.parametrize("mode", ["query", "foreign", "missing-source", "unindexed-catalog"])
def test_query_echo_or_unbound_observation_cannot_supply_alias(point, technology, alias, mode):
    args = bound_page(point, technology, technology + "视频课程")
    _, resource, evidence, _ = args
    if mode == "query":
        evidence[0]["query"] = technology + " " + alias
    else:
        evidence.append({"evidence_id": "attempted-alias", "kind": "catalog", "field": "chapters.2",
            "source": "html.video.pages", "url": resource["canonical_url"], "text": {"title": alias}})
        if mode == "foreign":
            evidence[-1]["url"] = "https://example.org/other-course"
        elif mode == "missing-source":
            evidence[-1]["source"] = ""
        else:
            evidence[-1]["field"] = "chapters.related"
    assert related_recommendation(*args) is None


@pytest.mark.parametrize("point,technology,title", [
    (*FORM, "Streamlit 不讲输入类控件"),
    (*FORM, "Streamlit form input widgets are not covered"),
    (*FORM, "Streamlit contact form is not covered"),
    (*DOCUMENT, "python-docx 不包含模板填充"),
    (*DOCUMENT, "python-docx Word模板填充 is not covered"),
    (*DOCUMENT, "python-docx template replacement is not covered"),
])
def test_explicit_noncoverage_blocks_alias_even_with_lexical_overlap(point, technology, title):
    assert related_recommendation(*bound_page(point, technology, title)) is None


@pytest.mark.parametrize("point,technology,alias", [(*FORM, "输入类控件"), (*DOCUMENT, "模板填充")])
def test_current_own_title_noncoverage_outweighs_positive_search_excerpt(point, technology, alias):
    args = bound_page(point, technology, technology + " 不讲" + alias)
    args[2][0].update(title=technology + " " + alias, snippet="")
    assert related_recommendation(*args) is None


@pytest.mark.parametrize("point,technology,alias", [(*FORM, "输入类控件"), (*DOCUMENT, "模板填充")])
@pytest.mark.parametrize("invalid", ["foreign", "missing-source", "query-only"])
def test_unbound_negative_cannot_veto_current_positive_page(point, technology, alias, invalid):
    args = bound_page(point, technology, technology + " " + alias)
    _, resource, evidence, _ = args
    negative = {"evidence_id": "untrusted-negative", "kind": "page", "field": "title",
                "source": "html.title", "url": resource["canonical_url"], "text": technology + " 不讲" + alias}
    if invalid == "foreign":
        negative["url"] = "https://example.org/foreign"
    elif invalid == "missing-source":
        negative["source"] = ""
    else:
        negative.update(kind="search", title=technology + "视频课程", text="", query=negative["text"])
    evidence.append(negative)
    result = related_recommendation(*args)
    assert result and result["reference"]["exact_teaching_verified"] is False
    assert "untrusted-negative" not in result["reference"]["evidence_ids"]
