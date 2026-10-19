"""Pure grouping from observed URLs and explicit same-source course relations.

This never changes URL/resource identity, fetches a page, or merges semantic names.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from urllib.parse import urlsplit, urlunsplit

from .models import CourseIdentity
from .ranking import has_course_page, has_type_evidence, has_video_evidence
from .url_utils import UnsafeURL, host_matches, normalize_url


def _url(value) -> str | None:
    try:
        return normalize_url(value)
    except UnsafeURL:
        return None


def _key(kind: str, url: str) -> str:
    return kind + "_" + hashlib.sha256(url.encode()).hexdigest()[:24]


def _same_origin(first: str, second: str) -> bool:
    a, b = urlsplit(first), urlsplit(second)
    return (a.scheme, a.netloc) == (b.scheme, b.netloc)


def _course_anchor(url: str) -> tuple[str, str | None, str] | None:
    """Known path structure only; entire MIT slug retained across years."""
    parts = urlsplit(url)
    host, path = parts.hostname or "", parts.path
    if host in {"ocw.mit.edu", "www.ocw.mit.edu"}:
        match = re.match(r"^(/courses/([^/]+))(?:/(.*))?$", path)
        if match:
            parent = urlunsplit((parts.scheme, parts.netloc, match[1] + "/", "", ""))
            tail = match[3] or ""
            role = "course" if tail in {"", "pages/", "pages"} else "catalog" if tail.startswith("video_galleries/") else "unknown"
            offering = parent if re.search(r"-(?:spring|summer|fall|winter|january-iap)-\d{4}$", match[2]) else None
            return parent, offering, role
    if host_matches(host, "icourse163.org"):
        match = re.fullmatch(r"/(?:course|learn)/((?:[A-Za-z0-9_-]*-)?\d+)/?", path)
        if match:
            # Course/learn are entry forms for the same platform course token.
            return urlunsplit((parts.scheme, parts.netloc, "/course/" + match[1], "", "")), None, "course"
    if host_matches(host, "xuetangx.com"):
        match = re.fullmatch(r"/course/([A-Za-z0-9_-]+)/?", path)
        if match:
            return urlunsplit((parts.scheme, parts.netloc, "/course/" + match[1], "", "")), None, "course"
    return None


def _parent_relation(resource: dict, evidence: list[dict], current_url: str) -> tuple[str, str] | None:
    parent = _url(resource.get("parent_course_url"))
    provenance = resource.get("field_provenance", {}).get("parent_course_url", {})
    if not parent or not isinstance(provenance, dict) or not _same_origin(current_url, parent):
        return None
    if provenance.get("source") not in {"jsonld.isPartOf.Course", "html.explicit_course_parent"}:
        return None
    record = next((entry for entry in evidence if entry.get("evidence_id") == provenance.get("evidence_id")), {})
    if (record.get("kind") != "page" or record.get("field") != "parent_course_url"
            or record.get("source") != provenance.get("source") or _url(record.get("url")) != current_url):
        return None
    if provenance.get("url") is not None and _url(provenance["url"]) != current_url:
        return None
    try:
        facts = json.loads(record.get("text", ""))
    except (ValueError, TypeError):
        return None
    if not isinstance(facts, dict) or facts.get("@type") != "Course" or _url(facts.get("url")) != parent:
        return None
    evidence_id = record.get("evidence_id")
    return (parent, evidence_id) if isinstance(evidence_id, str) and evidence_id.strip() else None


def derive_course_identity(resource: dict, evidence: list[dict]) -> dict:
    result = CourseIdentity().model_dump()
    current_url = _url(resource.get("url"))
    if not current_url:
        result["unknown_reason"] = "原始资源 URL 无法用于安全的来源身份识别"
        return result
    resolved = _url(resource.get("resolved_url"))
    if (resolved and resource.get("fetch_status") in {"fetched", "success"}
            and any(entry.get("kind") == "page" and _url(entry.get("url")) == resolved
                    and entry.get("evidence_id") for entry in evidence)):
        current_url = resolved
    observed = [entry for entry in evidence if entry.get("kind") in {"search", "page", "page_link"}
                and _url(entry.get("url")) == current_url and isinstance(entry.get("evidence_id"), str) and entry["evidence_id"].strip()]
    anchor = _course_anchor(current_url) if observed else None
    parent = _parent_relation(resource, evidence, current_url)
    if parent:
        parent_anchor = _course_anchor(parent[0]) or (parent[0], None, "course")
        if anchor and anchor[0] != parent_anchor[0]:
            result["unknown_reason"] = "页面父课程依据与 URL 课程路径冲突，未自动合并"
            return result
        family_url, offering_url, _ = parent_anchor
        role = "lesson" if resource.get("resource_type") == "video" and has_video_evidence(resource, evidence) else "unknown"
        basis, ids = "page_is_part_of", [parent[1]]
    elif anchor:
        family_url, offering_url, role = anchor
        if "/resources/" in urlsplit(current_url).path and resource.get("resource_type") == "video" and has_video_evidence(resource, evidence):
            role = "lesson"
        basis, ids = "recognized_url", list(dict.fromkeys(entry["evidence_id"] for entry in observed))[:8]
    elif has_course_page(resource, evidence):
        family_url, offering_url, role = current_url, None, "course"
        basis, ids = "page_course", [resource["field_provenance"]["resource_type"]["evidence_id"]]
    else:
        if has_video_evidence(resource, evidence) and has_type_evidence(resource, evidence):
            result.update(status="partial", role="catalog" if resource.get("catalog_kind") == "video_playlist" else "video",
                          source_url=current_url,
                          evidence_ids=[resource["field_provenance"]["video_evidence_status"]["evidence_id"]],
                          unknown_reason="已观察到视频或视频列表依据；没有可确认的同来源父课程，未按标题或跨站镜像合并")
        return result
    result.update(status="identified", family_id=_key("course", family_url), family_url=family_url,
                  offering_id=_key("offering", offering_url) if offering_url else None, offering_url=offering_url,
                  lesson_id=_key("lesson", current_url) if role == "lesson" else None,
                  role=role, basis=basis, source_url=current_url, evidence_ids=ids,
                  unknown_reason=None if offering_url else "开课版本/学期未从现有来源确认；不跨来源或相似标题合并")
    return result


def summarize_course_identities(resources: Iterable[dict]) -> dict:
    unique = {}
    for resource in resources:
        key = resource.get("resource_id") or resource.get("canonical_url") or resource.get("url")
        if key:
            unique.setdefault(key, resource)
    identities = [resource.get("course_identity") or {} for resource in unique.values()]
    def count(field):
        return len({identity[field] for identity in identities if identity.get(field)})
    return {"resource_records": len(unique), "identified_course_families": count("family_id"),
            "identified_course_offerings": count("offering_id"), "identified_lessons": count("lesson_id"),
            "unknown_course_family_resources": sum(not identity.get("family_id") for identity in identities),
            "unknown_offering_resources": sum(bool(identity.get("family_id")) and not identity.get("offering_id") for identity in identities),
            "unknown_identity_resources": sum(identity.get("status", "unknown") == "unknown" for identity in identities),
            "scope": "observed_source_scoped_identities_not_global_course_deduplication"}


def diversify(items: list[dict], limit: int) -> list[dict]:
    """Choose distinct observed families first, then fill from source ordering.

    Unknown families remain separate. This neither mutates nor deletes the full
    stored candidate list; callers can still expose its other related entries.
    """
    if limit <= 0:
        return []
    selected, deferred, families = [], [], set()
    for item in items:
        family = (item.get("resource", {}).get("course_identity") or {}).get("family_id")
        if family and family in families:
            deferred.append(item)
        else:
            selected.append(item)
            if family:
                families.add(family)
    return (selected + deferred)[:limit]
