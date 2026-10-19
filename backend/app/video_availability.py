"""Pure derived views for pages whose particular media identity is unconfirmed.

No HTTP, extraction, platform/title blacklist, media probing or persistence.
"""
from __future__ import annotations

from backend.app.url_utils import UnsafeURL, normalize_url, host_matches
from urllib.parse import parse_qs, urlsplit
import re

PAGE_SHELL_NOTICE = "页面需要 JavaScript，当前仅取得页面外壳，具体视频身份和教学内容尚未核对；请到原平台查看。"
PAGE_SHELL_REASON = "page_shell_unconfirmed"
MEDIA_IDENTITY_NOTICE = "已取得页面元数据，但尚无与本链接绑定的视频或课程身份依据，页面教学文字不能替代媒体身份；请到来源确认。"
MEDIA_IDENTITY_REASON = "media_identity_unconfirmed"
# These are extractor/adapter proof kinds, not platform admission rules. Generic
# og:type=video and search media templates never identify a particular page video.
_PAGE_VIDEO_PROOFS = frozenset({
    "jsonld.VideoObject",
    "html.bilibili.__INITIAL_STATE__.videoData.bvid",
    "html.freecodecamp.course_announcement.video",
    "html.techwithtim.lesson.video",
})


def _target(resource: dict) -> str | None:
    try:
        target = normalize_url(resource.get("canonical_url") or resource.get("url") or "")
        if resource.get("url") and normalize_url(resource["url"]) != target:
            return None
        return target
    except (UnsafeURL, ValueError, TypeError):
        return None


def _same_url(value, target: str | None) -> bool:
    if not target or not isinstance(value, str):
        return False
    try:
        return normalize_url(value) == target
    except (UnsafeURL, ValueError, TypeError):
        return False


def _bound_page_video(resource: dict, evidence: list[dict]) -> bool:
    if resource.get("video_evidence_status") != "page_verified" or resource.get("metadata_evidence_level") not in {"page", "catalog"}:
        return False
    target = _target(resource)
    proof = (resource.get("field_provenance") or {}).get("video_evidence_status")
    if not isinstance(proof, dict) or proof.get("source") not in _PAGE_VIDEO_PROOFS or not _same_url(proof.get("url"), target):
        return False
    return any(row.get("evidence_id") and row.get("evidence_id") == proof.get("evidence_id")
               and row.get("kind") == "page" and row.get("field") == "video_evidence_status"
               and row.get("source") == proof.get("source") and _same_url(row.get("url"), target)
               for row in evidence)


def is_unconfirmed_video_shell(resource: dict, evidence: list[dict]) -> bool:
    return resource.get("fetch_status") == "javascript_required" and not _bound_page_video(resource, evidence)


def project_unconfirmed_video_shell(resource: dict, evidence: list[dict]) -> dict:
    """Return a display copy, retaining exact raw URLs and original evidence.

    A same-resource search media record can restore its observed specific title;
    it does not thereby become current-page identity or teaching evidence.
    """
    if not is_unconfirmed_video_shell(resource, evidence):
        return resource
    target = _target(resource)
    projected = dict(resource)
    previous = resource.get("access_notice")
    projected["access_notice"] = (previous if isinstance(previous, str) and PAGE_SHELL_NOTICE in previous else
                                  previous + " " + PAGE_SHELL_NOTICE if isinstance(previous, str) and previous.strip() else PAGE_SHELL_NOTICE)
    for row in evidence:
        title = row.get("title")
        if (row.get("kind") == "search" and row.get("source") and row.get("evidence_id")
                and row.get("type_source") == "search_template"
                and row.get("resource_type_hint") in {"video", "playlist"}
                and isinstance(title, str) and title.strip() and _same_url(row.get("url"), target)):
            projected["title"] = title
            projected["field_provenance"] = dict(resource.get("field_provenance") or {})
            projected["field_provenance"]["title"] = {
                "source": "search", "evidence_id": row["evidence_id"], "url": row["url"],
                "note": "保留同一规范化链接的原始搜索标题；当前页面外壳不能核对具体视频。",
            }
            break
    return projected


def unconfirmed_video_shell_assessment(assessment: dict | None, resource: dict, evidence: list[dict]) -> dict | None:
    """Downgrade an already-relevant assessment; never invent a candidate hit."""
    if assessment is None or not is_unconfirmed_video_shell(resource, evidence):
        return assessment
    target = _target(resource)
    ids = list(dict.fromkeys(row["evidence_id"] for row in evidence if row.get("evidence_id")
        and row.get("kind") == "page" and _same_url(row.get("url"), target)
        and row.get("field") in {"title", "fetch_status"}))
    return {**assessment, "topic_evidence_status": "needs_review", "supporting_evidence_ids": [],
        "topic_evidence_reasons": [{"code": PAGE_SHELL_REASON, "message": PAGE_SHELL_NOTICE, "evidence_ids": ids}],
        "subtopic_coverage": [{**part, "status": "unknown", "evidence_ids": [],
            "reason": "仅取得页面外壳，先前搜索信息不能核对当前具体视频教学内容。"}
            for part in assessment.get("subtopic_coverage", [])]}


def _bound_media_field(resource: dict, evidence: list[dict], field: str, sources: set[str]) -> bool:
    target = _target(resource)
    origin = (resource.get("field_provenance") or {}).get(field) or {}
    return (origin.get("source") in sources and _same_url(origin.get("url"), target)
        and any(row.get("evidence_id") == origin.get("evidence_id") and row.get("evidence_id")
            and row.get("kind") == "page" and row.get("field") == field
            and row.get("source") == origin.get("source") and _same_url(row.get("url"), target)
            and row.get("text") == resource.get(field) for row in evidence))


def native_media_entry_type(url: str) -> str:
    """Existing native entry grammar, never a playback or access assertion."""
    try:
        parsed = urlsplit(normalize_url(url))
    except (UnsafeURL, ValueError, TypeError):
        return "unknown"
    host, path = parsed.hostname or "", parsed.path
    if host_matches(host, "bilibili.com") and re.fullmatch(r"/video/(?:BV[0-9A-Za-z]{10}|av\d+)/?", path):
        return "video"
    if host_matches(host, "icourse163.org") and re.fullmatch(r"/(?:course|learn)/(?:[A-Za-z0-9_-]*-)?\d+/?", path):
        return "course"
    if host_matches(host, "xuetangx.com") and re.fullmatch(r"/course/[A-Za-z0-9_-]+/?", path):
        return "course"
    if host in {"youtube.com", "www.youtube.com", "m.youtube.com"} and path == "/watch":
        ids = parse_qs(parsed.query, keep_blank_values=True).get("v", [])
        if len(ids) == 1 and re.fullmatch(r"[A-Za-z0-9_-]{11}", ids[0]):
            return "video"
    if host in {"youtu.be", "www.youtu.be"} and re.fullmatch(r"/[A-Za-z0-9_-]{11}/?", path):
        return "video"
    return "unknown"


# Registered extractors write explanatory excerpts for these own type fields.
# The type/domain/source binding is separate from the teaching-content gate.
_ADAPTER_TYPE_SOURCES = {
    "html.bilibili.__INITIAL_STATE__.videoData.bvid": ("video", {"bilibili.com"}),
    "html.bilibili.video_pod.multip": ("video", {"bilibili.com"}),
    "html.freecodecamp.course_announcement.video": ("video", {"freecodecamp.org"}),
    "html.techwithtim.lesson.video": ("video", {"techwithtim.net"}),
    "html.mit_ocw.video_player": ("video", {"ocw.mit.edu"}),
    "html.mit_ocw.video_gallery": ("playlist", {"ocw.mit.edu"}),
    "html.archive.play_av.playlist": ("playlist", {"archive.org"}),
    "html.mit_ocw.course_home": ("course", {"ocw.mit.edu"}),
    "html.microsoft_ai.curriculum_table": ("course", {"microsoft.github.io"}),
    "html.icourse163.course_structure": ("course", {"icourse163.org"}),
    "html.icourse163.embedded_course_structure": ("course", {"icourse163.org"}),
}


def _bound_adapter_media_type(resource: dict, evidence: list[dict]) -> bool:
    target = _target(resource)
    origin = (resource.get("field_provenance") or {}).get("resource_type") or {}
    contract = _ADAPTER_TYPE_SOURCES.get(origin.get("source"))
    if not target or not contract or resource.get("resource_type") != contract[0]:
        return False
    if not any(host_matches(urlsplit(target).hostname or "", domain) for domain in contract[1]):
        return False
    return _same_url(origin.get("url"), target) and any(
        row.get("evidence_id") and row.get("evidence_id") == origin.get("evidence_id")
        and row.get("kind") == "page" and row.get("field") == "resource_type"
        and row.get("source") == origin.get("source") and _same_url(row.get("url"), target)
        and isinstance(row.get("text"), str) and bool(row["text"].strip()) for row in evidence)


def _bound_native_media_entry(resource: dict, evidence: list[dict]) -> bool:
    target = _target(resource)
    if not target or native_media_entry_type(target) != resource.get("resource_type"):
        return False
    # Discovery provenance must cite an actual same-resource search row; a
    # forged source label on a generic article does not make a native entry.
    origins = resource.get("field_provenance") or {}
    fields = ["resource_type"]
    if resource.get("video_evidence_status") == "search_discovered":
        fields.append("video_evidence_status")
    for field in fields:
        origin = origins.get(field) or {}
        if origin.get("source") == "url_pattern" and _same_url(origin.get("url"), target) and any(
            row.get("kind") == "search" and row.get("source") and row.get("evidence_id")
            and row.get("evidence_id") == origin.get("evidence_id") and _same_url(row.get("url"), target)
            for row in evidence):
            return True
    return False


def is_unconfirmed_fetched_media(resource: dict, evidence: list[dict]) -> bool:
    """A teaching page alone cannot confirm a search-template media identity.

    Independently bound own types, registered source structure, explicit own
    video labels and native course/video entries retain the existing contract.
    No access restriction or lack of playback verification is called invalid.
    """
    media_type = resource.get("resource_type")
    if media_type not in {"video", "course", "playlist"} or resource.get("fetch_status") not in {"fetched", "success"}:
        return False
    if _bound_native_media_entry(resource, evidence):
        return False
    if resource.get("metadata_evidence_level") not in {"page", "catalog"}:
        return True
    if _bound_media_field(resource, evidence, "resource_type", {"jsonld.@type", "meta.og:type"}):
        # og:type parsing only emits video; Course is a JSON-LD type, not an
        # arbitrary og media label. Typed value equality was checked above.
        source = ((resource.get("field_provenance") or {}).get("resource_type") or {}).get("source")
        if source == "jsonld.@type" and media_type in {"video", "course"} or source == "meta.og:type" and media_type == "video":
            return False
    if _bound_adapter_media_type(resource, evidence):
        return False
    # Page VideoObject identity can coexist with a discovery type field.
    if (media_type == "video" and _bound_page_video(resource, evidence)
            and _bound_media_field(resource, evidence, "video_evidence_status", {"jsonld.VideoObject"})):
        return False
    title = resource.get("title") or ""
    label = re.compile(r"^(?:\[video\]|\(video\)|video\s*[:：]|\[视频\]|【视频】|视频\s*[:：])\s*\S|(?:\(video\)|\[video\]|【视频】)\s*$", re.I)
    if (media_type == "video" and isinstance(title, str) and label.search(title)
            and _bound_media_field(resource, evidence, "title", {"html.title", "html.h1", "meta.og:title", "jsonld.name"})):
        return False
    return True


def project_unconfirmed_fetched_media(resource: dict, evidence: list[dict]) -> dict:
    if not is_unconfirmed_fetched_media(resource, evidence):
        return resource
    previous = resource.get("access_notice")
    return {**resource, "access_notice": previous if isinstance(previous, str) and MEDIA_IDENTITY_NOTICE in previous
        else (previous + " " + MEDIA_IDENTITY_NOTICE if isinstance(previous, str) and previous.strip() else MEDIA_IDENTITY_NOTICE)}


def unconfirmed_fetched_media_assessment(assessment: dict | None, resource: dict, evidence: list[dict]) -> dict | None:
    if assessment is None or not is_unconfirmed_fetched_media(resource, evidence):
        return assessment
    target = _target(resource)
    ids = list(dict.fromkeys(row["evidence_id"] for row in evidence if row.get("evidence_id")
        and _same_url(row.get("url"), target) and (row.get("kind") == "search" or row.get("field") == "title")))
    return {**assessment, "topic_evidence_status": "needs_review", "supporting_evidence_ids": [],
        "topic_evidence_reasons": [{"code": MEDIA_IDENTITY_REASON, "message": MEDIA_IDENTITY_NOTICE, "evidence_ids": ids}],
        "subtopic_coverage": [{**part, "status": "unknown", "evidence_ids": [],
            "reason": "页面教学文字不等于视频身份；确认本条视频身份后再核对视频技能覆盖。"}
            for part in assessment.get("subtopic_coverage", [])]}
