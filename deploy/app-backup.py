"""Read-only SQLite source snapshots; restore/migrate only to new files.

No Store is opened against the source. No job service or provider is started.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
from uuid import uuid4

DATA_ROOT = Path("/var/lib/knowledge-sprite")
BACKUP_ROOT = Path("/var/backups/knowledge-sprite")


def safe_file(root: Path, name: str, *, existing=False) -> Path:
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,120}\.sqlite3", name) or ".." in name:
        raise ValueError("invalid_database_filename")
    parent = root.resolve(strict=True)
    path = parent / name
    if path.is_symlink() or path.resolve().parent != parent or (existing and not path.is_file()):
        raise ValueError("invalid_database_path")
    return path


def verify(path: Path) -> dict:
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)) as source:
        source.execute("PRAGMA query_only=ON")
        if source.execute("PRAGMA integrity_check").fetchall() != [("ok",)] or source.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("database_integrity_failed")
        tables = source.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchone()[0]
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"status": "ok", "file": path.name, "sha256": digest, "tables": tables}


def snapshot(source_path: Path, target_path: Path, *, timeout_seconds=30) -> dict:
    if source_path.resolve() == target_path.resolve() or not source_path.is_file() or source_path.is_symlink():
        raise ValueError("invalid_snapshot_source")
    # O_EXCL prevents replacement of an existing snapshot or symlink.
    descriptor = os.open(target_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    deadline = time.monotonic() + timeout_seconds
    def progress(_status, _remaining, _total):
        if time.monotonic() >= deadline:
            raise TimeoutError("backup_deadline_exceeded")
    try:
        with closing(sqlite3.connect(source_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)) as source, \
             closing(sqlite3.connect(target_path, timeout=5)) as destination:
            source.execute("PRAGMA query_only=ON")
            source.execute("BEGIN")
            source.backup(destination, pages=256, progress=progress, sleep=0.01)
        return verify(target_path)
    except BaseException:
        target_path.unlink(missing_ok=True)
        raise


def migrate_copy(source_path: Path, target_path: Path) -> dict:
    snapshot(source_path, target_path)
    # Additive schema rehearsal only, on the new copy; no worker/recovery or
    # model/search API is invoked. This does not promise a reversible migration.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from backend.app.db import Store
    from backend.app.project_db import ProjectStore
    store = Store(str(target_path))
    try:
        ProjectStore(store)
    finally:
        store.close()
    return verify(target_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["backup", "restore", "verify", "migrate-copy"])
    parser.add_argument("--database", default=Path(os.getenv("DATABASE_PATH", "discovery.sqlite3")).name)
    parser.add_argument("--snapshot")
    args = parser.parse_args()
    try:
        os.umask(0o077)
        if args.action in {"backup", "migrate-copy"}:
            source = safe_file(DATA_ROOT, args.database, existing=True)
            name = args.snapshot or "snapshot-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid4().hex[:8] + ".sqlite3"
            target = safe_file(BACKUP_ROOT, name)
            report = migrate_copy(source, target) if args.action == "migrate-copy" else snapshot(source, target)
        elif args.action == "restore":
            source = safe_file(BACKUP_ROOT, args.snapshot, existing=True)
            target = safe_file(DATA_ROOT, args.database)
            report = snapshot(source, target)
        else:
            report = verify(safe_file(BACKUP_ROOT, args.snapshot, existing=True))
        print(json.dumps(report, separators=(",", ":")))
        return 0
    except (OSError, ValueError, sqlite3.Error, TimeoutError):
        print(json.dumps({"status": "failed", "code": "database_operation_failed"}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
