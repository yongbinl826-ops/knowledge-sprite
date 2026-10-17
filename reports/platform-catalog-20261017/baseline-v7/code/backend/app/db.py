from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from .models import now


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class Store:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, status TEXT NOT NULL, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS knowledge_points(id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id), text TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS resources(id TEXT NOT NULL, job_id TEXT NOT NULL REFERENCES jobs(id), canonical_url TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(job_id,id), UNIQUE(job_id,canonical_url));
            CREATE TABLE IF NOT EXISTS matches(job_id TEXT NOT NULL REFERENCES jobs(id), knowledge_point_id TEXT NOT NULL REFERENCES knowledge_points(id), resource_id TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(job_id,knowledge_point_id,resource_id));
            CREATE TABLE IF NOT EXISTS evidence(id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id), resource_id TEXT NOT NULL, knowledge_point_id TEXT, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS search_attempts(id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL REFERENCES jobs(id), data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS cache(key TEXT PRIMARY KEY, kind TEXT NOT NULL, created REAL NOT NULL, expires REAL NOT NULL, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS idempotency_keys(key TEXT PRIMARY KEY, request_hash TEXT NOT NULL, job_id TEXT NOT NULL REFERENCES jobs(id));
            CREATE INDEX IF NOT EXISTS evidence_job_resource ON evidence(job_id,resource_id);
            CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status);
        """)
        self.connection.commit()

    def recover(self):
        for row in self.connection.execute("SELECT data FROM jobs WHERE status IN ('queued','running')").fetchall():
            job = json.loads(row["data"])
            job.update(status="interrupted", phase="done", updated_at=now())
            job["warnings"].append("进程已重启，任务被中断；可重新提交相同知识点")
            self.save_job(job)

    def save_job(self, job: dict):
        self.connection.execute("INSERT INTO jobs VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,data=excluded.data", (job["job_id"], job["status"], dumps(job)))
        self.connection.commit()

    def create_job(self, job: dict, idempotency_key: str | None = None, request_hash: str | None = None):
        # The queue must never see a job without all of its knowledge-point rows.
        with self.connection:
            self.connection.execute("INSERT INTO jobs VALUES(?,?,?)", (job["job_id"], job["status"], dumps(job)))
            self.connection.executemany("INSERT INTO knowledge_points VALUES(?,?,?)", [
                (point["knowledge_point_id"], job["job_id"], point["text"]) for point in job["knowledge_points"]])
            if idempotency_key:
                self.connection.execute("INSERT INTO idempotency_keys VALUES(?,?,?)", (idempotency_key, request_hash, job["job_id"]))

    def idempotent_request(self, key: str) -> dict | None:
        row = self.connection.execute("SELECT request_hash,job_id FROM idempotency_keys WHERE key=?", (key,)).fetchone()
        return dict(row) if row else None

    def bind_idempotency_key(self, key: str, request_hash: str, job_id: str):
        with self.connection:
            self.connection.execute("INSERT INTO idempotency_keys VALUES(?,?,?)", (key, request_hash, job_id))

    def active_job_for_request(self, request: dict) -> dict | None:
        # Creation and lookup are synchronous on the single application event loop.
        # Terminal jobs intentionally do not participate in request coalescing.
        for row in self.connection.execute("SELECT data FROM jobs WHERE status IN ('queued','running')"):
            job = json.loads(row["data"])
            if job.get("request") == request:
                return job
        return None

    def get_job(self, job_id: str) -> dict | None:
        row = self.connection.execute("SELECT data FROM jobs WHERE id=?", (job_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def job_counts(self) -> dict:
        return {row["status"]: row["n"] for row in self.connection.execute("SELECT status,COUNT(*) AS n FROM jobs GROUP BY status")}

    def oldest_queued_at(self) -> str | None:
        row = self.connection.execute("SELECT MIN(json_extract(data,'$.created_at')) FROM jobs WHERE status='queued'").fetchone()
        return row[0] if row else None

    def add_point(self, job_id: str, point: dict):
        self.connection.execute("INSERT INTO knowledge_points VALUES(?,?,?)", (point["knowledge_point_id"], job_id, point["text"]))
        self.connection.commit()

    def save_resource(self, job_id: str, resource: dict):
        self.connection.execute("INSERT INTO resources VALUES(?,?,?,?) ON CONFLICT(job_id,id) DO UPDATE SET data=excluded.data", (resource["resource_id"], job_id, resource["canonical_url"], dumps(resource)))
        self.connection.commit()

    def resources(self, job_id: str) -> dict[str, dict]:
        return {r["id"]: json.loads(r["data"]) for r in self.connection.execute("SELECT id,data FROM resources WHERE job_id=?", (job_id,))}

    def save_match(self, job_id: str, match: dict):
        self.connection.execute("INSERT INTO matches VALUES(?,?,?,?) ON CONFLICT(job_id,knowledge_point_id,resource_id) DO UPDATE SET data=excluded.data", (job_id, match["knowledge_point_id"], match["resource_id"], dumps(match)))
        self.connection.commit()

    def matches(self, job_id: str) -> list[dict]:
        return [json.loads(r[0]) for r in self.connection.execute("SELECT data FROM matches WHERE job_id=?", (job_id,))]

    def delete_match(self, job_id: str, point_id: str, resource_id: str):
        self.connection.execute("DELETE FROM matches WHERE job_id=? AND knowledge_point_id=? AND resource_id=?", (job_id, point_id, resource_id))
        self.connection.commit()

    def add_evidence(self, job_id: str, resource_id: str, point_id: str | None, evidence: dict):
        self.connection.execute("INSERT OR IGNORE INTO evidence VALUES(?,?,?,?,?)", (evidence["evidence_id"], job_id, resource_id, point_id, dumps(evidence)))
        self.connection.commit()

    def evidence(self, job_id: str, resource_id: str, point_id: str | None = None) -> list[dict]:
        rows = self.connection.execute("SELECT data FROM evidence WHERE job_id=? AND resource_id=? AND (knowledge_point_id=? OR knowledge_point_id IS NULL)", (job_id, resource_id, point_id)) if point_id else self.connection.execute("SELECT data FROM evidence WHERE job_id=? AND resource_id=?", (job_id, resource_id))
        return [json.loads(r[0]) for r in rows]

    def add_attempt(self, job_id: str, attempt: dict):
        self.connection.execute("INSERT INTO search_attempts(job_id,data) VALUES(?,?)", (job_id, dumps(attempt)))
        self.connection.commit()

    def attempts(self, job_id: str) -> list[dict]:
        return [json.loads(r[0]) for r in self.connection.execute("SELECT data FROM search_attempts WHERE job_id=? ORDER BY id", (job_id,))]

    @staticmethod
    def cache_key(kind: str, fields: dict) -> str:
        return hashlib.sha256((kind + json.dumps(fields, sort_keys=True, ensure_ascii=False)).encode()).hexdigest()

    def cache_get(self, key: str, allow_stale: bool = False) -> dict | None:
        row = self.connection.execute("SELECT * FROM cache WHERE key=?", (key,)).fetchone()
        if not row:
            return None
        stale = row["expires"] <= time.time()
        if stale and not allow_stale:
            return None
        from datetime import datetime, timezone
        return {"data": json.loads(row["data"]), "cache": {"hit": True, "stale": stale, "cached_at": datetime.fromtimestamp(row["created"], timezone.utc).isoformat()}}

    def cache_set(self, key: str, kind: str, data, ttl: int):
        stamp = time.time()
        self.connection.execute("INSERT OR REPLACE INTO cache VALUES(?,?,?,?,?)", (key, kind, stamp, stamp + ttl, dumps(data)))
        self.connection.commit()

    def close(self):
        self.connection.close()
