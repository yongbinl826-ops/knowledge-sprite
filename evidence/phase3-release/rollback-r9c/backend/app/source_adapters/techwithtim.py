"""Visible lesson HTML binds one video to its own teaching notes.

Series directories, sidebar lessons and cumulative full-program code are not
video teaching evidence. This adapter never requests a player, API or media.
"""
from __future__ import annotations

import ast
import textwrap
import hashlib
import json
import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, Tag

from .base import FieldFact, SourceFacts, clean_text
from ..url_utils import UnsafeURL, normalize_url


TITLE_SOURCE = "html.techwithtim.lesson.title"
VIDEO_SOURCE = "html.techwithtim.lesson.video"
SUMMARY_SOURCE = "html.techwithtim.lesson.summary"
SUMMARY_LIMIT = 6000
DOM_BINDING_KIND = "same_lesson_dom_v2"
DOM_TEACHING_BINDING = "One visible own lesson title and teaching notes share a unique visible embedded video in the same lesson content container."
_BINDING = re.compile(r"\bthe video above offers more in[- ]depth explanations\b", re.I)
_CUMULATIVE = re.compile(r"^(?:full|complete|final|source)\s+(?:code|program)$", re.I)
_NON_LESSON = re.compile(r"^(?:prerequisites?|previous lessons?|related tutorials?|next lesson)$", re.I)
_SLUG = r"[a-z0-9][a-z0-9-]{0,120}"


def lesson_page_url(url: str) -> str | None:
    try:
        value = normalize_url(url)
        parsed = urlsplit(value)
    except (UnsafeURL, TypeError, ValueError):
        return None
    if (parsed.scheme != "https" or parsed.hostname not in {"www.techwithtim.net", "techwithtim.net"}
            or parsed.port not in {None, 443} or parsed.query or parsed.fragment
            or not re.fullmatch(rf"/tutorials/{_SLUG}/{_SLUG}/{_SLUG}/?", parsed.path)):
        return None
    return value


def _video_id(url: str) -> str | None:
    try:
        parsed = urlsplit(normalize_url(url))
    except (UnsafeURL, TypeError, ValueError):
        return None
    if (parsed.scheme != "https" or parsed.hostname not in {"www.youtube.com", "www.youtube-nocookie.com"}
            or parsed.port not in {None, 443} or parsed.query or parsed.fragment):
        return None
    match = re.fullmatch(r"/embed/([A-Za-z0-9_-]{11})", parsed.path)
    return match[1] if match else None


def _visible(tag: Tag) -> bool:
    for ancestor in (tag, *tag.parents):
        if (ancestor.name in {"script", "style", "template", "noscript"} or ancestor.has_attr("hidden")
                or ancestor.get("aria-hidden") == "true"
                or re.search(r"display\s*:\s*none|visibility\s*:\s*hidden", str(ancestor.get("style", "")), re.I)):
            return False
    return not (tag.name == "iframe" and (str(tag.get("height")) == "0" or str(tag.get("width")) == "0"))


def _text(tag: Tag) -> str:
    # Syntax-highlighted spans are separate DOM nodes, not spaces in API names.
    return " ".join("".join(str(node) for node in tag.strings
                            if isinstance(node.parent, Tag) and _visible(node.parent)).split())


def _title_key(value: str) -> str:
    return " ".join(value.casefold().split())



def _function_demonstration(block: Tag, prose: str) -> str | None:
    """Preserve one small, explicitly explained own Pygame function, never run it."""
    code = textwrap.dedent("".join(str(node) for node in block.strings
        if isinstance(node.parent, Tag) and _visible(node.parent))).strip()
    if not code or len(code) > 1500 or len([line for line in code.splitlines() if line.strip()]) > 35:
        return None
    if (re.search(r"\b(?:prerequisites?|previous\s+lesson|next\s+lesson|todo|future\s+lesson|not|never|cannot|can['’]t|don't|won't)\b|先修|不教|不讲|\b(?:full|complete|final)\s+(?:code|program)\b", prose, re.I)
            or re.search(r"(?im)^\s*#.*\b(?:todo|next lesson|prerequisites?|not taught)\b", code)):
        return None
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError, RecursionError):
        return None
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
        return None
    function = tree.body[0]
    if (function.decorator_list or function.args.defaults or function.args.kw_defaults
            or any(argument.arg == "pygame" for argument in [*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs])):
        return None
    if not re.search(r"(?<![A-Za-z0-9_])" + re.escape(function.name) + r"\s*(?:\([^)]{0,80}\)|function\b)", prose, re.I):
        return None
    if not re.search(r"\b(?:we|this|our|will|going|function)\b", prose, re.I):
        return None
    nodes = list(ast.walk(function))
    if any(isinstance(node, (ast.ClassDef, ast.Import, ast.ImportFrom, ast.AsyncFunctionDef))
           or (isinstance(node, ast.FunctionDef) and node is not function) for node in nodes):
        return None
    if any(isinstance(node, ast.Name) and node.id == "pygame" and isinstance(node.ctx, (ast.Store, ast.Del)) for node in nodes):
        return None
    def owns_pygame_call(node):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            return False
        root = node.func
        while isinstance(root, ast.Attribute):
            root = root.value
        return isinstance(root, ast.Name) and root.id == "pygame"
    if not any(owns_pygame_call(node) for node in nodes):
        return None
    return "```python\n" + code + "\n```"


def _teaching_summary(markdown: Tag, title: str) -> str | None:
    selected = [title]
    prose_count = 0
    previous_prose = False
    preceding_prose = ""
    blocks = [tag for tag in markdown.children if isinstance(tag, Tag) and _visible(tag)][:200]
    for block in blocks:
        text = _text(block)
        if block.name in {"h2", "h3", "h4"} and (_CUMULATIVE.fullmatch(text) or _NON_LESSON.fullmatch(text)):
            break
        if block.name in {"h2", "h3", "p", "ul", "ol"}:
            if (not text or len(text) > 700 or _BINDING.search(text)
                    or block.select_one("iframe,script,style,nav,aside")):
                previous_prose = False
                continue
            previous_prose = block.name == "p"
            preceding_prose = text if previous_prose else ""
            prose_count += bool(previous_prose and len(text) >= 30)
        elif block.name == "pre" and previous_prose:
            demonstration = _function_demonstration(block, preceding_prose)
            if demonstration:
                text = demonstration
            elif not 1 <= len(text) <= 260 or re.search(r"\b(?:class|def|import)\s", text):
                previous_prose = False
                continue
            previous_prose = False
        else:
            previous_prose = False
            continue
        if sum(map(len, selected)) + len(selected) + len(text) > SUMMARY_LIMIT:
            break
        selected.append(text)
    return "\n".join(selected) if prose_count >= 2 and len(selected) >= 3 else None


class TechWithTimLessonAdapter:
    name = "techwithtim_lesson"

    def matches(self, url: str) -> bool:
        return lesson_page_url(url) is not None

    def extract(self, soup: BeautifulSoup, url: str) -> SourceFacts:
        facts = SourceFacts()
        page_url = lesson_page_url(url)
        if not page_url:
            return facts
        containers = soup.select('div[class*="tutoriallayout__Content-"]')
        if len(containers) != 1 or not _visible(containers[0]):
            return facts
        content = containers[0]
        headings = content.select(':scope > h1[class*="tutoriallayout__Title-"]')
        bodies = content.select(':scope > div[class*="markdown__Container-"]')
        embeds = content.select(':scope > div[class*="tutoriallayout__EmbededVideo-"] > iframe[src]')
        if (len(headings) != 1 or len(content.select("h1")) != 1 or len(bodies) != 1 or len(embeds) != 1
                or len(content.select("iframe")) != 1
                or any(not _visible(tag) for tag in (headings[0], bodies[0], embeds[0]))):
            return facts
        title = clean_text(_text(headings[0]), 500)
        if not title or len(_text(headings[0])) > 500 or _title_key(embeds[0].get("title", "")) != _title_key(title):
            return facts
        identity = _video_id(embeds[0]["src"])
        if not identity:
            return facts
        body = bodies[0]
        bindings = [tag for tag in body.find_all("p", recursive=False) if _visible(tag)
                    and len(_text(tag)) <= 300 and _BINDING.search(_text(tag))
                    and not re.search(r"\b(?:not|never|doesn't|cannot)\b", _text(tag), re.I)]
        summary = _teaching_summary(body, title)
        # An explicit negative cannot fall back to structural video association.
        if any(_visible(tag) and _BINDING.search(_text(tag))
                and re.search(r"\b(?:not|never|doesn't|cannot)\b", _text(tag), re.I)
                for tag in body.find_all("p", recursive=False)) or not summary:
            return facts
        summary_hash = hashlib.sha256(summary.encode()).hexdigest()
        proof = {"lesson_title": title, "lesson_url": page_url,
                              "video_id": identity, "embed_url": embeds[0]["src"],
                              "embed_title": embeds[0]["title"],
                              "teaching_binding": _text(bindings[0]) if bindings else DOM_TEACHING_BINDING,
                              "summary_sha256": summary_hash,
                              "basis": "same visible lesson container, title-matched iframe and explicit video-above teaching statement; no player/media request",
                              "excluded": "series sidebar, navigation and cumulative Full Code"}
        if not bindings:
            proof.update(binding_version=2, binding_kind=DOM_BINDING_KIND,
                basis="same visible own lesson container, unique title-matched iframe and own teaching notes; no player/media request",
                dom_witness={"content_count": 1, "heading_count": 1, "markdown_count": 1,
                    "embedded_iframe_count": 1, "all_content_iframe_count": 1, "visible": True,
                    "heading_text": title, "iframe_title": embeds[0]["title"],
                    "notes_sha256": summary_hash, "notes_characters": len(summary),
                    "teaching_prose_count": sum(1 for block in body.children if isinstance(block, Tag)
                        and block.name == "p" and _visible(block) and len(_text(block)) >= 30
                        and _text(block) in summary and not _BINDING.search(_text(block)))})
        binding = json.dumps(proof, ensure_ascii=False, sort_keys=True)
        facts.fields.extend([
            FieldFact("title", title, TITLE_SOURCE),
            FieldFact("resource_type", "video", VIDEO_SOURCE, binding),
            FieldFact("video_evidence_status", "page_verified", VIDEO_SOURCE, binding),
            FieldFact("video_topic_summary", summary, SUMMARY_SOURCE),
            FieldFact("description", summary, SUMMARY_SOURCE),
        ])
        return facts


def bound_video_topic_summary(resource: dict, evidence: list[dict]) -> str | None:
    """Recheck same-page/source/title/embed proof for persisted recommendations."""
    page_url = lesson_page_url(resource.get("url", ""))
    if (not page_url or resource.get("resource_type") != "video"
            or resource.get("video_evidence_status") != "page_verified"
            or resource.get("fetch_status") not in {"fetched", "success"}
            or resource.get("metadata_evidence_level") not in {"page", "catalog"}):
        return None
    summary = resource.get("video_topic_summary")
    if (not isinstance(summary, str) or not 1 <= len(summary) <= SUMMARY_LIMIT
            or summary.split("\n", 1)[0] != resource.get("title")):
        return None
    provenance = resource.get("field_provenance") or {}
    rows = {}
    try:
        for field, source in (("title", TITLE_SOURCE), ("video_evidence_status", VIDEO_SOURCE), ("video_topic_summary", SUMMARY_SOURCE)):
            origin = provenance.get(field) or {}
            matching = [r for r in evidence if r.get("evidence_id") == origin.get("evidence_id")]
            if not origin.get("evidence_id") or len(matching) != 1:
                return None
            row = matching[0]
            if (origin.get("source") != source or row.get("source") != source
                    or row.get("kind") != "page" or row.get("field") != field
                    or lesson_page_url(row.get("url", "")) != page_url
                    or normalize_url(origin.get("url", "")) != normalize_url(row.get("url", ""))):
                return None
            rows[field] = row
        binding = json.loads(rows["video_evidence_status"]["text"])
    except (UnsafeURL, TypeError, ValueError, KeyError, RecursionError):
        return None
    if (not isinstance(binding, dict) or binding.get("lesson_title") != resource.get("title")
            or rows["title"].get("text") != resource.get("title")
            or binding.get("lesson_url") != page_url or binding.get("lesson_url") != rows["video_evidence_status"].get("url")
            or _title_key(str(binding.get("embed_title", ""))) != _title_key(str(resource.get("title", "")))
            or not binding.get("video_id") or _video_id(binding.get("embed_url", "")) != binding["video_id"]
            or not _valid_binding(binding, summary, resource.get("title"))
            or rows["video_topic_summary"].get("text") != summary
            or binding.get("summary_sha256") != hashlib.sha256(summary.encode()).hexdigest()):
        return None
    if len({row["url"] for row in rows.values()}) != 1:
        return None
    return summary


def _valid_binding(binding: dict, summary: str, title: str) -> bool:
    if "binding_version" not in binding:
        return ("binding_kind" not in binding and "dom_witness" not in binding
            and bool(_BINDING.search(str(binding.get("teaching_binding", ""))))
            and not re.search(r"\b(?:not|never|doesn't|cannot)\b", str(binding.get("teaching_binding", "")), re.I))
    if (type(binding.get("binding_version")) is not int or binding["binding_version"] != 2
            or binding.get("binding_kind") != DOM_BINDING_KIND
            or binding.get("teaching_binding") != DOM_TEACHING_BINDING):
        return False
    witness = binding.get("dom_witness")
    if not isinstance(witness, dict):
        return False
    counts = ("content_count", "heading_count", "markdown_count", "embedded_iframe_count", "all_content_iframe_count")
    return (all(type(witness.get(key)) is int and witness[key] == 1 for key in counts)
        and witness.get("visible") is True
        and witness.get("heading_text") == title and witness.get("iframe_title") == binding.get("embed_title")
        and witness.get("notes_sha256") == hashlib.sha256(summary.encode()).hexdigest()
        and type(witness.get("notes_characters")) is int and witness["notes_characters"] == len(summary)
        and type(witness.get("teaching_prose_count")) is int and 2 <= witness["teaching_prose_count"] <= 200)
