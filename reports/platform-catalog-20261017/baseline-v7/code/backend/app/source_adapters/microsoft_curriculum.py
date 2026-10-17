"""Microsoft's explicit AI curriculum table, never a general docs navigation."""
from urllib.parse import urljoin, urlsplit
import re

from bs4 import BeautifulSoup

from .base import FieldFact, SourceFacts, clean_text
from ..url_utils import normalize_url, UnsafeURL


class MicrosoftCurriculumAdapter:
    name = "microsoft_ai_curriculum"

    def matches(self, url: str) -> bool:
        parsed = urlsplit(url)
        return (parsed.scheme == "https" and parsed.hostname == "microsoft.github.io"
                and parsed.path.rstrip("/") == "/AI-For-Beginners")

    def extract(self, soup: BeautifulSoup, url: str) -> SourceFacts:
        result = SourceFacts()
        article = soup.select_one(".markdown-section")
        if not article:
            return result
        heading = article.find("h1")
        title = clean_text(heading.get_text(" ", strip=True), 500) if heading else None
        introduction = next((p for p in article.select("p")[:12]
            if re.search(r"\bcurriculum\b", p.get_text(" ", strip=True), re.I)
            and re.search(r"\blessons?\b", p.get_text(" ", strip=True), re.I)), None)
        if not title or "curriculum" not in title.lower() or introduction is None:
            return result
        for table in article.select("table")[:8]:
            headers = [cell.get_text(" ", strip=True).lower() for cell in table.select("thead th")]
            if "lesson link" not in headers:
                continue
            column = headers.index("lesson link")
            for row in table.select("tbody tr")[:100]:
                cells = row.find_all("td", recursive=False)
                if len(cells) <= column or not re.fullmatch(r"\d{1,3}", cells[0].get_text(strip=True)):
                    continue
                for anchor in cells[column].select("a[href]")[:4]:
                    chapter_title = clean_text(anchor.get_text(" ", strip=True), 300)
                    try:
                        chapter_url = normalize_url(urljoin(url, str(anchor["href"])))
                    except UnsafeURL:
                        continue
                    parsed = urlsplit(chapter_url)
                    if not chapter_title or parsed.hostname != "microsoft.github.io" or not parsed.path.startswith("/AI-For-Beginners/lessons/"):
                        continue
                    result.chapters.append({"title": chapter_title, "url": chapter_url})
            if result.chapters:
                break
        if not result.chapters:
            return result
        source = "html.microsoft_ai.curriculum_table"
        result.fields.extend([
            FieldFact("resource_type", "course", source,
                "Official AI curriculum heading, curriculum/lessons introduction and numbered Lesson Link table with same-curriculum lesson URLs"),
            FieldFact("title", title, "html.microsoft_ai.curriculum_title"),
            FieldFact("description", clean_text(introduction.get_text(" ", strip=True)), "html.microsoft_ai.curriculum_description"),
        ])
        result.catalog_source = source
        result.catalog_kind = "course_outline"
        return result
