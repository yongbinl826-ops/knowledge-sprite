"""Pure synthetic source-bound public metadata and aggregate-budget checks."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get("MOBILE_AUDIT_SOURCE_ROOT", ROOT)).resolve()
sys.path.insert(0, str(SOURCE))


@pytest.fixture
def modules():
    config = importlib.import_module("backend.app.config")
    public = importlib.import_module("backend.app.mobile_public")
    extractor = importlib.import_module("backend.app.extractor")
    assert Path(config.__file__).resolve().is_relative_to(SOURCE), "wrong/cached runtime imported"
    return config, public, extractor


@pytest.fixture
def own_video(modules):
    config, public, extractor = modules
    timestamp = datetime.now(timezone.utc).isoformat()
    url = "https://www.bilibili.com/video/BV1AAAAAAAAA/"
    state = {"videoData": {"bvid": "BV1AAAAAAAAA", "title": "Synthetic public Python list course",
        "desc": "A synthetic source fixture; no real course or playback is claimed.",
        "pic": "https://i0.hdslb.com/synthetic-public-image.jpg", "owner": {"name": "Synthetic author"},
        "pages": [{"page": 1, "part": "Python list indexing", "duration": 120, "cid": 123}]}}
    html = "<html><head></head><body><script>window.__INITIAL_STATE__=" + json.dumps(state) + ";</script></body></html>"
    parsed = extractor.MetadataExtractor().extract(html, url, timestamp)
    evidence = parsed.pop("evidence")
    resource = {**parsed, "url": url, "canonical_url": url, "resolved_url": url,
                "platform": "bilibili", "resource_id": "synthetic-private-resource-id"}
    now = datetime.now(timezone.utc).timestamp()
    assert public.public_course(resource, evidence, 3600, now), "real extractor fixture must be admitted first"
    return resource, evidence, now


def test_only_public_whitelist_survives_personal_extras(modules, own_video):
    _, public, _ = modules
    resource, evidence, now = own_video
    resource.update(project_context="PRIVATE_PROJECT_SENTINEL", query="PRIVATE_QUERY_SENTINEL",
                    selected_points=["PRIVATE_SELECTION_SENTINEL"], progress={"PRIVATE_PROGRESS_SENTINEL": 1},
                    job_id="PRIVATE_JOB_SENTINEL", title_from_client="PRIVATE_CLIENT_TITLE_SENTINEL")
    result = public.public_course(resource, evidence, 3600, now)
    assert set(result) <= {"course_id", "url", "title", "platform", "thumbnail_url", "author",
                           "resource_type", "observed_at", "expires_at", "access_notice"}
    assert "PRIVATE_" not in json.dumps(result)
    assert resource["resource_id"] not in json.dumps(result)


@pytest.mark.parametrize("mutation", ["search_title", "cross_url", "missing_page", "stale", "private_url", "changed_title"])
def test_public_store_rejects_unbound_or_stale_sources(modules, own_video, mutation):
    _, public, _ = modules
    resource, evidence, now = deepcopy(own_video)
    if mutation == "search_title":
        resource["field_provenance"]["title"]["source"] = "search"
    elif mutation == "cross_url":
        resource["field_provenance"]["title"]["url"] = "https://www.bilibili.com/video/BV1BBBBBBBBB/"
    elif mutation == "missing_page":
        evidence = [row for row in evidence if row.get("field") != "title"]
    elif mutation == "stale":
        resource["cache"] = {"stale": True}
    elif mutation == "private_url":
        resource["url"] = resource["canonical_url"] = "http://127.0.0.1/private"
    else:
        resource["title"] = "PRIVATE_CLIENT_TITLE_SENTINEL"
    assert public.public_course(resource, evidence, 3600, now) is None


def test_task_failure_cancellation_and_restart_cannot_refund_daily_reservation(modules, tmp_path):
    config, public, _ = modules
    settings = config.Settings(mobile_public_database_path=str(tmp_path / "public.sqlite3"), mobile_daily_tasks=2)
    current = datetime(2026, 10, 20, 23, 59, tzinfo=timezone.utc).timestamp()
    store = public.MobilePublicStore(settings, clock=lambda: current)
    costs = dict.fromkeys(public.COUNTERS, 0)
    costs.update(tasks=1, model_calls=2, search_requests=3)
    try:
        store.reserve(costs)
        before = [tuple(row) for row in store.connection.execute("SELECT * FROM mobile_daily_budget")]
    finally:
        store.close()
    store = public.MobilePublicStore(settings, clock=lambda: current)
    try:
        assert [tuple(row) for row in store.connection.execute("SELECT * FROM mobile_daily_budget")] == before
        store.reserve(costs)
        with pytest.raises(public.DailyBudgetFull):
            store.reserve(costs)
        row = store.connection.execute("SELECT * FROM mobile_daily_budget").fetchone()
        assert row["tasks"] == 2 and row["model_calls"] == 4 and row["search_requests"] == 6
        current += 120
        store.reserve(costs)
        assert len(store.connection.execute("SELECT * FROM mobile_daily_budget").fetchall()) == 2
    finally:
        store.close()


def test_existing_unknown_database_not_opened_or_migrated(modules, tmp_path):
    config, public, _ = modules
    target = tmp_path / "legacy.sqlite3"
    original = b"SYNTHETIC_LEGACY_TRAP_DO_NOT_OPEN"
    target.write_bytes(original)
    settings = config.Settings(mobile_public_database_path=str(target))
    with pytest.raises(ValueError, match="Not a dedicated"):
        public.MobilePublicStore(settings)
    assert target.read_bytes() == original
    assert not target.with_name(target.name + "-wal").exists()


def test_missing_budget_database_with_surviving_marker_fails_closed(modules, tmp_path):
    config, public, _ = modules
    target = tmp_path / "lost.sqlite3"
    settings = config.Settings(mobile_public_database_path=str(target))
    store = public.MobilePublicStore(settings)
    store.close()
    target.unlink()
    with pytest.raises(ValueError, match="refusing to reset"):
        public.MobilePublicStore(settings)


def test_own_mooc_curriculum_can_be_public_without_inventing_video_evidence(modules):
    _, public, extractor = modules
    url = "https://www.icourse163.org/course/OWN-123"
    now = datetime.now(timezone.utc).timestamp()
    term = {"id": "456", "outLineDto": {"outLine": "", "outLineStructureDtos": [
        {"name": "List indexing", "goals": "", "plan": ""},
        {"name": "Dictionary lookup", "goals": "", "plan": ""}]}}
    intro = "This synthetic public course introduction describes Python collection concepts and a separately observed public curriculum. It is not an assertion of video playback or student progress."
    html = '<div id="j-course-heading-intro"><div class="course-heading-intro_intro">' + intro + '</div></div><div id="j-rectxt">spContent=' + intro + '</div><div id="j-course-outline"></div><script>window.termDto=' + json.dumps(term) + ';window.courseDto=' + json.dumps({"id": "123", "name": "Synthetic Python collections course"}) + ';</script>'
    resource = extractor.MetadataExtractor().extract(html, url, datetime.fromtimestamp(now-1, timezone.utc).isoformat())
    evidence = resource.pop("evidence")
    resource.update(url=url, canonical_url=url, platform="icourse163")
    result = public.public_course(resource, evidence, 3600, now)
    assert result and result["resource_type"] == "course"
    assert result["title"] == "Synthetic Python collections course"
    assert resource.get("video_evidence_status") != "page_verified"
    assert "chapters" not in result and "coverage" not in result
