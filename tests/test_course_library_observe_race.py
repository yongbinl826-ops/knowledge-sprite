"""Normal new observations also preserve a concurrent, newer public record."""
from contextlib import ExitStack, closing
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from backend.app import course_library as module
from backend.app.course_library import CourseLibrary
from backend.app.db import Store
from test_course_library import NOW, PROFILE, URL, observed


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("concurrent_change", ["revoke", "newer_outline"])
def test_new_observation_cannot_overwrite_a_concurrent_newer_row_or_its_terms(
        tmp_path, monkeypatch, existing, concurrent_change):
    monkeypatch.setattr(module, "time", SimpleNamespace(time=lambda: NOW))
    with ExitStack() as stack:
        database = str(tmp_path / "normal-observation-race.sqlite3")
        first = CourseLibrary(stack.enter_context(closing(Store(database))))
        second = CourseLibrary(stack.enter_context(closing(Store(database))))
        if existing:
            assert first.observe(*observed(timestamp=NOW - 30), PROFILE)
        snapshot = module._snapshot
        concurrent_row, concurrent_terms = None, None

        def newer_commit(candidate, evidence):
            nonlocal concurrent_row, concurrent_terms
            if concurrent_row is None:
                concurrent_row = {}  # Do not recurse through the second writer.
                if concurrent_change == "revoke":
                    resource = {"url": URL, "fetch_status": "not_found",
                                "fetched_at": datetime.fromtimestamp(NOW - 10, timezone.utc).isoformat()}
                    assert not second.observe(resource, [], PROFILE)
                else:
                    assert second.observe(*observed(chapters=("列表", "字典", "异步协程"), timestamp=NOW - 10), PROFILE)
                concurrent_row = dict(second.store.connection.execute("SELECT * FROM shared_mooc_courses").fetchone())
                concurrent_terms = [tuple(row) for row in second.store.connection.execute(
                    "SELECT * FROM shared_mooc_terms ORDER BY term,entry_key")]
            return snapshot(candidate, evidence)

        monkeypatch.setattr(module, "_snapshot", newer_commit)
        assert not first.observe(*observed(timestamp=NOW - 20), PROFILE)
        assert dict(second.store.connection.execute("SELECT * FROM shared_mooc_courses").fetchone()) == concurrent_row
        assert [tuple(row) for row in second.store.connection.execute(
            "SELECT * FROM shared_mooc_terms ORDER BY term,entry_key")] == concurrent_terms
