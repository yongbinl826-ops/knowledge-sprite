"""Source-linked relevance recommendations, without a teaching-proof gate.

The stricter teaching assessment remains useful for ranking and diagnostics.
These references need topical relevance and a safe media entry, not a proof
that this exact video teaches every part of the selected concept.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

from .ranking import (ADS, SEARCH_PATH, has_type_evidence, own_resource_snippet, own_video_description,
                      prerequisite_only_match, search_instructional_text,
                      tokens, topic_context_conflict, version_conflict)
from .technical_prefix import leading_technical_owner
from .url_utils import UnsafeURL, normalize_url
from .video_availability import has_known_media_fault
from .mooc_relevance import is_mooc_resource
from .related_concepts import (reference_concept_denied, reference_concept_hints,
                               reference_mechanism_compatible, reference_technology_context)

POLICY_VERSION = "related-reference-v1"
_REFERENCE_SEARCH_PROVIDERS = {"tavily", "serper", "searxng", "bing", "google", "duckduckgo"}
_REFERENCE_UNAVAILABLE_STATUSES = {"unsafe_url", "not_found", "error_page", "unavailable", "removed", "deleted",
                                   "access_denied", "access_blocked", "robots_blocked"}
_TECH_GROUPS = (
    ("python", "javascript", "typescript", "java", "c++", "c#", "ruby", "swift", "kotlin", "rust", "golang"),
    ("pygame", "unity", "unreal", "godot", "phaser"),
    ("react", "vue", "angular", "svelte"),
    ("pandas", "polars", "pyspark"),
    ("streamlit", "flet", "gradio", "dash"),
    ("arduino", "esp32", "stm32", "micro:bit"),
)
_URL_TEXT = re.compile(r"(?:https?://|www\.)[^\s<>\"']+", re.I)
_TECH_ALIASES = {"arduino uno": "arduino", "uno": "arduino", "cubemx": "stm32", "stm32cubemx": "stm32"}
_CONCEPT_ACTION = re.compile(r"^(?P<noun>[\u4e00-\u9fff]{2,20}?)(?P<action>检测|聚合|校验|渲染|生成|转换|排序|遍历|表示|限制|处理|管理|分析|操作)$")
# Named implementations can own a chapter even when they are not alternatives
# in one _TECH_GROUPS family. Ordinary English heading words remain unknown,
# not assumed to be technologies. An unknown mixed-case identifier needs an
# explicit library/framework declaration: API/class names also use CamelCase.
_CHAPTER_TECH_OWNERS = frozenset(name for group in _TECH_GROUPS for name in group) | frozenset({
    "redis", "langgraph", "langchain", "mongodb", "postgresql", "mysql", "sqlite",
    "flask", "django", "fastapi", "numpy", "matplotlib", "opencv", "tensorflow", "pytorch",
})


def _prose(text: str) -> str:
    return _URL_TEXT.sub(" ", text)


def _specific_core(concept: str, content: str) -> bool:
    for term in re.findall(r"[\u4e00-\u9fff]+", concept):
        parsed = _CONCEPT_ACTION.fullmatch(term)
        if parsed:
            noun = parsed["noun"]
            core = noun if len(noun) <= 3 else noun[-2:]
            if core not in {"数据", "文件", "文本", "区域", "对象", "类型", "方法", "功能", "基础", "内容"} and core in content:
                if parsed["action"] in content and not _coherent_topic(concept, content):
                    continue
                return True
    return False


def _coherent_topic(concept: str, content: str) -> bool:
    """Reject bag-of-words joins, without requiring exact lesson coverage.

    A qualified concept may match its core (rectangle collision -> collision),
    but rectangle area + file detection is not that core. Reordered noun/action
    and ordinary lesson modifiers stay eligible. No example URL/title is used.
    """
    chinese = re.findall(r"[\u4e00-\u9fff]+", concept)
    if not chinese:
        return True
    for term in chinese:
        if term in content:
            return True
        if re.fullmatch(r"(?:文本|字符串)(?:分段|分割|切分)", term):
            # The shared prefix 文本分 also appears in 文本分类. It cannot
            # stand in for this selected operation, even as a related reference.
            if reference_concept_hints(term, content):
                return True
            continue
        if len(term) >= 4 and any(term[index:index+3] in content for index in range(len(term)-2)):
            return True
        parsed = _CONCEPT_ACTION.fullmatch(term)
        if not parsed:
            continue
        noun, action = parsed["noun"], parsed["action"]
        # The final two-character noun is a qualified topic's core. Preserve
        # a longer exact noun whenever it appears; never borrow the action
        # from another object/lesson separated by conjunctions.
        core = noun[-2:]
        fillers = r"(?:的|基础|入门|教程|教学|讲解|详解|进行|实现|操作|方法|技术|示例|实例|统计|区域|机制|逻辑|算法|与|和|及|[\s:：_-]){0,10}"
        if re.search(re.escape(core) + fillers + re.escape(action), content) or re.search(re.escape(action) + fillers + re.escape(core), content):
            return True
    return False


def _mentions(name: str, text: str) -> bool:
    return bool(re.search(r"(?<![a-z0-9_])" + re.escape(name) + r"(?![a-z0-9_])", text, re.I))


def obvious_technology_conflict(technology: str, text: str) -> bool:
    """Only explicitly competing ecosystems; absent context is uncertainty."""
    technology = technology.casefold().strip()
    technology = _TECH_ALIASES.get(technology, technology)
    text = _prose(text)
    for alias, canonical in _TECH_ALIASES.items():
        if _mentions(alias, text):
            text += " " + canonical
    for group in _TECH_GROUPS:
        expected = next((name for name in group if technology == name or technology.startswith(name + " ")), None)
        if expected and not _mentions(expected, text) and any(_mentions(other, text) for other in group if other != expected):
            # TypeScript and JavaScript are often the same browser ecosystem.
            if expected in {"javascript", "typescript"} and (_mentions("javascript", text) or _mentions("typescript", text)):
                continue
            return True
    return False


def _unambiguous_parent_technology(technology: str, text: str) -> bool:
    if not reference_technology_context(technology, text):
        return False
    expected = technology.casefold().strip()
    for group in _TECH_GROUPS:
        owner = next((name for name in group if expected == name or expected.startswith(name + " ")), None)
        if owner and any(_mentions(other, text) for other in group if other != owner):
            return False
    return True


def chapter_can_inherit_technology(technology: str, chapter_title) -> bool:
    """Allow borrowing a course owner, never replacing an explicit other owner.

    This grants inheritance only, not topic relevance. Target-named integration
    lessons and known host-language foundations remain eligible. Unknown API
    names and ordinary English headings are not guessed to be frameworks.
    """
    if not technology:
        return True
    if isinstance(chapter_title, str):
        try:
            parsed = json.loads(chapter_title)
            if isinstance(parsed, dict):
                chapter_title = parsed.get("title") or parsed.get("name") or ""
        except (TypeError, ValueError):
            pass
    elif isinstance(chapter_title, dict):
        chapter_title = chapter_title.get("title") or chapter_title.get("name") or ""
    if not isinstance(chapter_title, str):
        return False
    text = _prose(chapter_title).strip()
    if reference_technology_context(technology, text):
        return True
    # Numbered catalog headings may wrap an otherwise explicit owner.
    for _ in range(2):
        text = re.sub(r"^\s*(?:第\s*)?(?:\d+(?:\.\d+)*|[一二三四五六七八九十百]+)\s*(?:[.、:：_)\]】\-]+|[章节课讲])\s*", "", text)
        text = re.sub(r"^\s*[\[【(（]\s*\d+\s*[\]】)）]\s*", "", text)
    text = re.sub(r"^(?:最新|新版)\s*", "", text)
    owner = leading_technical_owner(text)
    callable_owner = re.match(r"([A-Za-z][A-Za-z0-9_.+#-]*)(?=\s*[(：:]|$)", text)
    if not owner and callable_owner:
        owner = callable_owner[1]
    if not owner:
        return True
    # Inspect a namespace's root, so Redis.get cannot masquerade as a generic
    # API and borrow Streamlit context. self/cls and unknown plain identifiers
    # do not become external frameworks merely because they contain a dot.
    owner_tail = text[len(owner):]
    owner = re.sub(r"\d+(?:\.\d+)*$", "", owner).rstrip(".").split(".", 1)[0]
    if reference_technology_context(owner, technology):
        return True  # e.g. Python foundations within a Streamlit course.
    declared_brand = bool(re.search(r"[a-z][A-Z]", owner) and re.match(
        r"\s*(?:(?:framework|library|sdk|package)\b|框架|类库|库)", owner_tail, re.I))
    explicit_owner = owner.casefold() in _CHAPTER_TECH_OWNERS or declared_brand
    return not explicit_owner


def _reference_fresh(row, resource):
    return (not row.get("stale") and not row.get("cache", {}).get("stale")
            and not (row.get("fetched_at") and resource.get("fetched_at")
                     and row["fetched_at"] != resource["fetched_at"]))


def bound_native_course_identity(resource, evidence):
    """An existing native course adapter proves course, never video, identity."""
    from .mooc_urls import public_course_url
    from .ranking import has_course_page
    from .video_availability import _same_url
    try:
        canonical = normalize_url(resource.get("canonical_url") or resource.get("url", ""))
        if (not public_course_url(canonical) or not has_course_page(resource, evidence)
                or resource.get("stale") or resource.get("cache", {}).get("stale")
                or any(not _same_url(resource[key], canonical) for key in ("url", "resolved_url") if resource.get(key))):
            return None
        proof = (resource.get("field_provenance") or {}).get("resource_type") or {}
        if proof.get("source") not in {"html.icourse163.course_structure", "html.icourse163.embedded_course_structure"}:
            return None
        row = next((row for row in evidence if row.get("evidence_id") == proof.get("evidence_id")), None)
        if (not row or not _same_url(proof.get("url"), canonical) or not _same_url(row.get("url"), canonical)
                or not _reference_fresh(row, resource) or not _reference_fresh(proof, resource)):
            return None
        return proof, row
    except (UnsafeURL, TypeError, ValueError):
        return None


def reference_link_eligible(resource, evidence, retained, *, target=None):
    """A current bound native link is displayable without asserting playback."""
    from .video_availability import _same_url, _bound_page_video, native_media_entry_type
    try:
        canonical = normalize_url(resource.get("canonical_url") or resource.get("url", ""))
        target = normalize_url(target or canonical)
        if (resource.get("fetch_status") in _REFERENCE_UNAVAILABLE_STATUSES
                or resource.get("stale") or resource.get("cache", {}).get("stale")
                or has_known_media_fault(resource, evidence)
                or native_media_entry_type(canonical) not in {"video", "course", "playlist"}
                or any(not _same_url(resource[key], canonical) for key in ("url", "resolved_url") if resource.get(key))
                or not retained or any(not _reference_fresh(row, resource) for row in retained)):
            return False
        if not _same_url(target, canonical):
            from .teaching_match import _own_catalog_target
            if not any(chapter.get("url") == target and any(row.get("evidence_id") == chapter.get("evidence_id")
                    and _same_url(row.get("url"), canonical) and _own_catalog_target(canonical, chapter, row)
                    for row in retained) for chapter in resource.get("chapters", [])):
                return False
        search_relevance = any(row.get("kind") == "search" and row.get("source") in _REFERENCE_SEARCH_PROVIDERS
            and row.get("evidence_id") and row.get("knowledge_point_id") and _same_url(row.get("url"), canonical)
            and (row.get("title") or row.get("snippet")) for row in retained)
        own_identity = _bound_page_video(resource, evidence) or bound_native_course_identity(resource, evidence)
        if own_identity:
            return search_relevance or any(row.get("kind") in {"page", "catalog"}
                and _same_url(row.get("url"), canonical) for row in retained)
        proof = (resource.get("field_provenance") or {}).get("resource_type") or {}
        identity = next((row for row in evidence if row.get("evidence_id") == proof.get("evidence_id")), None)
        if (not identity or identity.get("kind") != "search" or identity.get("source") not in _REFERENCE_SEARCH_PROVIDERS
                or proof.get("source") not in {"url_pattern", "search_template", "search_title_url"}
                or not _same_url(identity.get("url"), canonical) or not _reference_fresh(identity, resource)
                or not has_type_evidence(resource, evidence)):
            return False
        return search_relevance
    except (UnsafeURL, TypeError, ValueError, AttributeError):
        return False


def _own_search_reference_body(resource, text):
    """Explicitly external full-course adverts cannot donate their syllabus."""
    text = own_video_description(resource, own_resource_snippet(text))
    marker = re.compile(r"(?:(?:完整|整套|全套)(?:课程|教程)(?:下载|购买|链接|地址)|"
                        r"(?:full|complete)\s+(?:course|tutorial)\s+(?:download|purchase|link))"
                        r"\s*[:：]?\s*(https?://[^\s<>，。；]+)", re.I)
    for found in marker.finditer(text):
        try:
            if normalize_url(found[1]) in {normalize_url(resource[key]) for key in ("url", "canonical_url", "resolved_url") if resource.get(key)}:
                continue
        except (UnsafeURL, TypeError, ValueError):
            continue
        after = re.search(r"(?:本|此)(?:视频|节|段)|\b(?:this|current)\s+(?:video|lesson|clip)\b", text[found.end():], re.I)
        return text[found.end()+after.start():] if after else text[:found.start()]
    return text


def _weak_framework_capability(concept, title, body):
    """Generic product feature claims alone are not this lesson's mechanism."""
    wanted = tokens(concept)
    title_overlap = wanted & tokens(title)
    title_topic = (_coherent_topic(concept, title) if re.search(r"[一-鿿]", concept)
                   else len(title_overlap) >= min(2, len(wanted)) and len(title_overlap) / max(1, len(wanted)) >= .4)
    if (title_topic or reference_concept_hints(concept, title)
            or not re.search(r"框架|类库|工具|\b(?:framework|library|toolkit)\b", title+" "+body, re.I)
            or not re.search(r"核心特点|主要特性|核心特性|功能特点|\b(?:key\s+)?(?:features|capabilities)\b", body, re.I)
            or re.search(r"(?:本(?:视频|课|节)|我们)(?:将|会)?(?:讲解|学习|演示|实现)|\b(?:learn|teach|demonstrate)\b", body, re.I)
            or reference_concept_hints(concept, body)):
        return False
    weak = tokens("类型安全 类型约束 严格约束 数据模型 性能 高效 灵活 稳定 质量 控制 集成 支持 type safety constraints data model performance efficiency flexibility reliability integration support")
    return not ((tokens(concept) & tokens(body)) - weak)


def related_recommendation(point: dict, resource: dict, evidence: list[dict], request, *, qualified_outline=None, grounded_decision=None) -> dict | None:
    if (resource.get("fetch_status") in _REFERENCE_UNAVAILABLE_STATUSES
            or has_known_media_fault(resource, evidence)):
        return None
    try:
        aliases = {normalize_url(resource[key]) for key in ("url", "canonical_url", "resolved_url") if resource.get(key)}
        target = normalize_url(resource.get("canonical_url") or resource.get("url", ""))
    except (UnsafeURL, TypeError, ValueError):
        return None
    url = urlsplit(target)
    if not has_type_evidence(resource, evidence) or SEARCH_PATH.search(url.path) or (url.hostname or "").startswith("search."):
        return None
    pid = point["knowledge_point_id"]
    requested = request.topic_technologies.get(point["text"])
    if requested and point.get("technology") and requested.casefold() != point["technology"].casefold():
        return None
    technology = requested or point.get("technology") or leading_technical_owner(point["text"]) or ""
    concept = point["text"]
    if technology and re.match(re.escape(technology) + r"(?:\s+|(?=[\u4e00-\u9fff]))", concept, re.I):
        concept = re.sub(r"^" + re.escape(technology) + r"\s*", "", concept, count=1, flags=re.I)
    wanted = tokens(concept) - tokens(technology)
    if not wanted:
        return None  # A tool name alone cannot fill every concept's coverage.
    for row in evidence:
        if row.get("kind") == "page" and row.get("field") == "title":
            try:
                # A current, bound title explicitly saying the topic is not
                # covered outweighs an older positive discovery excerpt.
                if (resource.get("fetch_status") in {"fetched", "success"}
                        and row.get("evidence_id") and row.get("source")
                        and row.get("text") == resource.get("title")
                        and normalize_url(row.get("url", "")) in aliases
                        and reference_concept_denied(concept, _prose(str(row.get("text") or "")))):
                    return None
                if (normalize_url(row.get("url", "")) in aliases
                        and obvious_technology_conflict(technology, _prose(str(row.get("text") or "")))):
                    return None
            except (UnsafeURL, TypeError, ValueError):
                continue
    # A chapter can inherit its own course's explicitly observed technology.
    # Never borrow context from a query, an uploader profile or another URL.
    own_technology_row = None
    own_page_technology_row = None
    page_read = resource.get("fetch_status") in {"fetched", "success"}
    if technology:
        for row in evidence:
            try:
                if (row.get("kind") in {"page", "catalog"} and row.get("field") in {"title", "description"}
                        and row.get("evidence_id") and row.get("source")
                        and not row.get("cache", {}).get("stale")
                        and normalize_url(row.get("url", "")) in aliases
                        and _unambiguous_parent_technology(technology, _prose(
                            own_video_description(resource, str(row.get("text") or "")) if row.get("field") == "description"
                            else own_resource_snippet(str(row.get("text") or ""))))):
                    if row.get("field") == "title" and own_technology_row is None:
                        own_technology_row = row
                    if row.get("kind") == "page" and own_page_technology_row is None:
                        own_page_technology_row = row
            except (UnsafeURL, TypeError, ValueError):
                continue
    observations = []
    indexed_catalog = False
    for row in evidence:
        try:
            if (row.get("kind") == "catalog" and row.get("evidence_id") and row.get("source")
                    and re.fullmatch(r"chapters\.\d{1,4}", str(row.get("field", "")))
                    and normalize_url(row.get("url", "")) in aliases):
                indexed_catalog = True
                break
        except (UnsafeURL, TypeError, ValueError):
            continue
    # Relevance can reuse an actual source title found for another concept,
    # but never its query echo or an unrelated page sharing a resource ID.
    for row in evidence:
        if not row.get("evidence_id") or not row.get("source"):
            continue
        # Prefer individually bound chapters over their concatenated summary.
        # Otherwise one framework's chapter can borrow another chapter's owner,
        # and the UI cannot identify which actual part supplies the reference.
        if indexed_catalog and row.get("kind") == "catalog" and row.get("field") == "chapters":
            continue
        try:
            bound = normalize_url(row.get("url", "")) in aliases
        except (UnsafeURL, TypeError, ValueError):
            continue
        if not bound:
            continue
        if row.get("kind") == "search":
            if not row.get("knowledge_point_id") or row.get("source") in {"official_sitemap", "public_catalog", "techwithtim_catalog"}:
                continue  # URL-word inventories are not title/snippet results.
            title = search_instructional_text(row.get("title") or "")
            body = search_instructional_text(_own_search_reference_body(resource, row.get("snippet") or ""))
            if _weak_framework_capability(concept, _prose(title), _prose(body)):
                continue
            basis = "search"
        elif row.get("kind") in {"page", "catalog"} and (row.get("field") in {"title", "description", "chapters", "video_topic_summary"}
                or re.fullmatch(r"chapters\.\d{1,4}", str(row.get("field", "")))):
            raw = row.get("text")
            title = raw if row.get("field") == "title" and isinstance(raw, str) else ""
            body = raw if isinstance(raw, str) and not title else ""
            if isinstance(raw, dict):
                body = str(raw.get("title") or raw.get("name") or "")
            body = own_video_description(resource, body) if row.get("field") == "description" else own_resource_snippet(body)
            title, body = search_instructional_text(title), search_instructional_text(body)
            basis = "catalog" if row.get("kind") == "catalog" else "page"
        else:
            continue
        title, body = _prose(title), _prose(body)
        content = title + " " + body
        if not content.strip() or topic_context_conflict(point["text"], content):
            continue
        if reference_concept_denied(concept, content):
            continue
        if not reference_mechanism_compatible(concept, content):
            continue
        if obvious_technology_conflict(technology, content):
            continue
        overlap = wanted & tokens(content)
        ratio = len(overlap) / len(wanted)
        # Chinese bigrams need two topical overlaps; a short English concept
        # can have one meaningful term. No course is admitted for owner alone.
        minimum = 1 if len(wanted) <= 2 else 2
        core_reference = bool(technology and reference_technology_context(technology, content) and _specific_core(concept, content))
        is_chapter = (row.get("kind") == "catalog"
                      and re.fullmatch(r"chapters(?:\.\d{1,4})?", str(row.get("field", ""))))
        can_inherit = not is_chapter or chapter_can_inherit_technology(technology, row.get("text"))
        chapter_context = own_technology_row if is_chapter and can_inherit else None
        # Own page title/description may supply context to another field on
        # that page. Only the unambiguous course title may donate to a chapter;
        # a sibling chapter or mixed course description cannot do so.
        context_row = chapter_context or (own_page_technology_row if row.get("kind") == "page" else None)
        hints = reference_concept_hints(concept,content) if reference_technology_context(technology,content) or context_row else []
        if not core_reference and not hints and (len(overlap) < minimum or ratio < .4 or not _coherent_topic(concept, content)):
            continue
        ratio = max(ratio,.6) if hints else ratio
        ratio = max(ratio, .4) if core_reference else ratio
        if ADS.search(content) or prerequisite_only_match(point["text"], title, body, "", ""):
            continue
        if version_conflict(point["text"], request.technical_version, content):
            continue
        observations.append({"row": row, "basis": basis, "ratio": ratio,
                             "concept_hints": hints,
                             "context": bool(context_row or technology
                                 and (not page_read or row.get("kind") != "search"
                                      or row.get("source") in _REFERENCE_SEARCH_PROVIDERS and own_page_technology_row)
                                 and not row.get("cache", {}).get("stale")
                                 and _unambiguous_parent_technology(technology, content)),
                             "can_inherit": can_inherit,
                             "context_row": context_row})
    if grounded_decision is not None and not any(item["basis"] != "search" and
            (not technology or item["context"]) for item in observations):
        # A reviewed current own-page observation outranks a search-only or
        # owner-unconfirmed lexical projection. Earlier hard vetoes and the
        # semantic projector's independent binding checks still apply.
        from .grounded_related import project_reference
        semantic = project_reference(point, resource, evidence, request, grounded_decision)
        if semantic is not None:
            return semantic
    if observations and not any(item["basis"] != "search" for item in observations):
        # Search can describe a generic course, but cannot replace a current
        # concrete own topic/catalog that supplies no relevant observation.
        if resource.get("fetch_status") in {"fetched", "success"}:
            for row in evidence:
                try:
                    if (not row.get("evidence_id") or not row.get("source")
                            or not _reference_fresh(row, resource)
                            or normalize_url(row.get("url", "")) not in aliases):
                        continue
                    field = str(row.get("field", ""))
                    text = None
                    if row.get("kind") == "page" and field == "title" and row.get("text") == resource.get("title"):
                        text = row.get("text")
                    elif row.get("kind") == "catalog" and re.fullmatch(r"chapters\.\d{1,4}", field):
                        index = int(field.split(".")[1])
                        chapters = resource.get("chapters") or []
                        if index < len(chapters) and chapters[index].get("evidence_id") == row["evidence_id"]:
                            text = chapters[index].get("title")
                    if not isinstance(text, str):
                        continue
                    label = _prose(text)
                    if technology:
                        label = re.sub(r"(?<![a-z0-9_])" + re.escape(technology) + r"(?![a-z0-9_])", " ", label, flags=re.I)
                    label = re.sub(r"公开|视频|课程|教程|教学|入门|基础|编程|全集|完整|零基础|第[一二三四五六七八九十百0-9]+[课讲章]|"
                                   r"\b(?:public|videos?|courses?|tutorials?|lessons?|teaching|programming|complete|full|basic|basics|beginner|beginners|introduction|introductory)\b", " ", label, flags=re.I)
                    if {word for word in tokens(label) if not word.isdigit()}:
                        return None
                except (UnsafeURL, TypeError, ValueError):
                    continue
    if not observations:
        # The discovery projection already validates each course's own complete
        # outline. Preserve that stronger source-linked result when separate
        # chapters cover a compound topic that lexical matching cannot join.
        # Only that internal projection supplies this assessment, never a raw
        # search candidate or a different course's outline.
        assessment = qualified_outline or {}
        identifiers = set(assessment.get("evidence_ids", []))
        retained = [row for row in evidence if row.get("evidence_id") in identifiers]
        bound_outline = []
        for row in retained:
            try:
                bound_outline.append(row.get("kind") in {"page", "catalog"} and bool(row.get("source"))
                                     and normalize_url(row.get("url", "")) == target)
            except (UnsafeURL, TypeError, ValueError):
                bound_outline.append(False)
        if (assessment.get("status") != "outline_supported" or not assessment.get("display_eligible")
                or not is_mooc_resource(resource) or not all(bound_outline)
                or not identifiers or identifiers != {row.get("evidence_id") for row in retained}
                or not any(row.get("kind") == "catalog" and str(row.get("field", "")).startswith("chapters.") for row in retained)):
            return None
        fields = ("resource_id", "title", "platform", "thumbnail_url", "fetch_status", "video_evidence_status", "resource_type", "access_notice", "requires_payment", "requires_login", "requires_enrollment", "cache", "stale", "resolved_url")
        return {"resource": {**{key: resource.get(key) for key in fields}, "url": target, "canonical_url": target},
                "reference": {"policy": POLICY_VERSION, "kind": "related_reference", "knowledge_point_id": pid,
                    "ranking_score": 90, "reason": "该课程自己的目录已列出所选主题的相关章节。作为相关参考推荐，未验证精确讲授或完整覆盖；章节深度、登录、付费和地区条件请以原平台为准。",
                    "exact_teaching_verified": False, "basis": ["catalog"],
                    "evidence_ids": [row["evidence_id"] for row in retained], "technical_context": "observed",
                    "link_eligible": reference_link_eligible(resource, evidence, retained, target=target)},
                "evidence": retained}
    # A contradictory own title wins over a weak search excerpt. A parent
    # course may supply technology context, but never exact lesson coverage.
    parent_context = False
    parent_evidence = None
    try:
        parent = normalize_url(resource.get("parent_course_url", "")) if resource.get("parent_course_url") else None
    except (UnsafeURL, TypeError, ValueError):
        parent = None
    if parent and technology:
        for row in evidence:
            try:
                if (row.get("kind") == "page" and row.get("field") in {"title", "description"}
                        and row.get("evidence_id") and row.get("source")
                        and not row.get("cache", {}).get("stale")
                        and normalize_url(row.get("url", "")) == parent
                        and _unambiguous_parent_technology(technology, _prose(own_resource_snippet(str(row.get("text") or ""))))):
                    parent_context = True
                    parent_evidence = row
            except (UnsafeURL, TypeError, ValueError):
                continue
    if technology:
        # A different chapter's matching framework cannot validate this one.
        # Keep ordinary own-page evidence and legitimate parent-course context,
        # but only cite individually qualified chapters as navigation targets.
        observations = [item for item in observations if item["context"] or parent_context and item["can_inherit"]
                        or not (item["row"].get("kind") == "catalog"
                                and re.fullmatch(r"chapters(?:\.\d{1,4})?", str(item["row"].get("field", ""))))]
        if not observations:
            return None
    observations.sort(key=lambda item: (item["basis"] == "search", -item["ratio"], not item["context"]))
    observed_context = any(item["context"] for item in observations)
    if technology and not observed_context and not parent_context:
        return None
    own = any(item["basis"] != "search" for item in observations)
    score = max(item["ratio"] for item in observations) * 65 + (15 if own else 0) + (10 if observed_context else 5 if parent_context else 0)
    reason = ("本视频/课程的标题、简介或目录与该知识点相关。" if own else
              "检索结果的标题或简介与该知识点相关；页面详情尚未读取。")
    hints=list(dict.fromkeys(hint for item in observations for hint in item['concept_hints']))
    if hints:
        reason += "相关性采用常见中英文术语或API提示："+"、".join(hints)+"。"
    if parent_context and not observed_context:
        reason += "技术语境来自父课程，具体课节仍需核对。"
    elif technology and not observed_context:
        reason += "目标技术语境尚未确认。"
    reason += "作为相关参考推荐，未验证精确讲授或完整覆盖；登录、付费、地区及播放条件以原平台为准。"
    retained = [item["row"] for item in observations[:5 if parent_evidence else 6]]
    for item in observations:
        context_row = item.get("context_row")
        if context_row and context_row not in retained:
            retained.append(context_row)
    if parent_evidence and parent_evidence not in retained:
        retained.append(parent_evidence)
    retained = list({row["evidence_id"]: row for row in retained}.values())
    fields = ("resource_id", "title", "platform", "thumbnail_url", "fetch_status", "video_evidence_status", "resource_type", "access_notice", "requires_payment", "requires_login", "requires_enrollment", "cache", "stale", "resolved_url")
    return {"resource": {**{key: resource.get(key) for key in fields}, "url": target, "canonical_url": target},
            "reference": {"policy": POLICY_VERSION, "kind": "related_reference", "knowledge_point_id": pid,
                "ranking_score": round(score, 2), "reason": reason, "exact_teaching_verified": False,
                "basis": list(dict.fromkeys([*(item["basis"] for item in observations), *(["parent_course"] if parent_evidence else [])])),
                "evidence_ids": [row["evidence_id"] for row in retained],
                "technical_context": "observed" if observed_context else "parent_course" if parent_context else "unconfirmed",
                "link_eligible": reference_link_eligible(resource, evidence, retained, target=target)},
            "evidence": retained}


def related_recommendations(point, resources, evidence, request, limit, *, qualified_outlines=None):
    qualified_outlines = qualified_outlines or {}
    candidates = [value for rid, resource in resources.items()
                  if (value := related_recommendation(point, resource, evidence.get(rid, []), request,
                                                      qualified_outline=qualified_outlines.get(rid)))]
    candidates.sort(key=lambda row: (-row["reference"]["ranking_score"], row["resource"]["canonical_url"]))
    unique = list({row["resource"]["canonical_url"]: row for row in reversed(candidates)}.values())
    unique.sort(key=lambda row: (-row["reference"]["ranking_score"], row["resource"]["canonical_url"]))
    platforms = sorted({row["resource"]["platform"] for row in unique})
    return unique[:limit], {platform: [row for row in unique if row["resource"]["platform"] == platform][:limit]
                            for platform in platforms}
