from itertools import zip_longest
import re
from .models import Query, SearchRequest
from .probe_priority import has_literal_identifier
from .config import course_domains
from .ai_video_fallback import normalize_empty_api_calls, video_recovery_required_literals

PLATFORMS = {"bilibili": "bilibili.com", "icourse163": "icourse163.org", "xuetangx": "xuetangx.com"}

# Word classes select among technologies the request itself declares. They do
# not map APIs to languages or invent undeclared framework ownership.
_PROGRAMMING_LANGUAGES = {"javascript", "typescript", "python", "java", "c", "c++", "c#",
    "rust", "go", "ruby", "php", "swift", "kotlin", "dart", "scala", "julia", "lua", "r"}


def _query_context(text: str) -> list[str]:
    """Retain the leading technology and explicit named object/version tokens."""
    leading = re.match(r"\s*([A-Za-z][A-Za-z0-9+#._]*(?:\s+[A-Za-z0-9][A-Za-z0-9+#._]*)*)", text)
    if not leading:
        return []
    words = leading[1].split()
    context = words[:1]
    for word in words[1:]:
        if not (word[0].isupper() or word[0].isdigit()):
            break
        context.append(word)
    return context


def _recall_terms(text: str) -> set[str]:
    # Used only to detect almost unchanged queries, never teaching equivalence.
    text = re.sub(
        r"(?:\s*(?:视频教程|基础教程|入门教程|教程|课程|入门|教学|示例|视频|"
        r"(?<![A-Za-z0-9_])(?:tutorials?|courses?|lessons?|examples?|beginner)))+\s*$", "", text, flags=re.I)
    return {term.casefold() for term in re.findall(r"[A-Za-z][A-Za-z0-9_+#.]*|[\u4e00-\u9fff]", text)
            if term.casefold() not in {"and", "with", "of"}}


def _explicit_query_parts(text: str, context: list[str]) -> list[str]:
    body = re.sub(r"^\s*" + r"\s+".join(re.escape(term) for term in context), "", text, count=1, flags=re.I).strip()
    parts = split_query_parts(body)
    return parts if 2 <= len(parts) <= 4 and all(len(part) >= 2 for part in parts) else []


def split_query_parts(text: str) -> list[str]:
    """Literal conjunctions only, never a new knowledge-point decomposition."""
    # Avoid ordinary words such as 涉及/普及/及格/及时. A short or empty
    # component cannot create a recall part either; no API synonyms are inferred.
    # Prefer explicit boundaries once, so an internal 和 in a component is
    # not recursively treated as a conjunction. A bare 和 is ambiguous.
    parts = re.split(r"以及|[与、]|\s+and\s+", text, flags=re.I)
    if len(parts) == 1:
        parts = re.split(r"(?<![涉触波普提顾危不累殃])及(?![格第时早其])", text)
    return [part.strip() for part in parts]


def declared_query_stack(request: SearchRequest, text: str = "") -> list[str]:
    """Bounded positive stack declaration from original input, never a plan.

    The list is literal search context, not an assertion of API ownership.
    Ambiguous/negative/example/experience clauses deliberately contribute none.
    """
    forbidden = re.compile(r"(?:https?://|www\.|\b(?:site|filetype|inurl)\s*:|[!@`$]|"
        r"不|未|无|禁止|比较|对比|而非|例如|比如|已会|熟悉|学过|曾经|假如|如果|或|"
        r"\b(?:not|without|rather\s+than|instead\s+of|compare\w*|example|previously|either|or|secret|token|password|key)\b)", re.I)
    for clause in re.split(r"[。；;，!?\n]", request.project_context):
        if forbidden.search(clause):
            continue
        match = re.search(r"(?:只用|仅用|使用|采用|基于|原生|(?i:\busing\b|\buse\b|\bbased\s+on\b))\s*(?:原生\s*)?"
                          r"([A-Za-z][A-Za-z0-9+#]*(?:\s+(?:[A-Z][A-Za-z0-9+#]*|[0-9][0-9.]*)){0,2})", clause)
        if not match:
            continue
        terms = [" ".join(_query_context(match[1]))]
        if not terms or len(" ".join(terms)) > 60:
            continue
        # A declared native stack may list several literal technologies. Do
        # not guess which language owns a particular API or append pin nouns.
        tail = clause[match.end():]
        for _ in range(3):
            item = re.match(r"\s*(?:[、, /]|和|与|\band\b)\s*([A-Za-z][A-Za-z0-9+#]*)(?=\s|[、,/和与]|做|开发|实现|编写|搭建|$)", tail, re.I)
            if not item:
                break
            terms.append(item[1])
            tail = tail[item.end():]
        terms = list(dict.fromkeys(terms))[:4]
        named = [term for term in terms if re.search(r"(?<![A-Za-z0-9_.+#])" + re.escape(term.split()[0])
                + r"(?![A-Za-z0-9_.+#])", text, re.I)]
        languages = [term for term in terms if term.split()[0].casefold() in _PROGRAMMING_LANGUAGES]
        return named or languages or terms
    return []


def query_contextual_concept_name(text: str, technology: str) -> str:
    """Join a search-only owner, removing only exact leading suffix overlap.

    Ranking and canonical point labels retain their existing independent rules.
    No aliases, token substitutions or inferred technology ownership are used.
    """
    from .professional_concepts import clean_topic_technology
    technology = clean_topic_technology(technology)
    if not technology:
        return text
    words = technology.split()
    for index in range(len(words)):
        overlap = " ".join(words[index:])
        match = re.match(re.escape(overlap).replace(r"\ ", r"\s+")
                         + r"(?=$|\s|[\u3400-\u9fff])", text, re.I)
        if match:
            suffix = text[match.end():].strip()
            return " ".join([technology, suffix]).strip()
    return technology + " " + text


def contextual_search_phrase(text: str, request: SearchRequest) -> str:
    """Keep the entire professional label; only prepend declared missing stack."""
    if request.topic_technologies.get(text):
        return query_contextual_concept_name(text, request.topic_technologies[text])
    if request.learning_targets.get(text) or request.learning_skills.get(text):
        return text  # Legacy target-specific pipelines keep their own contract.
    missing = [term for term in declared_query_stack(request, text) if not re.search(
        r"(?<![A-Za-z0-9_.+#])" + re.escape(term) + r"(?![A-Za-z0-9_.+#])", text, re.I)]
    phrase = " ".join([*missing, text])
    return phrase if len(phrase) <= 180 else text  # Never truncate the original.


def complementary_search_phrase(text: str, request: SearchRequest, round_index: int) -> str | None:
    """Use each explicit named component in an existing subsequent slot."""
    if (round_index not in {1, 2} or request.learning_targets.get(text)
            or request.learning_skills.get(text)):
        return None
    parts = _explicit_query_parts(text, [])
    if not parts or round_index > len(parts):
        return None
    # A repeated component with/without its literal leading owner is not a
    # distinct recall target ("QuillFlow queues and queues").
    context = _query_context(text)
    cores = _explicit_query_parts(text, context)
    if len({re.sub(r"\s+", "", value).casefold() for value in cores}) < 2:
        return None
    part = re.sub(r"([A-Za-z0-9_.+#])(?=[\u3400-\u9fff])", r"\1 ", parts[round_index - 1])
    owner = request.topic_technologies.get(text)
    # A reviewed point owner is narrower than the full project's stack.
    # Its original leading identifiers still constrain every component query.
    stack = [owner, *_query_context(text)] if owner else declared_query_stack(request, text)
    if not stack:
        stack = _query_context(text)
    if owner:
        phrase = part
        for term in reversed(stack):
            if not re.search(r"(?<![A-Za-z0-9_.+#])" + re.escape(term)
                             + r"(?![A-Za-z0-9_.+#])", phrase, re.I):
                phrase = query_contextual_concept_name(phrase, term)
        return _bounded_expansion(text, phrase)
    prefix = [term for term in stack if not re.search(
        r"(?<![A-Za-z0-9_.+#])" + re.escape(term) + r"(?![A-Za-z0-9_.+#])", part, re.I)]
    return _bounded_expansion(text, " ".join([*prefix, part]))


def _bounded_expansion(text: str, value: str) -> str | None:
    phrase = " ".join(value.split())
    # Shared by compact selection and legacy supplementation, including topics
    # without a leading ASCII technology. Rejected phrases never enter queries.
    phrase_limit = min(80, max(40, len(" ".join(text.split())) + 16))
    if not 2 <= len(phrase) <= phrase_limit or re.search(r"https?://|www\.|[/\\<>:!@=\"()]|(?:^|\s)-\S", phrase, re.I):
        return None
    return phrase


def compact_search_phrase(text: str, expansions: list[str] | None) -> str | None:
    """Use bounded model keywords for recall, never as a matching target.

    Keep the leading named technology and at least one additional search term.
    The original topic remains a separate query and the sole evidence target.
    A URL, engine command or search operator cannot come from model output.
    """
    context = _query_context(text)
    if not context:
        return None
    candidates = []
    for value in expansions or []:
        phrase = _bounded_expansion(text, value)
        if phrase is None:
            continue
        remaining = phrase
        for term in context:
            pattern = r"(?<![A-Za-z0-9_.+#])" + re.escape(term) + r"(?![A-Za-z0-9_.+#])"
            if not re.search(pattern, remaining, re.I):
                break
            remaining = re.sub(pattern, " ", remaining, count=1, flags=re.I)
        else:
            if re.search(r"[\u4e00-\u9fff]{2}|[A-Za-z]{2}", remaining) and phrase.casefold() != text.strip().casefold():
                if phrase.casefold() not in {candidate.casefold() for candidate in candidates}:
                    candidates.append(phrase)
    if not candidates:
        return None
    parts = _explicit_query_parts(text, context)
    def covered(phrase):
        compact = re.sub(r"\s+", "", phrase).casefold()
        return sum(re.sub(r"\s+", "", part).casefold() in compact for part in parts)
    selected = candidates[0]
    # Prefer a demonstrably complete alternative over an obvious one-part
    # truncation. Unknown API aliases are not assumed to cover a missing part.
    complete = [phrase for phrase in candidates if parts and covered(phrase) == len(parts)]
    if complete:
        selected = complete[0]
    original_terms = _recall_terms(text)
    selected_terms = _recall_terms(selected)
    near_original = len(original_terms & selected_terms) / max(1, len(original_terms | selected_terms)) >= .8
    if near_original:
        for phrase in candidates:
            if phrase == selected:
                continue
            # Keep useful subsets (e.g. removing a business qualifier). Only
            # prefer a short novel variant when no currently covered part is lost.
            if covered(phrase) < covered(selected) or not (_recall_terms(phrase) - original_terms):
                continue
            if len(phrase) <= len(selected) + 16:
                return phrase
    return selected


def generate_queries(point_id: str, text: str, request: SearchRequest, expansions: list[str] | None = None, *, open_course_domains: tuple[str, ...] = ()) -> list[Query]:
    """Two open-web queries and one per preferred platform, at most six per point."""
    if request.learning_skills.get(text):
        return skill_queries(point_id, text, request)
    expansions = [phrase for value in expansions or [] if (phrase := _bounded_expansion(text, value)) is not None]
    version = f" {request.technical_version.strip()}" if request.technical_version.strip() else ""
    level = {"beginner": "入门", "intermediate": "进阶", "advanced": "高级", "any": ""}[request.student_level]
    if request.language == "en":
        level = {"beginner": "beginner", "intermediate": "intermediate", "advanced": "advanced", "any": ""}[request.student_level]
        teaching, alternate = "video tutorial", "course lesson"
    else:
        teaching, alternate = "视频教程", "课程 教学"
    stem = f"{contextual_search_phrase(text, request)}{version}"
    result = [Query(knowledge_point_id=point_id, query=f"{stem} {level} {teaching}".strip()),
              Query(knowledge_point_id=point_id, query=f"{stem} {alternate}")]
    for platform in dict.fromkeys(request.preferred_platforms):
        domain = PLATFORMS[platform]
        path = "/video" if platform == "bilibili" else ""
        platform_teaching = alternate if platform == "icourse163" else teaching
        result.append(Query(knowledge_point_id=point_id, query=f"site:{domain}{path} {stem} {platform_teaching}", domain_filters=[domain]))
    domains = course_domains(",".join(open_course_domains))
    if domains:
        scope = "(" + " OR ".join(f"site:{domain}" for domain in domains) + ")"
        result.append(Query(knowledge_point_id=point_id, query=f"{scope} {stem} {alternate}", domain_filters=list(domains)))
    if expansions and not domains:
        # Extension supplements the exact point, never replaces it or supplies URLs.
        result.append(Query(knowledge_point_id=point_id, query=f"{stem} {expansions[0]} {alternate}"))
    elif expansions:
        # Keep the bounded extra source query; optional expansion supplements the
        # existing second unrestricted query instead of creating a seventh query.
        result[1].query = f"{stem} {expansions[0]} {alternate}"
    compact = compact_search_phrase(text, expansions)
    if compact:
        # Preserve exact recall first: concise API terms alone can miss sources
        # whose title uses the original natural-language operation. The second
        # unrestricted query provides diversity without replacing that baseline.
        result[1].query = f"{compact}{version} {teaching}"
    return result[:6]


def skill_queries(point_id: str, text: str, request: SearchRequest) -> list[Query]:
    """Search reviewed teaching skills, retaining exact practice requirements elsewhere.

    No model expansion, project constants or hidden new goals are introduced.
    Existing query/request/detail limits still apply. Operators are removed from
    student labels; URLs and engine instructions are rejected by the schema.
    """
    labels = []
    for original in request.learning_skills.get(text, []):
        label = re.sub(r"[^\w.+#\-\s]", " ", original, flags=re.UNICODE)
        label = re.sub(r"(?<!\w)-(?=\w)", " ", label)
        label = " ".join(label.split())
        if label and label.casefold() not in {item.casefold() for item in labels}:
            labels.append(label)
    if not labels:
        return []
    suffix = "video tutorial" if request.language == "en" else "视频教程"
    version = f" {request.technical_version.strip()}" if request.technical_version.strip() else ""
    # Global student level does not imply familiarity with every new library.
    # Stage fit remains an observed, explained ranking factor, not a search gate.
    platforms = list(dict.fromkeys(request.preferred_platforms))
    general_count = max(1, 6 - len(platforms))
    has_bilibili = "bilibili" in platforms
    general_labels = ([labels[(index + 1) % len(labels)] for index in range(min(general_count, len(labels)))]
                      if has_bilibili else labels[:general_count])
    result = [Query(knowledge_point_id=point_id,query=f"{label}{version} {suffix}")
              for label in general_labels]
    non_bilibili_index = 0
    for index, platform in enumerate(platforms):
        domain = PLATFORMS[platform]
        path = "/video" if platform == "bilibili" else ""
        if has_bilibili:
            label = labels[0] if platform == "bilibili" else labels[(general_count + 1 + non_bilibili_index) % len(labels)]
            if platform != "bilibili":
                non_bilibili_index += 1
        else:
            label = labels[(general_count + index) % len(labels)]
        platform_suffix = ("course lesson" if request.language == "en" else "课程 教学") if platform == "icourse163" else suffix
        result.append(Query(knowledge_point_id=point_id,
            query=f"site:{domain}{path} {label}{version} {platform_suffix}",domain_filters=[domain]))
    return result[:6]


def fair_queries(groups: list[list[Query]]) -> list[Query]:
    return [q for row in zip_longest(*groups) for q in row if q is not None]


# Small lexical translations diversify discovery, not evidence or teaching
# equivalence. They apply across projects/tools and contain no resource URLs.
_RECALL_TRANSLATIONS = (
    (r"表单(?:输入|录入|数据收集)", "form input"),
    (r"文件下载|下载文件", "file download"),
    (r"文本(?:分段|切分|分割)", "text splitting"),
    (r"矩形.{0,4}(?:碰撞|相交|重叠)", "rectangle collision"),
    (r"(?:下落|下降).{0,4}(?:更新|移动)?", "falling movement update"),
    (r"(?:游戏结束|结束状态|失败状态)", "game over state"),
    (r"(?:重新开始|重开|状态重置)", "restart reset state"),
    (r"(?:键盘|按键).{0,6}(?:控制|输入|移动)", "keyboard input movement"),
    (r"(?:文字|文本|分数).{0,4}(?:显示|绘制)", "text rendering"),
    (r"事件循环", "event loop"),
    (r"窗口.{0,3}(?:创建|初始化)", "create window"),
    (r"(?:读取|导入).{0,4}CSV|CSV.{0,4}(?:读取|导入)", "read CSV"),
    (r"(?:读取|导入).{0,4}Excel|Excel.{0,4}(?:读取|导入)", "read Excel"),
    (r"缺失值", "missing values"),
    (r"分组聚合|分组统计", "groupby aggregation"),
    (r"数据筛选|数据过滤", "data filtering"),
    (r"(?:图表|图像|绘图).{0,4}(?:保存|导出)", "save plot image"),
    (r"响应式布局", "responsive layout"),
    (r"表单.{0,3}(?:校验|验证)", "form validation"),
    (r"状态管理", "state management"),
    (r"模拟.{0,6}(?:采样|读取)", "analog input sampling"),
    (r"串口.{0,4}(?:通信|输出|读取)", "serial communication"),
    (r"非阻塞|不阻塞", "nonblocking"),
)


def _recall_translation(fragment: str) -> str | None:
    translated = [english for pattern, english in _RECALL_TRANSLATIONS if re.search(pattern, fragment, re.I)]
    if not translated:
        return None
    # Preserve explicit API, file-format and version spellings from this part.
    literals = re.findall(r"[A-Za-z][A-Za-z0-9_.+#]*|\b\d+(?:\.\d+)*\b", fragment)
    return " ".join(dict.fromkeys([*literals, *translated]))


def _video_recovery_translation(text: str) -> str | None:
    """Replace known lexical spans, retaining every unmatched qualifier.

    Unlike a bag of translated terms, this cannot drop an unknown second
    operation, file format, API or version from a compound selected concept.
    """
    spans = sorted((hit.start(), hit.end(), english, hit.group())
                   for pattern, english in _RECALL_TRANSLATIONS
                   # Legacy gap recall permits wildcard paraphrases; this
                   # whole-point path must not consume an unknown operation
                   # between the known words (e.g. CSV conversion + reading).
                   if ".{" not in pattern
                   for hit in re.finditer(pattern, text, re.I))
    if not spans:
        return None
    pieces, cursor = [], 0
    for start, end, english, matched in spans:
        if start < cursor:
            continue
        literals = re.findall(r"[A-Za-z][A-Za-z0-9_.+#]*|\b\d+(?:\.\d+)*\b", matched)
        retained = [word for word in literals if not re.search(
            r"(?<![A-Za-z0-9_.+#])" + re.escape(word) + r"(?![A-Za-z0-9_.+#])", english, re.I)]
        pieces.extend([text[cursor:start], " ".join([*retained, english])])
        cursor = end
    pieces.append(text[cursor:])
    translated = re.sub(r"以及|与|、", " and ", " ".join(pieces))
    return " ".join(translated.split())


def video_recovery_search_phrases(text: str, request: SearchRequest,
                                  model_hints: list[str] | tuple[str, ...] = ()) -> list[str]:
    """Compatibility projection of bounded discovery; hints are never facts."""
    return video_recovery_search_phrases_with_diagnostics(text, request, model_hints)[0]


def video_recovery_search_phrases_with_diagnostics(
    text: str, request: SearchRequest, model_hints: list[str] | tuple[str, ...] = (),
) -> tuple[list[str], dict]:
    """Keep the full original first, with at most two complementary queries.

    Safe English leads may describe unfamiliar or partially known operations.
    Known operation spans, literal technology/API/version and all source gates
    remain unchanged. A lead is not a translation assertion or matching target.
    Diagnostics contain only bounded counts and fixed labels, never input text.
    """
    values = model_hints[:2] if isinstance(model_hints, (list, tuple)) else ()
    diagnostic = {"schema_version": 1, "status": "normalized", "input_hints": len(values),
        "accepted_hints": 0, "not_evaluated_hints": 0,
        "rejected_hints": {key: 0 for key in ("empty", "invalid_syntax_or_length", "word_limit",
            "missing_literal", "version_conflict", "duplicate", "operation_not_preserved",
            "insufficient_specificity", "slots_exhausted")}, "phrase_kinds": []}
    if not isinstance(model_hints, (list, tuple)):
        diagnostic["status"] = "invalid_hint_container"

    def finish_early(status):
        diagnostic.update(status=status, not_evaluated_hints=len(values))
        return [], diagnostic

    if text not in request.knowledge_points:
        return finish_early("target_unavailable")

    def safe(value, limit):
        if not isinstance(value, str) or len(value) > limit or re.search(r"[\x00-\x1f\x7f]", value):
            return None
        value = normalize_empty_api_calls(value)
        if re.search(r'https?://|www\.|\b[\w-]+\.(?:com|org|net|cn|io)\b|'
                     r'[/\\<>:!@="();|`$]|(?:^|\s)-\S', value, re.I):
            return None
        phrase = " ".join(value.split())
        return phrase if 2 <= len(phrase) <= limit else None

    def contains(value, required):
        pattern = r"(?<![A-Za-z0-9_.+#])" + re.escape(required).replace(r"\ ", r"\s+") + r"(?![A-Za-z0-9_.+#])"
        return bool(re.search(pattern, value, re.I))

    source_contextual = normalize_empty_api_calls(contextual_search_phrase(text, request))
    contextual = re.sub(r"(?<=[\u3400-\u9fff])/(?=[\u3400-\u9fff])", " and ", source_contextual)
    version = " ".join(request.technical_version.split())
    original = contextual if not version or contains(contextual, version) else contextual + " " + version
    original = safe(original, 320)
    if original is None:
        return finish_early("original_rejected")
    results = [original]
    diagnostic["phrase_kinds"].append("original")
    candidates = []
    translated = _video_recovery_translation(contextual)
    if translated:
        if version and not contains(translated, version):
            translated += " " + version
        translated = safe(translated, 80)
        if translated and translated.casefold() != original.casefold():
            candidates.append((translated, "deterministic"))

    context = _query_context(contextual)
    core = re.sub(r"^\s*" + r"\s+".join(re.escape(term) for term in context),
                  "", contextual, count=1, flags=re.I).strip() if context else contextual
    parts = split_query_parts(core)
    literals = video_recovery_required_literals(source_contextual)
    allowed_numbers = set(re.findall(r"\d+(?:\.\d+)*", original))
    unknown_atomic = (len(parts) == 1 and bool(re.search(r"[\u3400-\u9fff]", core))
                      and not re.search(r"与|以及|和|及|、|\band\b", core, re.I)
                      and not any(re.search(pattern, core, re.I) for pattern, _ in _RECALL_TRANSLATIONS))

    generic = {"a", "an", "the", "to", "for", "in", "on", "using", "use", "learn", "learning",
               "intro", "introduction", "beginner", "beginners", "basic", "basics", "fundamentals",
               "overview", "tutorial", "tutorials", "course", "courses", "lesson", "lessons",
               "example", "examples", "guide", "complete", "full", "programming", "development"}

    def english_terms(phrase):
        if re.search(r"[\u3400-\u9fff]", phrase):
            return set()
        return _recall_terms(phrase) - {word.casefold() for word in literals} - _recall_terms(version) - generic

    def alternatives(part):
        result = [part, _video_recovery_translation(part)]
        if re.fullmatch(r"表单(?:输入|录入|数据收集)", part):
            result += ["form inputs", "input widgets"]
        if re.fullmatch(r"文件下载|下载文件", part):
            result += ["download files", "download button"]
        if re.fullmatch(r"文本(?:分段|切分|分割)", part):
            result += ["split text", "text segmentation"]
        return [value for value in result if value]

    def keeps_part(phrase, part):
        return any(contains(phrase, value) for value in alternatives(part))

    # Reuse only existing exact lexical spans; wildcard translations cannot
    # swallow an unknown intervening operation or convert CSV-to-JSON to read CSV.
    spans = sorted((hit.start(), hit.end(), hit.group()) for pattern, _ in _RECALL_TRANSLATIONS
                   if ".{" not in pattern for hit in re.finditer(pattern, core, re.I))
    known, remaining, cursor = [], [], 0
    for start, end, fragment in spans:
        if start < cursor:
            continue
        known.append(fragment)
        remaining.append(core[cursor:start])
        cursor = end
    remaining.append(core[cursor:])
    remainder = re.sub(r"以及|与|和|及|、|\band\b", " ", " ".join(remaining), flags=re.I)
    unfamiliar_compound = (bool(re.search(r"[\u3400-\u9fff]", remainder))
                           and (len(parts) > 1 or bool(re.search(r"与|以及|和|及|、|\band\b", core, re.I))))
    known_terms = set().union(*(_recall_terms(value) for part in known for value in alternatives(part))) if known else set()
    # Preserve an untranslated relationship between multiple identifiers (e.g.
    # CSV-to-JSON) rather than treating their mere presence as the same action.
    # One API plus an unknown action may use an independent English discovery
    # lead: requiring its Chinese suffix would defeat cross-language recall.
    relationship_text = contextual
    declared_owner = request.topic_technologies.get(text, "")
    if not declared_owner and context and context[0].casefold() in _PROGRAMMING_LANGUAGES:
        declared_owner = context[0]
    if declared_owner:
        relationship_text = re.sub(r"^\s*" + re.escape(declared_owner) + r"\s+", "",
                                   relationship_text, count=1, flags=re.I)
    def has_identifier_relation(part):
        identifiers = video_recovery_required_literals(part)
        return any(re.search(re.escape(left) + r"\s*[\u3400-\u9fff]+(?:\s*[\u3400-\u9fff]+)*\s*"
                             + re.escape(right), part)
                   for left, right in zip(identifiers, identifiers[1:]))

    # A relation between named objects is an original constraint even when no
    # operation has a known translation. Merely retaining both names says
    # nothing about direction; uncertain relations must remain verbatim.
    identifier_parts = [part for part in split_query_parts(relationship_text) if has_identifier_relation(part)]
    # Only request-declared owner tokens can be restored. Original
    # target identifiers, including identifiers also present in owner, stay core.
    core_literals = video_recovery_required_literals(text)
    owner_literals = video_recovery_required_literals(declared_owner)
    owner_set = {word.casefold() for word in owner_literals}
    non_owner_core = {word.casefold() for word in core_literals
                      if word.casefold() not in owner_set and re.search(r"[A-Za-z]", word)}

    def restore_declared_owner(phrase):
        missing = [word for word in literals if not contains(phrase, word)]
        if not missing:
            return phrase
        if (not declared_owner or any(word.casefold() not in owner_set for word in missing)
                or not all(contains(phrase, word) for word in core_literals)):
            return None
        # Adding the requested owner must not hide another explicit ecosystem.
        # Reuse existing inheritance in both directions, so complementary
        # markup/language contexts are not treated as competing frameworks.
        from .related_recommendations import (obvious_technology_conflict, chapter_can_inherit_technology,
                                               _CHAPTER_TECH_OWNERS)
        from .technical_prefix import leading_technical_owner
        hint_owner = leading_technical_owner(phrase)
        words = video_recovery_required_literals(phrase)
        named_owners = list(dict.fromkeys([*([hint_owner] if hint_owner else []),
            *(word for word in words if word.split(".", 1)[0].casefold() in _CHAPTER_TECH_OWNERS)]))
        if (obvious_technology_conflict(declared_owner, phrase)
                or any(not (chapter_can_inherit_technology(declared_owner, name + " topic")
                    or chapter_can_inherit_technology(name, declared_owner)) for name in named_owners)):
            return None
        # Punctuation is part of a technical name. C cannot stand in for C++
        # (or C#), even when an older compatibility matrix lacks that spelling.
        if any(re.sub(r"^\.|[.+#]+$", "", word).casefold() == re.sub(r"^\.|[.+#]+$", "", owner).casefold()
                and word.casefold() != owner.casefold() for word in words for owner in owner_literals):
            return None
        # CamelCase and namespaces can be ordinary APIs. Only an explicit new
        # framework/library declaration invokes the existing owner gate.
        declarations = re.finditer(r"[A-Za-z][A-Za-z0-9_.+#]*\s+(?:framework|library|sdk|package)\b", phrase, re.I)
        if any(not chapter_can_inherit_technology(declared_owner, match.group()) for match in declarations):
            return None
        # Restore the declaration's spelling, not reassembled lexical tokens.
        # Remove only an exact leading overlap (HTML5 Canvas + Canvas ...).
        owner_words = declared_owner.split()
        suffix = phrase
        for index in range(len(owner_words)):
            overlap = " ".join(owner_words[index:])
            match = re.match(re.escape(overlap).replace(r"\ ", r"\s+") + r"(?=\s|$)", phrase, re.I)
            if match:
                suffix = phrase[match.end():].strip()
                break
        return safe(" ".join([declared_owner, suffix]).strip(), 80)

    def keeps_chinese_discovery_fragment(phrase):
        # Only exact original compound components can be compact Chinese leads.
        # This does not translate, shorten the target, or supply source facts.
        if not unfamiliar_compound or not re.search(r"[\u3400-\u9fff]", phrase):
            return False
        if not all(contains(phrase, part) for part in identifier_parts):
            return False
        return any(len(re.findall(r"[\u3400-\u9fff]", part)) >= 4
                   and contains(phrase, part) for part in parts)

    deferred = []

    def discovery_key(phrase):
        # Reuse the existing literal conjunction boundaries. Removing only a
        # connector or punctuation cannot create another discovery direction.
        return _recall_terms(" ".join(split_query_parts(phrase)))

    def mixed_translation(phrase):
        # Declared owners and required APIs are not translated English prose.
        body = phrase
        for literal in sorted(literals, key=len, reverse=True):
            body = re.sub(r"(?<![A-Za-z0-9_.+#])" + re.escape(literal)
                          + r"(?![A-Za-z0-9_.+#])", " ", body, flags=re.I)
        return bool(re.search(r"[\u3400-\u9fff]", body) and re.search(r"[A-Za-z]", body))

    def reject(reason):
        diagnostic["rejected_hints"][reason] += 1

    for value in values:
        phrase = safe(value, 80)
        if not phrase:
            reject("empty" if isinstance(value, str) and not value.strip() else "invalid_syntax_or_length")
            continue
        if len(phrase.split()) > 8:
            reject("word_limit")
            continue
        phrase = restore_declared_owner(phrase)
        if not phrase:
            reject("missing_literal")
            continue
        if len(phrase.split()) > 8:
            reject("word_limit")
            continue
        if set(re.findall(r"\d+(?:\.\d+)*", phrase)) - allowed_numbers:
            reject("version_conflict")
            continue
        if version and not contains(phrase, version):
            phrase = safe(phrase + " " + version, 80)
        if not phrase:
            reject("invalid_syntax_or_length")
            continue
        if any(discovery_key(phrase) == discovery_key(item)
               for item in [original, *(item for item, _ in candidates), *deferred]):
            reject("duplicate")
            continue
        if not all(contains(phrase, part) for part in identifier_parts):
            reject("operation_not_preserved")
            continue
        if not all(keeps_part(phrase, part) for part in parts) and not (unknown_atomic and english_terms(phrase)):
            if not unfamiliar_compound or not all(keeps_part(phrase, part) for part in [*known, *identifier_parts]):
                reject("operation_not_preserved")
            elif (len(english_terms(phrase) - known_terms) < (1 if known or non_owner_core else 2)
                  and not keeps_chinese_discovery_fragment(phrase)):
                reject("insufficient_specificity")
            else:
                deferred.append(phrase)
            continue
        candidates.append((phrase, "model"))

    candidates.extend((phrase, "model") for phrase in deferred)
    # Select from the complete validated pool before allocating the two slots.
    # A partial bilingual translation is fallback when complete leads exist.
    selected = set()
    seen = [discovery_key(original)]
    for index in sorted(range(len(candidates)), key=lambda i: mixed_translation(candidates[i][0])):
        phrase, kind = candidates[index]
        key = discovery_key(phrase)
        if key in seen:
            if kind == "model":
                reject("duplicate")
        elif len(selected) == 2:
            if kind == "model":
                reject("slots_exhausted")
        else:
            selected.add(index)
            seen.append(key)
    # Keep stable presentation order among selected leads; only displaced
    # candidates change. The original point and matching target stay untouched.
    for index, (phrase, kind) in enumerate(candidates):
        if index in selected:
            results.append(phrase)
            diagnostic["phrase_kinds"].append(kind)
            if kind == "model":
                diagnostic["accepted_hints"] += 1
    ui_context = {"streamlit", "flet", "gradio", "dash", "html", "react", "vue", "angular", "svelte"}
    if (len(results) < 3 and translated and any(term.casefold() in ui_context for term in context)
            and contains(translated, "file download")):
        alternative = safe(re.sub(r"\bfile download\b", "download button", translated, flags=re.I), 80)
        if alternative and not any(discovery_key(alternative) == discovery_key(item) for item in results):
            results.append(alternative)
            diagnostic["phrase_kinds"].append("deterministic_alternative")
    return results, diagnostic


def gap_query_candidates(point_id: str, original_text: str, request: SearchRequest,
                         missing_parts: list[str], *, open_course_domains: tuple[str, ...] = ()) -> list[Query]:
    """At most six diverse recall queries for the original unit's missing skills.

    The caller supplies actual missing subtopics. Every query keeps the original
    point identity and its explicit tool/version, while the final evidence gate
    must still evaluate original_text. No background/project text is invented.
    """
    context = _query_context(original_text)
    prefix = " ".join(context)
    confirmed_targets = set(request.learning_targets.get(original_text, []))

    def safe_part(value):
        if not isinstance(value, str):
            return None
        if value in confirmed_targets:
            # Only an exact confirmed target may contain call/comparison syntax.
            # Reject URL/engine syntax before stripping punctuation, so it cannot
            # be laundered into an apparently ordinary recall phrase. Keep the
            # original target untouched for the independent evidence checks.
            if re.search(r"(?:[a-z][a-z0-9+.-]*://|www\.|(?<![\w.])(?:site|filetype|ext|inurl|allinurl|intitle|allintitle|intext|allintext|related|cache|before|after)\s*:|(?:^|\s)![A-Za-z]\w*)", value, re.I):
                return None
            # Slash, minus, quotes, brackets and comparison/call punctuation only
            # become spaces. API names/parameter words survive; no alias or URL
            # is invented, and no leading exclusion/operator is emitted.
            value = re.sub(r"[^\w.\s]", " ", value)
        elif re.search(r"[()[\]{}<>!=:;\"'/\\@|&?%`$^*]", value):
            return None  # Unconfirmed expansion syntax never gains this exception.
        return _bounded_expansion(original_text, value)

    # A concrete confirmed identifier can be the last missing target. Spend
    # the existing first gap slice on it before punctuation is removed. This
    # stable ordering never admits unknown expansions or supplies teaching proof.
    ordered_parts = sorted(missing_parts, key=lambda value: not (
        isinstance(value, str) and value in confirmed_targets and has_literal_identifier(value)))
    parts = list(dict.fromkeys(phrase for value in ordered_parts[:8]
        if (phrase := safe_part(value)) is not None))[:4]
    if not parts:
        return []
    version = " ".join(request.technical_version.split())
    teaching = "video tutorial" if request.language == "en" else "视频教程"

    def stem(part):
        phrase = part if not prefix or part.casefold().startswith(prefix.casefold() + " ") else f"{prefix} {part}"
        if version and version.casefold() not in phrase.casefold():
            phrase += " " + version
        return phrase

    results, identities = [], set()

    def append(phrase, domains=()):
        identity = (phrase.casefold(), tuple(domains))
        if identity not in identities and len(results) < 6:
            identities.add(identity)
            results.append(Query(knowledge_point_id=point_id, query=phrase, domain_filters=list(domains)))

    # Spend the first round on each missing skill and the unrestricted source
    # pool. Do not force a preferred platform or duplicate a whole long title.
    for part in parts:
        append(f"{stem(part)} {teaching}")
    for part in parts:
        translated = _recall_translation(part)
        if translated:
            append(f"{stem(translated)} video tutorial")
    domains = course_domains(",".join(open_course_domains))
    scopes = [domains] if domains else []
    scopes.extend((PLATFORMS[platform],) for platform in dict.fromkeys(request.preferred_platforms))
    for scope in scopes:
        restriction = " OR ".join("site:" + domain + ("/video" if domain == "bilibili.com" else "") for domain in scope)
        if len(scope) > 1:
            restriction = f"({restriction})"
        for part in parts:
            append(f"{restriction} {stem(part)} {teaching}", scope)
    return results


def prioritize_video_entry_query(queries: list[Query]) -> list[Query]:
    """Spend the first fair slice on the explicitly preferred video source.

    The original complete learning unit is retained in this source-scoped query.
    Open-web and other course-source queries remain in the bounded schedule.
    This is a scheduling choice, never a seeded URL or a relaxed evidence gate.
    """
    preferred = next((query for query in queries if query.domain_filters == ["bilibili.com"]), None)
    return [preferred, *(query for query in queries if query is not preferred)] if preferred else queries


def public_catalog_query(text: str) -> str:
    """Finite bilingual recall terms for observed English directory metadata.

    They only order detail probes. They never enter resource teaching evidence,
    change the original unit, identify a video, or supply an answer URL.
    """
    vocabulary = (
        (r"网格|二维|行列|地图", "grid tile map"),
        (r"碰撞|穿墙|阻挡", "collision wall"),
        (r"状态|胜利|结束", "state"),
        (r"重置|重开|重新开始", "reset restart"),
        (r"事件|按键|键盘", "keyboard event input"),
        (r"帧率|计时|定时|倒计时", "clock timer"),
        (r"窗口|绘制|显示", "drawing display"),
        (r"得分|分数|计分", "score text"),
        (r"按钮|上拉", "button pullup"),
        (r"去抖|消抖", "debounce"),
        (r"非阻塞|不阻塞|millis", "nonblocking millis"),
        (r"去重|重复记录", "duplicates drop_duplicates"),
        (r"时间.{0,4}(?:解析|清洗)", "datetime parsing"),
        (r"时长|时间差", "timedelta duration"),
        (r"分组|汇总|聚合|小时", "groupby aggregation"),
        (r"排序|前十|top.?10", "sorting counts"),
        (r"图表|条形图|绘图", "plotting chart"),
        (r"导出|保存", "export save"),
        (r"响应式|布局", "responsive layout"),
        (r"表单|校验|验证", "form validation"),
        (r"页面|文档结构", "DOM HTML"),
    )
    terms = [value for pattern, value in vocabulary if re.search(pattern, text, re.I)]
    return (text + " " + " ".join(dict.fromkeys(terms))).strip()[:400]
