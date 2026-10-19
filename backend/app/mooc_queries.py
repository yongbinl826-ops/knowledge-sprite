"""Bounded course discovery phrases, independent of curriculum verification.

Only the MOOC lane uses this strategy. Broad course-family terms and a small
literal bilingual vocabulary may improve recall; neither supplies evidence,
changes a knowledge point, adds a request, or relaxes the outline gate.
"""
from __future__ import annotations

import re
import unicodedata

from .models import Query, SearchRequest

MOOC_QUERY_POLICY = "course-discovery-phrases-v2"
MOOC_DOMAIN = "icourse163.org"

# Course-family words are discovery hints, not asserted ownership of a result
# or substitutes for the user's topic. Unknown names never acquire a family.
_COURSE_FAMILIES = {
    "python": ("程序设计", "programming"),
    "pandas": ("数据分析", "data analysis"),
    "numpy": ("科学计算", "scientific computing"),
    "sql": ("数据库", "databases"),
    "mysql": ("数据库", "databases"),
    "html": ("网页设计", "web design"),
    "css": ("网页设计", "web design"),
    "javascript": ("网页编程", "web programming"),
    "typescript": ("程序设计", "programming"),
    "java": ("程序设计", "programming"),
    "c++": ("程序设计", "programming"),
    "c#": ("程序设计", "programming"),
    "opencv": ("计算机视觉", "computer vision"),
    "pygame": ("游戏程序设计", "game programming"),
    "arduino": ("嵌入式系统", "embedded systems"),
    "matlab": ("科学计算", "scientific computing"),
}

# An exact part and its explicit owner are required. In particular, 函数列表
# does not add the Python list type, and an unspecified 连接 is not a SQL JOIN.
_CHAPTER_TERMS = {
    "python": {"列表": "list", "字典": "dictionary", "元组": "tuple", "集合": "set",
               "函数": "functions", "循环": "loops", "异常处理": "exception handling"},
    "pandas": {"数据分组": "groupby", "分组": "groupby", "聚合": "aggregation",
               "数据聚合": "aggregation", "分组聚合": "groupby aggregation", "缺失值": "missing values"},
    "sql": {"多表连接": "JOIN", "表连接": "JOIN", "连接查询": "JOIN",
            "分组查询": "GROUP BY", "分组统计": "GROUP BY", "聚合函数": "aggregate functions"},
    "mysql": {"多表连接": "JOIN", "表连接": "JOIN", "连接查询": "JOIN",
              "分组查询": "GROUP BY", "分组统计": "GROUP BY", "聚合函数": "aggregate functions"},
    "html": {"表单": "form", "网页结构": "document structure", "文档结构": "document structure"},
    "css": {"响应式布局": "responsive layout", "盒模型": "box model", "选择器": "selectors"},
}

# These less restrictive words only widen a search. They never enter the
# selected point or curriculum assessment (for example SQL "连接" is not
# accepted as proof of the requested multi-table join).
_RECALL_TERMS = {
    "pandas": {"数据分组": "分组", "聚合": "聚合"},
    "sql": {"多表连接": "连接", "分组查询": "分组"},
}

_FORBIDDEN = re.compile(
    r"[a-z][a-z0-9+.-]*://|www\.|(?<![\w.])(?:site|filetype|ext|inurl|allinurl|intitle|"
    r"allintitle|intext|allintext|related|cache|before|after)\s*:|(?:^|\s)![A-Za-z]\w*", re.I)


def _safe_label(value):
    if not isinstance(value, str) or _FORBIDDEN.search(value):
        return None
    value = "".join(" " if unicodedata.category(char) in {"Cc", "Cf", "Cs"} else char for char in value)
    # Preserve explicit identifiers, plus/C# spellings and numeric versions;
    # call punctuation, quoted search operators and exclusions are never sent.
    value = re.sub(r"[^\w.+#\s]", " ", value)
    value = " ".join(value.split())
    return value if 1 <= len(value) <= 180 else None


def _explicit_owner(text):
    for owner in sorted(_COURSE_FAMILIES, key=len, reverse=True):
        match = re.match(r"^\s*(" + re.escape(owner) + r")(?=$|[\s.\u3400-\u9fff])", text, re.I)
        if match:
            return match[1]
    return None


def _body(text, owner):
    if not owner:
        return text
    return re.sub(r"^" + re.escape(owner) + r"(?=$|[\s.\u3400-\u9fff])", "", text, count=1, flags=re.I).strip()


def _with_owner(label, owner):
    if not owner or re.match(r"^" + re.escape(owner) + r"(?=$|[\s.\u3400-\u9fff])", label, re.I):
        return label
    return owner + label if label.startswith(".") else owner + " " + label


def _explicit_parts(text, original_text, owner, request, *, exact=False):
    values = list(request.learning_targets.get(original_text, [])) or list(request.learning_skills.get(original_text, []))
    if not values:
        body = _body(text, owner)
        # A leading numeric version is retained elsewhere, not a chapter part.
        body = re.sub(r"^\d+(?:\.\d+)*\s+", "", body)
        values = re.split(r"[与和、]|\s+and\s+", body, flags=re.I)
        if len(values) < 2:
            values = [body]
    # The exact slot must retain every declared part, unlike the earlier
    # bounded per-part discovery slots. Fall back rather than silently omit one.
    if exact and not 2 <= len(values) <= 8:
        return []
    parts = []
    for value in values[:8]:
        label = _safe_label(value)
        if not label:
            if exact:
                return []
            continue
        part_owner = _explicit_owner(label)
        if owner and part_owner and part_owner.casefold() != owner.casefold():
            if exact:
                return []
            continue
        label = _body(label, owner)
        if exact and not label:
            return []
        if label and label.casefold() not in {part.casefold() for part in parts}:
            parts.append(label)
    return parts if exact else parts[:4]


def _english_chapters(parts, owner):
    vocabulary = _CHAPTER_TERMS.get((owner or "").casefold(), {})
    translated = []
    for part in parts:
        if part in vocabulary:
            translated.append(vocabulary[part])
        elif re.fullmatch(r"[A-Za-z0-9_.+# ]+", part):
            # Already explicit English/API terms need no semantic expansion.
            translated.append(part)
    return " ".join(dict.fromkeys(translated)) or None


def _query_labels(point: dict, request: SearchRequest) -> list[tuple[str, str]]:
    """Six stable slots plus four optional search-only recall slots.

    Keep the original point first, then a named technology's broader course
    family, the first two explicit parts, literal English chapter terms and an
    exact phrase query for all safely split original parts. Unknown owners or
    unsplittable topics retain the original syllabus wording. No source URL or
    course identity is synthesized. Optional slots keep every safe selected
    part, use no course suffix, and do not change the first six observations.
    """
    original = point.get("text")
    text = _safe_label(original)
    if not text:
        raise ValueError("MOOC knowledge point must be a plain, bounded topic label")
    owner = _explicit_owner(text)
    if not owner:
        # An unfamiliar literal name can still be retained as query context.
        # It receives no family, translation or inferred language ownership.
        explicit = re.match(r"^([A-Za-z][A-Za-z0-9_.+#]*)", text)
        owner = explicit[1] if explicit else None
    parts = _explicit_parts(text, original, owner, request)
    english = request.language == "en"
    family = _COURSE_FAMILIES.get((owner or "").casefold())
    broad = owner + " " + family[int(english)] if family else text
    translated = _english_chapters(parts, owner)
    labels = [text, broad,
              _with_owner(parts[0], owner) if parts else text,
              _with_owner(parts[1], owner) if len(parts) > 1 else text,
              _with_owner(translated, owner) if translated else (_with_owner(parts[2], owner) if len(parts) > 2 else text),
              text]
    suffixes = ("course", "course content", "course chapters", "course lessons", "course outline", "course syllabus") if english else (
        "课程", "课程 内容", "课程 章节", "课程 教学", "课程 目录", "课程 大纲")
    exact_parts = _explicit_parts(text, original, owner, request, exact=True) if family else []
    if len(exact_parts) >= 2:
        exact_label = owner + " " + " ".join('"' + part + '"' for part in exact_parts)
        if len(exact_label) <= 180:
            labels[-1] = exact_label
            suffixes = (*suffixes[:-1], "")
    optional = [text] * 4
    if exact_parts:
        vocabulary = _RECALL_TERMS.get(owner.casefold(), {})
        recall_parts = [vocabulary.get(part, part) for part in exact_parts]
        english_vocabulary = _CHAPTER_TERMS.get(owner.casefold(), {})
        # Unknown translations retain their original phrase, so a partly
        # translated query cannot silently remove a selected obligation.
        english_parts = [english_vocabulary.get(part, part) for part in exact_parts]
        optional = [owner + " " + " ".join('"' + part + '"' for part in recall_parts),
                    owner + " " + " ".join(exact_parts),
                    owner + " " + " ".join(english_parts),
                    owner + " " + " ".join(recall_parts)]
        optional = [label if len(label) <= 180 else text for label in optional]
    labels.extend(optional)
    suffixes = (*suffixes, "", "", "", "")
    # A declared version belongs to every recall slot, including broad course
    # discovery. Versionless sources still require independent outline checks.
    version = _safe_label(request.technical_version)
    if version and owner:
        version = _body(version, owner) or None
    initial_version = re.match(r"^" + re.escape(owner or "") + r"\s+(\d+(?:\.\d+)*)(?=\s|$)", text) if owner else None
    version = version or (initial_version[1] if initial_version else None)
    pairs = []
    for label, suffix in zip(labels, suffixes):
        if version and not re.search(r"(?<![\w.])" + re.escape(version) + r"(?![\w.])", label, re.I):
            label += " " + version
        pairs.append((label, suffix))
    return pairs


def mooc_query_label(point: dict, request: SearchRequest, round_index: int = 0) -> tuple[str, str]:
    """Stable label/suffix integration seam; caller owns platform scheduling."""
    mooc_query_site(round_index)
    return _query_labels(point, request)[round_index]


def mooc_query_site(round_index: int = 0) -> str:
    """Optional slots narrow the literal search scope, not provider domains."""
    if isinstance(round_index, bool) or not isinstance(round_index, int) or not 0 <= round_index < 10:
        raise ValueError("MOOC search round must be between 0 and 9")
    return "www.icourse163.org/course/" if round_index >= 6 else "icourse163.org/course"


def mooc_query_plan(point: dict, request: SearchRequest, *, rounds: int = 6) -> list[Query]:
    if isinstance(rounds, bool) or not isinstance(rounds, int) or not 1 <= rounds <= 10:
        raise ValueError("MOOC query plan must contain between 1 and 10 rounds")
    return [Query(knowledge_point_id=point["knowledge_point_id"],
        query=f"site:{mooc_query_site(index)} {label} {suffix}".strip(), domain_filters=[MOOC_DOMAIN])
        for index, (label, suffix) in enumerate(_query_labels(point, request)[:rounds])]


def mooc_platform_query(point: dict, request: SearchRequest, *, round_index: int = 0) -> Query:
    label, suffix = mooc_query_label(point, request, round_index)
    return Query(knowledge_point_id=point["knowledge_point_id"],
        query=f"site:{mooc_query_site(round_index)} {label} {suffix}".strip(), domain_filters=[MOOC_DOMAIN])
