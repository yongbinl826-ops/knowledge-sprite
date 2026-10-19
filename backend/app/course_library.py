"""Shared public MOOC observations, independent of users and search queries.

Only extractor-bound public page/outline facts enter this library. A lookup is
a fresh assessment for its supplied knowledge point, never a cached positive.
Evidence IDs may be remapped when copying a result into a job; extractor ``id``
values and all referenced evidence bindings must be retained.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import json
import math
import re
import time
from urllib.parse import urlsplit, urlunsplit

LIBRARY_SCHEMA = "public-mooc-library-v1"
_FACT_FIELDS = ("title", "description", "author", "institution", "thumbnail_url",
                "resource_type", "video_evidence_status", "language", "duration_seconds")
_RESOURCE_FIELDS = (*_FACT_FIELDS, "url", "canonical_url", "resolved_url", "platform",
                    "fetch_status", "fetched_at", "metadata_evidence_level", "catalog_kind",
                    "catalog_fetch_status", "chapters", "field_provenance")
_EVIDENCE_FIELDS = ("id", "evidence_id", "kind", "url", "source", "field", "text",
                    "fetched_at", "evidence_sha256")
_REVOKED = {"not_found", "access_denied", "login_required", "captcha", "blocked",
            "policy_restricted", "site_policy_restricted", "site_policy_blocked", "policy_unreviewed",
            "robots_disallowed", "robots_blocked", "rate_limited"}


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _timestamp(value):
    try:
        if isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.timestamp() if parsed.tzinfo else None
        if not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value):
            return float(value)
    except (ValueError, OverflowError, TypeError):
        pass
    return None


def course_entry_key(url):
    from .mooc_urls import course_identity_parts
    parts = course_identity_parts(url)
    if not parts:
        return None
    # Aliases deduplicate only after independent page/outline validation.
    return "mooc_" + _hash(parts)


def course_family_key(url):
    """Count a public course once without merging its semester observations."""
    from .mooc_urls import course_identity_parts
    parts = course_identity_parts(url)
    if not parts:
        return None
    return "mooc_course_" + _hash({"course_id": parts["course_id"]})


def profile_digest(profile):
    from .mooc_relevance import SCHEMA_VERSION
    return _hash({"library_schema": LIBRARY_SCHEMA, "relevance_schema": SCHEMA_VERSION, "profile": profile})


def _without_job_ids(value):
    if isinstance(value, dict):
        return {key: _without_job_ids(item) for key, item in value.items()
                if key not in {"evidence_id", "resource_id", "knowledge_point_id", "job_id", "course_library"}}
    if isinstance(value, list):
        return [_without_job_ids(item) for item in value]
    return value


def content_digest(resource, evidence):
    """Stable over job ID remapping, sensitive to every retained public fact."""
    facts = {key: resource[key] for key in _RESOURCE_FIELDS if key in resource}
    records = [{key: row[key] for key in _EVIDENCE_FIELDS if key in row}
               for row in evidence if row.get("kind") in {"page", "catalog"}]
    records = sorted((_without_job_ids(row) for row in records), key=_json)
    return _hash({"resource": _without_job_ids(facts), "evidence": records})


def library_observations(point, resource, evidence):
    """Validate fresh, content-bound receipts; an outline is checked separately."""
    from .mooc_relevance import _public_course, _url
    own_url = _public_course(resource.get("url"))
    metadata = resource.get("course_library")
    if not own_url or not isinstance(metadata, dict):
        return []
    observed, expires = _timestamp(metadata.get("observed_at")), _timestamp(metadata.get("expires_at"))
    current = time.time()
    if (metadata.get("schema_version") != LIBRARY_SCHEMA or observed is None or expires is None
            or not observed <= current < expires or expires - observed > 31 * 86400
            or _timestamp(resource.get("fetched_at")) != observed
            or metadata.get("entry_key") != course_entry_key(own_url)
            or metadata.get("content_sha256") != content_digest(resource, evidence)
            or not re.fullmatch(r"[0-9a-f]{64}", str(metadata.get("profile_sha256", "")))):
        return []
    return [row for row in evidence if row.get("kind") == "course_library"
            and row.get("source") == "shared_course_library"
            and _url(row.get("url")) == own_url and row.get("evidence_id")
            and row.get("id") == "library_" + _hash(metadata)
            and row.get("knowledge_point_id") == point.get("knowledge_point_id")
            and all(row.get(key) == value for key, value in metadata.items())]


def _terms(text):
    values = set()
    for word in re.findall(r"[a-zA-Z][a-zA-Z0-9+#.]*|[\u3400-\u9fff]+", text.casefold()):
        if re.match(r"[a-z]", word) or len(word) == 1:
            values.add(word[:100])
        else:
            values.update(word[index:index + 2] for index in range(len(word) - 1))
    return sorted(values)[:3000]


def _snapshot(resource, evidence):
    from .mooc_relevance import _outline, _public_course, _stale, _url
    own_url = _public_course(resource.get("url"))
    if (not own_url or _url(resource.get("canonical_url") or resource.get("url")) != own_url
            or _stale(resource) or any(_stale(row) for row in evidence if row.get("kind") in {"page", "catalog"})):
        return None
    outline, records, _ = _outline(resource, evidence, own_url)
    if outline is None:
        return None
    saved = {key: deepcopy(resource[key]) for key in _RESOURCE_FIELDS if key in resource}
    saved["field_provenance"] = {}
    saved["platform"] = "icourse163"
    saved["canonical_url"] = own_url
    identifiers = set()
    for field in _FACT_FIELDS:
        provenance = resource.get("field_provenance", {}).get(field, {})
        row = records.get(provenance.get("evidence_id"), {})
        value = resource.get(field)
        expected = "ev_" + hashlib.sha256(f"{own_url}|{field}|{row.get('source')}|{value}".encode()).hexdigest()[:20]
        text_matches = row.get("text") == str(value)[:2000]
        if field == "resource_type" and value == "course":
            curriculum = str(resource.get("field_provenance", {}).get("chapters", {}).get("source", "")).removeprefix("html.icourse163.")
            excerpts = {
                "html.icourse163.course_structure": "Observed MOOC course introduction and course-outline container; this is curriculum evidence, not video playback evidence",
                "html.icourse163.embedded_course_structure": f"Public course HTML contains matching courseDto.id, course introduction/outline containers and {curriculum} literal curriculum; no scripts executed or playback tested",
            }
            text_matches = text_matches or row.get("text") == excerpts.get(row.get("source"))
        if (value is None or row.get("kind") != "page" or row.get("field") != field
                or row.get("source") != provenance.get("source") or not row.get("source")
                or row.get("source") == "search" or _url(row.get("url")) != own_url
                or _url(provenance.get("url")) != own_url or row.get("id") != expected
                or not text_matches):
            saved.pop(field, None)
            continue
        saved["field_provenance"][field] = {key: provenance[key] for key in ("evidence_id", "source", "url", "fetched_at") if key in provenance}
        identifiers.add(row["evidence_id"])
    if not saved.get("title") or saved.get("resource_type") != "course":
        return None
    chapters = saved["chapters"]
    # The aggregate hashes the original extractor IDs, before per-job UUID remapping.
    originals = []
    for chapter in chapters:
        row = records[chapter["evidence_id"]]
        expected = "ev_" + hashlib.sha256(f"{own_url}|{row['field']}|{row['source']}|{row['text']}".encode()).hexdigest()[:20]
        if row.get("id") != expected:
            return None
        # Keep the extractor's insertion order: its aggregate uses Python repr,
        # whereas SQLite JSON serialization may have sorted dictionary keys.
        original = {key: chapter[key] for key in ("title", "url", "start_seconds", "end_seconds", "source_url", "duration_seconds", "page_number", "outline_parent_index") if key in chapter}
        original.update(source=chapter["source"], evidence_id=row["id"])
        originals.append(original)
        identifiers.add(chapter["evidence_id"])
    provenance = resource["field_provenance"]["chapters"]
    aggregate = records[provenance["evidence_id"]]
    expected = "ev_" + hashlib.sha256(f"{own_url}|chapters|{aggregate['source']}|{originals}".encode()).hexdigest()[:20]
    if aggregate.get("id") != expected or aggregate.get("text") != str(originals)[:2000]:
        return None
    saved["field_provenance"]["chapters"] = {key: provenance[key] for key in ("evidence_id", "source", "url", "fetched_at") if key in provenance}
    identifiers.add(provenance["evidence_id"])
    retained = [{key: row[key] for key in _EVIDENCE_FIELDS if key in row}
                for row in evidence if row.get("evidence_id") in identifiers]
    return saved, retained


class CourseLibrary:
    def __init__(self, store, ttl_seconds=604800, max_candidates=100):
        self.store = store
        self.ttl_seconds = max(1, min(int(ttl_seconds), 31 * 86400))
        self.max_candidates = max(1, min(int(max_candidates), 500))
        store.connection.executescript("""
            CREATE TABLE IF NOT EXISTS shared_mooc_courses(
                entry_key TEXT PRIMARY KEY, profile TEXT NOT NULL, observed REAL NOT NULL,
                expires REAL NOT NULL, status TEXT NOT NULL, data TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS shared_mooc_fresh ON shared_mooc_courses(profile,status,expires);
            CREATE TABLE IF NOT EXISTS shared_mooc_terms(
                term TEXT NOT NULL, entry_key TEXT NOT NULL REFERENCES shared_mooc_courses(entry_key) ON DELETE CASCADE,
                PRIMARY KEY(term,entry_key));
            CREATE INDEX IF NOT EXISTS shared_mooc_terms_entry ON shared_mooc_terms(entry_key);
        """)
        store.connection.commit()

    def observe(self, resource, evidence, profile, *, current_page_cache=False):
        """Save source facts, optionally revalidating an identical current cache.

        The service opts in only for its exact fresh page-cache key. A rule
        change may revalidate an existing verified observation, but cannot
        alter its age, extend its expiry, or resurrect a revoked observation.
        """
        from .mooc_relevance import _stale
        key = course_entry_key(resource.get("url"))
        if not key or _stale(resource):
            return False
        observed = _timestamp(resource.get("fetched_at"))
        current = time.time()
        status = resource.get("fetch_status")
        revoked = status in _REVOKED or "restricted" in str(status)
        if revoked and observed is None:
            # Policy/captcha blocks can be recorded before an HTTP body is fetched.
            observed = max((_timestamp(row.get("observed_at")) or 0 for row in evidence), default=0) or current
        if observed is None or observed > current or observed + self.ttl_seconds <= current:
            return False
        profile_hash = profile_digest(profile)
        old = self.store.connection.execute("SELECT * FROM shared_mooc_courses WHERE entry_key=?", (key,)).fetchone()
        revalidate = bool(old and current_page_cache is True and not revoked
                          and old["status"] == "verified" and old["observed"] == observed
                          and old["profile"] != profile_hash and old["expires"] > current)
        if old and old["observed"] >= observed and not revalidate:
            return False
        try:
            snapshot = None if revoked else _snapshot(resource, evidence)
            if revalidate:
                payload = json.loads(old["data"])
                previous_resource, previous_evidence = payload["resource"], payload["evidence"]
                previous_snapshot = _snapshot(previous_resource, previous_evidence)
                if (snapshot is None or previous_snapshot is None
                        or _timestamp(previous_resource.get("fetched_at")) != observed
                        or course_entry_key(previous_resource.get("url")) != key
                        or content_digest(*snapshot) != content_digest(previous_resource, previous_evidence)
                        or content_digest(*previous_snapshot) != content_digest(previous_resource, previous_evidence)):
                    return False
        except (KeyError, TypeError, ValueError, AttributeError):
            return False
        if not revoked and snapshot is None:
            return False
        expires = observed + self.ttl_seconds
        if revalidate:
            expires = min(old["expires"], expires)
        payload = {"resource": snapshot[0], "evidence": snapshot[1]} if snapshot else {}
        with self.store.connection:
            values = (profile_hash, observed, expires, "revoked" if revoked else "verified", _json(payload))
            if revalidate:
                # Another connection can revoke or replace the observation
                # while its source facts are being checked. Revalidate only
                # the exact version read above, never that newer state.
                written = self.store.connection.execute("""UPDATE shared_mooc_courses
                    SET profile=?,observed=?,expires=?,status=?,data=?
                    WHERE entry_key=? AND profile=? AND observed=? AND expires=? AND status=? AND data=?""",
                    (*values, key, old["profile"], old["observed"], old["expires"], old["status"], old["data"]))
            else:
                written = self.store.connection.execute("""INSERT INTO shared_mooc_courses VALUES(?,?,?,?,?,?)
                    ON CONFLICT(entry_key) DO UPDATE SET profile=excluded.profile,observed=excluded.observed,
                    expires=excluded.expires,status=excluded.status,data=excluded.data
                    WHERE shared_mooc_courses.observed < excluded.observed""", (key, *values))
            if written.rowcount != 1:
                return False
            self.store.connection.execute("DELETE FROM shared_mooc_terms WHERE entry_key=?", (key,))
            if snapshot:
                text = " ".join([snapshot[0]["title"], *(chapter["title"] for chapter in snapshot[0]["chapters"])])
                self.store.connection.executemany("INSERT INTO shared_mooc_terms VALUES(?,?)", ((term, key) for term in _terms(text)))
        return not revoked

    def lookup(self, point, profile, limit=3):
        from .mooc_relevance import assess_mooc_relevance
        limit = max(0, min(int(limit), self.max_candidates))
        terms = _terms(str(point.get("text") or "") + " " + " ".join(map(str, point.get("learning_targets") or [])))[:128]
        if not limit or not terms:
            return []
        current = time.time()
        profile_hash = profile_digest(profile)
        rows = self.store.connection.execute(f"""SELECT c.*,COUNT(*) AS overlap FROM shared_mooc_courses c
            JOIN shared_mooc_terms t ON t.entry_key=c.entry_key
            WHERE c.profile=? AND c.status='verified' AND c.expires>? AND c.observed<=? AND c.observed>?
            AND t.term IN ({','.join('?' for _ in terms)})
            GROUP BY c.entry_key ORDER BY overlap DESC,c.observed DESC,c.entry_key LIMIT ?""",
            (profile_hash, current, current, current - self.ttl_seconds, *terms, self.max_candidates)).fetchall()
        results = []
        for row in rows:
            try:
                payload = json.loads(row["data"])
                resource, evidence = payload["resource"], payload["evidence"]
                if (_timestamp(resource.get("fetched_at")) != row["observed"]
                        or _snapshot(resource, evidence) is None):
                    continue
                receipt = {"schema_version": LIBRARY_SCHEMA, "entry_key": row["entry_key"],
                           "profile_sha256": profile_hash, "observed_at": row["observed"], "expires_at": row["expires"],
                           "content_sha256": content_digest(resource, evidence)}
                resource["course_library"] = receipt
                resource["resource_id"] = row["entry_key"]
                evidence.append({**receipt, "id": "library_" + _hash(receipt), "evidence_id": "library_" + _hash(receipt),
                                 "kind": "course_library", "source": "shared_course_library", "url": resource["url"],
                                 "knowledge_point_id": point.get("knowledge_point_id"), "title": resource["title"]})
                assessment = assess_mooc_relevance(point, resource, evidence)
                if assessment.get("status") == "outline_supported" and assessment.get("display_eligible"):
                    results.append({"resource": resource, "evidence": evidence, "assessment": assessment, **receipt})
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
            if len(results) >= limit:
                break
        return results

    def is_current(self, resource, profile):
        """Revalidate a job's copied receipt against current policy and library.

        Call before counting/displaying a library-origin resource, even if a
        later search rediscovered its URL. A new search does not refresh its
        old outline. This read never renews or mutates an observation.
        """
        try:
            receipt = resource.get("course_library")
            if not isinstance(receipt, dict):
                return False
            key = course_entry_key(resource.get("url"))
            profile_hash = profile_digest(profile)
            observed, expires = _timestamp(receipt.get("observed_at")), _timestamp(receipt.get("expires_at"))
            current = time.time()
            if (receipt.get("schema_version") != LIBRARY_SCHEMA or not key
                    or receipt.get("entry_key") != key or receipt.get("profile_sha256") != profile_hash
                    or observed is None or expires is None or not observed <= current < expires
                    or current >= observed + self.ttl_seconds
                    or _timestamp(resource.get("fetched_at")) != observed):
                return False
            row = self.store.connection.execute("""SELECT data FROM shared_mooc_courses
                WHERE entry_key=? AND profile=? AND status='verified' AND observed=? AND expires=?""",
                (key, profile_hash, observed, expires)).fetchone()
            if row is None:
                return False
            payload = json.loads(row["data"])
            stored_resource, stored_evidence = payload["resource"], payload["evidence"]
            if _snapshot(stored_resource, stored_evidence) is None:
                return False
            current_digest = content_digest(stored_resource, stored_evidence)
            return (receipt.get("content_sha256") == current_digest
                    and content_digest(resource, stored_evidence) == current_digest)
        except (KeyError, TypeError, ValueError, AttributeError):
            return False

    def stats(self):
        current = time.time()
        row = self.store.connection.execute("""SELECT COUNT(*) AS total,
            SUM(status='verified' AND expires>? AND observed>?) AS fresh,
            SUM(status='verified' AND (expires<=? OR observed<=?)) AS expired,
            SUM(status='revoked') AS revoked FROM shared_mooc_courses""",
            (current, current - self.ttl_seconds, current, current - self.ttl_seconds)).fetchone()
        return {key: row[key] or 0 for key in ("total", "fresh", "expired", "revoked")}
