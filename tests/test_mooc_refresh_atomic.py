"""Real SQLite connections compete for a lease; no network or production DB."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, closing
from threading import Barrier
from types import SimpleNamespace

import pytest

from backend.app import mooc_refresh as module
from backend.app.db import Store
from backend.app.mooc_refresh import MoocRefresh


@pytest.mark.parametrize("existing", [False, True])
def test_simultaneous_connections_grant_exactly_one_due_refresh(tmp_path, monkeypatch, existing):
    current = 1800000000.0
    monkeypatch.setattr(module, "time", SimpleNamespace(time=lambda: current))
    with ExitStack() as stack:
        stores = [stack.enter_context(closing(Store(str(tmp_path / "leases.sqlite3")))) for _ in range(8)]
        refreshers = [MoocRefresh(store) for store in stores]
        if existing:
            with stores[0].connection:
                stores[0].connection.execute("INSERT INTO mooc_refresh_state VALUES(?,?,?,?)",
                    ("topic", current - 86400, current - 300, 3))
        barrier = Barrier(len(stores))

        def claim(refresh):
            barrier.wait(timeout=5)
            return refresh.claim("topic")

        with ThreadPoolExecutor(max_workers=len(stores)) as pool:
            claims = list(pool.map(claim, refreshers))
        winners = [result for result in claims if result is not None]
        assert winners == [{"query_index": 4, "sequence": 3} if existing else
                           {"query_index": 1, "sequence": 0}]
        row = stores[0].connection.execute("SELECT * FROM mooc_refresh_state WHERE topic_key='topic'").fetchone()
        assert row["last_attempt"] == current
        assert row["last_success"] == (current - 86400 if existing else 0)
        assert all(refresh.claim("topic") is None for refresh in refreshers)


@pytest.mark.parametrize("last_success,last_attempt", [
    (1800000000.0 - 86399, 1800000000.0 - 300),
    (1800000000.0 - 86400, 1800000000.0 - 299),
])
def test_cadence_or_lease_still_blocks_all_independent_connections(tmp_path, monkeypatch, last_success, last_attempt):
    current = 1800000000.0
    monkeypatch.setattr(module, "time", SimpleNamespace(time=lambda: current))
    with closing(Store(str(tmp_path / "leases.sqlite3"))) as first, closing(Store(str(tmp_path / "leases.sqlite3"))) as second:
        refreshers = [MoocRefresh(first), MoocRefresh(second)]
        with first.connection:
            first.connection.execute("INSERT INTO mooc_refresh_state VALUES(?,?,?,?)",
                ("topic", last_success, last_attempt, 3))
        assert all(refresh.claim("topic") is None for refresh in refreshers)
        row = first.connection.execute("SELECT * FROM mooc_refresh_state WHERE topic_key='topic'").fetchone()
        assert row["last_attempt"] == last_attempt and row["last_success"] == last_success
