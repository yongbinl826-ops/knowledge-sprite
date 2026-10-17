from __future__ import annotations

import re
from urllib.parse import urlsplit
from .models import SearchRequest
from .url_utils import UnsafeURL, host_matches, normalize_url

TEACHING = re.compile(r"教程|课程|教学|讲解|学习|课堂|lesson|tutorial|course|lecture|training|learn", re.I)
ADS = re.compile(r"招生|包就业|高薪就业|报名咨询|培训机构|限时优惠|优惠券|推广合作|\b(sponsored|promo code|enroll now)\b", re.I)
SEARCH_PATH = re.compile(r"/(search|s|results|tag|tags)(/|$)", re.I)
PREREQUISITE = re.compile(
    r"(?:需要|需|必须|应当|应)?\s*(?:预先|事先|已经|已)\s*(?:掌握|熟悉|具备|了解)"
    r"|先修要求|先修课程|先修知识|预备知识|前置知识"
    r"|(?:要求|需要|需)\s*(?:掌握|熟悉|具备)"
    r"|\bprerequisites?\b|\b(?:prior|previous)\s+(?:knowledge|experience|familiarity)\b"
    r"|\b(?:requires?|assumes?|expects?)\s+(?:(?:some|basic|prior|previous)\s+)?(?:knowledge|experience|familiarity)\b"
    r"|\b(?:you|students?|learners?)\s+(?:should|must|need to)\s+(?:already\s+)?(?:know|understand|be familiar with)\b", re.I)
NEGATED_REQUIREMENT = re.compile(r"(?:无需|无须|不需要|不要求|不必|不用|不|无|\bno|\bnot|\bwithout)\s*$", re.I)
ENGLISH_FUNCTION_WORDS = frozenset({"a", "an", "the", "and", "or", "with", "of", "to", "in", "on", "at", "by", "from", "as", "is", "are", "be", "this", "that", "using", "about"})
ASCII_TERM = re.compile(r"[a-zA-Z][a-zA-Z0-9+#]*(?:\.[a-zA-Z0-9+#]+)*")
PYTHON_VERSION_TERM = re.compile(r"pythonv?\d+(?:\.\d+)*")
CLAUSE_BOUNDARY = re.compile(
    r"[。！？!?;；\n]|\.\s+|\b(?:but|however)\b|[，,]\s*(?=(?:本课程|课程将|课程会|this course|we teach|(?:and\s+)?(?:"
    + PREREQUISITE.pattern + r")))", re.I)


def type_from_discovered_url(url: str) -> str:
    """Recognize public platform entry formats; this never verifies page access."""
    try:
        parsed = urlsplit(url)
    except ValueError:
        return "unknown"
    host, path = (parsed.hostname or "").lower(), parsed.path
    if host_matches(host, "bilibili.com") and re.fullmatch(r"/video/(?:BV[0-9A-Za-z]{10}|av\d+)/?", path):
        return "video"
    if host_matches(host, "icourse163.org") and re.fullmatch(r"/(?:course|learn)/(?:[A-Za-z0-9_-]*-)?\d+/?", path):
        return "course"
    if host_matches(host, "xuetangx.com") and re.fullmatch(r"/course/[A-Za-z0-9_-]+/?", path):
        return "course"
    return "unknown"


def has_type_evidence(resource: dict, evidence: list[dict]) -> bool:
    """A teaching keyword alone cannot turn text documentation into a course."""
    resource_type = resource.get("resource_type")
    if resource_type not in {"video", "course", "playlist"}:
        return False
    provenance = resource.get("field_provenance", {}).get("resource_type")
    if not isinstance(provenance, dict):
        return False
    source_evidence = next((item for item in evidence if item.get("evidence_id") == provenance.get("evidence_id")), None)
    if not source_evidence:
        return False
    if provenance.get("source") == "url_pattern":
        return source_evidence.get("kind") == "search" and type_from_discovered_url(resource.get("url", "")) == resource_type
    if provenance.get("source") == "search_template":
        return (source_evidence.get("kind") == "search" and source_evidence.get("type_source") == "search_template"
                and source_evidence.get("resource_type_hint") == resource_type)
    return (resource.get("metadata_evidence_level") in {"page", "catalog"}
            and source_evidence.get("kind") == "page" and source_evidence.get("field") == "resource_type"
            and resource.get("fetch_status") in {"fetched", "success"})


def has_video_evidence(resource: dict, evidence: list[dict]) -> bool:
    """Course structure and video evidence are independent, auditable facts."""
    status = resource.get("video_evidence_status", "none")
    provenance = resource.get("field_provenance", {}).get("video_evidence_status")
    if not isinstance(provenance, dict):
        return False
    observed = next((item for item in evidence if item.get("evidence_id") == provenance.get("evidence_id")), None)
    if not observed:
        return False
    if status == "search_discovered" and observed.get("kind") == "search":
        if provenance.get("source") == "url_pattern":
            return type_from_discovered_url(resource.get("url", "")) == "video"
        return (provenance.get("source") == "search_template" and observed.get("type_source") == "search_template"
                and observed.get("resource_type_hint") in {"video", "playlist"})
    return (status == "page_verified" and resource.get("metadata_evidence_level") in {"page", "catalog"}
            and resource.get("fetch_status") in {"fetched", "success"}
            and observed.get("kind") in {"page", "catalog"} and observed.get("field") == "video_evidence_status")


def has_course_discovery(resource: dict, evidence: list[dict]) -> bool:
    """A real searched platform course entry can remain an unverified course candidate."""
    if resource.get("resource_type") != "course" or type_from_discovered_url(resource.get("url", "")) != "course":
        return False
    try:
        target = normalize_url(resource["url"])
    except UnsafeURL:
        return False
    for item in evidence:
        if item.get("kind") != "search":
            continue
        try:
            if normalize_url(item.get("url", "")) == target:
                return True
        except UnsafeURL:
            continue
    return False


def has_course_page(resource: dict, evidence: list[dict]) -> bool:
    """Explicit course structure can support a course without asserting video."""
    if resource.get("resource_type") != "course" or resource.get("fetch_status") not in {"fetched", "success"} or resource.get("metadata_evidence_level") not in {"page", "catalog"}:
        return False
    provenance = resource.get("field_provenance", {}).get("resource_type", {})
    if not isinstance(provenance, dict) or provenance.get("source") not in {"jsonld.@type", "html.mit_ocw.course_home", "html.microsoft_ai.curriculum_table"}:
        return False
    observed = next((item for item in evidence if item.get("evidence_id") == provenance.get("evidence_id")), {})
    if observed.get("kind") != "page" or observed.get("field") != "resource_type" or observed.get("source") != provenance.get("source"):
        return False
    try:
        page_url = normalize_url(observed.get("url", ""))
        targets = {normalize_url(resource.get("url", ""))}
        if resource.get("resolved_url"):
            targets.add(normalize_url(resource["resolved_url"]))
        if page_url not in targets:
            return False
        if provenance.get("url") is not None and normalize_url(provenance["url"]) != page_url:
            return False
    except UnsafeURL:
        return False
    # JSON-LD type evidence is the actual type value, not a prose teaching keyword.
    if provenance["source"] == "jsonld.@type" and str(observed.get("text", "")).strip().lower() != "course":
        return False
    return bool(observed.get("text"))


def has_learning_evidence(resource: dict, evidence: list[dict]) -> bool:
    return has_type_evidence(resource, evidence) and (
        has_video_evidence(resource, evidence) or has_course_discovery(resource, evidence) or has_course_page(resource, evidence)
    )


def tokens(text: str) -> set[str]:
    # Symbol-suffixed language names keep their identity, including C++17/C#12.
    output = {re.sub(r"(?<=[+#])\d+$", "", term) for term in ASCII_TERM.findall(text.lower())} - ENGLISH_FUNCTION_WORDS
    # Only a complete Python version spelling receives this alias. Arbitrary
    # suffixes and digit-bearing names such as D3.js keep their exact identity.
    output = {"python" if PYTHON_VERSION_TERM.fullmatch(term) else term for term in output}
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        for part in re.split(r"[与及和的、]", run):
            if len(part) == 1:
                output.add(part)
            else:
                output.update(part[i:i+2] for i in range(len(part)-1))
    return output


def relevance(point: str, text: str) -> float:
    wanted = tokens(point)
    if not wanted:
        return 0.0
    return len(wanted & tokens(text)) / len(wanted)


def prerequisite_only_match(point: str, title: str, snippets: str, description: str, catalog: str) -> bool:
    """Exclude strong prerequisite matches with only weak topic overlap elsewhere.

    Requiring prior Python lists/dictionaries is not evidence of teaching them.
    Explicit negation such as '无需预先掌握' or 'no prerequisites' is not a requirement.
    """
    required, independent_fields = [], []
    # Inspect every field used for scoring. A prerequisite copied into the page
    # description or chapter title is not an independent teaching assertion.
    for field in (title, snippets, description, catalog):
        other = []
        sentences = CLAUSE_BOUNDARY.split(field)
        for sentence in sentences:
            match = PREREQUISITE.search(sentence)
            negated = match and (NEGATED_REQUIREMENT.search(sentence[:match.start()])
                or re.search(r"\b(?:is|are)\s+not\s+(?:required|necessary|needed)\b|不(?:作|是|属于).*先修", sentence, re.I))
            if match and not negated:
                # Include text before the marker: 'SQL joins are prerequisites'.
                required.append(sentence)
            else:
                other.append(sentence)
        independent_fields.append(" ".join(other))
    if not required:
        return False
    prerequisite_relevance = relevance(point, " ".join(required))
    independent_relevance = max(relevance(point, content) for content in independent_fields)
    return prerequisite_relevance >= .5 and independent_relevance <= .5 and prerequisite_relevance > independent_relevance + .1


def version_conflict(point: str, version: str, content: str) -> bool:
    expected = re.findall(r"([a-z][a-z0-9.+#-]*)\s*v?\s*(\d+(?:\.\d+)*)", f"{point} {version}".lower())
    for technology, target in expected:
        found = re.findall(r"\b" + re.escape(technology) + r"\s*v?\s*(\d+(?:\.\d+)*)", content.lower())
        if found and all(x.split(".")[0] != target.split(".")[0] for x in found):
            return True
    # Bare optional version is associated with the first technology in the point.
    if re.fullmatch(r"v?\d+(?:\.\d+)*", version.strip().lower()):
        tech = re.search(r"[a-z][a-z0-9.+#-]*", point.lower())
        if tech:
            return version_conflict(tech[0] + " " + version, "", content)
    return False


def rank_resource(point: dict, resource: dict, evidence: list[dict], request: SearchRequest, *, require_type: bool = True,
                  eligibility_evidence: list[dict] | None = None) -> dict | None:
    # The relaxed path is used only to prioritize metadata discovery; never for display.
    if require_type and not has_learning_evidence(resource, evidence if eligibility_evidence is None else eligibility_evidence):
        return None
    # Later discoveries of the same URL have their own titles. They belong to
    # this knowledge point and must not overwrite or reuse another point's first
    # search title. Page fields remain shared evidence about the resource itself.
    scoped_evidence = [entry for entry in evidence if entry.get("kind") != "search"
                       or entry.get("knowledge_point_id") in {None, point["knowledge_point_id"]}]
    searches = [entry for entry in scoped_evidence if entry.get("kind") == "search"]
    search_titles = list(dict.fromkeys(entry["title"] for entry in searches if isinstance(entry.get("title"), str) and entry["title"].strip()))
    title_source = resource.get("field_provenance", {}).get("title", {}).get("source")
    # Older unscoped records lack title provenance; keep their legacy title
    # fallback. Explicit search provenance or point-tagged records are strict.
    search_title_only = title_source == "search" or (resource.get("metadata_evidence_level") == "search"
        and any(entry.get("knowledge_point_id") is not None for entry in evidence if entry.get("kind") == "search"))
    page_title = "" if search_title_only else resource.get("title") or ""
    # Legacy isolated inputs without a search record may only have a title.
    # An explicit search provenance never permits borrowing another point's title.
    if not page_title and not search_titles and title_source != "search" and not any(entry.get("kind") == "search" for entry in evidence):
        page_title = resource.get("title") or ""
    titles = ([page_title] if page_title else []) + search_titles
    title = "\n".join(titles)
    snippets = "\n".join(e.get("snippet", "") or "" for e in searches)
    description_source = resource.get("field_provenance", {}).get("description", {}).get("source")
    description = (resource.get("description") or "") if resource.get("metadata_evidence_level") in {"page", "catalog"} and description_source != "search" else ""
    chapters = "\n".join(str(c.get("title", c.get("name", ""))) if isinstance(c, dict) else str(c) for c in resource.get("chapters", []))
    combined = " ".join((title, snippets, description, chapters))
    if resource.get("fetch_status") in {"unsafe_url", "not_found", "error_page"}:
        return None
    text = point["text"]
    if prerequisite_only_match(text, title, snippets, description, chapters):
        return None
    title_rel, snippet_rel = max((relevance(text, value) for value in titles), default=0.0), relevance(text, snippets)
    desc_rel, catalog_rel = relevance(text, description), relevance(text, chapters)
    topic = max(title_rel, snippet_rel * .85, desc_rel, catalog_rel)
    url = urlsplit(resource["url"])
    if SEARCH_PATH.search(url.path) or url.hostname in {"search.bilibili.com", "www.google.com", "www.baidu.com", "www.bing.com"}:
        return None
    if version_conflict(text, request.technical_version, combined):
        return None
    is_teaching = bool(TEACHING.search(combined)) or resource.get("resource_type") in {"course", "video", "playlist"}
    wanted = tokens(text)
    matched_terms = len(wanted & tokens(combined))
    # A broad technology name alone (SQL/Python/etc.) is insufficient for a
    # compound knowledge point. This applies to arbitrary topics, not a vocabulary.
    if topic < .4 or matched_terms < min(2, len(wanted)) or not is_teaching:
        return None
    score = 55 * topic + 15 * title_rel + (10 if is_teaching else 0)
    if ADS.search(combined):
        score -= 45
    if re.search(r"新闻|资讯|招聘|八卦|news|vacancies", title, re.I):
        score -= 30
    if score < 25:
        return None
    basis = [name for name, value in (("title", title_rel), ("snippet", snippet_rel), ("description", desc_rel), ("catalog", catalog_rel)) if value >= .22]
    if resource.get("metadata_evidence_level") in {"page", "catalog"}:
        score += 5
    actual_language = (resource.get("language") or "").lower()
    if request.language != "any" and actual_language:
        score += 4 if actual_language.startswith(request.language) else -6
    if request.student_level == "beginner":
        score += 3 if re.search(r"入门|零基础|beginner|introduction", combined, re.I) else 0
        score -= 4 if re.search(r"高级|advanced", title, re.I) else 0
    if request.technical_version:
        score += 4 if request.technical_version.lower() in combined.lower() else -3
    if "catalog" in basis:
        reason = "公开目录包含与该知识点相关的文字；未核验讲解深度或学生可播放性。"
    elif resource.get("metadata_evidence_level") in {"page", "catalog"} and "description" in basis:
        reason = "根据公开页面标题或简介匹配，可能涉及该知识点；未核验完整教学覆盖。"
    elif resource.get("metadata_evidence_level") in {"page", "catalog"}:
        reason = "根据已有标题与搜索摘要匹配，可能涉及该知识点；已获取部分页面元信息，但完整教学覆盖尚未核验。"
    else:
        reason = "根据该知识点对应的搜索标题与摘要匹配，可能涉及该知识点；页面详情及完整教学覆盖尚未核验。"
    if request.technical_version and request.technical_version.lower() not in combined.lower():
        reason += " 目标技术版本尚未核验。"
    return {"knowledge_point_id": point["knowledge_point_id"], "resource_id": resource["resource_id"],
            "ranking_score": round(max(0, min(score, 100)), 2), "recommendation_reason": reason,
            "matched_evidence_ids": [e["evidence_id"] for e in scoped_evidence if relevance(text, " ".join(str(e.get(k) or "") for k in ("title", "snippet", "description", "text"))) >= .22],
            "coverage_basis": basis}
