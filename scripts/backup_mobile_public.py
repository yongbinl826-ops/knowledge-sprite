"""Consistent, new-file-only backup of the dedicated public mobile database.

Does not accept, inspect, migrate, or export the legacy student database.
Not a user APP project export/import feature. Run with the service's filesystem
permissions; keep the returned database and marker together.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3

MARKER = b"knowledge-sprite-mobile-public-v1\n"
APPLICATION_ID = 1397772877
TABLES = {"mobile_metadata", "mobile_public_courses", "mobile_daily_budget"}
COLUMNS = {
    "mobile_metadata": ["schema_version"],
    "mobile_public_courses": ["course_id", "platform", "title", "observed", "expires", "data"],
    "mobile_daily_budget": ["day", "tasks", "analysis_calls", "model_calls", "search_requests", "detail_pages", "detail_http"],
}


def _plain(path: Path):
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise ValueError("Symlink paths are not supported")


def _check(connection):
    actual = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if actual != TABLES or connection.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
        raise ValueError("Not the dedicated public mobile schema")
    for table, columns in COLUMNS.items():
        if [row[1] for row in connection.execute(f"PRAGMA table_info({table})")] != columns:
            raise ValueError("Unexpected public mobile columns")
    if list(connection.execute("SELECT schema_version FROM mobile_metadata")) != [(1,)]:
        raise ValueError("Unsupported public mobile schema version")
    if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise ValueError("Public mobile database integrity check failed")


def backup_public(source: str | Path, destination: str | Path):
    source, destination = Path(source).absolute(), Path(destination).absolute()
    source_marker = source.with_name(source.name + ".mobile-public")
    destination_marker = destination.with_name(destination.name + ".mobile-public")
    for path in (source, source_marker, destination, destination_marker):
        _plain(path)
    if not source.is_file() or source.stat().st_nlink != 1 or not source_marker.is_file():
        raise ValueError("Source needs its dedicated public marker")
    if source_marker.stat().st_size != len(MARKER) or source_marker.read_bytes() != MARKER:
        raise ValueError("Unknown source; refusing to open it")
    if destination.exists() or destination_marker.exists():
        raise FileExistsError("Backup destination and marker must both be new")
    if not destination.parent.is_dir():
        raise ValueError("Backup parent directory must already exist")
    # mode=ro plus marker checks happen before any SQL opens the source.
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as reader:
        _check(reader)
        fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        # Failed backups intentionally remain unmarked and cannot be mistaken
        # for a recoverable public store. Never delete or overwrite user paths.
        with closing(sqlite3.connect(destination)) as writer:
            reader.backup(writer)
            _check(writer)
        with destination_marker.open("xb") as stream:
            stream.write(MARKER)
            stream.flush()
            os.fsync(stream.fileno())
    return {"status": "backed_up", "source": str(source), "destination": str(destination),
            "marker": str(destination_marker), "schema_version": 1,
            "at": datetime.now(timezone.utc).isoformat(),
            "contains": ["verified_public_courses", "aggregate_daily_reservations"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--destination", required=True)
    args = parser.parse_args()
    print(json.dumps(backup_public(args.source, args.destination), ensure_ascii=False))


if __name__ == "__main__":
    main()
