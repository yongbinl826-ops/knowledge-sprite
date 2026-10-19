"""A current page-cache replay may revalidate policy, never renew evidence."""
from copy import deepcopy
import json

import pytest

from backend.app.course_library import content_digest, course_entry_key, profile_digest
from test_course_library import library, observed, NOW, POINT, PROFILE, URL


CURRENT = {**PROFILE, "matching_rules": 4}


def stored(library):
    return dict(library.store.connection.execute("SELECT * FROM shared_mooc_courses").fetchone())


@pytest.mark.parametrize("ttl", [60, 604800, 2 * 604800])
def test_explicit_current_cache_revalidation_changes_profile_but_never_observation_age(library, ttl):
    resource, evidence = observed()
    assert library.observe(resource, evidence, PROFILE)
    before = stored(library)
    library.ttl_seconds = ttl
    assert not library.lookup(POINT, CURRENT)
    assert library.observe(resource, evidence, CURRENT, current_page_cache=True)
    after = stored(library)
    assert after["entry_key"] == before["entry_key"] == course_entry_key(URL)
    assert after["observed"] == before["observed"] == NOW - 10
    assert after["expires"] == min(before["expires"], before["observed"] + ttl)
    assert after["profile"] == profile_digest(CURRENT) and after["status"] == "verified"
    assert after["data"] == before["data"]
    hit, = library.lookup(POINT, CURRENT)
    assert hit["assessment"]["status"] == "outline_supported"
    assert hit["observed_at"] == before["observed"] and hit["expires_at"] == after["expires"]
    assert not library.lookup(POINT, PROFILE)
    assert not library.observe(resource, evidence, CURRENT, current_page_cache=True)
    assert stored(library) == after


def test_cache_revalidation_accepts_job_id_remapping_without_merging_or_copying_search_evidence(library):
    resource, evidence = observed()
    assert library.observe(resource, evidence, PROFILE)
    original = deepcopy((resource, evidence))
    mapping = {row["evidence_id"]: "new_job_" + str(index) for index, row in enumerate(evidence)}
    for row in evidence:
        row["evidence_id"] = mapping[row["evidence_id"]]
    for origin in resource["field_provenance"].values():
        origin["evidence_id"] = mapping[origin["evidence_id"]]
    for chapter in resource["chapters"]:
        chapter["evidence_id"] = mapping[chapter["evidence_id"]]
    resource["resource_id"] = "new_job_resource"
    resource["cache"] = {"hit": True, "stale": False}
    evidence.append({"kind": "search", "evidence_id": "private-search", "query": "private user project"})
    assert content_digest(resource, evidence) == content_digest(*original)
    assert library.observe(resource, evidence, CURRENT, current_page_cache=True)
    assert "private user project" not in stored(library)["data"]
    hit, = library.lookup(POINT, CURRENT)
    assert hit["assessment"]["display_eligible"]
    assert not any(row["kind"] == "search" for row in hit["evidence"])


@pytest.mark.parametrize("damage", [
    "no_opt_in", "false_opt_in", "truthy_not_true", "same_profile", "old_revoked", "new_revoked",
    "older_observation", "different_valid_content", "different_alias", "old_invalid_json",
    "old_tampered_chapter", "old_unbound_optional_field", "new_tampered_chapter",
    "new_unbound_optional_field", "old_expired", "new_stale", "evidence_stale", "shorter_elapsed_ttl",
])
def test_only_identical_fresh_verified_source_facts_may_cross_profile(library, damage):
    resource, evidence = observed()
    assert library.observe(resource, evidence, PROFILE)
    profile, options = CURRENT, {"current_page_cache": True}
    connection = library.store.connection
    if damage == "no_opt_in": options = {}
    elif damage == "false_opt_in": options = {"current_page_cache": False}
    elif damage == "truthy_not_true": options = {"current_page_cache": "true"}
    elif damage == "same_profile": profile = PROFILE
    elif damage == "old_revoked": connection.execute("UPDATE shared_mooc_courses SET status='revoked'")
    elif damage == "new_revoked": resource["fetch_status"] = "not_found"
    elif damage == "older_observation": resource, evidence = observed(timestamp=NOW - 11)
    elif damage == "different_valid_content": resource, evidence = observed(chapters=("列表", "字典", "异步协程"))
    elif damage == "different_alias": resource, evidence = observed(url=URL.replace("OWN-", "OTHER-"))
    elif damage == "old_invalid_json": connection.execute("UPDATE shared_mooc_courses SET data='not json'")
    elif damage in {"old_tampered_chapter", "old_unbound_optional_field"}:
        payload = json.loads(stored(library)["data"])
        if damage == "old_tampered_chapter": payload["resource"]["chapters"][0]["title"] = "篡改章节"
        else: payload["resource"]["description"] = "Unbound altered description"
        connection.execute("UPDATE shared_mooc_courses SET data=?", (json.dumps(payload),))
    elif damage == "new_tampered_chapter": resource["chapters"][0]["title"] = "篡改章节"
    elif damage == "new_unbound_optional_field": resource["description"] = "Unbound altered description"
    elif damage == "old_expired": connection.execute("UPDATE shared_mooc_courses SET expires=?", (NOW - 1,))
    elif damage == "new_stale": resource["cache"] = {"hit": True, "stale": True}
    elif damage == "evidence_stale": evidence[0]["cache"] = {"hit": True, "stale": True}
    elif damage == "shorter_elapsed_ttl": library.ttl_seconds = 1
    connection.commit()
    before = stored(library)
    before_terms = list(connection.execute("SELECT * FROM shared_mooc_terms ORDER BY term,entry_key"))
    assert not library.observe(resource, evidence, profile, **options)
    assert stored(library) == before
    assert list(connection.execute("SELECT * FROM shared_mooc_terms ORDER BY term,entry_key")) == before_terms


def test_opt_in_does_not_change_normal_newer_observation_and_revocation_rules(library):
    assert library.observe(*observed(timestamp=NOW - 20), PROFILE)
    assert library.observe(*observed(chapters=("列表", "字典", "异常处理")), CURRENT, current_page_cache=True)
    updated = stored(library)
    assert updated["observed"] == NOW - 10 and updated["expires"] == NOW - 10 + library.ttl_seconds
    resource, evidence = observed(timestamp=NOW - 5)
    resource["fetch_status"] = "not_found"
    assert not library.observe(resource, evidence, CURRENT, current_page_cache=True)
    revoked = stored(library)
    assert revoked["status"] == "revoked" and revoked["observed"] == NOW - 5
    assert not library.observe(*observed(timestamp=NOW - 5), PROFILE, current_page_cache=True)
    assert stored(library) == revoked
