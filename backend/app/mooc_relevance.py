"""Free, conservative MOOC recall admission and source-bound outline assessment.

An outline describes the advertised course scope, never playback, teaching depth,
or learner mastery. Search observations admit a bounded page probe only.
"""
from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import parse_qsl, urlsplit

from .ranking import (ADS, PREREQUISITE, decompose_topic, own_resource_snippet,
                      prerequisite_only_match, search_instructional_text)
from .url_utils import UnsafeURL, normalize_url
from .mooc_urls import public_course_url

SCHEMA_VERSION = "mooc-outline-v1"
MATCH_RULES_VERSION = 4
_HOSTS = {"www.icourse163.org", "icourse163.org"}
_CATALOG_SOURCES = {
    "html.icourse163.course_outline.text",
    "html.icourse163.termDto.outLineDto.outLine",
    "html.icourse163.termDto.outLineDto.outLineStructureDtos",
}
_TECHNOLOGIES = {"python", "java", "javascript", "typescript", "sql", "nosql", "mysql",
    "pandas", "numpy", "polars", "matplotlib", "seaborn", "pygame", "arduino", "esp32",
    "mqtt", "html", "css", "flask", "django", "http", "rest", "opencv", "c++", "c#",
    "rust", "swift", "kotlin", "php", "matlab", "tensorflow", "pytorch", "scratch"}
_LANGUAGES = {"python", "java", "javascript", "typescript", "c++", "c#", "rust", "swift", "kotlin", "php", "matlab"}
_GENERIC = {"基础", "入门", "学习", "知识", "课程", "教程", "数据", "应用", "操作", "使用", "介绍", "概述", "basics", "introduction", "course"}
_NON_TEACHING = re.compile(r"不(?:会|将)?(?:讲|教|涉及|包含|包括|涵盖|含)|未(?:讲|教|涉及|包含|包括|涵盖)|仅(?:作|供)(?:参考|拓展)|拓展阅读|预告|后续课程|未来课程|\b(?:not\s+(?:covered|taught|included)|will\s+not\s+(?:teach|cover)|future\s+(?:course|lesson)|excluding|excludes?)\b", re.I)
_EXTERNAL_URL = re.compile(r"https?://[^\s<>\"']+", re.I)
_ALIASES = {
    "列表": ("列表", "list", "lists"), "字典": ("字典", "dict", "dictionary", "dictionaries"),
    "数据分组": ("数据分组", "分组", "groupby", "group by"),
    "分组": ("分组", "groupby", "group by"),
    "聚合": ("聚合", "aggregate", "aggregation", "aggregations"),
    "分组聚合": ("分组聚合", "数据分组与聚合", "分组与聚合"),
    "多表连接": ("多表连接", "多表联接", "多表关联查询", "两表连接", "两个表连接", "多个表连接",
               "内连接", "外连接", "左连接", "右连接", "全连接", "inner join", "outer join",
               "left join", "right join", "full join", "cross join"),
    "分组查询": ("分组查询", "分组统计查询", "group by", "grouping queries"),
}
_HTML_STRUCTURE = re.compile(r"(?<![A-Za-z0-9_.+#-])html(?:\s*5)?\s*(?:结构元素|(?:网页)?(?:文档|文件)(?:的)?(?:基本)?结构|基本结构)", re.I)
_SEARCH_EXCLUDED_SECTION = re.compile(r"^(?:预备知识|先修知识|先修要求|先修课程|证书要求|参考资料|拓展阅读|课程评价|相关推荐)(?:\s*[:：].*)?$")
_SEARCH_TEACHING_SECTION = re.compile(r"^(?:课程概述|课程简介|课程目标|教学目标|课程内容|教学内容|课程大纲|课程详情)\s*[:：]?$")


def _url(value):
    try:
        return normalize_url(value)
    except (UnsafeURL, TypeError, ValueError):
        return None


def is_mooc_resource(resource: dict) -> bool:
    """Trust URL hosts, never a caller-controlled platform label."""
    for key in ("url", "canonical_url", "resolved_url"):
        value = _url(resource.get(key))
        host = urlsplit(value).hostname if value else ""
        if host == "icourse163.org" or host.endswith(".icourse163.org"):
            return True
    return False


def _public_course(value):
    return public_course_url(value)


def _has(term, text):
    if term.casefold() == "html":
        # HTML5 is the named version of HTML; do not treat arbitrary prefix
        # overlaps (HTML50, XHTML, template identifiers) as technical owners.
        return re.search(r"(?<![A-Za-z0-9_.+#-])html(?:\s*5)?(?![A-Za-z0-9_.+#-])", text, re.I) is not None
    if re.fullmatch(r"[A-Za-z0-9_+#. ]+", term):
        return re.search(r"(?<![A-Za-z0-9_.+#-])" + re.escape(term) + r"(?![A-Za-z0-9_.+#-])", text, re.I) is not None
    return term.casefold() in text.casefold()


def _clean(text):
    return search_instructional_text(_EXTERNAL_URL.sub(" ", own_resource_snippet(str(text or ""))))


def _search_instructional_fields(raw):
    """Preserve own instructional paragraphs before a separate prerequisite.

    Search snippets often contain an entire public course overview followed by
    a prerequisite section. That later heading must not erase earlier teaching
    text; nor can a blank line end a prerequisite section and donate its owner.
    These fields admit a page probe only, never outline coverage.
    """
    fields, paragraph = [], []
    excluded = False

    def flush():
        if paragraph:
            original = " ".join(paragraph)
            cleaned = _clean(original)
            if _teaching(original) and _teaching(cleaned):
                fields.append(cleaned)
            paragraph.clear()

    for line in raw.splitlines():
        text = line.strip()
        heading = text.strip("#[]【】 \t")
        if _SEARCH_EXCLUDED_SECTION.fullmatch(heading):
            flush()
            excluded = True
        elif _SEARCH_TEACHING_SECTION.fullmatch(heading):
            flush()
            excluded = False
        elif not text:
            flush()
        elif not excluded:
            paragraph.append(text)
    flush()
    return fields


def _parts(point):
    text = str(point.get("text") or "").strip()
    plan = decompose_topic(text)
    context = plan.get("shared_context", [])
    parts = plan.get("subtopics", [])
    if not context:
        first = re.match(r"^\s*([A-Za-z][A-Za-z0-9+#.]*)", text)
        context = [first[1]] if first else []
    if not parts:
        remainder = text
        for owner in context:
            remainder = re.sub(r"^\s*" + re.escape(owner) + r"\s*", "", remainder, count=1, flags=re.I)
        split = [part.strip() for part in re.split(r"[与及和、]|\s+and\s+", remainder, flags=re.I)]
        # Explicit conjunctions are retained even without an English owner.
        if 2 <= len(split) <= 6 and all(len(part) >= 2 for part in split):
            parts = [{"id": f"subtopic_{i + 1}", "text": part} for i, part in enumerate(split)]
        else:
            parts = [{"id": "whole_topic", "text": remainder or text}]
    # Confirmed user-selected concepts are additional obligations, not evidence.
    parts = [*parts, *[{"id": f"learning_target_{i + 1}", "text": str(value)}
                     for i, value in enumerate(point.get("learning_targets") or [])]]
    return context, parts


def _matches(part, text, context=()):
    value = part.strip()
    if not value or value.casefold() in _GENERIC:
        return False
    if value == "网页结构" and _HTML_STRUCTURE.search(text):
        return True
    if (value == "网页结构" and any(owner.casefold() == "html" for owner in context)
            and re.fullmatch(r"(?:第?\s*[\d一二三四五六七八九十]+(?:[.．-]\d+)*\s*[章节课、.．:：-]?\s*)?(?:网页文档(?:的)?(?:基本)?结构|文档(?:的)?基本结构)", text.strip())):
        return True
    if (value == "多表连接" and any(owner.casefold() == "sql" for owner in context)
            and not any(_has(tech, text) for tech in _TECHNOLOGIES - {"sql"})):
        # A relational table join, with independently verified SQL ownership.
        # Connection configuration/strings and NoSQL identifier suffixes do
        # not name this query operation.
        if "数据表连接查询" in text or re.search(r"(?<![A-Za-z0-9_.+#-])SQL连接查询", text, re.I):
            return True
    # A list of references/functions and a terminology dictionary are not
    # declarations of the requested programming data structures. Remove only
    # these explicit compound senses; an independent genuine mention remains.
    if value == "列表":
        text = re.sub(r"(?:函数|参数|课程|章节|参考文献|参考资料|参考|API(?:参考)?|相关课程|推荐课程)(?:的)?列表"
                      r"|\b(?:function|parameter|course|chapter|reference|api\s+reference)\s+lists?\b", " ", text, flags=re.I)
    elif value == "字典":
        text = re.sub(r"(?:术语|词汇|词语|英汉|汉英|英文|翻译)(?:的)?字典"
                      r"|\b(?:terminology|glossary|translation|english)\s+dictionar(?:y|ies)\b", " ", text, flags=re.I)
    alternatives = _ALIASES.get(value, (value,))
    if any(_has(alias, text) for alias in alternatives):
        return True
    # Whitespace-separated technical phrases retain every required word.
    pieces = value.split()
    return len(pieces) > 1 and all(piece.casefold() not in _GENERIC and _has(piece, text) for piece in pieces)


def _teaching(text):
    return bool(text.strip()) and not PREREQUISITE.search(text) and not _NON_TEACHING.search(text)


def _stale(value):
    return isinstance(value.get("cache"), dict) and bool(value["cache"].get("stale"))


def _bound_field(resource, records, field, own_url):
    provenance = resource.get("field_provenance", {}).get(field, {})
    if not isinstance(provenance, dict):
        return ""
    record = records.get(provenance.get("evidence_id"), {})
    value = resource.get(field)
    if (not isinstance(value, str) or record.get("kind") != "page" or record.get("field") != field
            or record.get("text") != value or record.get("source") != provenance.get("source")
            or not record.get("source") or record.get("source") == "search"
            or _url(record.get("url")) != own_url or _url(provenance.get("url")) != own_url or _stale(record)):
        return ""
    original_id = record.get("id")
    expected_id = "ev_" + hashlib.sha256(f"{own_url}|{field}|{record['source']}|{value}".encode()).hexdigest()[:20]
    if original_id is not None and original_id != expected_id:
        return ""
    return _clean(value) if _teaching(_clean(value)) else ""


def _outline(resource, evidence, own_url):
    chapters = resource.get("chapters")
    if (resource.get("fetch_status") not in {"fetched", "success"}
            or resource.get("metadata_evidence_level") != "catalog"
            or resource.get("catalog_kind") != "course_outline" or resource.get("catalog_fetch_status") not in {None, "fetched", "success"}
            or resource.get("resolved_url") and _url(resource["resolved_url"]) != own_url
            or _stale(resource) or not isinstance(chapters, list) or not 1 <= len(chapters) <= 500):
        return None, {}, "outline_not_available"
    records = {}
    for row in evidence:
        identifier = row.get("evidence_id")
        if identifier in records:
            return None, {}, "ambiguous_evidence_identity"
        if identifier:
            records[identifier] = row
    provenance = resource.get("field_provenance", {}).get("chapters", {})
    if not isinstance(provenance, dict):
        return None, records, "outline_provenance_invalid"
    source = provenance.get("source")
    aggregate = records.get(provenance.get("evidence_id"), {})
    if (source not in _CATALOG_SOURCES or _url(provenance.get("url")) != own_url
            or aggregate.get("kind") != "catalog" or aggregate.get("field") != "chapters"
            or aggregate.get("source") != source or _url(aggregate.get("url")) != own_url or _stale(aggregate)):
        return None, records, "outline_provenance_invalid"
    verified = []
    for index, chapter in enumerate(chapters):
        if not isinstance(chapter, dict):
            return None, records, "outline_chapter_invalid"
        row = records.get(chapter.get("evidence_id"), {})
        raw = row.get("text")
        if (chapter.get("source") != source or _url(chapter.get("source_url")) != own_url
                or row.get("kind") != "catalog" or row.get("field") != f"chapters.{index}"
                or row.get("source") != source or _url(row.get("url")) != own_url
                or not isinstance(raw, str) or len(raw) > 10000 or _stale(row)):
            return None, records, "outline_chapter_binding_invalid"
        facts = {key: value for key, value in chapter.items() if key not in {"evidence_id", "source"}}
        try:
            decoded = json.loads(raw)
        except (TypeError, ValueError):
            return None, records, "outline_chapter_json_invalid"
        digest = hashlib.sha256(raw.encode()).hexdigest()
        if (decoded != facts or not isinstance(facts.get("title"), str) or not facts["title"].strip()
                or row.get("evidence_sha256") not in {None, digest}):
            return None, records, "outline_chapter_text_mismatch"
        # Persisted evidence uses a remapped UUID but retains extractor's hash id.
        original_id = row.get("id")
        expected_id = "ev_" + hashlib.sha256(f"{own_url}|chapters.{index}|{source}|{raw}".encode()).hexdigest()[:20]
        if original_id is not None and original_id != expected_id:
            return None, records, "outline_chapter_hash_mismatch"
        entry = {"index": index, "title": facts["title"], "evidence_id": row["evidence_id"],
                 "source_url": own_url, "source_text_sha256": digest}
        if "outline_parent_index" in facts:
            parent_index = facts["outline_parent_index"]
            if (source != "html.icourse163.termDto.outLineDto.outLineStructureDtos"
                    or isinstance(parent_index, bool) or not isinstance(parent_index, int)
                    or not 0 <= parent_index < index
                    or "outline_parent_index" in verified[parent_index]
                    or any("outline_parent_index" not in item for item in verified[parent_index + 1:])):
                return None, records, "outline_parent_binding_invalid"
            entry["outline_parent_index"] = parent_index
        verified.append(entry)
    if (any("outline_parent_index" in chapter for chapter in chapters)
            and (aggregate.get("id") is None or any(records[chapter["evidence_id"]].get("id") is None for chapter in chapters))):
        return None, records, "outline_parent_hash_missing"
    if aggregate.get("id") is not None:
        originals = []
        for chapter in chapters:
            row = records[chapter["evidence_id"]]
            original = {key: chapter[key] for key in ("title", "url", "start_seconds", "end_seconds", "source_url", "duration_seconds", "page_number", "outline_parent_index") if key in chapter}
            original.update(source=source, evidence_id=row.get("id") or row["evidence_id"])
            originals.append(original)
        expected = "ev_" + hashlib.sha256(f"{own_url}|chapters|{source}|{originals}".encode()).hexdigest()[:20]
        if aggregate["id"] != expected or aggregate.get("text") != str(originals)[:2000]:
            return None, records, "outline_aggregate_hash_mismatch"
    return verified, records, None


def assess_mooc_relevance(point: dict, resource: dict, evidence: list[dict]) -> dict:
    """Return auditable admission and coverage, without network/model calls."""
    context, parts = _parts(point)
    result = {"schema_version": SCHEMA_VERSION, "status": "rejected", "display_eligible": False,
              "probe_eligible": False, "probe_priority": 0, "reason_codes": [],
              "subtopics": [{**part, "status": "unknown", "evidence_ids": []} for part in parts],
              "matched_chapters": [], "evidence_ids": []}
    target = _url(resource.get("canonical_url") or resource.get("url"))
    own_url = _public_course(resource.get("url"))
    if not is_mooc_resource(resource) or not own_url or target != own_url:
        result["reason_codes"] = ["unsupported_public_course_route"]
        return result
    searches = [row for row in evidence if row.get("kind") == "search"
                and row.get("knowledge_point_id") == point.get("knowledge_point_id")
                and _url(row.get("url")) == own_url and row.get("evidence_id") and row.get("title")]
    from .course_library import library_observations
    libraries = library_observations(point, resource, evidence)
    if not searches and not libraries:
        result["reason_codes"] = ["missing_same_point_search_observation"]
        return result
    outline, records, invalid_reason = _outline(resource, evidence, own_url)
    if outline is not None:
        parent = _bound_field(resource, records, "title", own_url)
        parent_tech = {tech for tech in _TECHNOLOGIES if _has(tech, parent)}
        for part in result["subtopics"]:
            part["status"] = "not_observed"
        for chapter in outline:
            text = _clean(chapter["title"])
            if not _teaching(text):
                continue
            chapter_tech = {tech for tech in _TECHNOLOGIES if _has(tech, text)}
            # Parent can donate only an unambiguous own-page technical owner.
            # No descriptions or sibling headings can donate a missing owner.
            module = outline[chapter["outline_parent_index"]] if "outline_parent_index" in chapter else None
            module_text = _clean(module["title"]) if module else ""
            if module and not _teaching(module_text):
                continue
            module_tech = {tech for tech in _TECHNOLOGIES if _has(tech, module_text)}
            inherited_ids = []
            owners_present = True
            for owner in context:
                if _has(owner, text):
                    continue
                if (module and _teaching(module_text) and _has(owner, module_text)
                        and not (chapter_tech - {owner.casefold()})
                        and not (module_tech - {owner.casefold()})):
                    inherited_ids.append(module["evidence_id"])
                elif (_has(owner, parent) and not (chapter_tech - {owner.casefold()})
                        and not (parent_tech - {owner.casefold()})
                        and not (module_tech - {owner.casefold()})):
                    inherited_ids.append(resource.get("field_provenance", {}).get("title", {}).get("evidence_id"))
                else:
                    owners_present = False
                    break
            if not owners_present:
                continue
            matched = []
            for part in result["subtopics"]:
                if _matches(part["text"], text, context):
                    part["status"] = "supported"
                    part["evidence_ids"].append(chapter["evidence_id"])
                    matched.append(part["id"])
            if matched:
                result["matched_chapters"].append({**chapter, "subtopic_ids": matched,
                    "context_evidence_ids": list(dict.fromkeys(identifier for identifier in inherited_ids if identifier))})
        supported = sum(part["status"] == "supported" for part in result["subtopics"])
        result["status"] = "outline_supported" if supported == len(parts) else "outline_partial" if supported else "outline_no_match"
        result["display_eligible"] = result["status"] == "outline_supported"
        result["reason_codes"] = ["all_selected_subtopics_observed_in_own_outline" if result["display_eligible"] else "some_selected_subtopics_not_observed" if supported else "selected_subtopics_not_observed_in_read_outline"]
        result["evidence_ids"] = list(dict.fromkeys(identifier for chapter in result["matched_chapters"]
            for identifier in [chapter["evidence_id"], *chapter["context_evidence_ids"]]))
        return result
    if not searches:
        # A public library receipt can reuse a complete, fresh outline. It is
        # never a substitute for a real search observation when probing a page.
        result["reason_codes"] = [invalid_reason or "outline_not_available", "library_requires_valid_outline"]
        return result
    best = 0
    reasons = []
    for row in searches:
        raw_title = own_resource_snippet(str(row.get("title") or ""))
        raw_snippet = own_resource_snippet(str(row.get("snippet") or ""))
        title, snippet = _clean(raw_title), _clean(raw_snippet)
        if ADS.search(title) or re.search(r"MOOC进校园|慕课进校园|招生简章|课程推荐汇总", title, re.I):
            reasons.append("promotional_or_directory_result")
            continue
        if prerequisite_only_match(point.get("text", ""), raw_title, raw_snippet, "", ""):
            reasons.append("prerequisite_only_search_match")
            continue
        if any(_NON_TEACHING.search(raw) and all(_matches(part["text"], raw) for part in parts)
               for raw in (raw_title, raw_snippet)):
            reasons.append("non_teaching_search_scope")
            continue
        clean_fields = ([title] if _teaching(raw_title) and _teaching(title) else [])
        clean_fields.extend(_search_instructional_fields(raw_snippet))
        # A sentence-ending full stop is punctuation, not a namespace suffix.
        # This normalization admits only a page read; outline evidence is exact.
        clean_fields = [re.sub(r"(?<=[A-Za-z])\.(?=\s|$)", " ", field) for field in clean_fields]
        observed = " ".join(clean_fields)
        if context and not all(_has(owner, observed) for owner in context):
            reasons.append("required_technical_context_missing")
            continue
        owners = {owner.casefold() for owner in context}
        title_languages = {tech for tech in _LANGUAGES if _has(tech, title)}
        if owners & _LANGUAGES and title_languages - owners and not owners & title_languages:
            reasons.append("conflicting_course_technology")
            continue
        hits = sum(_matches(part["text"], observed) for part in parts)
        explicit_instruction = (context and all(owner.casefold() in _TECHNOLOGIES for owner in context)
            and any(_teaching(field) and all(_has(owner, field) for owner in context)
                    and re.search(r"讲解|讲授|教授|教学|掌握|运用|使用|\b(?:teach|teaches|learn|learning|use|using)\b", field, re.I)
                    for field in clean_fields))
        if not hits and not (context and all(_has(owner, title) for owner in context) and _teaching(title)) and not explicit_instruction:
            reasons.append("no_specific_topic_signal")
            continue
        best = max(best, 10 if not hits and explicit_instruction and not all(_has(owner, title) for owner in context)
                   else 20 + 10 * hits + 5 * all(_has(owner, title) for owner in context))
    if not best:
        result["reason_codes"] = list(dict.fromkeys(reasons)) or ["no_specific_topic_signal"]
        return result
    result.update(status="outline_unavailable" if resource.get("fetch_status") not in {None, "not_fetched"} else "search_candidate",
                  probe_eligible=resource.get("fetch_status") in {None, "not_fetched"}, probe_priority=best,
                  reason_codes=[invalid_reason or "outline_not_available", "search_only_never_coverage"])
    return result
