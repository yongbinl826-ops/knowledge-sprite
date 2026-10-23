"""Own charging flag is a restriction, even when legacy rights are zero."""
import json

import pytest

from test_bilibili_embedded_parts import SOURCE, URL, extract, markup, payload


def charging_payload():
    data = payload()
    # Shape observed in the complete public page and its charging/preview UI.
    data["videoData"].update(is_upower_exclusive=True, is_upower_preview=True,
        is_upower_play=False, is_chargeable_season=False,
        rights={"pay": 0, "ugc_pay": 0, "ugc_pay_preview": 0, "arc_pay": 0, "free_watch": 0})
    return data


@pytest.mark.parametrize("preview", [True, False])
@pytest.mark.parametrize("pages", ["valid", "missing", "invalid"])
def test_own_exclusive_flag_requires_payment_despite_preview_or_zero_legacy_rights(preview, pages):
    data = charging_payload()
    data["videoData"]["is_upower_preview"] = preview
    if pages == "missing": data["videoData"].pop("pages")
    if pages == "invalid": data["videoData"]["pages"] = "invalid"
    result = extract(markup(data))
    assert result["fetch_status"] == "fetched" and result["video_evidence_status"] == "page_verified"
    assert result["requires_payment"] is True
    provenance = result["field_provenance"]["requires_payment"]
    assert provenance["source"] == SOURCE + ".is_upower_exclusive" and provenance["url"] == URL
    evidence = next(row for row in result["evidence"] if row["evidence_id"] == provenance["evidence_id"])
    assert evidence["kind"] == "page" and evidence["field"] == "requires_payment"
    assert json.loads(evidence["text"]) == {"bvid": data["videoData"]["bvid"], "is_upower_exclusive": True}


@pytest.mark.parametrize("value", [None, False, 0, 1, "true", "1", {}, []])
def test_absent_false_or_wrong_type_exclusive_flag_preserves_unknown(value):
    data = charging_payload()
    if value is None:
        data["videoData"].pop("is_upower_exclusive")
    else:
        data["videoData"]["is_upower_exclusive"] = value
    result = extract(markup(data))
    assert result.get("requires_payment") is None
    assert "requires_payment" not in result["field_provenance"]


@pytest.mark.parametrize("mode", ["foreign-video", "recommendation", "season", "description", "dom", "script-string"])
def test_foreign_or_unbound_charging_flag_is_not_own_payment_evidence(mode):
    data = payload()
    extra = ""
    if mode == "foreign-video":
        data = charging_payload()
        data["videoData"]["bvid"] = "BV1OTHER0000"
    elif mode == "recommendation":
        data["recommendations"] = [charging_payload()["videoData"]]
    elif mode == "season":
        data["videoData"]["ugc_season"] = charging_payload()["videoData"]
    elif mode == "description":
        data["videoData"]["desc"] = "is_upower_exclusive=true，讲解充电专属视频功能"
    elif mode == "dom":
        extra = '<aside data-is-upower-exclusive="true">中档充电专属推荐视频</aside>'
    else:
        extra = '<script>var example="is_upower_exclusive=true";</script>'
    result = extract(markup(data, extra=extra))
    assert result.get("requires_payment") is None
    assert "requires_payment" not in result["field_provenance"]


def test_generic_free_jsonld_cannot_override_own_exclusive_flag():
    unrelated = {"@context": "https://schema.org", "@type": "VideoObject", "name": "Other free video",
                 "url": URL, "isAccessibleForFree": True, "offers": {"price": 0}}
    result = extract(markup(charging_payload(), extra='<script type="application/ld+json">' + json.dumps(unrelated) + '</script>'))
    assert result["requires_payment"] is True
    assert result["field_provenance"]["requires_payment"]["source"] == SOURCE + ".is_upower_exclusive"
