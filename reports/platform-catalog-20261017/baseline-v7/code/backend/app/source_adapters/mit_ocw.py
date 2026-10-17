"""MIT OCW course, gallery and resource pages, scoped to their public DOM."""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from ..url_utils import UnsafeURL, normalize_url
from .base import FieldFact, SourceFacts, clean_text


class MITOCWAdapter:
    name = "mit_ocw"

    def matches(self, url: str) -> bool:
        parsed = urlsplit(url)
        return parsed.hostname in {"ocw.mit.edu", "www.ocw.mit.edu"} and parsed.path.startswith("/courses/")

    def extract(self, soup: BeautifulSoup, url: str) -> SourceFacts:
        result = SourceFacts()
        parsed = urlsplit(url)
        course_entry = re.fullmatch(r"(/courses/[^/]+)(?:/pages)?/?", parsed.path)
        banner = soup.select_one("#course-banner h1")
        is_gallery = "/video_galleries/" in parsed.path
        is_resource = "/resources/" in parsed.path
        if course_entry and banner:
            result.fields.append(FieldFact("resource_type", "course", "html.mit_ocw.course_home", "Official OCW course homepage or pages overview with #course-banner h1 and same-course resource navigation"))
            result.fields.append(FieldFact("title", clean_text(banner.get_text(" ", strip=True), 500), "html.mit_ocw.course_title"))
            course_path = course_entry.group(1) + "/"
            for anchor in soup.select('a[href*="video_galleries/"]'):
                link_text = clean_text(anchor.get_text(" ", strip=True), 200)
                if not link_text or not re.search(r"video|lecture", link_text, re.I):
                    continue
                try:
                    linked = normalize_url(urljoin(url, str(anchor["href"])))
                except UnsafeURL:
                    continue
                linked_parts = urlsplit(linked)
                if linked_parts.scheme == parsed.scheme and linked_parts.netloc == parsed.netloc and linked_parts.path.startswith(course_path + "video_galleries/"):
                    result.catalog_followup = {"url": linked, "source_url": url, "link_text": link_text, "source": "html.mit_ocw.course_navigation"}
                    break
        # Course staff and the instructors of a reused historical video are
        # distinct roles. Never use page-wide course staff for a chapter author.
        if course_entry or is_gallery:
            names = list(dict.fromkeys(filter(None, (clean_text(tag.get_text(" ", strip=True), 250) for tag in soup.select(".course-info-instructor")[:20]))))
            if names:
                result.fields.append(FieldFact("author", ", ".join(names), "html.mit_ocw.course_instructors"))
                result.fields.append(FieldFact("author_role", "course_instructors", "html.mit_ocw.course_instructors", ".course-info-instructor: " + ", ".join(names)))
        if is_resource:
            description = soup.select_one(".video-page .description")
            if description:
                result.fields.append(FieldFact("description", clean_text(description.get_text(" ", strip=True)), "html.mit_ocw.video_description"))
                for paragraph in description.select("p")[:20]:
                    label = paragraph.find(["strong", "b"])
                    if label and re.fullmatch(r"Instructors?\s*:?", label.get_text(" ", strip=True), re.I):
                        text = paragraph.get_text(" ", strip=True)
                        name = clean_text(re.sub(r"^Instructors?\s*:?\s*", "", text, flags=re.I), 500)
                        if name:
                            result.fields.append(FieldFact("author", name, "html.mit_ocw.video_instructors", text))
                            result.fields.append(FieldFact("author_role", "video_instructors", "html.mit_ocw.video_instructors", text))
                            break
            if soup.select_one(".video-page .video-player-wrapper video"):
                excerpt = "Official OCW resource page contains .video-page .video-player-wrapper video; playback not tested"
                result.fields.extend([FieldFact("resource_type", "video", "html.mit_ocw.video_player", excerpt),
                                      FieldFact("video_evidence_status", "page_verified", "html.mit_ocw.video_player", excerpt)])
        if is_gallery:
            content = soup.select_one("main#course-content-section")
            if content:
                paragraphs = [tag.get_text(" ", strip=True) for tag in content.find_all("p", recursive=False)[:20]]
                if paragraphs:
                    result.fields.append(FieldFact("description", clean_text(" ".join(paragraphs)), "html.mit_ocw.gallery_description"))
                for card in content.select(".video-gallery-card")[:100]:
                    anchor, heading = card.select_one("a.video-link[href]"), card.select_one(".video-title")
                    if not anchor or not heading:
                        continue
                    title = clean_text(heading.get_text(" ", strip=True), 300)
                    try:
                        chapter_url = normalize_url(urljoin(url, str(anchor["href"])))
                    except UnsafeURL:
                        continue
                    if title and urlsplit(chapter_url).hostname == parsed.hostname:
                        result.chapters.append({"title": title, "url": chapter_url})
                if result.chapters:
                    result.catalog_source, result.catalog_kind = "html.mit_ocw.video_gallery", "video_playlist"
                    result.fields.extend([
                        FieldFact("resource_type", "playlist", result.catalog_source, "main#course-content-section contains video-gallery-card / a.video-link / video-title"),
                        FieldFact("video_evidence_status", "page_verified", result.catalog_source, "main#course-content-section contains actual video-gallery-card / a.video-link / video-title entries"),
                    ])
        return result
