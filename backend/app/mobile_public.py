"""Separate anonymous aggregate/public persistence; never a personal Store."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from copy import deepcopy
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time

from .url_utils import normalize_url, safe_thumbnail_url

MARKER = b"knowledge-sprite-mobile-public-v1\n"
APPLICATION_ID = 1397772877
TABLES = {"mobile_metadata", "mobile_public_courses", "mobile_daily_budget"}
COUNTERS = ("tasks", "analysis_calls", "model_calls", "search_requests", "detail_pages", "detail_http")
SCHEMA_COLUMNS = {
    "mobile_metadata": ["schema_version"],
    "mobile_public_courses": ["course_id", "platform", "title", "observed", "expires", "data"],
    "mobile_daily_budget": ["day", *COUNTERS],
}


def public_path(settings):
    """Reject unknown existing files before a lock or SQLite open is attempted."""
    path = Path(settings.mobile_public_database_path)
    marker = path.with_name(path.name + ".mobile-public")
    if any(x.is_symlink() for x in (path, marker, *path.parents)):
        raise ValueError("Mobile public path cannot be a symlink")
    if path.exists():
        if (path.stat().st_nlink != 1 or not marker.is_file() or marker.stat().st_size != len(MARKER)
                or marker.read_bytes() != MARKER):
            raise ValueError("Not a dedicated mobile public database")
    elif marker.exists():
        raise ValueError("Mobile public database missing; refusing to reset its budget")
    return path


class DailyBudgetFull(ValueError):
    pass


def stamp(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.timestamp() if result.tzinfo else None
    except (ValueError, TypeError, AttributeError):
        return None


def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def bound_fact(resource, evidence, field):
    """Original extractor IDs plus current same-resource provenance, no search."""
    from .video_availability import _same_url, _target
    origin = (resource.get("field_provenance") or {}).get(field)
    value = resource.get(field)
    if not isinstance(origin, dict) or value is None or not _same_url(origin.get("url"), _target(resource)):
        return None
    expected_text = str(value)[:2000]
    from .source_adapters.bilibili import BILIBILI_DESCRIPTION_SOURCE, BILIBILI_DESCRIPTION_LIMIT, BILIBILI_DESCRIPTION_BYTES
    if field == "description" and origin.get("source") == BILIBILI_DESCRIPTION_SOURCE:
        if (not isinstance(value, str) or len(value) > BILIBILI_DESCRIPTION_LIMIT
                or len(value.encode("utf-8")) > BILIBILI_DESCRIPTION_BYTES):
            return None
        expected_text = value  # The registered source preserves its full bounded description.
    for row in evidence:
        if (row.get("kind") == "page" and row.get("field") == field and row.get("evidence_id")
                and row.get("evidence_id") == origin.get("evidence_id")
                and row.get("source") == origin.get("source")
                and isinstance(row.get("source"), str) and row["source"].startswith(("html.", "meta.", "jsonld."))
                and _same_url(row.get("url"), _target(resource))
                and row.get("text") == expected_text):
            expected = "ev_" + hashlib.sha256(f"{row['url']}|{field}|{row['source']}|{value}".encode()).hexdigest()[:20]
            if row.get("id") == expected:
                return value
    return None


def public_course(resource, evidence, ttl, now):
    """Whitelist only observed own public facts; no input/match/evidence dump."""
    try:
        from .course_library import _snapshot
        from .video_availability import _bili_part_identity, _bound_page_video, _target
        observed = stamp(resource.get("fetched_at"))
        if observed is None or not observed <= now < observed + ttl or resource.get("fetch_status") != "fetched":
            return None
        if (resource.get("cache") or {}).get("stale"):
            return None
        platform = resource.get("platform")
        if platform == "icourse163":
            own = _snapshot(resource, evidence)
            if own is None:
                return None
            clean = own[0]
        elif platform == "bilibili":
            target = _target(resource)
            if not _bili_part_identity(target) or not _bound_page_video(resource, evidence):
                return None
            # Only the already validated same-native target can shed tracking
            # metadata. Retain the original observation and its source IDs.
            clean = {**resource, "url": target, "canonical_url": target}
        else:
            return None
        title = bound_fact(clean, evidence, "title")
        if not isinstance(title, str) or not title.strip() or len(title) > 500:
            return None
        url = normalize_url(clean["url"])
        item = {"course_id": "public_" + hashlib.sha256(url.encode()).hexdigest()[:24],
                "url": url, "title": title, "platform": platform,
                "resource_type": "course" if platform == "icourse163" else "video",
                "observed_at": iso(observed), "expires_at": iso(observed + ttl)}
        for field, limit in (("author", 300), ("access_notice", 600)):
            value = bound_fact(clean, evidence, field)
            if isinstance(value, str) and 0 < len(value) <= limit:
                item[field] = value
        image = bound_fact(clean, evidence, "thumbnail_url")
        if image and (image := safe_thumbnail_url(image)):
            item["thumbnail_url"] = image
        return item
    except (KeyError, ValueError, TypeError, AttributeError):
        return None


def public_source_snapshot(resource, evidence):
    """Internal reusable public facts; never a job, query, or match snapshot."""
    from .course_library import _snapshot
    from .video_availability import _bili_part_identity, _bound_adapter_media_type, _bound_page_video, _same_url, _target
    if resource.get("platform") == "icourse163":
        snapshot = _snapshot(resource, evidence)
        if snapshot is None:
            return None
        clean, records = snapshot
    elif resource.get("platform") == "bilibili":
        target = _target(resource)
        if not _bili_part_identity(target) or not _bound_page_video(resource, evidence):
            return None
        fields = ("title", "description", "thumbnail_url", "author", "language", "duration_seconds")
        clean = {key: deepcopy(resource[key]) for key in
                 ("url", "canonical_url", "platform", "fetch_status", "fetched_at", "metadata_evidence_level",
                  "resource_type", "video_evidence_status") if key in resource}
        clean["field_provenance"], clean["chapters"], records = {}, [], []
        clean.update(url=target, canonical_url=target)
        for field in (*fields, "resource_type", "video_evidence_status"):
            proof = (resource.get("field_provenance") or {}).get(field) or {}
            row = next((row for row in evidence if row.get("evidence_id") == proof.get("evidence_id")), {})
            value = bound_fact(resource, evidence, field)
            identity = row.get("field") == field and (
                field == "video_evidence_status" or field == "resource_type" and _bound_adapter_media_type(resource, evidence))
            if identity:
                expected = "ev_" + hashlib.sha256(f"{row.get('url')}|{field}|{row.get('source')}|{resource.get(field)}".encode()).hexdigest()[:20]
                identity = (row.get("kind") == "page" and row.get("id") == expected
                            and _same_url(row.get("url"), _target(resource)))
            if value is None and not identity:
                continue
            clean[field] = deepcopy(resource[field])
            clean["field_provenance"][field] = {k: proof[k] for k in ("evidence_id", "source", "url", "fetched_at") if k in proof}
            records.append(row)
        if not all(field in clean["field_provenance"] for field in ("title", "resource_type", "video_evidence_status")):
            return None
        for chapter in resource.get("chapters", [])[:200]:
            if not isinstance(chapter, dict):
                continue
            row = next((row for row in evidence if row.get("evidence_id") == chapter.get("evidence_id")), {})
            if (row.get("kind") != "catalog" or row.get("source") != chapter.get("source")
                    or not str(row.get("source", "")).startswith("html.bilibili.")
                    or not _same_url(row.get("url"), _target(resource))):
                continue
            expected = "ev_" + hashlib.sha256(f"{row['url']}|{row.get('field')}|{row['source']}|{row.get('text')}".encode()).hexdigest()[:20]
            if row.get("id") != expected or not isinstance(row.get("text"), str):
                continue
            try:
                parsed = json.loads(row["text"])
            except ValueError:
                try:
                    parsed = ast.literal_eval(row["text"])
                except (ValueError, SyntaxError, RecursionError):
                    continue
            allowed = ("title", "url", "source_url", "start_seconds", "end_seconds", "duration_seconds", "page_number")
            if (not isinstance(parsed, dict) or parsed.get("title") != chapter.get("title")
                    or any(k in chapter and parsed.get(k) != chapter[k] for k in allowed)):
                continue
            clean["chapters"].append({**{k: deepcopy(chapter[k]) for k in allowed if k in chapter},
                                      "source": chapter["source"], "evidence_id": chapter["evidence_id"]})
            records.append(row)
    else:
        return None
    # Replace transient per-job evidence UUIDs by the original extractor IDs.
    # Preserve the extractor's ``id`` values, required for later source checks.
    ids = {row["evidence_id"]: row["id"] for row in records if row.get("evidence_id") and row.get("id")}
    if len(ids) != len(records):
        return None
    clean = deepcopy(clean)
    for proof in clean.get("field_provenance", {}).values():
        if isinstance(proof, dict) and proof.get("evidence_id") in ids:
            proof["evidence_id"] = ids[proof["evidence_id"]]
    for chapter in clean.get("chapters", []):
        chapter["evidence_id"] = ids.get(chapter.get("evidence_id"), chapter.get("evidence_id"))
    fields = ("id", "kind", "url", "source", "field", "text", "fetched_at")
    records = [{**{k: deepcopy(row[k]) for k in fields if k in row}, "evidence_id": ids[row["evidence_id"]]}
               for row in records]
    payload = {"resource": clean, "evidence": records}
    if len(json.dumps(payload, ensure_ascii=False).encode()) > 128_000:
        return None
    return payload


class MobilePublicStore:
    def __init__(self, settings, *, clock=time.time):
        self.settings, self.clock = settings, clock
        path = public_path(settings)
        marker = path.with_name(path.name + ".mobile-public")
        if any(x.is_symlink() for x in (path, marker, *path.parents)):
            raise ValueError("Mobile public path cannot be a symlink")
        path.parent.mkdir(parents=True, exist_ok=True)
        created = not path.exists()
        if created:
            if marker.exists():
                raise ValueError("Mobile public database missing; refusing to reset its budget")
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
        elif (path.stat().st_nlink != 1 or not marker.is_file() or marker.stat().st_size != len(MARKER)
              or marker.read_bytes() != MARKER):
            # Do not even open an unknown/legacy database to inspect/migrate it.
            raise ValueError("Not a dedicated mobile public database")
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        if not created:
            if not self.healthy():
                self.connection.close()
                raise ValueError("Unexpected mobile public schema")
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA secure_delete=ON")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS mobile_metadata(schema_version INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS mobile_public_courses(
                course_id TEXT PRIMARY KEY, platform TEXT NOT NULL, title TEXT NOT NULL,
                observed REAL NOT NULL, expires REAL NOT NULL, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS mobile_daily_budget(
                day TEXT PRIMARY KEY, tasks INTEGER NOT NULL, analysis_calls INTEGER NOT NULL,
                model_calls INTEGER NOT NULL, search_requests INTEGER NOT NULL,
                detail_pages INTEGER NOT NULL, detail_http INTEGER NOT NULL);
        """)
        if created:
            self.connection.execute(f"PRAGMA application_id={APPLICATION_ID}")
            self.connection.execute("INSERT INTO mobile_metadata VALUES(1)")
        self.connection.commit()
        if created:
            with marker.open("xb") as stream:
                stream.write(MARKER)

    def reserve(self, costs):
        if set(costs) != set(COUNTERS) or any(type(costs[k]) is not int or costs[k] < 0 for k in COUNTERS):
            raise ValueError("Invalid aggregate reservation")
        day = datetime.fromtimestamp(self.clock(), timezone.utc).date()
        limits = {k: getattr(self.settings, "mobile_daily_" + k) for k in COUNTERS}
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            current = self.connection.execute("SELECT * FROM mobile_daily_budget WHERE day=?", (str(day),)).fetchone()
            values = {k: (current[k] if current else 0) + costs[k] for k in COUNTERS}
            if any(values[k] > limits[k] for k in COUNTERS):
                raise DailyBudgetFull("daily_budget_exhausted")
            self.connection.execute("INSERT OR REPLACE INTO mobile_daily_budget VALUES(?,?,?,?,?,?,?)",
                                    (str(day), *(values[k] for k in COUNTERS)))
            self.connection.execute("DELETE FROM mobile_daily_budget WHERE day<?",
                                    (str(day - timedelta(days=self.settings.mobile_budget_retention_days - 1)),))
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise

    def observe(self, resource, evidence):
        item = public_course(resource, evidence, self.settings.mobile_public_ttl_seconds, self.clock())
        if item is None:
            return False
        snapshot = public_source_snapshot(resource, evidence)
        if snapshot is None:
            return False
        observed, expires = stamp(item["observed_at"]), stamp(item["expires_at"])
        previous = self.connection.execute("SELECT observed,data FROM mobile_public_courses WHERE course_id=?",
            (item["course_id"],)).fetchone()
        if previous and (previous[0] > observed or (previous[0] == observed and
                isinstance(json.loads(previous[1]).get("_source_snapshot"), dict))):
            return False
        payload = {**item, "_source_snapshot": snapshot}
        with self.connection:
            self.connection.execute("DELETE FROM mobile_public_courses WHERE expires<=?", (self.clock(),))
            self.connection.execute("""INSERT INTO mobile_public_courses VALUES(?,?,?,?,?,?)
                ON CONFLICT(course_id) DO UPDATE SET platform=excluded.platform,title=excluded.title,
                    observed=excluded.observed,expires=excluded.expires,data=excluded.data
                WHERE excluded.observed>=mobile_public_courses.observed""",
                (item["course_id"], item["platform"], item["title"], observed, expires,
                 json.dumps(payload, ensure_ascii=False, separators=(",", ":"))))
            self.connection.execute("""DELETE FROM mobile_public_courses WHERE course_id IN (
                SELECT course_id FROM mobile_public_courses ORDER BY observed DESC,course_id LIMIT -1 OFFSET ?)""",
                (self.settings.mobile_public_max_courses,))
        return True

    def browse(self, query="", platform=None, offset=0, limit=20):
        if (not isinstance(query, str) or len(query) > 200 or any(ord(c) < 32 for c in query)
                or platform not in {None, "bilibili", "icourse163"}
                or type(offset) is not int or not 0 <= offset <= self.settings.mobile_public_max_courses
                or type(limit) is not int or not 1 <= limit <= 50):
            raise ValueError("Invalid public browse parameters")
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        where = "expires>? AND title LIKE ? ESCAPE '\\'" + (" AND platform=?" if platform else "")
        args = [self.clock(), "%" + escaped + "%", *([platform] if platform else [])]
        total = self.connection.execute("SELECT count(*) FROM mobile_public_courses WHERE " + where, args).fetchone()[0]
        rows = self.connection.execute("SELECT data FROM mobile_public_courses WHERE " + where +
                                      " ORDER BY observed DESC,course_id LIMIT ? OFFSET ?", (*args, limit, offset))
        items = [{k: v for k, v in json.loads(r[0]).items() if k != "_source_snapshot"} for r in rows]
        return {"items": items, "total": total, "has_more": offset + len(items) < total}

    def lookup(self, point, request, limit=12):
        """Read-only, fresh relevance assessment; never reuse a user's match."""
        from .related_recommendations import related_recommendation
        if type(limit) is not int or not 1 <= limit <= 100:
            return []
        rows = self.connection.execute("SELECT data FROM mobile_public_courses WHERE expires>? ORDER BY observed DESC,course_id LIMIT ?",
                                       (self.clock(), self.settings.mobile_public_max_courses))
        hits = []
        for row in rows:
            try:
                item = json.loads(row[0])
                snapshot = item.get("_source_snapshot")
                if not isinstance(snapshot, dict):
                    continue  # Old card-only records cannot invent provenance.
                resource, evidence = deepcopy(snapshot["resource"]), deepcopy(snapshot["evidence"])
                if request.preferred_platforms and resource.get("platform") not in request.preferred_platforms:
                    continue
                if public_course(resource, evidence, self.settings.mobile_public_ttl_seconds, self.clock()) != {k: v for k, v in item.items() if k != "_source_snapshot"}:
                    continue
                reference = related_recommendation(point, resource, evidence, request)
                if reference is None:
                    continue
                hits.append({"resource": resource, "evidence": evidence, "course_id": item["course_id"],
                             "observed_at": item["observed_at"], "expires_at": item["expires_at"],
                             "content_sha256": hashlib.sha256(json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode()).hexdigest()})
            except (KeyError, ValueError, TypeError, AttributeError):
                continue
            if len(hits) == limit:
                break
        return hits

    def is_current(self, resource, evidence):
        receipt = resource.get("public_library") or {}
        row = self.connection.execute("SELECT data FROM mobile_public_courses WHERE course_id=? AND expires>?",
                                      (receipt.get("course_id"), self.clock())).fetchone()
        if row is None:
            return False
        item = json.loads(row[0])
        return (item.get("observed_at") == receipt.get("observed_at")
                and item.get("expires_at") == receipt.get("expires_at")
                and public_source_snapshot(resource, evidence) == item.get("_source_snapshot")
                and hashlib.sha256(json.dumps(item.get("_source_snapshot"), ensure_ascii=False, sort_keys=True).encode()).hexdigest()
                    == receipt.get("content_sha256"))

    def prune(self):
        cutoff = datetime.fromtimestamp(self.clock(), timezone.utc).date() - timedelta(days=self.settings.mobile_budget_retention_days - 1)
        with self.connection:
            self.connection.execute("DELETE FROM mobile_public_courses WHERE expires<=?", (self.clock(),))
            self.connection.execute("DELETE FROM mobile_daily_budget WHERE day<?", (str(cutoff),))

    def close(self):
        self.connection.close()

    def healthy(self):
        try:
            return (self.connection.execute("PRAGMA application_id").fetchone()[0] == APPLICATION_ID
                and [r[0] for r in self.connection.execute("SELECT schema_version FROM mobile_metadata")] == [1]
                and {r[0] for r in self.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")} == TABLES
                and all([r[1] for r in self.connection.execute(f"PRAGMA table_info({table})")] == columns
                    for table, columns in SCHEMA_COLUMNS.items()))
        except sqlite3.Error:
            return False
