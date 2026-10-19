"""Verify additive project schema against a backup of an existing SQLite DB.

The source is opened read-only. Only the output copy receives schema changes.
Original table schemas and complete row digests must match before/after.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.db import Store
from backend.app.project_db import ProjectStore
from backend.app.models import now


def table_fingerprints(connection, names=None):
    schema = dict(connection.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"))
    result = {}
    for name in names or sorted(schema):
        quoted = '"' + name.replace('"', '""') + '"'
        rows = [json.dumps(list(row), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                for row in connection.execute(f"SELECT * FROM {quoted}")]
        result[name] = {"schema": schema[name], "rows": len(rows),
                        "rows_sha256": hashlib.sha256("\n".join(sorted(rows)).encode()).hexdigest()}
    return result


def verify(source: Path, output: Path):
    output.mkdir(parents=True, exist_ok=True)
    database = output / "migrated-copy.sqlite3"
    if database.exists():
        raise RuntimeError("Refusing to replace an existing migration snapshot")
    reader = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
    target = sqlite3.connect(database)
    try:
        reader.backup(target)
        before = table_fingerprints(target)
    finally:
        target.close()
        reader.close()
    store = Store(str(database))
    ProjectStore(store)
    after = table_fingerprints(store.connection, before)
    integrity = store.connection.execute("PRAGMA integrity_check").fetchone()[0]
    foreign_keys = [list(row) for row in store.connection.execute("PRAGMA foreign_key_check")]
    new_tables = sorted(set(table_fingerprints(store.connection)) - before.keys())
    store.close()
    report = {"checked_at": now(), "source_read_only": True, "source": str(source.resolve()),
              "copy": str(database.resolve()), "original_tables_unchanged": before == after,
              "integrity_check": integrity, "foreign_key_errors": foreign_keys,
              "before": before, "after": after, "new_tables": new_tables}
    (output / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if before != after or integrity != "ok" or foreign_keys:
        raise RuntimeError("Migration verification failed; inspect verification.json")
    print(json.dumps({"original_tables_unchanged": True, "original_table_count": len(before),
                      "new_tables": new_tables, "integrity_check": integrity}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "data/discovery.sqlite3")
    parser.add_argument("--output", type=Path, default=ROOT / "reports/project-analysis-v1-20261017/migration")
    args = parser.parse_args()
    verify(args.source, args.output)
