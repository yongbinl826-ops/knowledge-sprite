"""No-network public observation reuse and evidence isolation contracts."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from backend.app import course_library as module
from backend.app.course_library import CourseLibrary, course_entry_key
from backend.app.db import Store
from backend.app.discovery_display import discovered_video
from backend.app.extractor import MetadataExtractor
from backend.app.mooc_relevance import assess_mooc_relevance

NOW = 1800000000.0
URL = "https://www.icourse163.org/course/OWN-123"
PROFILE = {"extractor": "13", "outline_policy": "v1", "page_fetch": True}
POINT = {"knowledge_point_id": "new_point", "text": "Python 列表与字典"}


def observed(chapters=("列表", "字典", "函数"), title="Python 程序设计", url=URL, timestamp=NOW - 10):
    parsed = urlsplit(url)
    course_id = (parse_qs(parsed.query)["cid"][0] if parsed.path == "/course/detail.htm"
                 else parsed.path.rstrip("/").rsplit("-", 1)[1])
    term = {"id": "456", "outLineDto": {"outLine": "", "outLineStructureDtos": [
        {"name": text, "goals": "", "plan": ""} for text in chapters]}}
    html = ('<div id="j-course-heading-intro"><div class="course-heading-intro_intro">'
            '本课程依据公开的课程介绍和课程目录开展教学。本页提供课程的独立章节列表，供学生核对课程范围。'
            '学生可在课程页面查看各单元的学习安排和课程内容说明。'
            '</div></div><div id="j-rectxt">spContent=本课程讲授Python程序设计与数据结构，提供公开课程介绍和独立章节安排。</div>'
            '<div id="j-course-outline"></div><script>window.termDto = '
            + json.dumps(term) + '; window.courseDto = ' + json.dumps({"id": course_id, "name": title}) + ';</script>')
    resource = MetadataExtractor().extract(html, url, datetime.fromtimestamp(timestamp, timezone.utc).isoformat())
    resource.update(url=url, canonical_url=url, resource_id="original_resource", platform="icourse163")
    return resource, resource.pop("evidence")


@pytest.fixture
def library(monkeypatch):
    monkeypatch.setattr(module, "time", SimpleNamespace(time=lambda: NOW))
    store = Store(":memory:")
    result = CourseLibrary(store)
    yield result
    store.connection.close()


def test_observation_needs_no_user_search_and_reassesses_every_point(library):
    resource, evidence = observed()
    original = deepcopy((resource, evidence))
    assert library.observe(resource, evidence, PROFILE)
    assert (resource, evidence) == original
    rows = library.lookup(POINT, PROFILE)
    assert len(rows) == 1 and rows[0]["assessment"]["status"] == "outline_supported"
    assert rows[0]["assessment"]["matched_chapters"]
    assert discovered_video(POINT, rows[0]["resource"], rows[0]["evidence"])
    other = {"knowledge_point_id": "another", "text": "Python 函数"}
    assert library.lookup(other, PROFILE)[0]["assessment"]["display_eligible"]
    assert not library.lookup({"knowledge_point_id": "other", "text": "Java 列表与字典"}, PROFILE)
    assert not library.lookup({"knowledge_point_id": "partial", "text": "Python 列表与异常处理"}, PROFILE)
    assert not library.lookup({"knowledge_point_id": "extra", "text": "Python 列表与字典", "learning_targets": ["异步协程"]}, PROFILE)


def test_library_never_persists_queries_user_ids_or_unbound_search_fields(library):
    resource, evidence = observed()
    resource.update(job_id="secret_job", knowledge_point_id="secret_point", query="private project", private_note="user story")
    evidence.append({"evidence_id": "search_secret", "kind": "search", "query": "private project", "snippet": "secret snippet", "title": "secret title", "knowledge_point_id": "secret_point"})
    for row in evidence:
        row.update(job_id="secret_job", knowledge_point_id="secret_point", query="private project")
    assert library.observe(resource, evidence, PROFILE)
    raw = library.store.connection.execute("SELECT data FROM shared_mooc_courses").fetchone()[0]
    assert all(secret not in raw for secret in ("secret_job", "secret_point", "private project", "secret snippet", "secret title", "user story", "search_secret"))
    assert '"kind":"search"' not in raw
    assert not any(row["kind"] == "search" for row in library.lookup(POINT, PROFILE)[0]["evidence"])


def test_copied_job_ids_can_change_without_weakening_original_bindings(library):
    assert library.observe(*observed(), PROFILE)
    hit = library.lookup(POINT, PROFILE)[0]
    resource, evidence = hit["resource"], hit["evidence"]
    mapping = {row["evidence_id"]: "job_evidence_" + str(index) for index, row in enumerate(evidence)}
    for row in evidence:
        row["evidence_id"] = mapping[row["evidence_id"]]
    for provenance in resource["field_provenance"].values():
        provenance["evidence_id"] = mapping[provenance["evidence_id"]]
    for chapter in resource["chapters"]:
        chapter["evidence_id"] = mapping[chapter["evidence_id"]]
    resource["resource_id"] = "new_job_resource"
    assert assess_mooc_relevance(POINT, resource, evidence)["display_eligible"]
    assert discovered_video(POINT, resource, evidence)
    evidence[0]["id"] = "changed_extractor_hash"
    assert not assess_mooc_relevance(POINT, resource, evidence)["display_eligible"]


@pytest.mark.parametrize("damage", ["chapter_text", "chapter_hash", "chapter_binding", "aggregate_hash", "aggregate_text", "duplicate_id", "page_title_hash", "type_search_only", "stale_resource", "stale_catalog", "no_timestamp", "future_timestamp", "unsupported_route", "partial_catalog", "foreign_resolved"])
def test_invalid_observations_never_enter_shared_library(library, damage):
    resource, evidence = observed()
    chapter = resource["chapters"][0]
    row = next(row for row in evidence if row["evidence_id"] == chapter["evidence_id"])
    aggregate = next(row for row in evidence if row.get("field") == "chapters")
    if damage == "chapter_text": row["text"] += "private"
    elif damage == "chapter_hash": row["id"] = "ev_wrong"
    elif damage == "chapter_binding": chapter["evidence_id"] = "missing"
    elif damage == "aggregate_hash": aggregate["id"] = "ev_wrong"
    elif damage == "aggregate_text": aggregate["text"] += "other course"
    elif damage == "duplicate_id": evidence.append(dict(row))
    elif damage == "page_title_hash": resource["title"] = "Python modified title"
    elif damage == "type_search_only": resource["field_provenance"]["resource_type"]["source"] = "url_pattern"
    elif damage == "stale_resource": resource["cache"] = {"stale": True}
    elif damage == "stale_catalog": aggregate["cache"] = {"stale": True}
    elif damage == "no_timestamp": resource["fetched_at"] = None
    elif damage == "future_timestamp": resource["fetched_at"] = datetime.fromtimestamp(NOW + 100, timezone.utc).isoformat()
    elif damage == "unsupported_route": resource["url"] = URL.replace("/course/", "/learn/")
    elif damage == "partial_catalog": resource["catalog_fetch_status"] = "catalog_limit_exceeded"
    elif damage == "foreign_resolved": resource["resolved_url"] = URL.replace("123", "999")
    assert not library.observe(resource, evidence, PROFILE)
    assert library.stats()["total"] == 0


def test_library_receipt_alone_never_admits_a_probe(library):
    assert library.observe(*observed(), PROFILE)
    hit = library.lookup(POINT, PROFILE)[0]
    resource, evidence = hit["resource"], hit["evidence"]
    resource.update(chapters=[], fetch_status="not_fetched", metadata_evidence_level="search")
    # Even an internally consistent receipt has no useful authority without
    # its complete own-page outline. No search evidence is manufactured.
    resource["course_library"]["content_sha256"] = module.content_digest(resource, evidence)
    receipt = evidence[-1]
    receipt.update(resource["course_library"])
    receipt["id"] = "library_" + module._hash(resource["course_library"])
    assessment = assess_mooc_relevance(POINT, resource, evidence)
    assert not assessment["display_eligible"] and not assessment["probe_eligible"]
    assert discovered_video(POINT, resource, evidence) is None


def test_expiry_and_policy_changes_never_refresh_or_reuse(library, monkeypatch):
    assert library.observe(*observed(), PROFILE)
    before = dict(library.store.connection.execute("SELECT * FROM shared_mooc_courses").fetchone())
    assert not library.lookup(POINT, {**PROFILE, "page_fetch": False})
    for _ in range(3):
        assert library.lookup(POINT, PROFILE)
    after = dict(library.store.connection.execute("SELECT * FROM shared_mooc_courses").fetchone())
    assert before == after
    hit = library.lookup(POINT, PROFILE)[0]
    monkeypatch.setattr(module, "time", SimpleNamespace(time=lambda: before["expires"] + 1))
    assert not library.lookup(POINT, PROFILE)
    assert not library.observe(*observed(), PROFILE)
    assert not assess_mooc_relevance(POINT, hit["resource"], hit["evidence"])["display_eligible"]
    assert library.stats() == {"total": 1, "fresh": 0, "expired": 1, "revoked": 0}


@pytest.mark.parametrize("status", ["not_found", "access_denied", "login_required", "captcha", "site_policy_restricted", "site_policy_blocked", "policy_unreviewed", "robots_blocked", "rate_limited"])
def test_new_unavailable_observation_revokes_and_old_replay_cannot_resurrect(library, status):
    original = observed()
    assert library.observe(*original, PROFILE)
    failure = {"url": URL, "fetch_status": status, "fetched_at": datetime.fromtimestamp(NOW - 5, timezone.utc).isoformat()}
    assert not library.observe(failure, [], PROFILE)
    assert not library.lookup(POINT, PROFILE)
    assert library.stats()["revoked"] == 1
    assert not library.observe(*original, PROFILE)
    assert not library.lookup(POINT, PROFILE)
    assert library.observe(*observed(timestamp=NOW - 1), PROFILE)
    assert library.lookup(POINT, PROFILE)


def test_pre_http_policy_block_revokes_without_a_fetched_timestamp(library):
    assert library.observe(*observed(), PROFILE)
    assert not library.observe({"url": URL, "fetch_status": "site_policy_restricted"}, [], PROFILE)
    assert library.stats()["revoked"] == 1 and not library.lookup(POINT, PROFILE)


def test_course_and_term_identity_preserved_and_no_tracking_rewrites():
    assert course_entry_key(URL) == course_entry_key(URL + "/")
    assert course_entry_key(URL) == course_entry_key(URL.replace("www.", ""))
    assert course_entry_key(URL + "?tid=123") != course_entry_key(URL + "?tid=456")
    assert course_entry_key(URL + "?tid=123") != course_entry_key(URL)
    assert course_entry_key(URL + "?outVendor=search") == course_entry_key(URL)
    assert course_entry_key(URL.replace("OWN-", "OTHER-")) == course_entry_key(URL)
    assert course_entry_key("https://www.icourse163.org/course/detail.htm?cid=123") == course_entry_key(URL)
    assert course_entry_key("https://www.icourse163.org/course/detail.htm?cid=123&tid=456") == course_entry_key(URL + "?tid=456")
    assert course_entry_key(URL + "?unknown=search") is None


@pytest.mark.parametrize("alias", [URL + "?outVendor=search", URL.replace("OWN-", "OTHER-"),
    "https://www.icourse163.org/course/detail.htm?cid=123"])
def test_alias_keys_do_not_allow_relabeling_another_urls_page_evidence(library, alias):
    resource, evidence = observed()
    resource.update(url=alias, canonical_url=alias)
    assert course_entry_key(alias) == course_entry_key(URL)
    assert not library.observe(resource, evidence, PROFILE)
    assert library.stats()["total"] == 0
    # Fresh, independently extracted evidence for this alias is admissible.
    assert library.observe(*observed(url=alias), PROFILE)
    hit = library.lookup(POINT, PROFILE)[0]
    assert hit["resource"]["url"] == hit["resource"]["canonical_url"] == alias
    assert {row["url"] for row in hit["evidence"]} == {alias}
    assert {row["source_url"] for row in hit["assessment"]["matched_chapters"]} == {alias}


@pytest.mark.parametrize("alias", [URL + "?outVendor=search", URL.replace("OWN-", "OTHER-"),
    "https://www.icourse163.org/course/detail.htm?cid=123"])
def test_newer_independent_alias_replaces_entry_without_renewing_old_receipts(library, alias):
    first = observed(timestamp=NOW - 20)
    assert library.observe(*first, PROFILE)
    old_hit = library.lookup(POINT, PROFILE)[0]
    assert library.is_current(old_hit["resource"], PROFILE)
    second = observed(url=alias, chapters=("列表", "字典", "异常处理"), timestamp=NOW - 5)
    assert library.observe(*second, PROFILE)
    assert library.stats() == {"total": 1, "fresh": 1, "expired": 0, "revoked": 0}
    assert not library.is_current(old_hit["resource"], PROFILE)
    current = library.lookup(POINT, PROFILE)[0]
    assert library.is_current(current["resource"], PROFILE)
    assert current["resource"]["url"] == alias
    assert current["observed_at"] == NOW - 5
    assert current["expires_at"] == NOW - 5 + library.ttl_seconds
    assert {row["url"] for row in current["evidence"]} == {alias}
    assert not library.observe(*first, PROFILE)
    assert library.lookup(POINT, PROFILE)[0]["observed_at"] == NOW - 5


def test_term_dedup_keeps_newest_source_without_coalescing_different_terms(library):
    assert library.observe(*observed(url=URL), PROFILE)
    assert library.observe(*observed(url=URL + "/", timestamp=NOW - 9), PROFILE)
    assert library.observe(*observed(url=URL + "?tid=456", timestamp=NOW - 8), PROFILE)
    assert library.stats()["total"] == 2
    assert len(library.lookup(POINT, PROFILE, limit=5)) == 2


def test_lookup_work_is_bounded_and_sql_query_is_not_interpolated(library, monkeypatch):
    library.max_candidates = 2
    for index in range(5):
        assert library.observe(*observed(url=URL.replace("123", str(123 + index))), PROFILE)
    calls = []
    from backend.app import mooc_relevance
    real = mooc_relevance.assess_mooc_relevance
    monkeypatch.setattr(mooc_relevance, "assess_mooc_relevance", lambda *args: calls.append(args) or real(*args))
    assert len(library.lookup(POINT, PROFILE, limit=10)) == 2
    assert len(calls) == 2
    assert not library.lookup({"knowledge_point_id": "x", "text": "'); DROP TABLE shared_mooc_courses; --"}, PROFILE)
    assert library.stats()["total"] == 5


def test_tampered_stored_outline_is_revalidated_before_reuse(library):
    assert library.observe(*observed(), PROFILE)
    row = library.store.connection.execute("SELECT entry_key,data FROM shared_mooc_courses").fetchone()
    value = json.loads(row["data"])
    value["resource"]["chapters"][0]["title"] = "Python all topics"
    library.store.connection.execute("UPDATE shared_mooc_courses SET data=? WHERE entry_key=?", (json.dumps(value), row["entry_key"]))
    assert not library.lookup(POINT, PROFILE)


def test_constructor_adds_only_separate_tables_and_never_imports_history():
    store = Store(":memory:")
    before = {row[0]: row[1] for row in store.connection.execute("SELECT name,sql FROM sqlite_master WHERE type='table'")}
    library = CourseLibrary(store)
    after = {row[0]: row[1] for row in store.connection.execute("SELECT name,sql FROM sqlite_master WHERE type='table'")}
    assert all(after[key] == value for key, value in before.items())
    assert set(after) - set(before) == {"shared_mooc_courses", "shared_mooc_terms"}
    assert library.stats()["total"] == 0
    store.connection.close()


def test_current_receipt_check_is_read_only_and_accepts_job_id_remapping(library):
    assert library.observe(*observed(), PROFILE)
    resource = library.lookup(POINT, PROFILE)[0]["resource"]
    resource["resource_id"] = "another_job_id"
    for provenance in resource["field_provenance"].values():
        provenance["evidence_id"] = "job_" + provenance["evidence_id"]
    for chapter in resource["chapters"]:
        chapter["evidence_id"] = "job_" + chapter["evidence_id"]
    resource["cache"] = {"hit": True, "stale": False}
    before = dict(library.store.connection.execute("SELECT * FROM shared_mooc_courses").fetchone())
    copy = deepcopy(resource)
    assert library.is_current(resource, PROFILE)
    assert library.is_current(resource, PROFILE)
    assert resource == copy
    assert dict(library.store.connection.execute("SELECT * FROM shared_mooc_courses").fetchone()) == before


@pytest.mark.parametrize("change", ["profile", "revoked", "new_observation", "new_content", "expires", "altered_resource", "altered_receipt", "altered_stored_evidence", "missing_entry"])
def test_previously_seeded_receipt_cannot_survive_policy_or_observation_changes(library, monkeypatch, change):
    assert library.observe(*observed(), PROFILE)
    resource = library.lookup(POINT, PROFILE)[0]["resource"]
    profile = PROFILE
    if change == "profile": profile = {**PROFILE, "page_fetch": False}
    elif change == "revoked":
        assert not library.observe({"url": URL, "fetch_status": "not_found",
            "fetched_at": datetime.fromtimestamp(NOW - 1, timezone.utc).isoformat()}, [], PROFILE)
    elif change == "new_observation": assert library.observe(*observed(timestamp=NOW - 1), PROFILE)
    elif change == "new_content": assert library.observe(*observed(chapters=("异常处理",), timestamp=NOW - 1), PROFILE)
    elif change == "expires":
        monkeypatch.setattr(module, "time", SimpleNamespace(time=lambda: resource["course_library"]["expires_at"]))
    elif change == "altered_resource": resource["title"] = "Python changed page"
    elif change == "altered_receipt": resource["course_library"]["observed_at"] += 1
    elif change == "altered_stored_evidence":
        value = json.loads(library.store.connection.execute("SELECT data FROM shared_mooc_courses").fetchone()[0])
        value["evidence"][0]["id"] = "ev_altered"
        library.store.connection.execute("UPDATE shared_mooc_courses SET data=?", (json.dumps(value),))
    elif change == "missing_entry": library.store.connection.execute("DELETE FROM shared_mooc_courses")
    assert not library.is_current(resource, profile)


def test_shorter_runtime_ttl_applies_to_existing_entries_without_extending_longer_ttl(library, monkeypatch):
    assert library.observe(*observed(timestamp=NOW - 100), PROFILE)
    resource = library.lookup(POINT, PROFILE)[0]["resource"]
    shorter = CourseLibrary(library.store, ttl_seconds=60)
    assert not shorter.lookup(POINT, PROFILE)
    assert not shorter.is_current(resource, PROFILE)
    assert shorter.stats() == {"total": 1, "fresh": 0, "expired": 1, "revoked": 0}
    longer = CourseLibrary(library.store, ttl_seconds=30 * 86400)
    assert longer.is_current(resource, PROFILE)
    monkeypatch.setattr(module, "time", SimpleNamespace(time=lambda: resource["course_library"]["expires_at"]))
    assert not longer.is_current(resource, PROFILE)
    assert not longer.lookup(POINT, PROFILE)
