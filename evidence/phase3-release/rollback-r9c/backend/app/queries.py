from itertools import zip_longest
import re
from .models import Query, SearchRequest
from .probe_priority import has_literal_identifier
from .config import course_domains

PLATFORMS = {"bilibili": "bilibili.com", "icourse163": "icourse163.org", "xuetangx": "xuetangx.com"}


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
    # This deliberately omits ambiguous '及' (e.g. 及格率) and does not infer
    # API synonyms. Parts are query-selection hints, not a new topic structure.
    parts = [part.strip() for part in re.split(r"[与和、]|\s+and\s+", body, flags=re.I)]
    return parts if 2 <= len(parts) <= 4 and all(len(part) >= 2 for part in parts) else []


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
    expansions = [phrase for value in expansions or [] if (phrase := _bounded_expansion(text, value)) is not None]
    version = f" {request.technical_version.strip()}" if request.technical_version.strip() else ""
    level = {"beginner": "入门", "intermediate": "进阶", "advanced": "高级", "any": ""}[request.student_level]
    if request.language == "en":
        level = {"beginner": "beginner", "intermediate": "intermediate", "advanced": "advanced", "any": ""}[request.student_level]
        teaching, alternate = "video tutorial", "course lesson"
    else:
        teaching, alternate = "视频教程", "课程 教学"
    stem = f"{text}{version}"
    result = [Query(knowledge_point_id=point_id, query=f"{stem} {level} {teaching}".strip()),
              Query(knowledge_point_id=point_id, query=f"{stem} {alternate}")]
    for platform in dict.fromkeys(request.preferred_platforms):
        domain = PLATFORMS[platform]
        path = "/video" if platform == "bilibili" else ""
        result.append(Query(knowledge_point_id=point_id, query=f"site:{domain}{path} {stem} {teaching}", domain_filters=[domain]))
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


def fair_queries(groups: list[list[Query]]) -> list[Query]:
    return [q for row in zip_longest(*groups) for q in row if q is not None]


# Small lexical translations diversify discovery, not evidence or teaching
# equivalence. They apply across projects/tools and contain no resource URLs.
_RECALL_TRANSLATIONS = (
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
