"""Offline contract checks; fixture output is never live-source acceptance."""
from types import SimpleNamespace
import asyncio

import pytest

from backend.app.extractor import MetadataExtractor
from backend.app.fetcher import Fetcher, HTTPResult
from backend.app.ranking import has_course_page, has_video_evidence
from backend.app.rendering import RenderResult

URL = "https://microsoft.github.io/AI-For-Beginners/"
DOM = '''<html><title>AI for Beginners</title><article class="markdown-section">
<h1>Artificial Intelligence for Beginners - A Curriculum</h1>
<p>This curriculum provides beginner lessons on neural networks.</p>
<table><thead><tr><th></th><th>Lesson Link</th><th>Lab</th></tr></thead><tbody>
<tr><td>I</td><td><a href="lessons/intro/">Introduction group</a></td></tr>
<tr><td>01</td><td><a href="lessons/intro/">History of AI</a></td><td><a href="lessons/intro/lab">Lab</a></td></tr>
<tr><td>02</td><td><a href="lessons/neural/">Neural Networks</a> and <a href="lessons/deep/">Deep Learning</a></td></tr>
<tr><td>03</td><td><a href="https://other.example/lesson">Other</a></td></tr>
</tbody></table></article></html>'''


def test_explicit_curriculum_table_preserves_lesson_links_not_labs_or_groups():
    data = MetadataExtractor().extract(DOM, URL, "2026-10-13T00:00:00Z")
    assert [chapter["title"] for chapter in data["chapters"]] == ["History of AI", "Neural Networks", "Deep Learning"]
    assert has_course_page(dict(data, url=URL), data["evidence"])
    assert not has_video_evidence(data, data["evidence"])
    assert all(chapter["start_seconds"] is None for chapter in data["chapters"])


@pytest.mark.parametrize("html,url", [
    (DOM, "https://docs.example/AI-For-Beginners/"),
    (DOM.replace("A Curriculum", "Documentation"), URL),
    (DOM.replace("Lesson Link", "Navigation"), URL),
    (DOM.replace("markdown-section", "sidebar"), URL),
])
def test_ordinary_documentation_is_not_promoted_to_course(html, url):
    data = MetadataExtractor().extract(html, url, "stamp")
    assert not data["chapters"]
    assert data.get("resource_type") != "course"


async def run_enrichment(monkeypatch, static, dynamic=DOM, status="rendered"):
    fetcher = Fetcher()
    async def fetch(url):
        return HTTPResult(200, {"content-type": "text/html"}, static.encode(), url)
    async def render(instance, response):
        return RenderResult(status=status, html=dynamic, source_sha256="source", manifest_sha256="manifest", dom_sha256="dom")
    monkeypatch.setattr(fetcher, "fetch", fetch)
    fetcher.renderer = SimpleNamespace(config=SimpleNamespace(enabled=True, allowed_hosts=("microsoft.github.io",)), render=render)
    return await fetcher.enrich({"url": URL, "source": "offline_test"})


async def test_dom_facts_have_acquisition_and_semantic_provenance(monkeypatch):
    resource = await run_enrichment(monkeypatch, '<title>AI for Beginners</title><meta name="description" content="Description"><div id="app">Loading</div>')
    assert len(resource["chapters"]) == 3
    assert has_course_page(resource, resource["evidence"])
    assert resource["description"].startswith("This curriculum")
    provenance = resource["field_provenance"]["chapters"]
    assert provenance["source"] == "html.microsoft_ai.curriculum_table"
    assert provenance["acquisition"] == "offline_rendered_dom"
    assert provenance["dom_sha256"] == "dom"
    assert all(c["acquisition"] == "offline_rendered_dom" for c in resource["chapters"])
    assert "html" not in resource["render_diagnostics"]


async def test_render_failure_preserves_static_and_explicit_jsonld(monkeypatch):
    static = '<script type="application/ld+json">{"@type":"Course","name":"Verified title","description":"Explicit original description"}</script>'
    failure = await run_enrichment(monkeypatch, static, status="render_incomplete")
    assert failure["title"] == "Verified title" and failure["chapters"] == []
    success = await run_enrichment(monkeypatch, static)
    assert success["title"] == "Verified title"
    assert success["description"] == "Explicit original description"
    assert len(success["chapters"]) == 3


async def test_cancellation_propagates(monkeypatch):
    fetcher = Fetcher()
    async def fetch(url):
        return HTTPResult(200, {"content-type": "text/html"}, b'<title>AI</title>', url)
    async def render(instance, response):
        raise asyncio.CancelledError()
    monkeypatch.setattr(fetcher, "fetch", fetch)
    fetcher.renderer = SimpleNamespace(config=SimpleNamespace(enabled=True, allowed_hosts=("microsoft.github.io",)), render=render)
    with pytest.raises(asyncio.CancelledError):
        await fetcher.enrich({"url": URL})


async def test_dynamic_access_gate_is_preserved_with_dom_evidence(monkeypatch):
    resource = await run_enrichment(monkeypatch, '<title>Curriculum</title>', '<h1>Access Denied</h1>')
    assert resource["fetch_status"] == "access_denied"
    assert resource["render_diagnostics"]["page_status"] == "access_denied"
    assert any(e.get("source") == "html.rendered_access_gate" and e["dom_sha256"] == "dom" for e in resource["evidence"])


async def test_dynamic_generic_placeholder_cannot_replace_static_og_title(monkeypatch):
    resource = await run_enrichment(monkeypatch, '<meta property="og:title" content="Reliable course"><meta name="description" content="Real description">', '<title>Loading...</title><p>' + 'ordinary page ' * 15 + '</p>')
    assert resource["title"] == "Reliable course"
