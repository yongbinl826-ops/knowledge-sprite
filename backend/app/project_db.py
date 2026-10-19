"""Additive, versioned project persistence on the existing SQLite connection."""
from __future__ import annotations

import json
from .db import Store, dumps
from .models import now


class ProjectStore:
    def __init__(self, store: Store):
        self.connection = store.connection
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS projects(
                id TEXT PRIMARY KEY, original_input TEXT NOT NULL, input TEXT NOT NULL,
                current_version INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS project_versions(
                project_id TEXT NOT NULL REFERENCES projects(id), version INTEGER NOT NULL,
                status TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(project_id,version));
            CREATE TABLE IF NOT EXISTS project_functions(
                project_id TEXT NOT NULL, version INTEGER NOT NULL, id TEXT NOT NULL, data TEXT NOT NULL,
                PRIMARY KEY(project_id,version,id), FOREIGN KEY(project_id,version) REFERENCES project_versions(project_id,version));
            CREATE TABLE IF NOT EXISTS project_knowledge_points(
                project_id TEXT NOT NULL, version INTEGER NOT NULL, id TEXT NOT NULL, data TEXT NOT NULL,
                PRIMARY KEY(project_id,version,id), FOREIGN KEY(project_id,version) REFERENCES project_versions(project_id,version));
            CREATE TABLE IF NOT EXISTS project_prerequisites(
                project_id TEXT NOT NULL, version INTEGER NOT NULL, point_id TEXT NOT NULL, prerequisite_id TEXT NOT NULL,
                PRIMARY KEY(project_id,version,point_id,prerequisite_id),
                FOREIGN KEY(project_id,version,point_id) REFERENCES project_knowledge_points(project_id,version,id),
                FOREIGN KEY(project_id,version,prerequisite_id) REFERENCES project_knowledge_points(project_id,version,id));
            CREATE TABLE IF NOT EXISTS project_batches(
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL, version INTEGER NOT NULL, ordinal INTEGER NOT NULL,
                status TEXT NOT NULL, job_id TEXT REFERENCES jobs(id), data TEXT NOT NULL,
                UNIQUE(project_id,version,ordinal), FOREIGN KEY(project_id,version) REFERENCES project_versions(project_id,version));
            CREATE TABLE IF NOT EXISTS project_point_job_mappings(
                project_id TEXT NOT NULL, version INTEGER NOT NULL, project_point_id TEXT NOT NULL,
                batch_id TEXT NOT NULL REFERENCES project_batches(id), job_id TEXT NOT NULL REFERENCES jobs(id),
                knowledge_point_id TEXT NOT NULL REFERENCES knowledge_points(id),
                PRIMARY KEY(project_id,version,project_point_id),
                FOREIGN KEY(project_id,version,project_point_id) REFERENCES project_knowledge_points(project_id,version,id));
            CREATE INDEX IF NOT EXISTS project_versions_status ON project_versions(status);
            CREATE INDEX IF NOT EXISTS project_batches_job ON project_batches(job_id);
        """)
        self.connection.commit()

    def create(self, project_id: str, input_data: dict):
        stamp = now()
        with self.connection:
            self.connection.execute("INSERT INTO projects VALUES(?,?,?,?,?,?)",
                (project_id, dumps(input_data), dumps(input_data), 0, stamp, stamp))

    def project(self, project_id: str) -> dict | None:
        row = self.connection.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if not row:
            return None
        return {"project_id": row["id"], "original_input": json.loads(row["original_input"]),
                "input": json.loads(row["input"]), "current_version": row["current_version"],
                "created_at": row["created_at"], "updated_at": row["updated_at"]}

    def list(self) -> list[dict]:
        return [{"project_id": row["id"], "name": json.loads(row["input"])["name"],
                 "current_version": row["current_version"], "created_at": row["created_at"], "updated_at": row["updated_at"]}
                for row in self.connection.execute("SELECT * FROM projects ORDER BY updated_at DESC LIMIT 100")]

    def version(self, project_id: str, version: int) -> dict | None:
        row = self.connection.execute("SELECT data FROM project_versions WHERE project_id=? AND version=?",
                                      (project_id, version)).fetchone()
        return json.loads(row[0]) if row else None

    def versions(self, project_id: str) -> list[dict]:
        return [{"version": data["version"], "status": data["status"], "created_at": data["created_at"],
                 "model": data.get("model"), "prompt_version": data.get("prompt_version")}
                for row in self.connection.execute("SELECT data FROM project_versions WHERE project_id=? ORDER BY version DESC", (project_id,))
                if (data := json.loads(row[0]))]

    def save(self, project_id: str, version: dict, *, new: bool = False):
        version["updated_at"] = now()
        with self.connection:
            if new:
                self.connection.execute("INSERT INTO project_versions VALUES(?,?,?,?)",
                    (project_id, version["version"], version["status"], dumps(version)))
                self.connection.execute("UPDATE projects SET current_version=?,input=?,updated_at=? WHERE id=?",
                    (version["version"], dumps(version["input"]), now(), project_id))
            else:
                self.connection.execute("UPDATE project_versions SET status=?,data=? WHERE project_id=? AND version=?",
                    (version["status"], dumps(version), project_id, version["version"]))
                self.connection.execute("UPDATE projects SET updated_at=? WHERE id=?", (now(), project_id))
            # A version's analysis is immutable once confirmed. Draft analysis is written once after AI completes.
            analysis = version.get("analysis")
            if analysis:
                self.connection.executemany("INSERT OR IGNORE INTO project_functions VALUES(?,?,?,?)", [
                    (project_id, version["version"], item["id"], dumps(item)) for item in analysis["functions"]])
                self.connection.executemany("INSERT OR IGNORE INTO project_knowledge_points VALUES(?,?,?,?)", [
                    (project_id, version["version"], item["id"], dumps(item)) for item in analysis["knowledge_points"]])
                self.connection.executemany("INSERT OR IGNORE INTO project_prerequisites VALUES(?,?,?,?)", [
                    (project_id, version["version"], item["id"], prerequisite)
                    for item in analysis["knowledge_points"] for prerequisite in item["prerequisite_ids"]])
            for batch in version.get("batches", []):
                self.connection.execute("INSERT INTO project_batches VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,job_id=excluded.job_id,data=excluded.data",
                    (batch["batch_id"], project_id, version["version"], batch["ordinal"], batch["status"], batch.get("job_id"), dumps(batch)))
                for mapping in batch.get("mappings", []):
                    self.connection.execute("INSERT OR IGNORE INTO project_point_job_mappings VALUES(?,?,?,?,?,?)",
                        (project_id, version["version"], mapping["project_knowledge_point_id"], batch["batch_id"], batch["job_id"], mapping["knowledge_point_id"]))

    def running(self) -> list[tuple[str, int]]:
        return [(row[0], row[1]) for row in self.connection.execute(
            "SELECT project_id,version FROM project_versions WHERE status='running'")]

    def recover_analysis(self):
        for row in self.connection.execute("SELECT project_id,data FROM project_versions WHERE status='analyzing'").fetchall():
            data = json.loads(row["data"])
            data.update(status="analysis_failed", error={"code": "interrupted", "message": "服务重启中断了分析，原始输入已保留，可重新分析。"})
            self.save(row["project_id"], data)
