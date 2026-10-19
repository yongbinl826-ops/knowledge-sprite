from __future__ import annotations

from .pygame_frame_limit import is_pygame_clock_frame_limit
from .technical_prefix import canonical_search_name, leading_technical_owner

import re
from contextvars import ContextVar
from urllib.parse import urlsplit
from .models import SearchRequest, TopicEvidenceAssessment
from .css_skills import css_target_rule, css_target_non_teaching
from .source_adapters.bilibili import UNAVAILABLE_NOTICE, unavailable_video_projection
from .source_adapters.freecodecamp import VIDEO_SOURCE as FCC_VIDEO_SOURCE, bound_video_topic_summary, course_announcement_url
from .source_adapters.techwithtim import bound_video_topic_summary as twt_bound_summary, lesson_page_url
from .topic_operations import assess_operation_fallback, operation_decomposition, _KNOWN_LIBRARY
from .url_utils import UnsafeURL, host_matches, normalize_url as _normalize_url_uncached
from .video_availability import is_unconfirmed_video_shell, project_unconfirmed_video_shell, unconfirmed_video_shell_assessment, _bound_page_video, is_unconfirmed_fetched_media, native_media_entry_type, project_unconfirmed_fetched_media, unconfirmed_fetched_media_assessment

# Pure string work is reused only inside one synchronous rank call. No fetched
# facts, evidence, permission/DNS decision or input survives this local scope.
_RANK_CACHE_LIMIT = 4096
_RANK_CACHE: ContextVar[tuple[dict[str, str], dict[str, frozenset[str]]] | None] = ContextVar("rank_pure_strings", default=None)


def normalize_url(url: str) -> str:
    scope = _RANK_CACHE.get()
    if scope is None or type(url) is not str:
        return _normalize_url_uncached(url)
    cache = scope[0]
    if url in cache:
        return cache[url]
    value = _normalize_url_uncached(url)  # Exceptions retain original behavior.
    if len(cache) < _RANK_CACHE_LIMIT:
        cache[url] = value
    return value


def tokens(text: str) -> set[str]:
    scope = _RANK_CACHE.get()
    if scope is None or type(text) is not str:
        return _tokens_uncached(text)
    cache = scope[1]
    if text not in cache:
        value = frozenset(_tokens_uncached(text))
        if len(cache) < _RANK_CACHE_LIMIT:
            cache[text] = value
        return set(value)
    return set(cache[text])  # Preserve the public mutable-set API per caller.


TEACHING = re.compile(r"教程|课程|教学|讲解|学习|课堂|lesson|tutorial|course|lecture|training|learn", re.I)
ADS = re.compile(r"招生|包就业|高薪就业|报名咨询|培训机构|限时优惠|优惠券|推广合作|\b(sponsored|promo code|enroll now)\b", re.I)
SEARCH_PATH = re.compile(r"/(search|s|results|tag|tags)(/|$)", re.I)
# "I'll show you everything you need to know" promises teaching; the exact
# show/teach prefix does not turn ordinary prior-knowledge requirements into it.
PREREQUISITE = re.compile(
    r"(?:需要|需|必须|应当|应)?\s*(?:预先|事先|已经|已)\s*(?:掌握|熟悉|具备|了解)"
    r"|先修要求|先修课程|先修知识|预备知识|前置知识"
    r"|(?:要求|需要|需)\s*(?:掌握|熟悉|具备)"
    r"|\bprerequisites?\b|\b(?:prior|previous)\s+(?:knowledge|experience|familiarity)\b"
    r"|\b(?:requires?|assumes?|expects?)\s+(?:(?:some|basic|prior|previous)\s+)?(?:knowledge|experience|familiarity)\b"
    r"|(?<!show you everything )(?<!teach you everything )\b(?:you|students?|learners?)\s+(?:should|must|need to)\s+(?:already\s+)?(?:know|understand|be familiar with)\b", re.I)
NEGATED_REQUIREMENT = re.compile(r"(?:无需|无须|不需要|不要求|不必|不用|不|无|\bno|\bnot|\bwithout)\s*(?:任何|额外的?|相关的?)?\s*$", re.I)
ENGLISH_FUNCTION_WORDS = frozenset({"a", "an", "the", "and", "or", "with", "of", "to", "in", "on", "at", "by", "from", "as", "is", "are", "be", "this", "that", "using", "about"})
ASCII_TERM = re.compile(r"[a-zA-Z][a-zA-Z0-9+#]*(?:\.[a-zA-Z0-9+#]+)*")
RELATED_RESOURCE_TAIL = re.compile(r"(?:相关(?:视频|课程)|相关推荐)\s*[:：]|\b(?:related|recommended)\s+(?:videos|courses)\s*:", re.I)
PYTHON_VERSION_TERM = re.compile(r"pythonv?\d+(?:\.\d+)*")
CLAUSE_BOUNDARY = re.compile(
    r"[。！？!?;；\n]|\.\s+|\b(?:but|however)\b|[，,]\s*(?=(?:无需|无须|不需要|不要求|本课程|课程将|课程会|this course|we teach|(?:and\s+)?(?:"
    + PREREQUISITE.pattern + r")))", re.I)


def type_from_discovered_url(url: str) -> str:
    """Recognize public platform entry formats; this never verifies page access."""
    return native_media_entry_type(url)


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
    if provenance.get("source") == "search_title_url":
        return resource_type == "course" and search_course_evidence(resource.get("url", ""), source_evidence)
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
    if resource.get("resource_type") != "course":
        return False
    try:
        target = normalize_url(resource["url"])
    except UnsafeURL:
        return False
    for item in evidence:
        if item.get("kind") != "search":
            continue
        try:
            if normalize_url(item.get("url", "")) == target and (
                type_from_discovered_url(target) == "course" or search_course_evidence(target, item)
            ):
                return True
        except UnsafeURL:
            continue
    return False


def search_course_evidence(url: str, evidence: dict) -> bool:
    """Strict search-only identity; never upgrades to page or video evidence."""
    if evidence.get("kind") != "search" or not evidence.get("evidence_id") or not evidence.get("source"):
        return False
    try:
        canonical = normalize_url(url)
        if canonical != normalize_url(evidence.get("url", "")):
            return False
        path = urlsplit(canonical).path
    except (UnsafeURL, ValueError, TypeError):
        return False
    title = evidence.get("title") or ""
    snippet = evidence.get("snippet") or ""
    if not isinstance(title, str) or not isinstance(snippet, str) or not snippet.strip():
        return False
    # A tutorial article or a list/review of courses is not a course entry.
    if not re.fullmatch(r"/(?:[a-z]{2}/)?(?:courses?|learn|class|classes)/[^/.]+/?", path, re.I):
        return False
    if re.search(r"/(?:blog|articles?|news|docs?|search|tags?)/", path, re.I):
        return False
    if not re.search(r"课程|公开课|慕课|\bcourse\b", title, re.I):
        return False
    if re.search(r"笔记|讲义|文档|课程推荐|课程列表|课程评测|课程排名|\b(?:notes?|documentation|handouts?)\b|\b(?:best|top)\b.*\bcourses?\b|\bcourse\s+reviews?\b", title, re.I):
        return False
    if re.search(r"not a course|不是课程", title + " " + snippet, re.I):
        return False
    return bool(TEACHING.search(snippet)) and not ADS.search(title + " " + snippet)


def candidate_topic_signal(candidate, point_text: str, request: SearchRequest) -> bool:
    """Only a display-eligible search link can stop independent source discovery."""
    evidence = {"evidence_id": "signal", "kind": "search", "source": candidate.source,
                "url": candidate.url, "title": candidate.title, "snippet": candidate.snippet,
                "type_source": candidate.type_source, "resource_type_hint": candidate.resource_type_hint}
    kind, source = type_from_discovered_url(candidate.url), "url_pattern"
    if kind == "unknown" and candidate.type_source == "search_template":
        kind, source = candidate.resource_type_hint, "search_template"
    if kind == "unknown" and search_course_evidence(candidate.url, evidence):
        kind, source = "course", "search_title_url"
    provenance = {"evidence_id": "signal", "source": source, "url": candidate.url}
    resource = {"resource_id": candidate.id, "url": candidate.url, "resource_type": kind,
                "video_evidence_status": "search_discovered" if kind in {"video", "playlist"} else "none",
                "metadata_evidence_level": "search", "field_provenance": {"title": {"source": "search"},
                    "resource_type": provenance, "video_evidence_status": provenance}}
    match = rank_resource({"knowledge_point_id": "signal", "text": point_text}, resource, [evidence], request)
    return bool(match and match.get("topic_evidence_status") == "supported")


def has_course_page(resource: dict, evidence: list[dict]) -> bool:
    """Explicit course structure can support a course without asserting video."""
    if resource.get("resource_type") != "course" or resource.get("fetch_status") not in {"fetched", "success"} or resource.get("metadata_evidence_level") not in {"page", "catalog"}:
        return False
    provenance = resource.get("field_provenance", {}).get("resource_type", {})
    if not isinstance(provenance, dict) or provenance.get("source") not in {"jsonld.@type", "html.mit_ocw.course_home", "html.microsoft_ai.curriculum_table", "html.icourse163.course_structure", "html.icourse163.embedded_course_structure"}:
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


def _split_concepts(text: str, *, possessive: bool = False) -> list[str]:
    # A conjunction must have complete concepts on both sides. In particular,
    # the second character in 与及格率 / 和及格率 starts a word, not another
    # conjunction. Preserve common lexical prefixes containing these characters.
    conjunction = r"与(?!门)|及(?!格)|和(?!弦)" + (r"|的" if possessive else "")
    boundary = rf"(?<=[\u4e00-\u9fff]{{2}})(?<![与及和的])(?:{conjunction})(?=[\u4e00-\u9fff]{{2}}|\s+[A-Za-z][A-Za-z0-9+#.]*)"
    ascii_conjunction = rf"(?<=[A-Za-z0-9_+#.])(?:{conjunction})(?=[\u4e00-\u9fff]{{2}})"
    return [part.strip() for part in re.split(boundary + "|" + ascii_conjunction + r"|、|\s+and\s+", text, flags=re.I)]


def _chinese_concepts(text: str) -> list[str]:
    output = []
    for match in re.finditer(r"[\u4e00-\u9fff]+", text):
        run = match[0]
        if (len(run) > 2 and run[0] in "与及和的" and not run.startswith(("与门", "及格", "和弦"))
                and re.search(r"[a-zA-Z0-9+#]\s*$", text[:match.start()])):
            run = run[1:]
        output.extend(_split_concepts(run, possessive=True))
    return output


def _tokens_uncached(text: str) -> set[str]:
    # Symbol-suffixed language names keep their identity, including C++17/C#12.
    output = {re.sub(r"(?<=[+#])\d+$", "", term) for term in ASCII_TERM.findall(text.lower())} - ENGLISH_FUNCTION_WORDS
    # Only a complete Python version spelling receives this alias. Arbitrary
    # suffixes and digit-bearing names such as D3.js keep their exact identity.
    output = {"python" if PYTHON_VERSION_TERM.fullmatch(term) else term for term in output}
    for part in _chinese_concepts(text):
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


def own_resource_snippet(snippet: str) -> str:
    """Keep the source record intact, but do not score its recommended links."""
    return RELATED_RESOURCE_TAIL.split(snippet, maxsplit=1)[0]


def own_video_description(resource: dict, text: str) -> str:
    """Project only own prose; do not assign related lessons or a long syllabus.

    A public page may advertise the complete course below one ten-minute lesson.
    Require an observable duration contradiction before excluding its syllabus;
    keep the raw description/evidence intact, and retain long complete courses.
    """
    text = own_resource_snippet(text)
    chapters = resource.get("chapters") or []
    if resource.get("resource_type") != "video" or len(chapters) != 1:
        return text
    marker = re.search(r"课程大纲", text)
    if not marker or len(re.findall(r"课时\s*\d+", text[marker.start():])) < 3:
        return text
    duration = resource.get("duration_seconds") or (chapters[0].get("duration_seconds") if isinstance(chapters[0], dict) else None)
    if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration <= 0:
        return text
    times = [int(minutes) * 60 + int(seconds) for minutes, seconds in
             re.findall(r"(?<!\d)(\d{1,3}):([0-5]\d)(?!\d)", text[marker.start():])]
    if len(times) >= 3 and max(times) > duration + 10 and sum(times) > 2 * duration:
        return text[:marker.start()]
    return text



def source_scope_notice(resource: dict, evidence: list[dict]) -> str:
    """Explain a bound author's explicit example-only scope without hiding it.

    This is derived display text, never new teaching evidence. Only an intact
    own-page description may supply the self-declaration, before related links.
    """
    description = resource.get("description") or ""
    provenance = resource.get("field_provenance", {}).get("description", {})
    source = next((row for row in evidence if row.get("evidence_id") == provenance.get("evidence_id")), {})
    if (resource.get("resource_type") != "video" or source.get("kind") != "page"
            or source.get("field") != "description" or source.get("text") != description
            or not provenance.get("source") or source.get("source") != provenance["source"]):
        return ""
    try:
        own_urls = {normalize_url(resource[key]) for key in ("url", "canonical_url") if resource.get(key)}
        if normalize_url(source.get("url", "")) not in own_urls:
            return ""
        audio_bound = bool(provenance.get("url") and normalize_url(provenance["url"]) in own_urls)
    except (UnsafeURL, ValueError, TypeError):
        return ""
    own = own_video_description(resource, description)
    audio_notice = ""
    # Narrow source self-report, not playback verification or an invalid URL.
    audio_problem = re.compile(r"^(?:(?:本视频|该视频|这个视频|这条视频)的?)?(?:音频|声音|录音)(?:已经|已)?(?:坏了|损坏|缺失|丢失)(?=$|[，,。；;!?\s])")
    if resource.get("video_evidence_status") == "page_verified" and audio_bound:
        for clause in re.split(r"[。；;!?\n]", own):
            if (audio_problem.search(clause.strip())
                    and not re.search(r"如何|怎么|修复|排查|解决|检测|教程", clause)):
                audio_notice = " 作者自述：本视频音频存在问题；请到平台试听后决定是否使用，当前未验证播放。"
                break
    version_notice = ""
    future_version = re.compile(r"(?:后面|后续|之后|以后|将来|未来)[^。；;!?\n]{0,18}(?:会有|会提供|会发布|会推出|补录|更新|上传)[^。；;!?\n]{0,12}完整版")
    non_future_version = re.compile(r"不会|不再|不打算|不准备|不计划|不一定|未必|并非|不是|没有|无需|不用|如何|怎么|教程|修复|排查|解决|检测|另一个视频|另一条视频|其他视频|别的视频|已(?:经)?(?:完成|发布|上传)|现已")
    completed_version = re.compile(r"完整版[^。；;!?\n]{0,8}(?:已(?:经)?|现已)(?:完成|发布|上传)|(?:已(?:经)?|现已)(?:完成|发布|上传)[^。；;!?\n]{0,8}完整版")
    if resource.get("video_evidence_status") == "page_verified" and audio_bound and not completed_version.search(own):
        for clause in re.split(r"[。；;!?\n]", own):
            if future_version.search(clause) and not non_future_version.search(clause):
                version_notice = " 作者提及后续可能提供完整版；当前未核实该版本的发布情况。"
                break
    # Deliberately narrow author self-description. Ordinary examples, mentions
    # of a different lesson and phrases such as 'not merely sharing' do not fit.
    declaration = re.compile(
        r"(?:本视频|该视频|这个视频|这条视频)[^。；;!?\n]{0,40}"
        r"(?:分享|自学记录|学习记录|项目示例)\s*(?:而非|而不是)\s*(?:系统(?:性)?的?)?教程", re.I)
    for clause in re.split(r"[。；;!?\n]", own):
        if (declaration.search(clause)
                and not re.search(r"(?:不是|并非|并不是)\s*(?:自己[^，,。]{0,12})?(?:分享|自学记录|学习记录|项目示例)", clause)):
            return " 作者自述：分享或项目示例，非系统教程；请结合已证实的具体技能学习。" + audio_notice + version_notice
    return audio_notice + version_notice


def search_instructional_text(text: str) -> str:
    """Score prose, not standalone social hashtags, in search observations.

    C# and hashes inside identifiers/strings are not standalone tags. Preserve
    explicitly formatted code and C preprocessor lines as code rather than
    erasing their hash syntax. Persisted evidence is never edited here.
    """
    code = r"(```[\s\S]*?```|`[^`\n]*`|(?m:^[ \t]*#(?:include|define|undef|if|ifdef|ifndef|elif|else|endif|pragma|error|line)\b[^\n]*))"
    hashtag = r"(?<!\S)#[A-Za-z_\u4e00-\u9fff][\w-]*#?(?=$|\s|[，。；！？,;!?])"
    return "".join(part if index % 2 else re.sub(hashtag, " ", part)
                   for index, part in enumerate(re.split(code, text)))


def topic_context_conflict(point: str, observation: str) -> bool:
    """Disambiguate database normal forms from animation pose normalization.

    Only explicit competing context triggers this guard. A bare title such as
    Database Normalization remains eligible; no URL or case identity is used.
    """
    target = tokens(point)
    relational_topic = ('database' in target and bool(target & {'normalization', 'normalisation'})) or bool(re.search(r'数据库.*(?:范式|规范化)', point))
    if not relational_topic:
        return False
    pose_context = bool(re.search(r'\bpose\s+database\b', observation, re.I)) and bool(re.search(r'\bmotion\s+matching\b|\bnormalization\s+set\b', observation, re.I))
    relational_context = bool(re.search(r'\b(?:sql|rdbms|relational|bcnf|[1-5]nf)\b|\bnormal\s+forms?\b|关系数据库|关系模式|函数依赖|第[一二三四五]范式', observation, re.I))
    return pose_context and not relational_context


def locally_bound_chinese_action(concept: str, text: str) -> bool | None:
    """Recognize the same noun/action with bounded teaching-title modifiers.

    A title may say 表单零基础教程：双重校验. Only a small teaching-modifier
    grammar can intervene; 图像 or a different lesson cannot donate its action.
    None means this is not one of the guarded noun/action concepts.
    """
    bound = re.fullmatch(r"([\u4e00-\u9fff]{1,12})(处理|绘制|校验)", concept)
    if not bound:
        return None
    noun, action = map(re.escape, bound.groups())
    modifier = r"(?:零基础|基础|入门|教程|教学|课程|详解|示例|实例|双重|前端|后端|安全|可以|能够|直接|通过|使用|采用|进行|正则表达式|用|的|[：:\s-])"
    modified = rf"{noun}{modifier}{{1,8}}{action}(?=$|[^\u4e00-\u9fff]|安全|思路|方法|教程|教学|详解|实战|案例|工具|机制|流程|函数|[与和及啦了吧哦])"
    pattern = rf"{noun}\s*的?\s*{action}|{action}\s*(?:指定的?\s*)?{noun}|{modified}"
    return any(not PARTIAL_SKILL_NONTEACHING.search(clause) and bool(re.search(pattern, clause))
               for clause in re.split(r"[。；;!?，,\n]", text))


def pygame_text_display_match(point: str, observation: str) -> bool | None:
    """Equivalent Pygame text-display wording, without inferring any scoring.

    A font install/API mention cannot stand in for rendering text. Preserve
    local action ownership, prerequisites, negation and related-video isolation.
    """
    aliases = r"(?:屏幕(?:文字|文本)显示|文字显示|文本显示|字体渲染|文本渲染|文本绘制|文字绘制)"
    if not re.fullmatch(rf"\s*(?:pygame\s*{aliases}|pygame\.font\s+渲染文字)\s*", point, re.I):
        return None
    if "pygame" not in tokens(_technical_text(observation)):
        return False
    # Pygame's documented Font.render -> Surface -> blit flow is also a
    # concrete text-display lesson when its local variable binding is visible.
    # Never infer this from a font install, an API list or unrelated code.
    # https://www.pygame.org/docs/ref/font.html#pygame.font.Font.render
    clean = own_resource_snippet(observation)
    for font in re.finditer(r"(?<![A-Za-z0-9_.])([A-Za-z_]\w*)\s*=\s*pygame\.font\.(?:SysFont|Font)\s*\(", clean):
        prefix = re.split(r"[。；;!?！？\n]", clean[:font.start()])[-1]
        if (PARTIAL_SKILL_NONTEACHING.search(prefix) or PREREQUISITE.search(prefix)
                or re.search(r"API\s*(?:列表|清单)|\bAPI\s+list\b", prefix, re.I)):
            continue
        tail = clean[font.end():font.end() + 1800]
        variable = re.escape(font[1])
        render = re.search(rf"\b([A-Za-z_]\w*)\s*=\s*{variable}\.render\s*\(", tail)
        if not render or re.search(rf"\b{variable}\s*=(?!=)", tail[:render.start()]):
            continue
        image = re.escape(render[1])
        blit = re.search(rf"\b[A-Za-z_]\w*\.blit\s*\(\s*{image}\s*[,)]", tail[render.end():])
        if not blit:
            continue
        flow = tail[:render.end() + blit.end()]
        if (PARTIAL_SKILL_NONTEACHING.search(flow) or PREREQUISITE.search(flow)
                or re.search(r"\b(?:Qt|PyQt\d*|Godot|Unity|JavaScript|Java)\b|API\s*(?:列表|清单)|\bAPI\s+list\b", flow, re.I)
                or re.search(rf"\b{image}\s*=(?!=)", tail[render.end():render.end() + blit.start()])):
            continue
        return True
    display = r"(?:屏幕)?(?:文字|文本)(?:的)?(?:显示|渲染)|(?:显示|渲染)(?:屏幕(?:上的)?)?(?:文字|文本)|字体(?:的)?渲染"
    negative_display = rf"(?:{PARTIAL_SKILL_NONTEACHING.pattern}|没有(?:教|讲|演示|实现|提供)|不是)(?:如何|关于|进行|任何|相关|这个|的|[：:\s]){{0,6}}(?:{display})"
    for clause in re.split(r"[。；;!?！？\n]", own_resource_snippet(observation)):
        # A course may explicitly teach text while saying it does not teach
        # scoring. Only a negation bound to this display operation blocks it.
        if PREREQUISITE.search(clause) or re.search(negative_display, clause, re.I):
            continue
        # A named module is more specific than the generic display intent.
        # Keep its own explicit API wording; never infer it from a title/font download.
        if (re.fullmatch(r"\s*pygame\.font\s+渲染文字\s*", point, re.I)
                and not re.search(r"(?<![A-Za-z0-9_.])pygame\.font(?![A-Za-z0-9_.])", clause, re.I)):
            continue
        for found in re.finditer(display, clause):
            owners = ["pygame", "python"]
            if re.fullmatch(r"\s*pygame\.font\s+渲染文字\s*", point, re.I):
                owners.append("pygame.font")
            if _new_skill_owner_matches(owners, clause, found.start()):
                return True
    return False


PYGAME_RECT_COLLISION_API = re.compile(r"(?<![A-Za-z0-9_.])(?:(?:pygame\.)?Rect\.)?colliderect(?![A-Za-z0-9_.])", re.I)


def pygame_rect_collision_match(point: str, observation: str) -> bool | None:
    """A locally taught colliderect operation tests rectangle overlap only.

    https://www.pygame.org/docs/ref/rect.html#pygame.Rect.colliderect
    This adds no falling, object shape, hit response, scoring or restart proof.
    Bare collision/Sprite lessons retain the ordinary strict concept matcher.
    """
    if not re.fullmatch(r"\s*pygame\s*矩形(?:碰撞|重叠|相交)(?:判定|检测|判断)\s*", point, re.I):
        return None
    clean = re.sub(r"https?://\S+", " ", own_resource_snippet(observation))
    # A search excerpt's ellipsis is not the end of a sentence. Keep explicit
    # foreign owners/outline markers below; missing excerpt text is no proof.
    clean = re.sub(r"\.{2,}", " … ", clean)
    if not PYGAME_RECT_COLLISION_API.search(clean):
        return None
    for clause in re.split(r"[。；;!?！？\n]|\.(?=\s|$)", clean):
        if (PREREQUISITE.search(clause) or PARTIAL_SKILL_NONTEACHING.search(clause)
                or re.search(r"课程大纲|(?:课时\s*\d.*){2}|(?:仅|只)?列出\s*API\s*(?:列表|清单)|(?:需|需要|要)(?:先|预先|事先)掌握|"
                             r"\b(?:api\s+list|list\s+of\s+apis|course\s+(?:outline|syllabus)|see\s+also|references?|links?\s+to)\b|"
                             r"\b(?:list(?:s|ing)?|enumerate)\b.{0,30}\b(?:APIs?|functions?|methods?)\b", clause, re.I)):
            continue
        for found in PYGAME_RECT_COLLISION_API.finditer(clause):
            full_owner = found[0].lower().startswith("pygame.rect.")
            if not full_owner and "pygame" not in tokens(clause):
                continue
            # Ignore ordinary English teaching words between owner and API,
            # while an explicitly introduced other technology still isolates it.
            owners = re.findall(r"\b(?:pygame|python|qt|pyqt\d*|pyside\d*|scratch|godot|unity|sdl\d*|libgdx|javascript|java)\b", clause[:found.start()], re.I)
            if not full_owner and owners and owners[-1].lower() not in {"pygame", "python"}:
                continue
            if (re.match(r"\s*\(", clause[found.end():]) or re.search(
                    r"教程|教学|演示|用法|使用|讲解|\b(?:tutorial|lesson|explain\w*|show\w*|using|function|method)\b", clause, re.I)):
                return True
    return False


def pygame_keyboard_movement_match(point: str, observation: str) -> bool | None:
    """Match an explicit keyboard-to-sprite movement operation, not its wording.

    A learner's character and a lesson's boat are interchangeable examples of
    this operation. Keep the input, movement and Pygame owner in the same source;
    a keyboard mention plus an unrelated animation lesson is insufficient. This
    finite intent grammar does not discard unrecognised request qualifications.
    """
    entity = r"(?:游戏人物|游戏角色|角色|人物|小船|飞船|挡板|精灵|物体|矩形)"
    target = re.fullmatch(rf"\s*pygame\s*(?:(?:键盘|按键)(?:控制|操控){entity}(?:左右|水平)?移动|{entity}(?:键盘|按键)(?:左右|水平)?移动)\s*", point, re.I)
    held_target = re.fullmatch(rf"\s*pygame\s*(?:键盘|按键)(?:长按|持续按下|连续按下)(?:(?:控制|操控)?{entity}(?:左右|水平)?移动|(?:左右|水平)?移动{entity})\s*", point, re.I)
    if not target and not held_target:
        return None
    if "pygame" not in tokens(observation):
        return False
    keyboard = r"(?:键盘(?:事件|按键|状态)?|方向键|按键)"
    # Only known input/teaching modifiers may intervene, not other course topics.
    direct = rf"{keyboard}(?:的|来|用于|使用|通过|响应|处理|——|[-：:\s]){{0,8}}(?:控制|操控){entity}(?:的)?(?:上下左右|左右|上下|水平|方向)?移动"
    # Preserve the source's actual key-state -> position data flow. An API name
    # alone or an unspecified input-device state does not prove this operation.
    state_flow = rf"键盘(?:的某个按键)?(?:的)?按下状态[，,\s]*(?:然后)?根据状态调整{entity}(?:的)?位置"
    # Continuous movement needs explicit repeated/real-time state polling linked
    # to position updates. KEYDOWN/event handling by itself does not establish it.
    position_update = rf"(?:移动{entity}|(?:调整|更新|修改){entity}(?:的)?(?:位置|坐标))"
    realtime_flow = rf"(?:每帧|实时)(?:读取|获取|检测)(?P<device>键盘|按键|设备)(?:的)?(?:按下)?状态[，,\s]*(?:然后|并|再)?(?:根据状态)?{position_update}"
    realtime_modes = r"实时(?:读取|获取|检测)(?:和|或|与)(?:通过)?事件(?:读取|获取|检测)[，,\s]*本(?:视频|节课|教程)(?:将)?(?:为大家)?(?:演示|讲解|介绍)(?:这)?(?:两|二)种方式"
    held_flow = rf"(?:按住|长按)(?:左右)?(?:方向键|按键|左右键)[，,\s]*(?:时)?(?:连续|持续)(?:左右)?移动{entity}"
    for clause in re.split(r"[。；;!?！？\n]", observation):
        if PARTIAL_SKILL_NONTEACHING.search(clause) or PREREQUISITE.search(clause):
            continue
        for found in re.finditer(rf"{direct}|{state_flow}", clause):
            if _new_skill_owner_matches(["pygame", "python"], clause, found.start()):
                if not held_target:
                    return True
        if held_target:
            for found in re.finditer(rf"{realtime_flow}|{held_flow}", clause):
                if not _new_skill_owner_matches(["pygame", "python"], clause, found.start()):
                    continue
                if found.groupdict().get("device") != "设备":
                    return True
    if held_target:
        # Some lesson descriptions first establish keyboard -> position, then
        # give a timestamped real-time device-state segment. Require both nearby
        # descriptions in this one source, with no intervening lesson outline,
        # prerequisite, negation or newly introduced technology owner.
        keyboard_flows = [found for found in re.finditer(state_flow, observation)
                          if _new_skill_owner_matches(["pygame", "python"], observation, found.start())]
        for repeated in re.finditer(rf"{realtime_flow}|{realtime_modes}", observation):
            if not _new_skill_owner_matches(["pygame", "python"], observation, repeated.start()):
                continue
            for initial in keyboard_flows:
                if initial.end() <= repeated.start() <= initial.end() + 320:
                    prefix = re.split(r"[。；;!?！？\n]", observation[:initial.start()])[-1]
                    segment = prefix + observation[initial.start():repeated.end()]
                    if not (PARTIAL_SKILL_NONTEACHING.search(segment) or PREREQUISITE.search(segment)
                            or re.search(r"课程大纲|课时\s*\d|第[一二三四五六七八九十0-9]+课", segment)):
                        return True
    return False


def compound_english_match(point: str, observations: list[str], rule_audit: list[str] | None = None) -> bool:
    """Do not substitute a different concept that shares a few English words.

    Require the complete lexical topic within one source observation. This is
    deliberately conservative. Two bounded technical equivalences are audited;
    there is no URL allowlist or unrestricted semantic expansion.
    The same complete-observation guard applies to Chinese compound topics.
    """
    observations = [text for text in observations if text.strip() and not topic_context_conflict(point, text)]
    if not observations:
        return False
    wanted = tokens(point)
    if not wanted:
        return False
    ascii_wanted = {term for term in wanted if re.search(r"[a-z]", term)}
    chinese_concepts = _chinese_concepts(point)
    if len(ascii_wanted) >= 2:
        chinese_concepts = [concept for concept in chinese_concepts if concept not in {"与", "及", "和"}]
    def covers_concept(concept, observation):
        # Cover the entire concept with observed contiguous terms of >=2 Han
        # characters. Do not require artificial cross-word bigrams (单校),
        # and never stitch individual characters or different observations.
        bound_action = locally_bound_chinese_action(concept, observation)
        if bound_action is not None:
            return bound_action
        if concept in observation:
            return True
        reachable = {0}
        for end in range(2, len(concept)+1):
            if any(start in reachable and concept[start:end] in observation for start in range(end-1)):
                reachable.add(end)
        return len(concept) in reachable
    def variants(term):
        # Small, explicit plural equivalence; keep technical names such as CSS.
        output = {term, term + "s"}
        if len(term) > 4 and term.endswith("ies"):
            output.add(term[:-3] + "y")
        elif len(term) > 3 and term.endswith("s") and not term.endswith(("ss", "us", "is")):
            output.add(term[:-1])
        if len(term) > 3 and term.endswith("y"):
            output.add(term[:-1] + "ies")
        return output
    for observation in observations:
        observed = tokens(observation)
        rules = []
        owner = re.match(r"^\s*([A-Za-z][A-Za-z0-9_+#.]*)\s+", point)
        if owner:
            namespace = owner[1].casefold()
            qualified = [term for term in observed if term.startswith(namespace + ".")]
            if qualified:
                # Explicit qualification supplies this exact namespace and its
                # remaining attribute path, never an operation or API alias.
                observed.add(namespace)
                observed.update(term[len(namespace) + 1:] for term in qualified)
                rules.append("explicit_qualified_namespace_path")
        if _normal_forms_context(point, observation):
            observed.add("database")
            rules.append("database_standard_normal_forms_context")
        rectangle = pygame_rect_collision_match(point, observation)
        if rectangle is not None:
            if rectangle:
                if rule_audit is not None:
                    rule_audit.append("pygame_colliderect_tests_rectangle_overlap")
                return True
            continue
        display = pygame_text_display_match(point, observation)
        if display is not None:
            if display:
                if rule_audit is not None:
                    rule_audit.append("pygame_text_display_wording")
                return True
            continue
        movement = pygame_keyboard_movement_match(point, observation)
        if movement is not None:
            if movement:
                if rule_audit is not None:
                    rule_audit.append("pygame_keyboard_controls_sprite_movement")
                return True
            continue
        chinese_observation = observation
        if 'html' in ascii_wanted and 'html5' in observed:
            observed.add('html');rules.append('unversioned_html_includes_html5')
        if 'html' in ascii_wanted and '表单' in point and '校验' in point and '表单' in observation and '验证' in observation:
            chinese_observation = observation.replace('验证','校验')
            rules.append('html_form_validation_terms')
        # ROW_NUMBER is a SQL window function; its use is relevant application
        # evidence even when a Chinese title omits the English category name.
        # https://learn.microsoft.com/sql/t-sql/functions/row-number-transact-sql
        if re.search(r"(?<![a-z0-9_])(?:sql|mysql|postgresql|tsql)(?![a-z0-9_])", observation, re.I) and re.search(r"(?<![a-z0-9_])row[_\s]+number(?![a-z0-9_])", observation, re.I):
            observed.update({"sql", "window", "function"})
            rules.append("sql_row_number_is_window_function")
        # Explicit CSS Grid + its actual track-definition property supports
        # tracks without requiring the redundant English noun in the snippet.
        # https://www.w3.org/TR/css-grid-1/#explicit-grids
        if {"css", "grid", "explicit"} <= observed and re.search(r"\bgrid-template-(?:columns|rows)\b", observation, re.I):
            observed.add("track")
            rules.append("explicit_css_grid_track_definition")
        if all(variants(term) & observed for term in ascii_wanted) and all(covers_concept(term, chinese_observation) for term in chinese_concepts):
            if rule_audit is not None:
                original = tokens(observation)
                if not all(variants(term) & original for term in wanted):
                    rule_audit.extend(rules)
            return True
    return False


EXTERNAL_URL = re.compile(r"https?://[^\s<>\"']+", re.I)
PROMISE_MEMBER = re.compile(r"(?<![A-Za-z0-9_.])Promise\.(?:allSettled|all|any|race|resolve|reject|withResolvers|try)(?![A-Za-z0-9_.])", re.I)
COMPARISON_CLAUSE = re.compile(r"[^。！？!?;；\n，,]*(?:对比|比较|compared?\s+(?:with|to)|versus|\bvs\.?\s)[^。！？!?;；\n，,]*", re.I)
SCHEDULED_LESSON = re.compile(r"(?:预约|预告|即将|今晚|明晚).{0,25}(?:直播|开播)|(?:直播|开播).{0,25}(?:预约|预告)|\bupcoming\s+(?:live|lesson|webinar)|\b(?:live\s+stream|webinar|premiere)\s+(?:starts?|scheduled)\b", re.I)
RECORDED_LESSON = re.compile(r"直播回放|完整回放|课程回放|直播录播|录制版|已录制|\b(?:recorded\s+(?:lesson|webinar|live)|live\s+(?:replay|recording)|full\s+replay)\b", re.I)


def decompose_topic(text: str) -> dict:
    """Split only explicit conjunctions with an observable shared technical prefix.

    This is a bounded grammar, not a generated syllabus. Ambiguous all-prose
    topics keep their existing whole-topic matching and expose no invented parts.
    """
    text = canonical_search_name(text)
    plan = {"decomposition_status": "not_applicable", "shared_context": [], "subtopics": []}
    if not re.search(r"[与及和、]|\s+and\s+", text, re.I):
        return plan
    chinese = re.fullmatch(r"\s*((?:[A-Za-z][A-Za-z0-9+#.]*(?:\s+|(?=[\u4e00-\u9fff])))+)([\u4e00-\u9fff].*)", text)
    english = re.fullmatch(r"\s*((?:[A-Z][A-Za-z0-9+#.]*\s+)+)([a-z].*)", text)
    match = chinese or english
    if not match:
        return {**plan, "decomposition_status": "unknown"}
    context = match[1].strip().split()
    parts = _split_concepts(match[2])
    if not 2 <= len(parts) <= 4 or any(len(part) < 2 or len(part) > 100 for part in parts):
        return {**plan, "decomposition_status": "unknown"}
    return {"decomposition_status": "applied", "shared_context": context,
            "subtopics": [{"id": f"subtopic_{i + 1}", "text": part} for i, part in enumerate(parts)]}


def _technical_text(text: str) -> str:
    """Known standard API ownership, without inferring what a lesson teaches.

    Promise static methods are JavaScript Promise APIs (MDN Promise reference).
    Their names do not automatically prove concurrency or error-handling lessons.
    Keep arbitrary dotted names, Java/JavaScript and SQL/NoSQL distinct.
    """
    additions = []
    if re.search(r"(?<![A-Za-z0-9_.])(?:js|node\.js|nodejs)(?![A-Za-z0-9_.])", text, re.I):
        additions.append("JavaScript")
    if PROMISE_MEMBER.search(text):
        additions.extend(("JavaScript", "Promise"))
    # Only the fully qualified, documented Pygame method supplies ownership;
    # helper.colliderect or an arbitrary dotted identifier does not.
    if re.search(r"(?<![A-Za-z0-9_.])pygame\.Rect\.colliderect(?![A-Za-z0-9_.])", text, re.I):
        additions.append("pygame")
    # A fully qualified module spelling supplies its explicit namespace only;
    # this does not assert any operation or correctness of an arbitrary member.
    if re.search(r"(?<![A-Za-z0-9_.])pygame\.[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*(?![A-Za-z0-9_.])", text):
        additions.append("pygame")
    return text + " " + " ".join(additions)


BARE_ACTION = re.compile(r"运行|执行|创建|编写|调用|处理|操作|使用|配置|保存|导出|加载|读取|写入|修改|删除|调试|测试|"
                         r"run(?:ning)?|execut(?:e|ion)|creat(?:e|ion)|processing|configuration|saving|export(?:ing)?", re.I)
OBJECT_DESCRIPTOR = re.compile(r"(?:基础语法|语法基础|基础知识|语法|基础|编写|创建|定义|编译|配置|安装|读取|写入|修改|删除|设计|加载|操作|处理)$")
PARTIAL_SKILL_NONTEACHING = re.compile(
    r"不要|不(?:会|能|可|做|进行|讲|教|涉及|包括|包含|涵盖|支持|适用|建议|是)|未(?:讲解|涉及|实现|支持|涵盖)|"
    r"不需要|无需|禁止|无法|弃用|相关\s*(?:API|函数|方法)\s*(?:列表|清单)|(?:顺便|仅|只是)?提及|另见|顺带|"
    r"\b(?:(?:not|never)\s+(?:teach|cover|include|use)|deprecated|mention(?:s|ed)?|see\s+also|related\s+apis?)\b", re.I)


def _action_has_requested_object(action: str, text: str, whole_topic: str) -> bool:
    # A bare verb such as 运行 is not a standalone teaching concept. Preserve
    # direct whole-topic evidence, otherwise require the request's own object
    # immediately bound to that action in this observation. Neither inherited
    # language context nor an unrelated chapter's object can supply it.
    plan = decompose_topic(whole_topic)
    prefix = r"\s*".join(re.escape(term) for term in plan["shared_context"])
    requested_body = re.sub(r"^\s*" + prefix + r"\s*", "", whole_topic, count=1, flags=re.I).strip()
    # Preserve an explicit whole topic, not a bag of its words spread between
    # clauses ("脚本语法；爬虫服务运行" still has the wrong action object).
    if requested_body and re.search(re.escape(requested_body), text, re.I):
        return True
    for part in plan["subtopics"]:
        candidate = part["text"].strip()
        if candidate == action or BARE_ACTION.fullmatch(candidate):
            continue
        candidate = OBJECT_DESCRIPTOR.sub("", candidate).rstrip("的 ")
        if not re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9_.+# -]{2,60}", candidate):
            continue
        # This is literal object binding, not an operation or object synonym:
        # 脚本运行 / 运行脚本 are eligible; 程序执行 does not stand in for them.
        noun, verb = re.escape(candidate), re.escape(action)
        if re.search(rf"{noun}\s*的?\s*{verb}|{verb}\s*(?:该|这个|指定的)?\s*{noun}", text, re.I):
            return True
    return False


def _subtopic_matches(subtopic: str, text: str, *, whole_topic: str = "") -> bool:
    scoped_part = " ".join([*decompose_topic(whole_topic)["shared_context"], subtopic])
    rectangle = pygame_rect_collision_match(scoped_part, text)
    if rectangle is not None:
        return rectangle
    display = pygame_text_display_match(scoped_part, text)
    if display is not None:
        return display
    movement = pygame_keyboard_movement_match(scoped_part, text)
    if movement is not None:
        return movement
    if BARE_ACTION.fullmatch(subtopic):
        return bool(whole_topic) and _action_has_requested_object(subtopic, text, whole_topic)
    # Only the complete error-handling concept is interchangeable here; the
    # word 'error' or an API name by itself is not instructional coverage.
    error_concepts = r"错误处理|异常处理|\berror\s+handling\b|\bexception\s+handling\b"
    if re.fullmatch(error_concepts, subtopic, re.I):
        return bool(re.search(error_concepts, text, re.I))
    if re.fullmatch(r"并发|concurrency|concurrent\s+(?:operations?|programming)", subtopic, re.I):
        return bool(re.search(r"并发|\bconcurren(?:cy|t)\b", text, re.I))
    # A long course outline can mention keyboard events and image processing in
    # unrelated lessons. Those words do not prove event processing; likewise a
    # chart mention plus drawing a circle cannot prove chart drawing. Require
    # the requested noun and action to be locally bound in source wording.
    bound_action = locally_bound_chinese_action(subtopic, text)
    if bound_action is not None:
        return bound_action
    if _noun_action_match(subtopic, text, context=decompose_topic(whole_topic)["shared_context"]):
        return True
    # The complete-concept matcher already allows harmless Chinese word
    # boundaries such as 文件的读写. Do not re-impose cross-boundary bigrams.
    return compound_english_match(subtopic, [text]) and (len(tokens(subtopic)) >= 3 or relevance(subtopic, text) >= .999)


def _new_skill_owner_matches(context: list[str], text: str, start: int) -> bool:
    """Do not assign an explicitly introduced foreign subject's skill here.

    Inspect the nearest preceding identifier, rather than an open-ended list
    of competing languages. SQL/PHP/Lua before 基础语法 are all different
    owners even when Python appears earlier in the same clause. The pandas
    names below are contextual only: df still never proves a DataFrame type.
    """
    names = re.findall(r"[A-Za-z][A-Za-z0-9_.+#]*", text[:start])
    if not names or not context:
        return True
    allowed = {name.lower() for name in context}
    if "pandas" in allowed:
        allowed.update({"python", "dataframe", "series", "df"})
    return names[-1].lower() in allowed


def _noun_action_match(subtopic: str, text: str, *, context: list[str] | None = None) -> bool:
    """Bounded Chinese word order, with the same literal object and action.

    列选择 / 选择列 and 选择行与列 name the same selection object; selecting
    rows alone, selecting trains (列车), or renaming columns does not.
    """
    match = re.fullmatch(r"([\u4e00-\u9fff]{1,12})(选择|读取|写入|检查|检测|转换|绘制|保存|设置)", subtopic)
    if not match:
        return False
    noun, action = map(re.escape, match.groups())
    end = r"(?=$|[^\u4e00-\u9fff]|教程|方法|操作|示例|详解|基础|入门|课程|教学|[与和及、])"
    for clause in re.split(r"[。！？!?；;\n]", text):
        if PARTIAL_SKILL_NONTEACHING.search(clause):
            continue
        for found in re.finditer(rf"{action}\s*(?:指定的?)?\s*(?:[\u4e00-\u9fff]{{1,8}}[与和、])?{noun}{end}", clause):
            if _new_skill_owner_matches(context or [], clause, found.start()):
                return True
    return False


def _normal_forms_context(point: str, text: str) -> bool:
    """Recognize relational normal forms only within one teaching clause.

    A normal-form name in prerequisites, a denial, a reference URL or another
    sentence cannot donate the missing database sense to normalization.
    """
    wanted = tokens(point)
    if "database" not in wanted or not wanted & {"normalization", "normalisation"}:
        return False
    clean = EXTERNAL_URL.sub(" ", own_resource_snippet(text))
    nonteaching = re.compile(
        r"\b(?:api\s+list|list\s+of\s+(?:apis|functions)|references?|links?\s+to)\b|"
        r"\b(?:doesn['’]t|don['’]t|won['’]t|cannot|can['’]t)\s+(?:teach|cover|include|use)\b|"
        r"\bexclude[sd]?\s+(?:normal(?:iz|is)ation|[1-5]nf|bcnf)\b|"
        r"\b(?:no|without)\s+(?:normal(?:iz|is)ation|[1-5]nf|bcnf)\b|"
        r"\b(?:normal(?:iz|is)ation|[1-5]nf|bcnf)\b.{0,30}\b(?:not|never)\s+(?:covered|taught|included)\b",
        re.I,
    )
    for clause in re.split(r"[,，|•\n]", "\n".join(CLAUSE_BOUNDARY.split(clean))):
        if (PREREQUISITE.search(clause) or PARTIAL_SKILL_NONTEACHING.search(clause)
                or nonteaching.search(clause)):
            continue
        if (re.search(r"\bnormal(?:iz|is)ation\b", clause, re.I)
                and re.search(r"\b(?:[1-5]nf|bcnf)\b", clause, re.I)):
            return True
    return False


def _instructional_parts(title: str, body: str) -> tuple[str, str]:
    """Do not let a subtopic borrow its words or context from prerequisites.

    Even a statement that something is *not required* is not itself a promise
    to teach it. Independent teaching clauses and the source text remain intact.
    """
    teaching, prerequisites = [], []
    for field in (title, body):
        for sentence in CLAUSE_BOUNDARY.split(field):
            for clause in re.split(r"[,，]\s*(?=no\s+(?:prior\s+knowledge|prerequisites?)\b)", sentence, flags=re.I):
                (prerequisites if PREREQUISITE.search(clause) else teaching).append(clause)
    return " ".join(teaching), " ".join(prerequisites)


def _context_matches(context: list[str], text: str) -> bool:
    explicit = tokens(text)
    requested = tokens(" ".join(context))
    if "javascript" in requested and "javascript" not in explicit and not explicit & {"js", "node.js", "nodejs"}:
        # A library with a similarly named member in an explicitly different
        # language does not inherit JavaScript context from spelling alone.
        if explicit & {"java", "python", "c#", "c++", "rust", "swift", "kotlin"}:
            return False
    actual = tokens(_technical_text(text))
    return bool(context) and requested <= actual


def _weak_observation_reasons(point: str, title: str, body: str, raw: str) -> list[tuple[str, str]]:
    text = " ".join((title, body))
    reasons = []
    if SCHEDULED_LESSON.search(text) and not RECORDED_LESSON.search(text):
        reasons.append(("scheduled_teaching_unconfirmed", "当前文字是预约或直播预告；尚无已提供教学内容或回放的明确证据。"))
    comparisons = COMPARISON_CLAUSE.findall(body)
    without_comparison = COMPARISON_CLAUSE.sub(" ", body)
    wanted = tokens(point)
    comparison_terms = tokens(" ".join(comparisons))
    missing_elsewhere = wanted - tokens(title + " " + without_comparison)
    # A comparison lesson naming the requested subject in its own title remains
    # valid. A different technique mentioning it only as a baseline is weaker.
    explicit_comparison_teaching = any(re.search(r"讲解|演示|实现|\b(?:teach|explain|demonstrat\w*|implement\w*|walkthrough|tutorial)\b", clause, re.I)
        and relevance(point, clause) >= .999 for clause in comparisons)
    if comparisons and missing_elsewhere & comparison_terms and relevance(point, title) < .999 and not explicit_comparison_teaching:
        reasons.append(("comparison_mention_only", "目标术语只在比较其他方案时出现；当前标题与简介未明确证明会讲授该目标方案。"))
    closure_topic = bool(re.search(r"闭包|\bclosures?\b", point, re.I))
    alias_claim = bool(re.search(r"(?:匿名函数|anonymous\s+functions?).{0,80}(?:也称|称为|就是|also\s+(?:called|known)|is\s+(?:a|the)).{0,30}(?:闭包|closures?)", text, re.I))
    capture = re.search(r"词法(?:作用域|环境)|捕获.{0,12}(?:变量|环境)|外(?:部|层).{0,8}变量|\blexical\s+(?:scope|environment)\b|\bcaptur\w*\s+(?:variables?|environment)\b|\bouter\s+(?:scope|variables?)\b", text, re.I)
    if closure_topic and alias_claim and not capture and not re.search(r"闭包|\bclosures?\b", title, re.I):
        reasons.append(("definition_alias_unconfirmed", "当前文字将匿名函数称为闭包，但未提供词法作用域或变量捕获依据；不能据此确认闭包教学。"))
    missing_without_urls = tokens(point) - tokens(text)
    if _normal_forms_context(point, text):
        # Standard normal-form names in the title/body establish the database
        # sense independently of any reference URL containing that word.
        missing_without_urls.discard("database")
    if EXTERNAL_URL.search(raw) and missing_without_urls & tokens(" ".join(EXTERNAL_URL.findall(raw))):
        reasons.append(("external_link_terms_only", "部分目标术语仅出现在外部链接地址中；链接路径不能证明本资源讲授该内容。"))
    return reasons


def _chapter_parent_context(point_text: str, resource: dict, evidence: list[dict], chapter_title: str, catalog: dict) -> tuple[str, list[str]]:
    """Inherit only explicit technical identifiers from this page's own fields.

    A course titled Python can establish the language of its list lesson. Its
    title cannot supply the lesson's missing action, nor can a sibling chapter.
    Strict field/source/URL bindings prevent search snippets or another course
    from becoming parent context. The original observations remain unchanged.
    """
    prefix = re.match(r"\s*((?:[A-Za-z][A-Za-z0-9+#.]*(?:\s+|(?=[\u4e00-\u9fff])))+)(?=[\u4e00-\u9fff])", point_text)
    prefix = prefix or re.match(r"\s*((?:[A-Z][A-Za-z0-9+#.]*\s+)+)(?=[a-z])", point_text)
    if not prefix or resource.get("metadata_evidence_level") not in {"page", "catalog"} or resource.get("fetch_status") not in {"fetched", "success"}:
        return "", []
    # Only the first identifier names the enclosing technology. Later English
    # words may be the requested operation (e.g. Python file writing); a parent
    # title must not silently donate those instructional words to its chapter.
    context = prefix[1].strip().split()[0]
    requested = tokens(context)
    if requested <= tokens(chapter_title):
        return "", []
    # Explicitly different languages or a different named technical prefix
    # make inheritance ambiguous, even if a broad course mentions both.
    languages = {"python", "javascript", "java", "c++", "c#", "ruby", "rust", "swift", "kotlin", "php", "typescript", "matlab"}
    chapter_terms = tokens(chapter_title)
    leading = re.match(r"\s*([A-Za-z][A-Za-z0-9+#.]*)", chapter_title)
    if (requested & languages and chapter_terms & languages - requested
            or leading and not tokens(leading[1]) & requested):
        return "", []
    try:
        resource_urls = {normalize_url(resource[key]) for key in ("url", "canonical_url") if resource.get(key)}
        if not catalog.get("url") or normalize_url(catalog["url"]) not in resource_urls:
            return "", []
    except (UnsafeURL, ValueError):
        return "", []
    for field in ("title", "description"):
        provenance = resource.get("field_provenance", {}).get(field, {})
        if not isinstance(provenance, dict):
            continue
        source = next((row for row in evidence if row.get("evidence_id") == provenance.get("evidence_id")), None)
        if (not source or source.get("kind") != "page" or source.get("field") != field
                or not source.get("source") or source.get("source") != provenance.get("source")
                or not isinstance(source.get("text"), str) or source.get("text") != resource.get(field)):
            continue
        try:
            if (not source.get("url") or normalize_url(source["url"]) not in resource_urls
                    or provenance.get("url") and normalize_url(provenance["url"]) not in resource_urls):
                continue
        except (UnsafeURL, ValueError):
            continue
        clean = EXTERNAL_URL.sub(" ", own_resource_snippet(source["text"]))
        teaching, _ = _instructional_parts(clean, "")
        observed = tokens(teaching)
        if requested <= observed and not (requested & languages and observed & languages - requested):
            return context, [source["evidence_id"]]
    return "", []


def topic_observations(point: dict, resource: dict, evidence: list[dict]) -> list[dict]:
    """Create scoring copies; persisted search/page evidence is never changed."""
    observations = []
    fcc_binding = bool(course_announcement_url(resource.get("url", "")) and (
        resource.get("video_topic_summary") is not None
        or resource.get("field_provenance", {}).get("video_evidence_status", {}).get("source") == FCC_VIDEO_SOURCE))
    fcc_summary = bound_video_topic_summary(resource, evidence) if fcc_binding else None
    twt_binding = bool(lesson_page_url(resource.get("url", "")))
    scoped_binding = fcc_binding or twt_binding
    scoped_summary = twt_bound_summary(resource, evidence) if twt_binding else fcc_summary
    if scoped_binding and scoped_summary is None:
        return []  # A damaged binding cannot fall back to article/search prose.
    for entry in evidence:
        if scoped_binding:
            continue  # The public article's search excerpt is not video proof.
        if entry.get("kind") != "search" or entry.get("source") == "official_sitemap" or entry.get("knowledge_point_id") not in {None, point["knowledge_point_id"]}:
            continue
        title = entry.get("title") or ""
        if not title and not entry.get("knowledge_point_id") and resource.get("field_provenance", {}).get("title", {}).get("source") != "search":
            title = resource.get("title") or ""
        title = own_resource_snippet(title)
        snippet = own_video_description(resource, own_resource_snippet(entry.get("snippet") or ""))
        raw = title + " " + snippet
        clean_title, clean_body = search_instructional_text(EXTERNAL_URL.sub(" ", title)), search_instructional_text(EXTERNAL_URL.sub(" ", snippet))
        if topic_context_conflict(point["text"], clean_title + " " + clean_body):
            continue
        source_ids = [entry["evidence_id"]] if entry.get("evidence_id") else []
        observations.append({"title": clean_title, "body": clean_body, "raw": raw,
            "evidence_ids": source_ids,
            "field_evidence_ids": {"title": source_ids if entry.get("title") else [], "body": source_ids if entry.get("snippet") else []}})
    fields, ids = {}, []
    for field in ("title", "description"):
        source_field = "video_topic_summary" if scoped_binding and field == "description" else field
        provenance = resource.get("field_provenance", {}).get(source_field, {})
        if provenance.get("source") == "search":
            continue
        if resource.get("metadata_evidence_level") == "search" and any(row.get("kind") == "search" for row in evidence):
            continue
        value = scoped_summary if scoped_binding and field == "description" else resource.get(field) or ""
        if value:
            fields[field] = value
            if provenance.get("evidence_id") in {row.get("evidence_id") for row in evidence}:
                ids.append(provenance["evidence_id"])
    if fields:
        own_title = own_resource_snippet(fields.get("title", ""))
        own_description = own_video_description(resource, fields.get("description", ""))
        # Scoring raw keeps own links for URL-only guards, but excludes another
        # lesson's tail. Source-binding comparisons below still use full fields.
        raw = own_title + " " + own_description
        if not topic_context_conflict(point["text"], raw):
            field_ids = {}
            for field, target in (("title", "title"), ("description", "body")):
                source_field = "video_topic_summary" if scoped_binding and field == "description" else field
                provenance = resource.get("field_provenance", {}).get(source_field, {})
                source = next((row for row in evidence if row.get("evidence_id") == provenance.get("evidence_id")), {})
                valid = (source.get("kind") == "page" and source.get("field") == source_field
                         and source.get("text") == fields.get(field) and source.get("source") == provenance.get("source"))
                try:
                    valid = valid and normalize_url(source.get("url", "")) in {
                        normalize_url(resource[key]) for key in ("url", "canonical_url") if resource.get(key)}
                except (UnsafeURL, ValueError):
                    valid = False
                field_ids[target] = [source["evidence_id"]] if valid else []
            observations.append({"title": EXTERNAL_URL.sub(" ", own_title),
                "body": EXTERNAL_URL.sub(" ", own_description), "raw": raw, "evidence_ids": ids,
                "field_evidence_ids": field_ids})
    if scoped_binding:
        return observations  # Article outline/navigation is not a video catalog.
    # Each chapter is its own observation. Different chapter titles cannot be
    # stitched into one claimed lesson, and an unbacked chapter cannot add support.
    for chapter in resource.get("chapters", []):
        if not isinstance(chapter, dict):
            continue
        source = next((row for row in evidence if row.get("evidence_id") == chapter.get("evidence_id") and row.get("kind") == "catalog"), None)
        if source:
            try:
                own_urls = {normalize_url(resource[key]) for key in ("url", "canonical_url", "resolved_url") if resource.get(key)}
                if not source.get("url") or normalize_url(source["url"]) not in own_urls:
                    continue
            except (UnsafeURL, ValueError, TypeError):
                continue
            title = str(chapter.get("title") or chapter.get("name") or "")
            context, parent_ids = _chapter_parent_context(point["text"], resource, evidence, title, source)
            observations.append({"title": EXTERNAL_URL.sub(" ", title), "body": context, "raw": title,
                "evidence_ids": [source["evidence_id"], *parent_ids],
                "topic_match_rules": ["chapter_inherits_evidenced_parent_technical_context"] if parent_ids else []})
    return observations


def _supplementary_skill_coverage(point: dict, plan: dict, good: list[dict], coverage: list[dict]) -> tuple[list[dict], list[dict]]:
    """Keep observed core skills separate from unproved request qualifications.

    This can add only partial evidence. Literal qualified cores never mark the
    original, narrower subtopic supported. Documented APIs can support exactly
    their operation, never an unobserved input domain, workflow or pass-rate.
    """
    if plan["decomposition_status"] != "applied":
        return coverage, []
    contexts = plan["shared_context"]
    rows, reasons = list(coverage), []
    claims: dict[tuple[str, str], list[str]] = {}
    # Fixed conceptual heads, not model expansion or arbitrary suffix matching.
    # All omitted modifiers remain unknown; these are not synonym equivalences.
    qualified_heads = ("基础语法", "类型转换", "平均分", "最高分", "平均值", "最大值")
    sentence = re.compile(r"[。！？!?；;\n]|\.(?=\s|$)")
    for observation in good:
        if not observation["evidence_ids"]:
            continue
        inherited = "chapter_inherits_evidenced_parent_technical_context" in observation.get("topic_match_rules", [])
        for field in ("title", "body"):
            if inherited and field == "body":
                continue
            field_ids = observation.get("field_evidence_ids", {}).get(field, observation["evidence_ids"])
            if not field_ids:
                continue
            for clause in sentence.split(own_resource_snippet(observation[field])):
                if PREREQUISITE.search(clause) or PARTIAL_SKILL_NONTEACHING.search(clause):
                    continue
                text = clause + (" " + observation["body"] if inherited else "")
                # With an omitted qualifier we need unambiguous ownership of
                # the core. A clause naming competing languages or dataframe
                # libraries is insufficient to assign its action to this one.
                primary = contexts[0].lower()
                competitors = {"python": r"\b(?:java|javascript|rust|swift|kotlin)\b|(?<!\w)c(?:\+\+|#)",
                               "pandas": r"\b(?:numpy|polars|tensorflow|pytorch)\b"}
                if primary in competitors and re.search(competitors[primary], text, re.I):
                    continue
                full_context = _context_matches(contexts, text)
                # Column selection is meaningful pandas evidence even when a
                # lesson omits the requested class name. Keep DataFrame unknown;
                # never turn an arbitrary variable spelling such as df into it.
                class_unknown = (len(contexts) == 2 and [term.lower() for term in contexts] == ["pandas", "dataframe"]
                                 and _context_matches(contexts[:1], text))
                if not full_context and not class_unknown:
                    continue
                # These documented functions are recognized only inside their
                # pandas teaching clause, excluding competing library mentions.
                pandas_context = (contexts[0].lower() == "pandas" and _context_matches(["pandas"], text)
                                  and not re.search(r"\b(?:numpy|polars|tensorflow|pytorch)\b", text, re.I))
                def observed(pattern: str) -> bool:
                    return any(_new_skill_owner_matches(contexts, text, found.start())
                               for found in re.finditer(pattern, text, re.I))

                def api(name: str, suffix: str = r"\s*(?:\(|函数|方法|教程|详解|用法)") -> bool:
                    # Bare lesson names and explicitly owned standard APIs only.
                    # Arbitrary object members (helper.mean/df.mean), similarly
                    # named functions and another library's members stay unknown.
                    owners = r"(?:(?:pandas|pd)\.)?" if name == "to_numeric" else (
                        r"(?:(?:(?:pandas|pd)\.)?(?:DataFrame|Series)\.|(?:pandas|pd)\.)?" if name == "isna" else
                        r"(?:(?:(?:pandas|pd)\.)?(?:DataFrame|Series)\.)?")
                    return observed(r"(?<![A-Za-z0-9_.])" + owners + name + r"(?![A-Za-z0-9_])" + suffix)

                numeric = pandas_context and (api("to_numeric") or api("astype", r"\s*\(\s*['\"]?(?:u?int(?:8|16|32|64)?|float(?:16|32|64)?)['\"]?\s*\)"))
                missing = pandas_context and (api("isna") or observed(r"(?:检查|检测)(?:与处理|和处理)?缺失值|缺失值(?:检查|检测)"))
                dtype = pandas_context and api("astype")
                mean = pandas_context and api("mean")
                maximum = pandas_context and api("max")
                renamed = pandas_context and api("rename", r"\s*\(\s*columns\s*=")
                # Semantics: pandas.to_numeric converts to numeric; isna detects
                # missing values; astype alone specifies no numeric destination.
                # https://pandas.pydata.org/docs/reference/api/pandas.to_numeric.html
                # https://pandas.pydata.org/docs/reference/api/pandas.isna.html
                # https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.astype.html
                # mean/max return numeric aggregations, not a school-score or
                # pass-rate workflow. rename must explicitly target columns.
                # https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.mean.html
                # https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.max.html
                # https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.rename.html
                for index, part in enumerate(plan["subtopics"]):
                    if rows[index]["status"] == "supported":
                        continue
                    term, core = part["text"], None
                    exact_api = full_context and ((term == "数值类型转换" and numeric) or (term in {"缺失值检查", "缺失值检测"} and missing) or (term == "类型转换" and dtype))
                    if exact_api:
                        rows[index] = {**part, "status": "supported", "evidence_ids": list(field_ids),
                            "reason": "本观察明确使用规范定义的对应操作；未推断其它教学内容。"}
                        reasons.append({"code": "documented_operation_partial", "message": "规范操作证据仅支持标明的子项，其它原始要求仍需分别核验。", "evidence_ids": list(field_ids)})
                        continue
                    if full_context:
                        core = next((head for head in qualified_heads if term.endswith(head) and len(term) - len(head) >= 2 and observed(re.escape(head))), None)
                        if term.endswith("类型转换") and len(term) > len("类型转换") and dtype:
                            core = "类型转换"
                        if re.search(r"平均(?:分|值)$|均值$", term) and mean:
                            core = "平均值计算"
                        if re.search(r"最高(?:分|值)$|最大值$", term) and maximum:
                            core = "最大值计算"
                        if term == "列名处理" and renamed:
                            core = "列重命名"
                    if class_unknown and term == "列选择" and _noun_action_match(term, text, context=contexts):
                        core = "列选择（DataFrame 类型未确认）"
                    if core:
                        claims.setdefault((part["id"], core), []).extend(field_ids)
    for (part_id, core), identifiers in claims.items():
        original = next(part for part in plan["subtopics"] if part["id"] == part_id)
        if next(row for row in rows if row["id"] == part_id)["status"] == "supported":
            continue
        identifiers = list(dict.fromkeys(identifiers))
        rows.append({"id": f"{part_id}_core_{len(rows)}", "text": " ".join((contexts[0], core)), "status": "supported", "evidence_ids": identifiers,
                     "reason": f"仅有这一核心教学证据；原子项“{original['text']}”的完整限定仍未确认。"})
        reasons.append({"code": "qualified_skill_core_partial", "message": f"仅证明“{contexts[0]} {core}”；不能据此确认原子项“{original['text']}”或其它未标明的要求。", "evidence_ids": identifiers})
    return rows, reasons


def assess_topic_evidence(point: dict, resource: dict, evidence: list[dict]) -> dict | None:
    if point.get("learning_targets"):
        return _assess_confirmed_targets(point, resource, evidence)
    plan = decompose_topic(point["text"])
    observations = topic_observations(point, resource, evidence)
    good, weak = [], []
    for observation in observations:
        text = observation["title"] + " " + observation["body"]
        reasons = _weak_observation_reasons(point["text"], observation["title"], observation["body"], observation["raw"])
        if prerequisite_only_match(point["text"], observation["title"], observation["body"], "", ""):
            continue
        if reasons:
            if relevance(point["text"], observation["raw"]) >= .4:
                weak.extend({"code": code, "message": message, "evidence_ids": observation["evidence_ids"]} for code, message in reasons)
            continue
        good.append({**observation, "text": text})
    coverage = []
    whole = []
    if plan["decomposition_status"] == "applied":
        teaching_rows = []
        for row in good:
            teaching, prerequisite = _instructional_parts(row["title"], row["body"])
            teaching_rows.append({**row, "text": teaching, "prerequisite_text": prerequisite})
        contextual = [row for row in teaching_rows if _context_matches(plan["shared_context"], row["text"])]
        for subtopic in plan["subtopics"]:
            ids = list(dict.fromkeys(identifier for row in contextual if _subtopic_matches(subtopic["text"], row["text"], whole_topic=point["text"]) for identifier in row["evidence_ids"]))
            prior_only = not ids and any(_subtopic_matches(subtopic["text"], row["prerequisite_text"], whole_topic=point["text"]) for row in teaching_rows)
            coverage.append({**subtopic, "status": "supported" if ids else "unknown", "evidence_ids": ids,
                "reason": "同一条观察明确包含共同技术上下文和该子项。" if ids else "这一子项仅在先修说明中出现，尚未明确证明会讲授。" if prior_only else "这一子项是泛动作；当前观察未把原知识点中的明确对象与该动作绑定，不能仅凭动作词确认。" if BARE_ACTION.fullmatch(subtopic["text"]) else "当前资源自身的观察未同时证明共同技术上下文和这一子项。"})
        whole = [row for row in contextual if all(_subtopic_matches(part["text"], row["text"], whole_topic=point["text"]) for part in plan["subtopics"])]
    else:
        whole = [row for row in good if compound_english_match(point["text"], [row["text"]]) and relevance(point["text"], row["text"]) >= .4]
    supplements = []
    if not whole:
        coverage, supplements = _supplementary_skill_coverage(point, plan, good, coverage)
    supporting = list(dict.fromkeys(identifier for row in whole for identifier in row["evidence_ids"]))
    if whole:
        status = "supported"
        reasons = [{"code": "direct_topic_support", "message": "已有本资源自身的标题、简介或目录文字直接支持该主题；不代表完整教学或播放已核验。", "evidence_ids": supporting}]
    elif any(part["status"] == "supported" for part in coverage):
        status = "partial"
        supporting = list(dict.fromkeys(identifier for part in coverage for identifier in part["evidence_ids"]))
        fragmented = all(part["status"] == "supported" for part in coverage)
        reasons = supplements or [{"code": "fragmented_compound_evidence" if fragmented else "partial_compound_coverage",
                    "message": "各子项分别出现在不同观察中；没有同一观察支持整个复合知识点，仍需核对。" if fragmented else "仅有部分子项的自身证据；不能把这条资源当作整个复合知识点的完整支持。",
                    "evidence_ids": supporting}]
    elif weak:
        status, reasons = "needs_review", weak
    else:
        instructional = []
        for row in good:
            teaching, _ = _instructional_parts(own_resource_snippet(row["title"]), own_resource_snippet(row["body"]))
            instructional.append({**row, "text": teaching})
        fallback = assess_operation_fallback(point["text"], instructional)
        return _target_assessment(point["text"], fallback) if fallback else None
    if not coverage:
        target = _coverage_plan(point["text"])
        coverage = [{**part, "status": "supported" if status == "supported" else "unknown",
                     "evidence_ids": supporting if status == "supported" else [],
                     "reason": "同一资源自身的观察支持原始完整主题。" if status == "supported" else "当前观察尚未证明这一学习目标。"}
                    for part in target["subtopics"]]
    result = TopicEvidenceAssessment(topic_evidence_status=status, topic_evidence_reasons=reasons,
        supporting_evidence_ids=supporting, subtopic_coverage=coverage).model_dump()
    return _target_assessment(point["text"], result)


def _coverage_plan(point_text: str) -> dict:
    plan = decompose_topic(point_text)
    operation = operation_decomposition(point_text)
    if operation:
        # Preserve the original explicitly requested parts as well as a
        # narrower operational core. A business qualification is never erased.
        return {**operation, "subtopics": [*plan["subtopics"], *operation["subtopics"]]}
    return plan if plan["subtopics"] else {**plan, "subtopics": [{"id": "whole_topic", "text": point_text}]}


def coverage_targets(point_text: str, learning_targets: list[str] | None = None) -> dict:
    """Retain original project constraints and every confirmed skill verbatim."""
    plan = _coverage_plan(point_text)
    return {**plan, "subtopics": [*plan["subtopics"], *[
        {"id": f"learning_target_{index + 1}", "text": text}
        for index, text in enumerate(learning_targets or [])]]}


def _assess_confirmed_targets(point: dict, resource: dict, evidence: list[dict]) -> dict | None:
    # Targets are student intent, never external teaching evidence. Evaluate
    # each independently against the unchanged, source-bound page observations.
    plain = {key: value for key, value in point.items() if key != "learning_targets"}
    base = assess_topic_evidence(plain, resource, evidence)
    rows = list(base.get("subtopic_coverage", [])) if base else [
        {**part, "status": "unknown", "evidence_ids": [], "reason": "原项目要求仍缺少教学证据。"}
        for part in _coverage_plan(point["text"])["subtopics"]]
    prefix = leading_technical_owner(point["text"]) or ""
    observed = [entry for entry in evidence if entry.get("kind") in {"page", "catalog"}]
    # The legacy unit assessment is also untrusted input to this merge. A
    # future/prerequisite/negated clause must not re-enter as an original or
    # supplemental skill after its confirmed target was correctly rejected.
    base_observations = topic_observations(plain, resource, observed)
    base_retracted = False
    for index, row in enumerate(rows):
        if row["status"] == "supported" and _confirmed_target_non_teaching(row["text"], prefix, base_observations):
            rows[index] = {**row, "status": "unknown", "evidence_ids": [],
                "reason": "该项仅有否定、先修或未来内容说明，不能作为当前教学证据。"}
            base_retracted = True
    for index, text in enumerate(point["learning_targets"]):
        target_text = text if not prefix or re.search(r"(?<![A-Za-z0-9_])" + re.escape(prefix) + r"(?![A-Za-z0-9_])", text, re.I) else prefix + " " + text
        identifiers = []
        target_observations = topic_observations({**plain, "text": target_text}, resource, observed)
        def own_css_fields(observation):
            fields = observation.get("field_evidence_ids")
            inherited = "chapter_inherits_evidenced_parent_technical_context" in observation.get("topic_match_rules", [])
            return [observation[field] for field in ("title", "body")
                    if (fields is None or fields.get(field)) and not (inherited and field == "body")]
        veto = _confirmed_target_non_teaching(text, prefix, target_observations) or any(
            css_target_non_teaching(target_text, field)
            for observation in target_observations for field in own_css_fields(observation))
        for observation in target_observations:
            if veto:
                break
            fields = observation.get("field_evidence_ids")
            title = observation["title"] if not fields or fields.get("title") else ""
            body = observation["body"] if not fields or fields.get("body") else ""
            teaching, _ = _instructional_parts(title, body)
            # A foreign tool's operation cannot borrow this unit's owner from
            # the page title. Ambiguous multi-tool claims stay unknown.
            competitors = {"pandas": r"\b(?:numpy|polars|tensorflow|pytorch|duckdb|pyarrow)\b",
                "python": r"\b(?:javascript|java|rust|swift|kotlin)\b",
                "pygame": r"\b(?:unity|godot|scratch)\b",
                "javascript": r"\b(?:python|java|rust|swift|kotlin)\b",
                "matplotlib": r"\b(?:pillow|pil|opencv|cv2|plotly|bokeh)\b",
                "arduino": r"\b(?:raspberry\s*pi|rpi|micropython)\b"}
            if prefix.lower() in competitors and re.search(competitors[prefix.lower()], teaching, re.I):
                continue
            clock_frame_limit = bool(prefix.casefold() == "pygame"
                and fields is not None and fields.get("body")
                and is_pygame_clock_frame_limit(text, title + "\n" + body))
            if (_whole_source_non_teaching(title, body)
                    or _weak_observation_reasons(target_text, title, body, observation["raw"])
                    or not _confirmed_target_boundaries(text, teaching)
                    or not (compound_english_match(target_text, [teaching]) or clock_frame_limit or any(
                        css_target_rule(target_text, field) for field in own_css_fields(observation)))):
                continue
            identifiers.extend(identifier for values in fields.values() for identifier in values) if fields is not None else identifiers.extend(observation["evidence_ids"])
        identifiers = list(dict.fromkeys(identifiers))
        rows.append({"id": f"learning_target_{index + 1}", "text": text,
            "status": "supported" if identifiers else "unknown", "evidence_ids": identifiers,
            "reason": "该项已确认技能有本来源页面的独立证据。" if identifiers else "该项已确认技能仍需补充来源证据。"})
    api_cores = _confirmed_api_operation_cores(point, resource, observed, rows)
    rows.extend(api_cores)
    supported = list(dict.fromkeys(identifier for row in rows if row["status"] == "supported" for identifier in row["evidence_ids"]))
    if not supported:
        if base and base["topic_evidence_status"] == "needs_review":
            return {**base, "subtopic_coverage": rows}
        # Returning the original base here would restore the retracted claims.
        return None if base_retracted else base
    complete = bool(base and base["topic_evidence_status"] == "supported" and all(row["status"] == "supported" for row in rows))
    reason = {"code": "confirmed_api_operation_core" if api_cores else "confirmed_learning_targets",
        "message": ("此局部核心仅限来源原拼写 API 的使用，不表示别名或参数等价。尚未确认的原概念："
                    + "、".join(row["text"] for row in rows if row["id"].startswith("learning_target_") and row["status"] == "unknown")
                    + "；项目行为仍需分别取证。") if api_cores else "逐项核对已确认概念；项目中的具体应用及未覆盖技能仍需补充。",
        "evidence_ids": supported}
    return TopicEvidenceAssessment(topic_evidence_status="supported" if complete else "partial",
        topic_evidence_reasons=[*(base.get("topic_evidence_reasons", []) if base and complete else []), reason],
        supporting_evidence_ids=supported, subtopic_coverage=rows).model_dump()



def _confirmed_api_operation_cores(point, resource, observed, rows):
    """A source-spelled API-use core never completes the original target.

    Only a same-page verified video title can declare this narrow teaching
    topic. No API meaning, alias, parameter or project behavior is inferred.
    """
    owner = leading_technical_owner(point["text"]) or ""
    if (not owner or resource.get("fetch_status") not in {"fetched", "success"}
            or not _bound_page_video(resource, observed)):
        return []
    try:
        canonical = normalize_url(resource.get("canonical_url") or resource.get("url", ""))
        own = [row for row in observed if row.get("kind") == "page"
               and row.get("source") not in {"search", "search_template"}
               and normalize_url(row.get("url", "")) == canonical]
    except (UnsafeURL, TypeError, ValueError):
        return []
    provenance = resource.get("field_provenance", {})
    video_proof = provenance.get("video_evidence_status", {})
    title_proof = provenance.get("title", {})
    if not isinstance(video_proof, dict) or not isinstance(title_proof, dict):
        return []
    video_id, title_id = video_proof.get("evidence_id"), title_proof.get("evidence_id")
    if not any(row.get("evidence_id") == video_id and row.get("field") == "video_evidence_status"
               and row.get("source") == video_proof.get("source")
               and isinstance(row.get("text"), str) and row["text"].strip() for row in own):
        return []
    try:
        title_url_bound = normalize_url(title_proof.get("url", "")) == canonical
    except (UnsafeURL, TypeError, ValueError):
        return []
    title_row = next((row for row in own if row.get("evidence_id") == title_id and row.get("field") == "title"
                      and row.get("source") == title_proof.get("source")
                      and row.get("text") == resource.get("title")), None)
    if title_row is None or not title_url_bound:
        return []
    title = own_video_description(resource, title_row["text"])
    body = " ".join(own_video_description(resource, row.get("text", ""))
                    for row in own if row.get("field") in {"description", "video_topic_summary"})
    if _whole_source_non_teaching(title, body):
        return []
    if (not re.search(r"使用|用法|教程|教学|讲解|函数|方法|\b(?:using|tutorial|lesson|function|method|how\s+to)\b", title, re.I)
            or re.search(r"项目演示|效果展示|演示项目|自学分享|分享而非|非(?:系统)?教程|\b(?:project\s+demo|showcase|portfolio|api\s+list|symbol\s+index)\b", title + " " + body, re.I)):
        return []
    pattern = re.compile(r"(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]*(?:[.-][A-Za-z_][A-Za-z0-9_]*)*)(\s*\()?")
    def identifiers(text):
        return [match[1] for match in pattern.finditer(text[:1000])
                if len(match[1]) <= 120 and (match[2] or any(mark in match[1] for mark in "._-")
                    or re.search(r"[a-z][A-Z]", match[1]))]
    # Explicit indexes and future material are not a usage lesson. This is a
    # conservative veto on the own scope, independent of the title's action.
    if re.search(r"(?:函数|方法)\s*(?:清单|列表)|(?:API|符号)\s*索引|速查\s*(?:列表|清单)|"
                 r"\b(?:api|symbol)\s+(?:index|list|reference)\b", title + " " + body, re.I):
        return []
    observations = topic_observations(point, resource, own)
    output, seen = [], set()
    for index, target in enumerate(point.get("learning_targets", [])[:8]):
        target_id = f"learning_target_{index + 1}"
        if any(row["id"] == target_id and row["status"] == "supported" for row in rows):
            continue
        names = identifiers(target)
        # Existing known-tool vocabulary is used only to reject cross-owner
        # targets, never to assert an alias, operation or parameter equivalence.
        leaves = {name.rsplit(".", 1)[-1].casefold() for name in names
                  if not ("." in name and _KNOWN_LIBRARY.fullmatch(name.split(".", 1)[0])
                          and name.split(".", 1)[0].casefold() != owner.casefold())}
        for spelling in identifiers(title):
            if spelling.rsplit(".", 1)[-1].casefold() not in leaves:
                continue
            qualified = spelling.casefold().startswith(owner.casefold() + ".")
            unqualified = "." not in spelling and re.search(
                r"(?<![A-Za-z0-9_.])" + re.escape(owner) + r"(?![A-Za-z0-9_.])", title, re.I)
            core = owner + " " + spelling
            future = any(re.search(r"下一(?:课|节|讲|堂)|下次|未来|后续|以后|待(?:讲解|实现)|留作(?:作业|练习)", clause)
                         and spelling in identifiers(clause)
                         for clause in CLAUSE_BOUNDARY.split(title + "\n" + body))
            if (not (qualified or unqualified) or future or spelling.casefold() in seen
                    or _confirmed_target_non_teaching(core, owner, observations)
                    or _weak_observation_reasons(core, title, body, title + " " + body)):
                continue
            seen.add(spelling.casefold())
            output.append({"id": f"api_operation_core_{index + 1}",
                "text": spelling + " API 使用核心（参数未确认）", "status": "supported",
                "evidence_ids": [title_id],
                "reason": "仅来源自己的已验证视频标题明确讲授这一原拼写 API 的使用核心；不是别名或参数等价，原确认目标和项目限定仍未知。"})
            break
    return output

def _confirmed_target_boundaries(target: str, teaching: str) -> bool:
    # Numeric and comparison constraints are part of the student's target.
    # Token overlap cannot turn > into >=, reverse operands, or change 25/5.
    numbers = re.findall(r"(?<![A-Za-z0-9_.])\d+(?:\.\d+)?(?![0-9.])", target)
    if any(not re.search(r"(?<![A-Za-z0-9_.])" + re.escape(number) + r"(?![0-9.])", teaching) for number in numbers):
        return False
    normalized_target = re.sub(r"\s+", "", target).translate(str.maketrans({"–": "-", "—": "-", "～": "~"}))
    normalized_teaching = re.sub(r"\s+", "", teaching).translate(str.maketrans({"–": "-", "—": "-", "～": "~"}))
    ranges = re.findall(r"\d+(?:\.\d+)?[/~\-]\d+(?:\.\d+)?", normalized_target)
    if any(not re.search(r"(?<![0-9.])" + re.escape(pair) + r"(?![0-9.])", normalized_teaching) for pair in ranges):
        return False
    expressions = re.findall(r"[A-Za-z_][\w.]*\s*(?:<=|>=|==|!=|<|>)\s*(?:[A-Za-z_][\w.]*|\d+(?:\.\d+)?)", target)
    compact = re.sub(r"\s+", "", teaching)
    return all(re.search(r"(?<![A-Za-z0-9_.])" + re.escape(re.sub(r"\s+", "", expression)) + r"(?![A-Za-z0-9_.])", compact) for expression in expressions)


def _confirmed_target_non_teaching(target: str, prefix: str, observations: list[dict]) -> bool:
    core = re.sub(r"(?<![A-Za-z0-9_])" + re.escape(prefix) + r"(?![A-Za-z0-9_])", "", target, flags=re.I).strip() if prefix else target
    marker = re.compile(PARTIAL_SKILL_NONTEACHING.pattern + r"|\b(?:api\s+list|symbol\s+index|excludes?|todo|homework|future\s+lesson|next\s+lesson|coming\s+soon)\b|\b(?:doesn['’]t|don['’]t|won['’]t|is\s+not|are\s+not)\s+(?:cover(?:ed)?|teach|taught|include(?:d)?)\b", re.I)
    for observation in observations:
        fields = observation.get("field_evidence_ids")
        for field, key in (("title", "title"), ("body", "body")):
            if fields is not None and not fields.get(key):
                continue
            for clause in CLAUSE_BOUNDARY.split(observation[field]):
                if (PREREQUISITE.search(clause) or marker.search(clause)) and compound_english_match(core, [clause]):
                    return True
    return False


def _target_assessment(point_text: str, result: dict) -> dict:
    target = _coverage_plan(point_text)
    existing = {(row["id"], row["text"]): row for row in result.get("subtopic_coverage", [])}
    complete = result["topic_evidence_status"] == "supported"
    rows = []
    for part in target["subtopics"]:
        row = existing.get((part["id"], part["text"]))
        rows.append(row or {**part, "status": "supported" if complete else "unknown",
            "evidence_ids": result["supporting_evidence_ids"] if complete else [],
            "reason": "同一资源自身的观察支持原始完整主题。" if complete else "当前观察尚未证明这一原始要求。"})
    represented = {(row["id"], row["text"]) for row in rows}
    rows.extend(row for key, row in existing.items() if key not in represented)
    return {**result, "subtopic_coverage": rows}


def summarize_collection_coverage(point_text: str, items: list[dict], learning_targets: list[str] | None = None) -> dict:
    """Summarize only the actual displayed, deduplicated resource set."""
    plan = coverage_targets(point_text, learning_targets)
    resources = {item["resource"]["resource_id"]: item for item in items}
    subtopics = []
    for part in plan["subtopics"]:
        resource_ids, evidence_ids = [], []
        for rid, item in resources.items():
            match = item["match"]
            if match.get("topic_evidence_status") not in {"supported", "partial"}:
                continue
            available = {entry.get("evidence_id") for entry in item.get("evidence", [])}
            supported = set(match.get("supporting_evidence_ids", [])) & available
            detail = next((row for row in match.get("subtopic_coverage", []) if row["id"] == part["id"] and row["text"] == part["text"]), {})
            ids = [identifier for identifier in detail.get("evidence_ids", []) if identifier in supported]
            if detail.get("status") == "supported" and ids:
                resource_ids.append(rid); evidence_ids.extend(ids)
        subtopics.append({**part, "status": "supported" if resource_ids else "unknown", "resource_ids": resource_ids,
                          "evidence_ids": list(dict.fromkeys(evidence_ids))})
    count = sum(part["status"] == "supported" for part in subtopics)
    return {**plan, "subtopics": subtopics,
        "status": "all_subtopics_supported" if subtopics and count == len(subtopics) else "some_subtopics_supported" if count else "unknown",
        "single_resource_full_coverage": bool(subtopics) and any(item["match"].get("topic_evidence_status") == "supported" and all(
            rid in part["resource_ids"] for part in subtopics) for rid, item in resources.items()),
        "disclaimer": "候选之间的互补证据不代表任何单条覆盖全部，也不代表完整教学已核验；仅统计当前展示的资源。"}


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
    # A digit-bearing technology (D3.js) needs a separator before its version.
    # Attached versions (Python3.13, C++17) have a non-digit technology prefix.
    pattern = r"(?<![a-z0-9.])([a-z][a-z0-9.+#-]*?)\s+v?(\d+(?:\.\d+)*)(?![a-z0-9_.])|(?<![a-z0-9.])([a-z][a-z+#-]*?)v?(\d+(?:\.\d+)*)(?![a-z0-9_.])"
    expected = [(a or c, b or d) for a,b,c,d in re.findall(pattern, f"{point} {version}".lower())]
    for technology, target in expected:
        found = re.findall(r"(?<![a-z0-9.])" + re.escape(technology) + r"\s*v?\s*(\d+(?:\.\d+)*)(?![a-z0-9_.])", content.lower())
        if found and all(x.split(".")[0] != target.split(".")[0] for x in found):
            return True
    # Bare optional version is associated with the first technology in the point.
    if re.fullmatch(r"v?\d+(?:\.\d+)*", version.strip().lower()):
        tech = re.search(r"[a-z][a-z0-9.+#-]*", point.lower())
        if tech:
            return version_conflict(tech[0] + " " + version, "", content)
    return False


def source_language_notice(resource: dict, evidence: list[dict], preferred: str) -> str:
    """Explain the observed scope of a language tag, never infer audio language."""
    value = resource.get("language")
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z]{2,8}(?:[-_][A-Za-z0-9]{2,8})*", value):
        return " 视频/授课语言尚未由来源元数据确认。"
    provenance = resource.get("field_provenance", {})
    def fact(field):
        origin = provenance.get(field) or {}
        row = next((item for item in evidence if item.get("evidence_id") == origin.get("evidence_id")), None)
        if not row or row.get("kind") != "page" or row.get("field") != field or row.get("source") != origin.get("source"):
            return None
        try:
            targets = {normalize_url(resource[key]) for key in ("url", "canonical_url", "resolved_url") if resource.get(key)}
            return row if normalize_url(row.get("url", "")) in targets and normalize_url(origin.get("url", "")) in targets else None
        except (UnsafeURL, TypeError, ValueError):
            return None
    language = fact("language")
    if not language or language.get("text") != value:
        return " 来源语言标注尚未核实，视频/授课语言仍需确认。"
    base = value.replace("_", "-").split("-", 1)[0].lower()
    names = {"en": "英语", "english": "英语", "zh": "中文", "chinese": "中文", "es": "西班牙语", "fr": "法语", "de": "德语", "ja": "日语", "ko": "韩语", "pt": "葡萄牙语", "ru": "俄语"}
    label = f"{names[base]}（{value}）" if base in names else value
    source = language.get("source")
    type_fact = fact("resource_type")
    media = (source == "jsonld.inLanguage" and type_fact is not None and type_fact.get("source") == "jsonld.@type"
             and type_fact.get("text") in {"video", "course"} and resource.get("resource_type") == type_fact["text"])
    if media:
        notice = f" 来源视频/课程元数据标注语言：{label}；实际音轨与字幕请到平台确认。"
    elif source in {"html.lang", "jsonld.inLanguage"}:
        notice = f" 来源页面语言：{label}；视频/授课语言仍需确认。"
    else:
        return " 来源语言标注范围尚未核实，视频/授课语言仍需确认。"
    if preferred != "any" and base not in {preferred, {"zh": "chinese", "en": "english"}.get(preferred)}:
        notice += f" 你的偏好为{names.get(preferred, preferred)}，可先检查平台音轨或字幕。"
    return notice


def _whole_source_non_teaching(title: str, body: str) -> bool:
    """Only an explicit whole-source disclaimer can veto unrelated targets.

    Target-bound negation, prerequisite and future clauses are independently
    checked by _confirmed_target_non_teaching. A no-HTML prerequisite elsewhere
    in this source cannot retract its explicit Streamlit rerun teaching.
    """
    whole = re.compile(
        r"(?:本|此|这(?:个|段|门))\s*(?:视频|课程|课|教程|页面)\s*"
        r"(?:不提供(?:任何)?教学|不进行(?:任何)?教学|不讲解任何(?:技能|知识)|不教学|"
        r"不是(?:教学|教程)|(?:只|仅)(?:是|为|作)?(?:成品|结果|效果)?(?:展示|演示))|"
        r"\bthis\s+(?:(?:video|lesson|course|page|clip)\s+)?(?:is\s+)?"
        r"(?:not\s+(?:a|an)\s+(?:tutorial|lesson)|(?:only\s+(?:a\s+)?demo|a\s+demo\s+only)|"
        r"provides?\s+no\s+(?:teaching|instruction)|does\s+not\s+teach\s+anything)\b|"
        r"^\s*(?:not\s+(?:a|an)\s+tutorial|demo\s+only)\s*[.!。！]", re.I)
    if whole.search(title) or whole.search(body):
        return True
    label = r"(?:API\s+(?:list|reference)|symbol\s+index|prerequisites?|next\s+lesson|future\s+lesson|TODO|先修要求|前置要求|下节课|未来课程|API\s*(?:列表|清单))"
    # A standalone nonteaching document/section label governs its following
    # raw body. Ordinary sentences such as 'Prerequisites: HTML. This lesson
    # teaches X' are left to the existing target-bound clause checker.
    return bool(re.fullmatch(rf"\s*(?:[A-Za-z_][\w.]*\s+)?{label}\s*[:：]?\s*", title, re.I)
                or re.match(rf"\s*{label}\s*[:：]\s*\n", body, re.I))


def learner_fit(student_level: str, title: str, description: str) -> tuple[int, str]:
    """Only a source audience/entry-level declaration establishes learner fit.

    Titles can explicitly name their course level. Description topics such as
    '4. advanced application architecture' do not declare the whole audience.
    """
    if student_level == "any":
        return 0, ""
    not_for_beginners = re.compile(r"(?:不适合|不適合|非面向|非針對|非针对)\s*(?:零基础|入门|初学者)|\bnot\s+(?:intended\s+)?for\s+(?:absolute\s+)?beginners?\b", re.I)
    if student_level == "beginner" and not_for_beginners.search(title + " " + description):
        return -18, " 来源明确提示不适合初学者，建议先完成本单元先修再学习。"
    beginner = re.compile(r"零基础|零基礎|入门|入門|初学|初學|\bbeginner(?:s)?\b|\bintroduct(?:ion|ory)\b|\bgetting started\b", re.I)
    intermediate = re.compile(r"进阶|進階|中级|中級|\bintermediate\b", re.I)
    advanced = re.compile(r"高级|高級|高阶|高階|\badvanced\b|\bexpert\b", re.I)
    level_patterns = {"beginner": beginner, "intermediate": intermediate, "advanced": advanced}
    title_level = not_for_beginners.sub("", title)
    observed = [name for name, pattern in level_patterns.items() if pattern.search(title_level)]
    if not observed:
        level = r"(?:零基础|零基礎|入门|入門|初学者?|初學者?|进阶|進階|中级|中級|高级|高級|高阶|高階|beginner(?:s)?|intermediate|advanced|expert)"
        declaration = re.compile(
            rf"(?:适合|適合|面向|针对|針對|适用于|適用於|推荐给)\s*{level}(?:学员|學員|学生|學生|学习者|開發者|开发者)?|"
            rf"(?:课程难度|課程難度|课程级别|難度|难度|适用人群|目标受众|学习门槛|课程定位|受众)\s*[:：为是-]?\s*{level}|"
            rf"{level}\s*(?:课程|課程|教程)|"
            rf"\b(?:for|aimed\s+at|designed\s+for|intended\s+for|suitable\s+for)\s+(?:absolute\s+)?{level}\b|"
            rf"\b(?:course|tutorial|lesson)\s+(?:level|difficulty|audience)\s*[:=-]?\s*{level}\b|"
            rf"\b{level}(?:-level)?\s+(?:course|tutorial|lesson)\b", re.I)
        # Numbered module headings are not audience declarations. Keep only
        # actual declaration excerpts, rather than nearby advanced topic names.
        declarations = []
        clean_description = not_for_beginners.sub("", description)
        for clause in re.split(r"[。；;!?！？\n•]", clean_description):
            for match in declaration.finditer(clause):
                before = clause[:match.start()]
                if re.search(r"(?:^|\s)(?:\d+[.)、]|第[一二三四五六七八九十0-9]+[章节讲])\s*$", before):
                    continue
                declarations.append(match.group())
        observed = [name for name, pattern in level_patterns.items() if any(pattern.search(value) for value in declarations)]
    labels = {"beginner": "入门", "intermediate": "进阶", "advanced": "高级"}
    if len(observed) != 1:
        return 0, " 学习门槛未由来源明确确认，请先看课程简介。"
    actual = observed[0]
    if actual == student_level:
        return 8, f" 来源标注为{labels[actual]}，与当前学习阶段相符。"
    if student_level == "beginner" and actual in {"intermediate", "advanced"}:
        return -18, f" 来源标注为{labels[actual]}；初学者建议先完成本单元先修再学习。"
    if student_level == "advanced" and actual == "beginner":
        return -8, " 来源标注为入门；首次使用该技术可补基础，已掌握可跳过。"
    return -4, f" 来源标注为{labels[actual]}，请结合已有基础选择。"

def _rank_resource_uncached(point: dict, resource: dict, evidence: list[dict], request: SearchRequest, *, require_type: bool = True,
                  eligibility_evidence: list[dict] | None = None) -> dict | None:
    resource = unavailable_video_projection(resource, evidence)
    resource = project_unconfirmed_video_shell(resource, evidence)
    resource = project_unconfirmed_fetched_media(resource, evidence)
    # Recheck at read/rank time as persisted rows and direct callers may predate
    # the ingestion guard. Never expose an unsafe URL as a recommendation, even
    # on the relaxed metadata-discovery path. This performs no network request.
    try:
        for field in ("url", "canonical_url", "resolved_url"):
            if field == "url" or resource.get(field):
                normalize_url(resource.get(field, ""))
    except (UnsafeURL, TypeError, ValueError):
        return None
    # The relaxed path is used only to prioritize metadata discovery; never for display.
    if require_type and not has_learning_evidence(resource, evidence if eligibility_evidence is None else eligibility_evidence):
        return None
    # Later discoveries of the same URL have their own titles. They belong to
    # this knowledge point and must not overwrite or reuse another point's first
    # search title. Page fields remain shared evidence about the resource itself.
    scoped_evidence = [entry for entry in evidence if entry.get("kind") != "search"
                       or entry.get("knowledge_point_id") in {None, point["knowledge_point_id"]}]
    searches = [{**entry, "title": search_instructional_text(entry.get("title") or ""),
                 "snippet": search_instructional_text(own_video_description(resource, own_resource_snippet(entry.get("snippet") or "")))}
                for entry in scoped_evidence if entry.get("kind") == "search"]
    # Competing context cannot keep contributing scores just because another,
    # unrelated observation exists for the same URL.
    searches = [entry for entry in searches if not topic_context_conflict(point['text'],
                ' '.join((entry.get('title') or '', entry.get('snippet') or '')))]
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
    raw_description = (resource.get("description") or "") if resource.get("metadata_evidence_level") in {"page", "catalog"} and description_source != "search" else ""
    description = own_video_description(resource, raw_description)
    chapters = "\n".join(str(c.get("title", c.get("name", ""))) if isinstance(c, dict) else str(c) for c in resource.get("chapters", []))
    if topic_context_conflict(point['text'], ' '.join((page_title, description, chapters))):
        page_title = description = chapters = ''
        titles = search_titles
        title = '\n'.join(titles)
    combined = " ".join((title, snippets, description, chapters))
    if resource.get("fetch_status") in {"unsafe_url", "not_found", "error_page"}:
        return None
    text = point["text"]
    topic_rules = ["search_related_recommendations_excluded"] if any(
        own_resource_snippet(entry.get("snippet") or "") != (entry.get("snippet") or "")
        for entry in scoped_evidence if entry.get("kind") == "search") else []
    own_description = own_resource_snippet(raw_description)
    if own_description != raw_description:
        topic_rules.append("page_related_recommendations_excluded")
    if description != own_description:
        topic_rules.append("longer_course_outline_excluded_from_short_video")
    assessment = assess_topic_evidence(point, resource, scoped_evidence)
    shell_review = assessment is not None and is_unconfirmed_video_shell(resource, scoped_evidence)
    assessment = unconfirmed_video_shell_assessment(assessment, resource, scoped_evidence)
    identity_review = assessment is not None and is_unconfirmed_fetched_media(resource, scoped_evidence)
    assessment = unconfirmed_fetched_media_assessment(assessment, resource, scoped_evidence)
    availability_review = resource.get("fetch_status") == "unavailable_unconfirmed" and assessment is not None
    if availability_review:
        access_ids = [row["evidence_id"] for row in scoped_evidence if row.get("evidence_id")
                      and row.get("kind") == "page" and (row.get("field") == "fetch_status"
                      or (row.get("field") == "title" and "视频去哪了呢" in str(row.get("text") or "")))]
        assessment = {"topic_evidence_status": "needs_review", "supporting_evidence_ids": [],
            "topic_evidence_reasons": [{"code": "unavailable_page_unconfirmed", "message": UNAVAILABLE_NOTICE,
                                        "evidence_ids": access_ids}],
            "subtopic_coverage": [{**part, "status": "unknown", "evidence_ids": [],
                "reason": "页面不可见，先前搜索摘要不能证明当前教学内容。"} for part in assessment.get("subtopic_coverage", [])]}
    if require_type and assessment is None:
        return None
    # Existing lexical audit rules remain useful to explain bounded equivalences.
    compound_english_match(text, [" ".join((entry.get("title") or "", entry.get("snippet") or "")) for entry in searches]
                           + [" ".join((page_title, description, chapters))], topic_rules)
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
    partial = assessment is not None and assessment["topic_evidence_status"] == "partial"
    complete_contextual_support = bool(assessment and assessment["subtopic_coverage"] and assessment["topic_evidence_status"] == "supported")
    normal_forms_support = bool(assessment and assessment["topic_evidence_status"] == "supported" and any(
        set(row["evidence_ids"]).intersection(assessment["supporting_evidence_ids"]) and _normal_forms_context(text, row["title"] + " " + row["body"])
        for row in topic_observations(point, resource, scoped_evidence)))
    sql_window_support = False
    if assessment and assessment["topic_evidence_status"] == "supported":
        for row in topic_observations(point, resource, scoped_evidence):
            if not set(row["evidence_ids"]).intersection(assessment["supporting_evidence_ids"]):
                continue
            observed_rules = []
            if (compound_english_match(text, [row["title"] + " " + row["body"]], observed_rules)
                    and "sql_row_number_is_window_function" in observed_rules):
                sql_window_support = True
                break
    if ((topic < .4 or matched_terms < min(2, len(wanted))) and not (partial or complete_contextual_support or normal_forms_support or sql_window_support or availability_review or shell_review or identity_review)) or not is_teaching:
        return None
    if availability_review or shell_review or identity_review:
        # Only order the separate review section; this adds no topic coverage.
        topic = max(topic, .45)
    elif partial:
        # Partial candidates are in a separate section. Score their evidenced
        # subitems instead of pretending the original compound was fully matched.
        topic = .45 + .1 * sum(part["status"] == "supported" for part in assessment["subtopic_coverage"]) / len(assessment["subtopic_coverage"])
    elif complete_contextual_support or normal_forms_support or sql_window_support:
        # The per-observation checks above proved all requested parts and their
        # context, including audited API ownership / exact concept equivalences.
        topic = max(topic, .85)
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
    level_score, level_reason = learner_fit(request.student_level, title, " ".join((description, snippets)))
    score += level_score
    if request.technical_version:
        score += 4 if request.technical_version.lower() in combined.lower() else -3
    if "catalog" in basis:
        reason = "公开目录包含与该知识点相关的文字；未核验完整教学覆盖。"
    elif resource.get("metadata_evidence_level") in {"page", "catalog"} and "description" in basis:
        reason = "根据公开页面标题或简介匹配，可能涉及该知识点；未核验完整教学覆盖。"
    elif resource.get("metadata_evidence_level") in {"page", "catalog"}:
        reason = "根据已有标题与搜索摘要匹配，可能涉及该知识点；已获取部分页面元信息，但完整教学覆盖尚未核验。"
    else:
        reason = "根据该知识点对应的搜索标题与摘要匹配，可能涉及该知识点；页面详情及完整教学覆盖尚未核验。"
    if request.technical_version and request.technical_version.lower() not in combined.lower():
        reason += " 目标技术版本尚未核验。"
    if assessment and assessment["topic_evidence_status"] != "supported":
        reason = " ".join(row["message"] for row in assessment["topic_evidence_reasons"])
        if assessment["topic_evidence_status"] == "partial":
            supported = [part["text"] for part in assessment["subtopic_coverage"] if part["status"] == "supported"]
            unknown = [part["text"] for part in assessment["subtopic_coverage"] if part["status"] == "unknown"]
            details = ("已有来源证据：" + "、".join(supported[:4]) + "。") if supported else ""
            if unknown:
                details += "尚未确认：" + "、".join(unknown[:4]) + "。"
            reason = details + reason
    # State the actual learning unit and audience fit without claiming that a
    # search snippet proves the complete lesson or that access is unrestricted.
    reason = f"与“{text}”相关：" + reason + level_reason + source_language_notice(resource, scoped_evidence, request.language) + source_scope_notice(resource, scoped_evidence)
    if normal_forms_support:
        topic_rules.append("database_standard_normal_forms_context")
    if assessment and any(row["code"] == "bounded_operation_partial" for row in assessment["topic_evidence_reasons"]):
        topic_rules.append("bounded_operation_partial")
    if assessment:
        topic_rules.extend(row["code"] for row in assessment["topic_evidence_reasons"] if row["code"] in {"qualified_skill_core_partial", "documented_operation_partial"})
    if assessment:
        supported_ids = set(assessment["supporting_evidence_ids"])
        for observed in topic_observations(point, resource, scoped_evidence):
            if supported_ids.intersection(observed["evidence_ids"]):
                topic_rules.extend(observed.get("topic_match_rules", []))
    if assessment and assessment["subtopic_coverage"]:
        supported_ids = set(assessment["supporting_evidence_ids"])
        for observed in topic_observations(point, resource, scoped_evidence):
            if not supported_ids.intersection(observed["evidence_ids"]):
                continue
            content = observed["title"] + " " + observed["body"]
            for part in assessment["subtopic_coverage"]:
                scoped_part = " ".join([*decompose_topic(text)["shared_context"], part["text"]])
                if (part["status"] == "supported" and set(part["evidence_ids"]).intersection(observed["evidence_ids"])
                        and pygame_rect_collision_match(scoped_part, content) is True):
                    topic_rules.append("pygame_colliderect_tests_rectangle_overlap")
            if PROMISE_MEMBER.search(content):
                topic_rules.append("standard_javascript_promise_api_context")
            if re.search(r"异常处理|\bexception\s+handling\b", content, re.I):
                topic_rules.append("error_exception_handling_terms")
    matched_ids = [e["evidence_id"] for e in [*searches, *(x for x in scoped_evidence if x.get("kind") != "search")]
                   if relevance(text, " ".join(str(e.get(k) or "") for k in ("title", "snippet", "description", "text"))) >= .22]
    if assessment:
        matched_ids.extend(assessment["supporting_evidence_ids"])
        matched_ids.extend(identifier for row in assessment["topic_evidence_reasons"] for identifier in row["evidence_ids"])
    return {"knowledge_point_id": point["knowledge_point_id"], "resource_id": resource["resource_id"],
            "ranking_score": round(max(0, min(score, 100)), 2), "recommendation_reason": reason,
            "matched_evidence_ids": list(dict.fromkeys(matched_ids)),
            "coverage_basis": [] if shell_review or identity_review else basis, "topic_match_rules": list(dict.fromkeys(topic_rules)), **(assessment or {})}


def rank_resource(point: dict, resource: dict, evidence: list[dict], request: SearchRequest, *, require_type: bool = True,
                  eligibility_evidence: list[dict] | None = None) -> dict | None:
    if _RANK_CACHE.get() is not None:
        return _rank_resource_uncached(point, resource, evidence, request, require_type=require_type,
            eligibility_evidence=eligibility_evidence)
    token = _RANK_CACHE.set(({}, {}))
    try:
        return _rank_resource_uncached(point, resource, evidence, request, require_type=require_type,
            eligibility_evidence=eligibility_evidence)
    finally:
        _RANK_CACHE.reset(token)
