"""Read the public MOOC course introduction and its textual curriculum only."""
from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from ..url_utils import safe_thumbnail_url
from ..mooc_urls import course_identity_parts, public_course_url
from .base import FieldFact, SourceFacts, clean_text


_TOKEN = re.compile(r'''\s+|//[^\r\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[A-Za-z_$][\w$]*|-?\d+(?:\.\d+)?|[^\s]''')
MOOC_CATALOG_LIMIT = 500
MOOC_STRUCT_SOURCE = "html.icourse163.termDto.outLineDto.outLineStructureDtos"


def _structure_text(value: str) -> str:
    """Render literal text only; markup cannot add remote lessons or scripts."""
    soup = BeautifulSoup(value, "html.parser")
    for tag in soup.select("script, style, noscript, template, [hidden], [aria-hidden='true']"):
        if not tag.decomposed:
            tag.decompose()
    for tag in list(soup.select("[style]")):
        if not tag.decomposed and re.search(r"display\s*:\s*none|visibility\s*:\s*hidden", str(tag.get("style", "")), re.I):
            tag.decompose()
    return " ".join(soup.get_text(" ", strip=True).split())


def _read_structure(result: SourceFacts, rows: object, page_url: str) -> bool:
    """Read explicit DTO name/plan relations; goals are not lesson titles.

    Public pages use ordered name/goals/plan records.  The plan separator is
    literal ';;;', not a remote lesson identifier.  Reject an invalid/oversized
    whole catalog rather than presenting a silently truncated preview.
    """
    titles: list[tuple[str, int | None]] = []
    text_size = 0
    try:
        if not isinstance(rows, list) or len(rows) > 200:
            raise ValueError("record bounds")
        for row in rows:
            if not isinstance(row, dict) or not set(row) <= {"name", "goals", "plan"}:
                raise ValueError("record schema")
            name, goals, plan = row.get("name"), row.get("goals", ""), row.get("plan", "")
            if (not isinstance(name, str) or not isinstance(goals, str) or not isinstance(plan, str)
                    or len(name) > 300 or len(goals) > 4000 or len(plan) > 16000):
                raise ValueError("text schema or bounds")
            text_size += len(name) + len(goals) + len(plan)
            if text_size > 100000:
                raise ValueError("total text bounds")
            title = _structure_text(name)
            if not title:
                raise ValueError("empty parent")
            parent_index = len(titles)
            titles.append((title, None))
            for part in plan.split(";;;"):
                child = _structure_text(part)
                if len(child) > 300:
                    raise ValueError("child title bounds")
                if child:
                    titles.append((child, parent_index))
        if len(titles) > MOOC_CATALOG_LIMIT:
            result.fields.append(FieldFact("catalog_fetch_status", "catalog_limit_exceeded", MOOC_STRUCT_SOURCE + ".limit",
                f"Public course outline contains {len(titles)} nonempty entries, exceeding the {MOOC_CATALOG_LIMIT}-entry limit; no truncated catalog is displayed"))
            return False
    except (ValueError, TypeError):
        result.fields.append(FieldFact("catalog_fetch_status", "catalog_payload_invalid", MOOC_STRUCT_SOURCE + ".invalid",
            "Own public course structure has unsupported schema or exceeds text bounds; no partial catalog is displayed"))
        return False
    result.chapters = [{"title": title, "url": None, "source_url": page_url,
                        "start_seconds": None, "end_seconds": None,
                        "duration_seconds": None,
                        **({"outline_parent_index": parent} if parent is not None else {})}
                       for title, parent in titles]
    if result.chapters:
        result.catalog_source = MOOC_STRUCT_SOURCE
        result.catalog_kind = "course_outline"
    return True


def _read_paragraphs(result: SourceFacts, paragraphs: list, page_url: str, source: str) -> bool:
    """Keep the whole bounded outline or explicitly reject it; never slice it."""
    titles = [title for paragraph in paragraphs
              if (title := clean_text(paragraph.get_text(" ", strip=True), 300))]
    if len(titles) > MOOC_CATALOG_LIMIT:
        result.fields.append(FieldFact("catalog_fetch_status", "catalog_limit_exceeded", source + ".limit",
            f"Public course outline contains {len(titles)} nonempty entries, exceeding the {MOOC_CATALOG_LIMIT}-entry limit; no truncated catalog is displayed"))
        return False
    result.chapters = [{"title": title, "url": None, "source_url": page_url,
                        "start_seconds": None, "end_seconds": None,
                        "duration_seconds": outline_duration_seconds(title)} for title in titles]
    if result.chapters:
        result.catalog_source = source
        result.catalog_kind = "course_outline"
    return True


def _inline_objects(script: str, *, names=frozenset({"termDto", "courseDto"}), single_quotes=False, allow_eof=False) -> dict | None:
    """Read bounded literal assignments, defaulting to the main-site pair.

    This intentionally accepts only JSON-like literal data (including unquoted
    keys, comments and trailing commas seen on the public course page). Calls,
    concatenation, interpolation, duplicate keys and ambiguous assignments are
    rejected. It is not a JavaScript interpreter or a private API client.
    """
    if len(script) > 250_000:
        return None
    tokens = [match.group() for match in _TOKEN.finditer(script)
              if not match.group().isspace() and not match.group().startswith(("//", "/*"))]
    if len(tokens) > 12_000:
        return None

    def literal(index: int, depth: int = 0):
        if depth > 8 or index >= len(tokens):
            raise ValueError("literal bounds")
        token = tokens[index]
        if token.startswith('"'):
            return json.loads(token), index + 1
        if single_quotes and token.startswith("'"):
            import ast
            value = ast.literal_eval(token)
            if not isinstance(value, str):
                raise ValueError("non-string literal")
            return value, index + 1
        if token == "{":
            value = {}
            index += 1
            while index < len(tokens) and tokens[index] != "}":
                key = tokens[index]
                key = json.loads(key) if key.startswith('"') else key
                if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z_$][\w$]*", key) or key in value:
                    raise ValueError("invalid or duplicate property")
                if index + 1 >= len(tokens) or tokens[index + 1] != ":":
                    raise ValueError("property separator")
                value[key], index = literal(index + 2, depth + 1)
                if index >= len(tokens) or tokens[index] not in {",", "}"}:
                    raise ValueError("literal expression")
                if tokens[index] == ",":
                    index += 1
                if len(value) > 200:
                    raise ValueError("property bounds")
            if index >= len(tokens):
                raise ValueError("unterminated object")
            return value, index + 1
        if token == "[":
            value = []
            index += 1
            while index < len(tokens) and tokens[index] != "]":
                item, index = literal(index, depth + 1)
                value.append(item)
                if index >= len(tokens) or tokens[index] not in {",", "]"} or len(value) > 200:
                    raise ValueError("array bounds or expression")
                if tokens[index] == ",":
                    index += 1
            if index >= len(tokens):
                raise ValueError("unterminated array")
            return value, index + 1
        if token in {"true", "false", "null"} or re.fullmatch(r"-?\d+(?:\.\d+)?", token):
            return json.loads(token), index + 1
        raise ValueError("nonliteral value")

    found = {}
    depth = 0
    index = 0
    try:
        while index < len(tokens):
            if (depth == 0 and (index == 0 or tokens[index - 1] == ";") and tokens[index:index + 2] == ["window", "."]
                    and index + 3 < len(tokens) and tokens[index + 2] in names
                    and tokens[index + 3] == "="):
                name = tokens[index + 2]
                value, end = literal(index + 4)
                if name in found or not isinstance(value, dict):
                    return None
                if end == len(tokens) and allow_eof:
                    found[name] = value
                    index = end
                    continue
                if end >= len(tokens) or tokens[end] != ";":
                    return None
                found[name] = value
                index = end + 1
                continue
            if tokens[index] in {"{", "[", "("}:
                depth += 1
            elif tokens[index] in {"}", "]", ")"}:
                depth -= 1
                if depth < 0:
                    return None
            # Backtick interpolation cannot be treated as literal page data.
            elif tokens[index] in {"`", "/"}:
                return None
            index += 1
    except (ValueError, TypeError, SyntaxError, RecursionError):
        return None
    return found if depth == 0 and set(found) == set(names) else None


def extract_embedded_course_facts(soup: BeautifulSoup, url: str) -> SourceFacts:
    """Read the public course-page payload before executable nodes are stripped."""
    result = SourceFacts()
    page_url = _course_url(url)
    if not page_url or soup.select_one("#j-course-heading-intro .course-heading-intro_intro") is None or soup.select_one("#j-course-outline") is None:
        return result
    payloads = []
    for script in soup.select("script:not([src])")[:40]:
        content = script.string or script.get_text()
        if not re.search(r"\bwindow\s*\.\s*(?:termDto|courseDto)\s*=", content):
            continue
        payload = _inline_objects(content)
        if payload is None:
            return result
        payloads.append(payload)
    if len(payloads) != 1:
        return result
    payload = payloads[0]
    course = payload["courseDto"]
    identity = course_identity_parts(page_url)
    if not identity or str(course.get("id")) != identity["course_id"]:
        return result
    requested_term = identity["term_id"]
    if requested_term is not None and str(payload["termDto"].get("id")) != requested_term:
        return result
    # The literal course/term identity already binds this image container to
    # the requested course. A missing outline does not invalidate its cover.
    cover = soup.select_one("#j-courseImg img.img[src]")
    thumbnail = safe_thumbnail_url(cover.get("src"), page_url) if cover else None
    if thumbnail:
        result.fields.append(FieldFact("thumbnail_url", thumbnail, "html.icourse163.course_cover"))
    outline_dto = payload["termDto"].get("outLineDto")
    if not isinstance(outline_dto, dict) or not isinstance(outline_dto.get("outLine"), str):
        return result
    outline = BeautifulSoup(outline_dto["outLine"], "html.parser")
    for tag in outline.select("script, style, noscript, template, [hidden], [aria-hidden='true']"):
        if not tag.decomposed:
            tag.decompose()
    for tag in list(outline.select("[style]")):
        if not tag.decomposed and re.search(r"display\s*:\s*none|visibility\s*:\s*hidden", str(tag.get("style", "")), re.I):
            tag.decompose()
    within_limit = _read_paragraphs(result, outline.select("p"), page_url,
                                   "html.icourse163.termDto.outLineDto.outLine")
    # Alternative public-page representation. Never borrow related/telemetry
    # arrays or replace a nonempty/oversized legacy outline with this view.
    if not result.chapters and within_limit and not outline.get_text(strip=True) and "outLineStructureDtos" in outline_dto:
        within_limit = _read_structure(result, outline_dto["outLineStructureDtos"], page_url)
    if not result.chapters and within_limit:
        return result
    curriculum = (result.catalog_source or "html.icourse163.termDto.outLineDto").removeprefix("html.icourse163.")
    result.fields.append(FieldFact("resource_type", "course", "html.icourse163.embedded_course_structure",
        f"Public course HTML contains matching courseDto.id, course introduction/outline containers and {curriculum} literal curriculum; no scripts executed or playback tested"))
    title = clean_text(course.get("name"), 500)
    if title:
        result.fields.append(FieldFact("title", title, "html.icourse163.embedded_course.name"))
    intro = soup.select_one("#j-rectxt")
    intro_text = intro.get_text(" ", strip=True) if intro else ""
    if intro_text.startswith("spContent="):
        description = clean_text(intro_text[len("spContent="):])
        if description:
            result.fields.append(FieldFact("description", description, "html.icourse163.embedded_introduction"))
    return result


def _course_url(url: str) -> str | None:
    return public_course_url(url)


def outline_duration_seconds(value: str | None) -> int | float | None:
    """An explicit trailing '(Nmin)' describes this item, not a playable URL."""
    value = clean_text(value, 500)
    if not value:
        return None
    match = re.search(r"[（(]\s*(\d{1,5}(?:\.\d{1,3})?)\s*min\s*[）)]\s*$", value, re.I)
    if not match:
        return None
    seconds = float(match.group(1)) * 60
    return (int(seconds) if seconds.is_integer() else seconds) if seconds > 0 else None


class ICourse163Adapter:
    name = "icourse163_course_outline"

    def matches(self, url: str) -> bool:
        return _course_url(url) is not None

    def extract(self, soup: BeautifulSoup, url: str) -> SourceFacts:
        result = SourceFacts()
        page_url = _course_url(url)
        if not page_url:
            return result
        if urlsplit(page_url).path == "/course/detail.htm":
            # The legacy detail endpoint can contain generic HTML without any
            # course identifier. Containers/title alone cannot bind its cid.
            # A matching literal courseDto/termDto is handled before scripts
            # are removed by extract_embedded_course_facts above.
            return result
        for button in soup.select(".course-enroll-info_course-enroll_buttons .course-enroll-info_course-enroll_buttons_enroll-btn .ux-btn")[:5]:
            notice = clean_text(button.get_text(" ", strip=True), 500)
            if notice and re.fullmatch(r"老师已关闭该学期[，,]\s*无法查看[。.!！]?", notice):
                result.fields.append(FieldFact("access_notice", notice, "html.icourse163.enrollment_notice"))
                break
        introduction = soup.select_one("#j-course-heading-intro .course-heading-intro_intro")
        outline = soup.select_one("#j-course-outline")
        # The route alone is search discovery. The source-specific introduction
        # and curriculum container establish an observed course page.
        if introduction is None or outline is None:
            return result
        cover = soup.select_one("#j-courseImg img.img[src]")
        thumbnail = safe_thumbnail_url(cover.get("src"), page_url) if cover else None
        if thumbnail:
            result.fields.append(FieldFact("thumbnail_url", thumbnail, "html.icourse163.course_cover"))
        description = clean_text(introduction.get_text(" ", strip=True))
        if not description:
            return result
        result.fields.extend([
            FieldFact("description", description, "html.icourse163.course_introduction"),
            FieldFact("resource_type", "course", "html.icourse163.course_structure",
                      "Observed MOOC course introduction and course-outline container; this is curriculum evidence, not video playback evidence"),
        ])
        # Includes literal chapter headings, quizzes and assignments, with no
        # lesson/media URLs inferred. Oversized outlines are explicitly empty.
        _read_paragraphs(result, outline.select(".f-richEditorText p"), page_url,
                         "html.icourse163.course_outline.text")
        return result
