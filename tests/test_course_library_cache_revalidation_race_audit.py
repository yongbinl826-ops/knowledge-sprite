"""A concurrent library writer must outrank an old page-cache replay."""
from contextlib import ExitStack, closing
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from backend.app import course_library as module
from backend.app.course_library import CourseLibrary
from backend.app.db import Store
from test_course_library import NOW, PROFILE, URL, observed


CURRENT = {**PROFILE, "matching_rules": 4}


@pytest.mark.parametrize("concurrent_change", ["revoke", "newer_outline"])
def test_cache_revalidation_preserves_a_concurrently_committed_newer_observation(
    tmp_path, monkeypatch, concurrent_change
):
    monkeypatch.setattr(module, "time", SimpleNamespace(time=lambda: NOW))
    database = str(tmp_path / "shared.sqlite3")
    with ExitStack() as stack:
        first = CourseLibrary(stack.enter_context(closing(Store(database))))
        second = CourseLibrary(stack.enter_context(closing(Store(database))))
        resource, evidence = observed()
        assert first.observe(resource, evidence, PROFILE)
        snapshot = module._snapshot
        concurrent_row = None
        concurrent_terms = None

        def commit_after_revalidation_reads_old_row(candidate, records):
            nonlocal concurrent_row, concurrent_terms
            if concurrent_row is None:
                # The second real connection commits between the first
                # connection's read and write. Set a sentinel before the
                # second valid observation invokes the same extractor check.
                concurrent_row = {}
                if concurrent_change == "revoke":
                    failure = {"url": URL, "fetch_status": "not_found",
                        "fetched_at": datetime.fromtimestamp(NOW - 5, timezone.utc).isoformat()}
                    assert not second.observe(failure, [], CURRENT)
                else:
                    assert second.observe(*observed(
                        chapters=("列表", "字典", "异步协程"), timestamp=NOW - 5), CURRENT)
                concurrent_row = dict(second.store.connection.execute(
                    "SELECT * FROM shared_mooc_courses").fetchone())
                concurrent_terms = [tuple(row) for row in second.store.connection.execute(
                    "SELECT * FROM shared_mooc_terms ORDER BY term,entry_key")]
            return snapshot(candidate, records)

        monkeypatch.setattr(module, "_snapshot", commit_after_revalidation_reads_old_row)
        saved = first.observe(resource, evidence, CURRENT, current_page_cache=True)
        actual = dict(second.store.connection.execute("SELECT * FROM shared_mooc_courses").fetchone())
        actual_terms = [tuple(row) for row in second.store.connection.execute(
            "SELECT * FROM shared_mooc_terms ORDER BY term,entry_key")]
        assert actual == concurrent_row
        assert actual_terms == concurrent_terms
        assert not saved
