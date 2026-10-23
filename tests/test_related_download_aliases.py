"""Download vocabulary only admits source-bound related references."""
import pytest
from backend.app.related_recommendations import related_recommendation
from test_related_input_document_aliases import bound_page


@pytest.mark.parametrize("alias", ["图像下载按钮", "下载按钮", "上传下载文件", "上传下载大文件",
    "st.download_button", "streamlit.download_button", "st.download_button(label)",
    "Download Button", "Downloading Zip Files from AWS S3", "export PDF files"])
@pytest.mark.parametrize("kind", ["page", "catalog"])
def test_download_alias_has_own_technology_and_is_never_exact_teaching(alias, kind):
    args = bound_page("文件下载", "Streamlit", "Streamlit 视频课程" if kind == "catalog" else "Streamlit " + alias)
    if kind == "catalog":
        args[2].append({"evidence_id": "own-download", "kind": "catalog", "field": "chapters.2",
            "source": "html.video.pages", "url": args[1]["canonical_url"], "text": {"title": alias}})
    result = related_recommendation(*args)
    assert result and result["reference"]["basis"] == [kind]
    assert result["reference"]["technical_context"] == "observed"
    assert result["reference"]["exact_teaching_verified"] is False


@pytest.mark.parametrize("title", ["Django 下载按钮", "Python 下载按钮", "Streamlit 文件上传",
    "Streamlit 从GitHub下载学习资料", "Streamlit 安装教程", "Streamlit 下载器安装",
    "Streamlit my.st.download_button", "Streamlit st.download_button_other",
    "Streamlit 不讲下载按钮", "Streamlit 不包含上传下载大文件", "Streamlit st.download_button is not covered"])
def test_unrelated_missing_technology_and_explicit_noncoverage_are_rejected(title):
    assert related_recommendation(*bound_page("文件下载", "Streamlit", title)) is None


@pytest.mark.parametrize("mode", ["query", "foreign", "missing-source", "unindexed"])
def test_unbound_download_alias_cannot_supply_page_or_catalog_facts(mode):
    args = bound_page("文件下载", "Streamlit", "Streamlit 视频课程")
    if mode == "query":
        args[2][0]["query"] = "Streamlit 下载按钮"
    else:
        row = {"evidence_id": "invalid", "kind": "catalog", "field": "chapters.2",
            "source": "html.video.pages", "url": args[1]["canonical_url"], "text": {"title": "下载按钮"}}
        if mode == "foreign": row["url"] = "https://example.org/other"
        elif mode == "missing-source": row["source"] = ""
        else: row["field"] = "chapters.related"
        args[2].append(row)
    assert related_recommendation(*args) is None
