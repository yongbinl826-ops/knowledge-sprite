from __future__ import annotations

import re
from urllib.parse import urlsplit
from .models import SearchRequest, TopicEvidenceAssessment
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
    for chinese in re.finditer(r"[\u4e00-\u9fff]+", text):
        run = chinese[0]
        if len(run) > 2 and run[0] in "与及和的" and re.search(r"[a-zA-Z0-9+#]\s*$", text[:chinese.start()]):
            run = run[1:]
        # Split conjunctions between concepts, never the initial character of
        # a term such as 和弦 / 与门 into an unrelated one-character token.
        for part in re.split(r"(?<=[\u4e00-\u9fff]{2})[与及和的、](?=[\u4e00-\u9fff]{2})", run):
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
    if len(wanted) < 3:
        return True
    ascii_wanted = {term for term in wanted if re.search(r"[a-z]", term)}
    chinese_concepts = []
    for match in re.finditer(r"[\u4e00-\u9fff]+", point):
        run = match[0]
        if len(run)>2 and run[0] in "与及和的" and re.search(r"[a-zA-Z0-9+#]\s*$", point[:match.start()]):
            run = run[1:]
        chinese_concepts.extend(re.split(r"(?<=[\u4e00-\u9fff]{2})[与及和的、](?=[\u4e00-\u9fff]{2})", run))
    def covers_concept(concept, observation):
        # Cover the entire concept with observed contiguous terms of >=2 Han
        # characters. Do not require artificial cross-word bigrams (单校),
        # and never stitch individual characters or different observations.
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
    plan = {"decomposition_status": "not_applicable", "shared_context": [], "subtopics": []}
    if not re.search(r"[与及和、]|\s+and\s+", text, re.I):
        return plan
    chinese = re.fullmatch(r"\s*((?:[A-Za-z][A-Za-z0-9+#.]*(?:\s+|(?=[\u4e00-\u9fff])))+)([\u4e00-\u9fff].*)", text)
    english = re.fullmatch(r"\s*((?:[A-Z][A-Za-z0-9+#.]*\s+)+)([a-z].*)", text)
    match = chinese or english
    if not match:
        return {**plan, "decomposition_status": "unknown"}
    context = match[1].strip().split()
    parts = [part.strip() for part in re.split(r"[与及和、]|\s+and\s+", match[2], flags=re.I)]
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
    return text + " " + " ".join(additions)


def _subtopic_matches(subtopic: str, text: str) -> bool:
    # Only the complete error-handling concept is interchangeable here; the
    # word 'error' or an API name by itself is not instructional coverage.
    error_concepts = r"错误处理|异常处理|\berror\s+handling\b|\bexception\s+handling\b"
    if re.fullmatch(error_concepts, subtopic, re.I):
        return bool(re.search(error_concepts, text, re.I))
    if re.fullmatch(r"并发|concurrency|concurrent\s+(?:operations?|programming)", subtopic, re.I):
        return bool(re.search(r"并发|\bconcurren(?:cy|t)\b", text, re.I))
    # The complete-concept matcher already allows harmless Chinese word
    # boundaries such as 文件的读写. Do not re-impose cross-boundary bigrams.
    return compound_english_match(subtopic, [text]) and (len(tokens(subtopic)) >= 3 or relevance(subtopic, text) >= .999)


def _normal_forms_context(point: str, text: str) -> bool:
    wanted = tokens(point)
    return ("database" in wanted and bool(wanted & {"normalization", "normalisation"})
            and bool(re.search(r"\bnormal(?:iz|is)ation\b", text, re.I))
            and bool(re.search(r"\b(?:[1-5]nf|bcnf)\b", text, re.I)))


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


def topic_observations(point: dict, resource: dict, evidence: list[dict]) -> list[dict]:
    """Create scoring copies; persisted search/page evidence is never changed."""
    observations = []
    for entry in evidence:
        if entry.get("kind") != "search" or entry.get("source") == "official_sitemap" or entry.get("knowledge_point_id") not in {None, point["knowledge_point_id"]}:
            continue
        title = entry.get("title") or ""
        if not title and not entry.get("knowledge_point_id") and resource.get("field_provenance", {}).get("title", {}).get("source") != "search":
            title = resource.get("title") or ""
        title = own_resource_snippet(title)
        snippet = own_resource_snippet(entry.get("snippet") or "")
        raw = title + " " + snippet
        clean_title, clean_body = EXTERNAL_URL.sub(" ", title), EXTERNAL_URL.sub(" ", snippet)
        if topic_context_conflict(point["text"], clean_title + " " + clean_body):
            continue
        observations.append({"title": clean_title, "body": clean_body, "raw": raw,
            "evidence_ids": [entry["evidence_id"]] if entry.get("evidence_id") else []})
    fields, ids = {}, []
    for field in ("title", "description"):
        provenance = resource.get("field_provenance", {}).get(field, {})
        if provenance.get("source") == "search":
            continue
        if resource.get("metadata_evidence_level") == "search" and any(row.get("kind") == "search" for row in evidence):
            continue
        value = resource.get(field) or ""
        if value:
            fields[field] = value
            if provenance.get("evidence_id") in {row.get("evidence_id") for row in evidence}:
                ids.append(provenance["evidence_id"])
    if fields:
        raw = fields.get("title", "") + " " + fields.get("description", "")
        if not topic_context_conflict(point["text"], raw):
            observations.append({"title": EXTERNAL_URL.sub(" ", fields.get("title", "")),
                "body": EXTERNAL_URL.sub(" ", fields.get("description", "")), "raw": raw, "evidence_ids": ids})
    # Each chapter is its own observation. Different chapter titles cannot be
    # stitched into one claimed lesson, and an unbacked chapter cannot add support.
    for chapter in resource.get("chapters", []):
        if not isinstance(chapter, dict):
            continue
        source = next((row for row in evidence if row.get("evidence_id") == chapter.get("evidence_id") and row.get("kind") == "catalog"), None)
        if source:
            title = str(chapter.get("title") or chapter.get("name") or "")
            observations.append({"title": EXTERNAL_URL.sub(" ", title), "body": "", "raw": title, "evidence_ids": [source["evidence_id"]]})
    return observations


def assess_topic_evidence(point: dict, resource: dict, evidence: list[dict]) -> dict | None:
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
            ids = list(dict.fromkeys(identifier for row in contextual if _subtopic_matches(subtopic["text"], row["text"]) for identifier in row["evidence_ids"]))
            prior_only = not ids and any(_subtopic_matches(subtopic["text"], row["prerequisite_text"]) for row in teaching_rows)
            coverage.append({**subtopic, "status": "supported" if ids else "unknown", "evidence_ids": ids,
                "reason": "同一条观察明确包含共同技术上下文和该子项。" if ids else "这一子项仅在先修说明中出现，尚未明确证明会讲授。" if prior_only else "当前资源自身的观察未同时证明共同技术上下文和这一子项。"})
        whole = [row for row in contextual if all(_subtopic_matches(part["text"], row["text"]) for part in plan["subtopics"])]
    else:
        whole = [row for row in good if compound_english_match(point["text"], [row["text"]]) and relevance(point["text"], row["text"]) >= .4]
    supporting = list(dict.fromkeys(identifier for row in whole for identifier in row["evidence_ids"]))
    if whole:
        status = "supported"
        reasons = [{"code": "direct_topic_support", "message": "已有本资源自身的标题、简介或目录文字直接支持该主题；不代表完整教学或播放已核验。", "evidence_ids": supporting}]
    elif any(part["status"] == "supported" for part in coverage):
        status = "partial"
        supporting = list(dict.fromkeys(identifier for part in coverage for identifier in part["evidence_ids"]))
        fragmented = all(part["status"] == "supported" for part in coverage)
        reasons = [{"code": "fragmented_compound_evidence" if fragmented else "partial_compound_coverage",
                    "message": "各子项分别出现在不同观察中；没有同一观察支持整个复合知识点，仍需核对。" if fragmented else "仅有部分子项的自身证据；不能把这条资源当作整个复合知识点的完整支持。",
                    "evidence_ids": supporting}]
    elif weak:
        status, reasons = "needs_review", weak
    else:
        return None
    return TopicEvidenceAssessment(topic_evidence_status=status, topic_evidence_reasons=reasons,
        supporting_evidence_ids=supporting, subtopic_coverage=coverage).model_dump()


def summarize_collection_coverage(point_text: str, items: list[dict]) -> dict:
    """Summarize only the actual displayed, deduplicated resource set."""
    plan = decompose_topic(point_text)
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
    searches = [{**entry, "snippet": own_resource_snippet(entry.get("snippet") or "")}
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
    description = (resource.get("description") or "") if resource.get("metadata_evidence_level") in {"page", "catalog"} and description_source != "search" else ""
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
    assessment = assess_topic_evidence(point, resource, scoped_evidence)
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
    if ((topic < .4 or matched_terms < min(2, len(wanted))) and not (partial or complete_contextual_support or normal_forms_support)) or not is_teaching:
        return None
    if partial:
        # Partial candidates are in a separate section. Score their evidenced
        # subitems instead of pretending the original compound was fully matched.
        topic = .45 + .1 * sum(part["status"] == "supported" for part in assessment["subtopic_coverage"]) / len(assessment["subtopic_coverage"])
    elif complete_contextual_support or normal_forms_support:
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
    if request.student_level == "beginner":
        score += 3 if re.search(r"入门|零基础|beginner|introduction", combined, re.I) else 0
        score -= 4 if re.search(r"高级|advanced", title, re.I) else 0
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
    if normal_forms_support:
        topic_rules.append("database_standard_normal_forms_context")
    if assessment and assessment["subtopic_coverage"]:
        supported_ids = set(assessment["supporting_evidence_ids"])
        for observed in topic_observations(point, resource, scoped_evidence):
            if not supported_ids.intersection(observed["evidence_ids"]):
                continue
            content = observed["title"] + " " + observed["body"]
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
            "coverage_basis": basis, "topic_match_rules": list(dict.fromkeys(topic_rules)), **(assessment or {})}
