"""Observed native links remain private leads, not source teaching evidence."""
import html

import pytest

from test_bilibili_embedded_parts import URL, extract, markup, payload


OTHER = "https://www.bilibili.com/video/BV1000000001/"


def anchor(href=OTHER, text="Observed Streamlit course", **attrs):
    properties = " ".join(f'{key}="{html.escape(value, quote=True)}"' for key, value in attrs.items())
    return f'<a href="{html.escape(href, quote=True)}" {properties}>{html.escape(text)}</a>'


def test_native_observed_anchor_is_private_and_does_not_change_own_metadata():
    baseline = extract(markup())
    extra = anchor(OTHER + "?p=3&vd_source=tracking&utm_source=example&uid=42", "[Streamlit] 上传下载大文件")
    result = extract(markup(extra=extra))
    assert result.pop("_video_leads") == [{"url": OTHER + "?p=3", "title": "[Streamlit] 上传下载大文件", "source_url": URL}]
    assert result == baseline
    assert not any("上传下载" in str(row) for row in result["evidence"])


@pytest.mark.parametrize("href,expected", [
    ("/video/BV1000000001/?p=2", OTHER + "?p=2"),
    ("//www.bilibili.com/video/BV1000000001/", OTHER),
    ("https://bilibili.com/video/av12345/?p=1", "https://bilibili.com/video/av12345/?p=1"),
])
def test_relative_native_reference_and_valid_part_are_preserved(href, expected):
    assert extract(markup(extra=anchor(href)))["_video_leads"][0]["url"] == expected


def test_anchor_title_attribute_is_observed_label_when_text_is_empty():
    result = extract(markup(extra=anchor(text="", title="  Streamlit  download buttons  ")))
    assert result["_video_leads"][0]["title"] == "Streamlit download buttons"


@pytest.mark.parametrize("href", [
    URL, URL + "?p=2", URL.replace("www.", "") + "?p=3",
    "https://www.bilibili.com/robots.txt", "https://www.bilibili.com/search?keyword=streamlit",
    "https://search.bilibili.com/all?keyword=streamlit", "https://www.bilibili.com/video/BVshort/",
    "https://www.bilibili.com/video/BV1000000001/extra", "https://b23.tv/abc",
    "https://api.bilibili.com/x/web-interface/view?bvid=BV1000000001",
    "https://m.bilibili.com/video/BV1000000001/", "https://www.bilibili.com.evil.org/video/BV1000000001/",
    "https://example.org/video/BV1000000001/", "http://www.bilibili.com/video/BV1000000001/",
    "https://user:password@www.bilibili.com/video/BV1000000001/",
    "https://www.bilibili.com:80/video/BV1000000001/", "https://127.0.0.1/video/BV1000000001/",
    OTHER + "?token=unknown", OTHER + "?p=1&p=2", OTHER + "?p=0", OTHER + "?p=-1",
    OTHER + "?p=１", OTHER + "?p=", OTHER + "#part", "javascript:alert(1)",
    OTHER + "\\escape", "https://www.bili\nbili.com/video/BV1000000001/",
])
def test_unsafe_foreign_search_unknown_query_and_own_video_are_rejected(href):
    assert "_video_leads" not in extract(markup(extra=anchor(href)))


@pytest.mark.parametrize("text,title", [("", ""), ("x" * 301, ""), ("", "x" * 301)])
def test_nonempty_bounded_observed_label_is_required(text, title):
    assert "_video_leads" not in extract(markup(extra=anchor(text=text, title=title)))


@pytest.mark.parametrize("wrapper", [
    '<div hidden>{}</div>', '<div aria-hidden="true">{}</div>', '<div style="display:none">{}</div>',
    '<template>{}</template>', '<noscript>{}</noscript>', '<script>var links={};</script>',
])
def test_hidden_or_non_dom_script_text_cannot_supply_leads(wrapper):
    assert "_video_leads" not in extract(markup(extra=wrapper.format(anchor())))


def test_json_url_fields_are_not_scanned_and_foreign_video_identity_cannot_enable_leads():
    data = payload()
    data["recommendations"] = [{"url": OTHER, "title": "Streamlit 下载按钮"}]
    assert "_video_leads" not in extract(markup(data))
    data["videoData"]["bvid"] = "BV1000000002"
    assert "_video_leads" not in extract(markup(data, extra=anchor()))
    assert "_video_leads" not in extract('<title>Course video</title><meta property="og:type" content="video">' + anchor())


def test_distinct_link_and_anchor_inspection_limits_are_hard_bounds():
    links = [anchor(f"https://www.bilibili.com/video/BV{index:010}/", f"Observed course {index}") for index in range(30)]
    result = extract(markup(extra="".join(links)))
    assert len(result["_video_leads"]) == 24
    assert result["_video_leads"][-1]["title"] == "Observed course 23"
    # Rejected nodes still consume the original DOM inspection bound.
    junk = anchor("https://example.org/unknown")
    assert "_video_leads" not in extract(markup(extra=junk * 500 + anchor()))
    assert len(extract(markup(extra=junk * 499 + anchor()))["_video_leads"]) == 1


def test_duplicates_after_tracking_host_and_slash_normalization_do_not_consume_slots():
    repeated = anchor(OTHER + "?vd_source=a") + anchor(OTHER.rstrip("/")) + anchor(OTHER.replace("www.", ""))
    result = extract(markup(extra=repeated + anchor(OTHER + "?p=2", "Second observed part")))
    assert [lead["url"] for lead in result["_video_leads"]] == [OTHER, OTHER + "?p=2"]


def test_access_error_page_cannot_collect_navigation_leads():
    assert "_video_leads" not in extract('<title>Verify you are human</title>' + anchor())
