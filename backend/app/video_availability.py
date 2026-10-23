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
        if resource.get("url") and not _same_url(resource["url"], target):
            return None
        return target
    except (UnsafeURL, ValueError, TypeError):
        return None


def _bili_part_identity(value) -> tuple[str, str, str | None] | None:
    """Only native HTTPS BV paths; a trailing slash cannot change this part.

    Reuse established tracking normalization while preserving raw native p
    syntax, unknown query rejection, fragments, host and part boundaries.
    This compares public metadata identity and performs no fetch or URL rewrite.
    """
    if not isinstance(value, str) or value != value.strip():
        return None
    try:
        normalized = normalize_url(value)
        parts = urlsplit(value)
        if (parts.scheme != "https" or parts.hostname not in {"www.bilibili.com", "m.bilibili.com", "bilibili.com"}
                or parts.port not in {None, 443} or parts.username is not None or parts.password is not None
                or parts.fragment):
            return None
        # Keep the raw host/path boundary; only already-known tracking fields
        # may disappear from the query used to compare the media identity.
        prefix = r"/(?:zh-Hans/)?video/" if parts.hostname in {"www.bilibili.com", "bilibili.com"} else r"/video/"
        path = re.fullmatch(prefix + r"(BV[0-9A-Za-z]{10})/?", parts.path)
        query = urlsplit(normalized).query
        part = re.fullmatch(r"p=([1-9][0-9]*)", query) if query else None
        if not path or (query and (part is None or query not in parts.query.split("&"))):
            return None
        return parts.hostname, path[1], part[1] if part else None
    except (UnsafeURL, ValueError, TypeError):
        return None


def _same_url(value, target: str | None) -> bool:
    if not target or not isinstance(value, str):
        return False
    try:
        if normalize_url(value) == target:
            return True
        identity = _bili_part_identity(value)
        return identity is not None and identity == _bili_part_identity(target)
    except (UnsafeURL, ValueError, TypeError):
        return False


def _bound_page_video(resource: dict, evidence: list[dict]) -> bool:
    if resource.get("video_evidence_status") != "page_verified" or resource.get("metadata_evidence_level") not in {"page", "catalog"}:
        return False
    target = _target(resource)
    proof = (resource.get("field_provenance") or {}).get("video_evidence_status")
    if not isinstance(proof, dict) or not _same_url(proof.get("url"), target):
        return False
    multipart = proof.get("source") == "html.bilibili.video_pod.multip"
    if multipart:
        # The registered selector proves media identity only on its own native
        # BV/part page, with a separately bound video type. Generic og:video
        # alone, search labels, or another part cannot supply this proof.
        native = _bili_part_identity(resource.get("canonical_url") or resource.get("url"))
        type_proof = (resource.get("field_provenance") or {}).get("resource_type") or {}
        if (not native or not isinstance(type_proof, dict)
                or resource.get("fetch_status") not in {"fetched", "success"}
                or resource.get("resource_type") != "video"
                or any(_bili_part_identity(value) != native for value in
                       (resource.get("url"), resource.get("resolved_url") or resource.get("url"),
                        proof.get("url"), type_proof.get("url")))
                or not (_bound_adapter_media_type(resource, evidence)
                        or _bound_media_field(resource, evidence, "resource_type", {"jsonld.@type", "meta.og:type"}))
                or not any(row.get("evidence_id") == type_proof.get("evidence_id")
                           and _bili_part_identity(row.get("url")) == native for row in evidence)):
            return False
    elif proof.get("source") not in _PAGE_VIDEO_PROOFS:
        return False
    return any(row.get("evidence_id") and row.get("evidence_id") == proof.get("evidence_id")
               and row.get("kind") == "page" and row.get("field") == "video_evidence_status"
               and row.get("source") == proof.get("source") and _same_url(row.get("url"), target)
               and (not multipart or _bili_part_identity(row.get("url")) == native
                    and isinstance(row.get("text"), str) and bool(row["text"].strip()))
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


# Deliberately narrow author declarations, not a general audio-quality score.
# In particular, silence, missing narration and untested playback are not faults.
_AUDIO_FAULT_DECLARATION = re.compile(
    r"(?:^|[。.!！?？\n，,；;])\s*"
    r"(?:(?:(?:本(?:期|次)?|这(?:个|段|期)?)视频|本次录屏)(?:的)?\s*)?"
    r"(?:音频|音轨|录音)(?:文件)?\s*(?:已经|已|确实)?\s*(?:坏了|坏掉了|损坏(?:了)?)"
    r"|\b(?:this|my)\s+(?:video|recording)['’]s\s+(?:audio|audio\s+track|sound)\s+is\s+(?:broken|corrupted|damaged)\b"
    r"|\b(?:the\s+)?(?:audio|audio\s+track|sound)\s+(?:in|of|for)\s+this\s+video\s+is\s+(?:broken|corrupted|damaged)\b",
    re.I,
)
_AUDIO_FAULT_CONTEXT = re.compile(
    r"[?？]|(?:如何|怎样|怎么|教你|教大家|假如|如果|假设|例如|比如)|"
    r"(?:修复|修好|恢复).{0,18}(?:教程|教学|方法|演示)|"
    r"(?:教程|教学|方法|演示).{0,18}(?:修复|修好|恢复)|"
    r"(?:以前|曾经|之前|上一期|上个视频|别人的|不是|并非|并不是|并没有)|"
    r"\b(?:how\s+to|tutorial|example|suppose|if|previous(?:ly)?|used\s+to|not|isn['’]t|don['’]t)\b",
    re.I,
)
_AUDIO_REPAIRED = re.compile(
    r"(?<!未)(?<!没)(?<!没有)(?<!尚未)(?<!还没)(?:已经|现已|已|现在|目前)\s*"
    r"(?:修复|修好|恢复正常|恢复声音|重新录制|重新上传)|"
    r"(?:音频|音轨|录音|声音)(?:已经|现在|目前|已)?\s*(?:修复|修好|恢复正常|恢复了)|"
    r"\b(?:audio|sound|recording)\s+(?:(?:has\s+been|is)\s+)?(?:now\s+)?(?:fixed|repaired|restored)\b|"
    r"\b(?:now|already)\s+(?:fixed|repaired|restored)\b",
    re.I,
)
_AUDIO_REPAIR_LESSON = re.compile(
    r"(?:音频|音轨|录音).{0,18}(?:修复|修好|恢复).{0,18}(?:教程|教学|方法|演示)|"
    r"(?:如何|怎样|怎么).{0,18}(?:修复|修好|恢复).{0,18}(?:音频|音轨|录音)|"
    r"\bhow\s+to\s+(?:repair|fix|restore)\b.{0,30}\b(?:audio|sound|recordings?)\b|"
    r"\b(?:audio|sound|recording)\s+(?:repair|restoration)\s+tutorial\b",
    re.I,
)


def has_known_media_fault(resource: dict, evidence: list[dict]) -> bool:
    """Whether current own-page facts explicitly report broken audio.

    This is a pure exclusion signal, not a playback test or a claim that other
    videos work. Discovery text and superseded page facts cannot supply it.
    """
    def stale(value: dict) -> bool:
        cache = value.get("cache")
        return bool(value.get("stale") or isinstance(cache, dict) and cache.get("stale"))

    if resource.get("fetch_status") not in {"fetched", "success"} or stale(resource):
        return False
    target = _target(resource)
    if not target:
        return False
    current = []
    origins = resource.get("field_provenance") or {}
    for row in evidence:
        if not isinstance(row, dict):
            continue
        field, text = row.get("field"), row.get("text")
        if (row.get("kind") != "page" or field not in {"title", "description"}
                or not isinstance(row.get("evidence_id"), str) or not row["evidence_id"].strip()
                or not isinstance(row.get("source"), str) or not row["source"].strip() or stale(row)
                or not _same_url(row.get("url"), target)
                or not isinstance(text, str) or not text.strip() or len(text) > 20_000
                or text != resource.get(field)):
            continue
        if resource.get("fetched_at") and row.get("fetched_at") != resource["fetched_at"]:
            continue
        origin = origins.get(field)
        if isinstance(origin, dict) and (origin.get("evidence_id") != row["evidence_id"]
                or origin.get("source") != row["source"] or not _same_url(origin.get("url"), target)):
            continue
        current.append(text)
    # A current correction may be in the description while the old defect is
    # retained in the title. Never overrule an explicitly repaired declaration.
    if any(_AUDIO_REPAIRED.search(text) or _AUDIO_REPAIR_LESSON.search(text) for text in current):
        return False
    return any(_AUDIO_FAULT_DECLARATION.search(text) and not _AUDIO_FAULT_CONTEXT.search(text)
               for text in current)
