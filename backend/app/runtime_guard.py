"""One application worker may own a file-backed SQLite queue at a time.

Keep the adjacent lock file after unlock: unlinking it could allow a different
inode to be locked concurrently. This guard contains no identity or credential.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def database_owner(path: str):
    if path == ":memory:":
        yield
        return
    database = Path(path).resolve()
    database.parent.mkdir(parents=True, exist_ok=True)
    handle = database.with_name(database.name + ".app.lock").open("a+b")
    locked = False
    try:
        if os.name == "nt":
            import msvcrt
            if os.fstat(handle.fileno()).st_size == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise RuntimeError("Database already owned by another application worker; run one worker per database.") from None
        else:
            import fcntl
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise RuntimeError("Database already owned by another application worker; run one worker per database.") from None
        locked = True
        yield
    finally:
        try:
            if locked:
                if os.name == "nt":
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
