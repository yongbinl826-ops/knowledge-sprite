"""Isolated official-sitemap security/identity fixtures; no network or database."""
from html import escape
import hashlib

import pytest

from backend.app.config import Settings
from backend.app.fetcher import Fetcher, FetcherConfig, HTTPResult
from backend.app.official_sitemap import (
    ORIGIN, OfficialSitemapProvider, covers_original_topic, official_url, parse_sitemap, path_words,
)
from backend.app.providers import SearchError
from backend.app.resource_identity import derive_course_identity


NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
INDEX = ORIGIN + "/sitemap.xml"


def xml(kind, locations):
    child = "sitemap" if kind == "sitemapindex" else "url"
    rows = "".join(f"<{child}><loc>{escape(location)}</loc></{child}>" for location in locations)
    return f'<{kind} xmlns="{NS}">{rows}</{kind}>'.encode()


class MemoryHTTP:
    def __init__(self, responses):
        self.responses = responses
        self.requests = []

    async def request(self, url, addresses, max_bytes):
        self.requests.append(url)
        assert url in self.responses, "unlisted fixture request; never fall back to network"
        body = self.responses[url]
        assert len(body) <= max_bytes
        return HTTPResult(200, {"content-type": "application/xml"}, body, url)


def provider(children):
    """children maps exact observed child sitemap URLs to isolated XML bodies."""
    responses = {
        ORIGIN + "/robots.txt": f"User-agent: *\nAllow: /\nSitemap: {INDEX}\n".encode(),
        INDEX: xml("sitemapindex", children), **children,
    }
    transport = MemoryHTTP(responses)
    async def fixture_dns(url, timeout=8):
        return ["93.184.216.34"]  # Fixed fixture response; no resolver call.
    fetcher = Fetcher(FetcherConfig(min_interval_seconds=0, max_retries=0),
                      resolver=fixture_dns, http_client=transport)
    settings = Settings(official_sitemap_children_per_query=2, official_sitemap_cache_ttl=0)
    return OfficialSitemapProvider(settings, fetcher=fetcher, store=None), transport


@pytest.mark.parametrize("encoding", ["utf-16", "utf-16-le", "utf-16-be"])
def test_utf16_xml_is_rejected_instead_of_bypassing_declaration_guard(encoding):
    body = f'<urlset xmlns="{NS}"><url><loc>{ORIGIN}/courses/x/</loc></url></urlset>'.encode(encoding)
    with pytest.raises(SearchError) as error:
        parse_sitemap(body, "urlset")
    assert error.value.code == "invalid_response"


@pytest.mark.parametrize("declaration", [
    '<!DOCTYPE urlset [<!ENTITY secret SYSTEM "file:///C:/private.txt">]>',
    '<!DOCTYPE urlset SYSTEM "https://elsewhere.example.org/external.dtd">',
    '<!ENTITY secret "expanded">',
])
def test_dtd_and_entity_declarations_are_rejected(declaration):
    body = f'{declaration}<urlset xmlns="{NS}"/>'.encode()
    with pytest.raises(SearchError) as error:
        parse_sitemap(body, "urlset")
    assert error.value.code == "invalid_response"


@pytest.mark.parametrize("location", [
    "https://elsewhere.example.org/courses/python/", "https://ocw.mit.edu.evil.example.org/courses/python/",
    "http://ocw.mit.edu/courses/python/", "http://127.0.0.1/private", "https://10.0.0.1/private",
    "https://[::1]/private", "https://localhost/private", "https://user:password@ocw.mit.edu/courses/python/",
    "file:///C:/private.txt", "//ocw.mit.edu/courses/python/", "https://ocw.mit.edu:444/courses/python/",
])
def test_unapproved_loc_cannot_become_an_official_location(location):
    allowed = ORIGIN + "/courses/synthetic-python/"
    assert official_url(location) is None
    assert parse_sitemap(xml("urlset", [location, allowed]), "urlset") == [allowed]


@pytest.mark.parametrize(("actual", "expected"), [("urlset", "sitemapindex"), ("sitemapindex", "urlset"), ("root", "urlset")])
def test_root_kind_must_match_expected_sitemap_level(actual, expected):
    with pytest.raises(SearchError) as error:
        parse_sitemap(f'<{actual} xmlns="{NS}"/>'.encode(), expected)
    assert error.value.code == "invalid_response"


def test_only_one_direct_namespaced_loc_inside_correct_container_is_observed():
    allowed = ORIGIN + "/courses/synthetic-python/"
    body = f'''<urlset xmlns="{NS}">
      <url><loc>{allowed}</loc></url>
      <url><image><loc>{ORIGIN}/courses/nested-not-a-course/</loc></image></url>
      <url><loc>{ORIGIN}/courses/ambiguous-a/</loc><loc>{ORIGIN}/courses/ambiguous-b/</loc></url>
      <url><loc xmlns="https://other.example.org/ns">{ORIGIN}/courses/wrong-namespace/</loc></url>
      <sitemap><loc>{ORIGIN}/courses/wrong-container/</loc></sitemap>
      <title>{ORIGIN}/courses/title-is-not-loc/</title>
    </urlset>'''.encode()
    assert parse_sitemap(body, "urlset") == [allowed]
    with pytest.raises(SearchError):
        parse_sitemap(b"<urlset><url><loc>https://ocw.mit.edu/courses/x/</loc></url></urlset>", "urlset")


@pytest.mark.asyncio
@pytest.mark.parametrize("domains", [["bilibili.com"], ["icourse163.org"], ["bilibili.com", "icourse163.org"], ["xuetangx.com"]])
async def test_targeted_platform_queries_cannot_silently_become_mit_queries(domains):
    discovery, transport = provider({})
    assert await discovery.search("Python", "any", 3, domains) == []
    assert transport.requests == []
    assert discovery.last_discovery["stop_reason"] == "domain_filter_excludes_official_source"


@pytest.mark.asyncio
@pytest.mark.parametrize("point", ["Python dictionaries", "Python列表与字典", "SQL left joins"])
async def test_fine_grained_topic_does_not_widen_to_broad_course(point):
    child = ORIGIN + "/courses/0-001-introduction-to-python-and-sql-spring-2025/sitemap.xml"
    discovery, transport = provider({child: xml("urlset", [child.removesuffix("sitemap.xml")])})
    assert await discovery.search(point, "any", 3, []) == []
    assert child not in transport.requests
    assert discovery.last_discovery["matching_child_indexes"] == 0


@pytest.mark.parametrize(("point", "text", "version"), [
    ("Python", "introductory python course", "3"),
    ("Python", "python 3.10 course", "3.11"),
    ("Python", "python 13 course", "3"),
    ("Python 3", "introductory python course", ""),
    ("Python3", "introductory python course", ""),
    ("Python 3.11", "python 3.10 course", ""),
])
def test_original_and_separate_technical_versions_cannot_be_dropped(point, text, version):
    assert not covers_original_topic(point, text, version)


@pytest.mark.parametrize(("point", "text", "version"), [
    ("Python 3", "python 3 course", ""),
    ("Python3", "python 3 course", ""),
    ("Python 3.11", "python 3.11 course", ""),
    ("Python", "python3.11 course", "3.11"),
])
def test_matching_version_can_still_pass_the_lexical_gate(point, text, version):
    assert covers_original_topic(point, text, version)


@pytest.mark.asyncio
async def test_explicit_version_mismatch_does_not_fetch_an_unversioned_child():
    child = ORIGIN + "/courses/0-001-python-programming-spring-2025/sitemap.xml"
    discovery, transport = provider({child: xml("urlset", [child.removesuffix("sitemap.xml")])})
    assert await discovery.search("Python", "any", 2, [], technical_version="3.11") == []
    assert child not in transport.requests
    assert discovery.last_discovery["technical_version"] == "3.11"


@pytest.mark.asyncio
async def test_matching_version_selects_only_the_observed_versioned_child():
    unversioned = ORIGIN + "/courses/0-001-python-spring-2025/"
    versioned = ORIGIN + "/courses/0-002-python-3.11-spring-2025/"
    discovery, transport = provider({home + "sitemap.xml": xml("urlset", [home]) for home in (unversioned, versioned)})
    candidates = await discovery.search("Python", "any", 3, [], technical_version="3.11")
    assert [candidate.url for candidate in candidates] == [versioned]
    assert unversioned + "sitemap.xml" not in transport.requests
    assert versioned + "sitemap.xml" in transport.requests


@pytest.mark.asyncio
async def test_candidate_is_an_actual_loc_and_title_stays_low_confidence_url_words():
    child = ORIGIN + "/courses/0-001-python-lists-spring-2025/sitemap.xml"
    observed = child.removesuffix("sitemap.xml") + "resources/lesson-one/"
    # The home URL and a tempting title are absent as loc entries and must not be guessed.
    body = xml("urlset", [observed]).replace(b"</urlset>", b"<title>Verified professor title</title></urlset>")
    discovery, transport = provider({child: body})
    candidates = await discovery.search("Python lists", "any", 3, [])
    assert len(candidates) == 1 and candidates[0].url == observed
    candidate = candidates[0]
    assert candidate.title == path_words(observed) and candidate.title != "Verified professor title"
    assert candidate.resource_type_hint == "unknown" and candidate.type_source is None
    evidence = candidate.discovery_evidence
    assert evidence["kind"] == "sitemap_loc" and evidence["confidence"] == "low"
    assert evidence["title_basis"] == "url_path_words" and evidence["observed_url"] == observed
    assert evidence["source_url"] == child and evidence["source_sha256"] == hashlib.sha256(body).hexdigest()
    assert transport.requests == [ORIGIN + "/robots.txt", INDEX, child]


@pytest.mark.asyncio
async def test_matching_child_index_without_actual_loc_does_not_invent_home():
    child = ORIGIN + "/courses/0-001-python-lists-spring-2025/sitemap.xml"
    discovery, _ = provider({child: xml("urlset", [])})
    assert await discovery.search("Python lists", "any", 3, []) == []


@pytest.mark.asyncio
async def test_full_course_version_slug_is_preserved_and_not_merged_by_topic():
    homes = [ORIGIN + f"/courses/0-001-python-lists-spring-{year}/" for year in (2024, 2025)]
    discovery, _ = provider({home + "sitemap.xml": xml("urlset", [home]) for home in homes})
    candidates = await discovery.search("Python lists", "any", 3, [])
    assert {candidate.url for candidate in candidates} == set(homes)
    identities = []
    for index, candidate in enumerate(candidates):
        resource = {"url": candidate.url, "resource_type": "unknown"}
        evidence = [{"evidence_id": str(index), "kind": "search", "url": candidate.url}]
        identities.append(derive_course_identity(resource, evidence))
    assert len({identity["family_id"] for identity in identities}) == 2
    assert len({identity["offering_id"] for identity in identities}) == 2
    assert {identity["family_url"] for identity in identities} == set(homes)
