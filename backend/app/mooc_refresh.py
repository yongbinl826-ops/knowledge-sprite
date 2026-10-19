"""Bounded, query-time refresh of satisfied MOOC topics; no background scheduler.

Only opaque topic/profile digests and timestamps are stored. A cache read or
failed request cannot pretend that a fresh discovery was completed.
"""
import hashlib
import json
import time


class MoocRefresh:
    def __init__(self, store, interval_seconds=86400):
        self.store = store
        self.interval_seconds = interval_seconds
        store.connection.execute("""CREATE TABLE IF NOT EXISTS mooc_refresh_state(
            topic_key TEXT PRIMARY KEY, last_success REAL NOT NULL,
            last_attempt REAL NOT NULL, sequence INTEGER NOT NULL)""")
        store.connection.commit()

    @staticmethod
    def topic_key(point, request, profile):
        value = {"text": " ".join(point["text"].casefold().split()),
                 "targets": sorted(point.get("learning_targets") or []),
                 "language": request.language, "version": request.technical_version,
                 "profile": profile}
        return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def claim(self, key):
        """At most one due probe per point, with a five-minute in-flight lease."""
        current = time.time()
        with self.store.connection:
            # The due check and lease write are a single SQLite statement.
            # A SELECT followed by UPDATE could grant the same lease to two
            # independent connections before either write became visible.
            rows = self.store.connection.execute("""INSERT INTO mooc_refresh_state VALUES(?,0,?,0)
                ON CONFLICT(topic_key) DO UPDATE SET last_attempt=excluded.last_attempt
                WHERE excluded.last_attempt - mooc_refresh_state.last_success >= ?
                  AND excluded.last_attempt - mooc_refresh_state.last_attempt >= 300
                RETURNING sequence""", (key, current, self.interval_seconds)).fetchall()
        if not rows:
            return None
        sequence = rows[0]["sequence"]
        # Alternate broad and specific course queries over subsequent updates.
        return {"query_index": 1 + sequence % 5, "sequence": sequence}

    def observed(self, key, attempt):
        if (attempt.get("status") != "completed" or not attempt.get("network_attempted")
                or attempt.get("cache_hit") or attempt.get("upstream_warnings")):
            return False
        current = time.time()
        with self.store.connection:
            self.store.connection.execute("""INSERT INTO mooc_refresh_state VALUES(?,?,?,1)
                ON CONFLICT(topic_key) DO UPDATE SET last_success=excluded.last_success,
                last_attempt=excluded.last_attempt,sequence=mooc_refresh_state.sequence+1""", (key, current, current))
        return True
