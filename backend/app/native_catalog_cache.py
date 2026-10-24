"""Reuse fresh public native catalogs, never saved recommendation decisions.

The existing generic cache table is used by exact course identity. Construction
and lookup are read-only: missing/older databases simply yield a cache miss.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import math
import re
import time
from urllib.parse import urlsplit

from .course_library import _snapshot, course_entry_key
from .helpful_video_chapters import catalog_identity, observed_chapters, observed_cover
from .mooc_urls import public_course_url
from .url_utils import UnsafeURL, normalize_url


_KIND = "native_catalog_v1"
_HOMEPAGE_KIND = "mooc_homepage_alias_v1"
_HOMEPAGE_SOURCE_HOSTS = {"icourse163.org", "www.icourse163.org", "docs.icourse163.org"}
_BAD_STATUS = re.compile(r"error|fail|timeout|blocked|captcha|denied|invalid|limit_exceeded|not_found|login|restrict", re.I)


def _timestamp(value):
    """A page observation needs an explicit timezone, not a guessed local date."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        stamp = parsed.timestamp() if parsed.tzinfo is not None else None
        return stamp if stamp is not None and math.isfinite(stamp) else None
    except (ValueError, TypeError, OverflowError):
        return None


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _key(identity):
    return hashlib.sha256((_KIND + "|" + identity).encode()).hexdigest()


def _homepage_key(identity):
    return hashlib.sha256((_HOMEPAGE_KIND + "|" + identity).encode()).hexdigest()


def _homepage_url(value, identity):
    url = public_course_url(value)
    return (url if url and identity and identity.startswith("icourse163:")
            and urlsplit(url).path != "/course/detail.htm"
            and catalog_identity(url) == identity else None)


def _homepage_source(value):
    """Validate the recorded official discovery page; never fetch it here."""
    if not isinstance(value, str) or value != value.strip():
        return None
    try:
        parts = urlsplit(value)
        if (parts.scheme != "https" or parts.hostname not in _HOMEPAGE_SOURCE_HOSTS
                or parts.port not in {None, 443} or parts.fragment
                or parts.username is not None or parts.password is not None):
            return None
        return normalize_url(value)
    except (UnsafeURL, ValueError, TypeError):
        return None


class NativeCatalogCache:
    def __init__(self, store, *, ttl_seconds=86400, page_lookup=None, shared_library_enabled=True):
        self.store = store
        self.ttl_seconds = max(0, min(int(ttl_seconds), 31 * 86400))
        self.page_lookup = page_lookup
        self.shared_library_enabled = shared_library_enabled

    def _identity(self, resource):
        if not isinstance(resource, dict) or resource.get("requires_payment") is True:
            return None
        identity = catalog_identity(resource.get("url", ""))
        canonical = resource.get("canonical_url")
        if canonical and catalog_identity(canonical) != identity:
            return None
        return identity

    def _fresh(self, observed, current):
        return observed is not None and current - self.ttl_seconds < observed <= current

    def observe_homepage(self, resource, homepage_url, *, source_url, observed_at):
        """Retain an actually observed official link, not a guessed course slug.

        The caller supplies link-discovery evidence. This record contains no
        cover or catalog facts and does not certify that the target is usable.
        """
        identity = self._identity(resource)
        homepage = _homepage_url(homepage_url, identity)
        source = _homepage_source(source_url)
        observed, current = _timestamp(observed_at), time.time()
        if (not self.ttl_seconds or not homepage or not source
                or not self._fresh(observed, current)
                or self._revoked(self._shared_row(resource), observed, current)):
            return False
        saved = {"homepage_url": homepage, "source_url": source, "observed_at": observed_at}
        try:
            with self.store.connection:
                cursor = self.store.connection.execute("""INSERT INTO cache(key,kind,created,expires,data) VALUES(?,?,?,?,?)
                    ON CONFLICT(key) DO UPDATE SET kind=excluded.kind,created=excluded.created,
                    expires=excluded.expires,data=excluded.data WHERE cache.created < excluded.created""",
                    (_homepage_key(identity), _HOMEPAGE_KIND, observed, observed + self.ttl_seconds,
                     json.dumps(saved, ensure_ascii=False, sort_keys=True, separators=(",", ":"))))
            return cursor.rowcount > 0
        except Exception:
            return False

    def lookup_homepage(self, resource):
        """Read a fresh same-course-and-term public homepage without network."""
        identity = self._identity(resource)
        if not self.ttl_seconds or not identity or not identity.startswith("icourse163:"):
            return None
        current = time.time()
        try:
            row = self.store.connection.execute(
                "SELECT kind,created,expires,data FROM cache WHERE key=?", (_homepage_key(identity),)).fetchone()
            if row is not None and row["kind"] == _HOMEPAGE_KIND and _number(row["expires"]) and row["expires"] > current:
                data = json.loads(row["data"])
                observed = _timestamp(data.get("observed_at"))
                homepage = _homepage_url(data.get("homepage_url"), identity)
                if (homepage and _homepage_source(data.get("source_url")) and self._fresh(observed, current)
                        and row["created"] == observed
                        and not self._revoked(self._shared_row(resource), observed, current)):
                    return homepage
        except Exception:
            pass
        # Reuse an older native/page/shared observation without rewriting its
        # discovery time or mutating cache during a read.
        metadata = self.lookup(resource)
        if metadata:
            return _homepage_url(metadata.get("resolved_url") or metadata.get("url"), identity)
        return None

    def _metadata(self, resource, metadata, current):
        """Project a small allowlist; strip jobs, searches, matches and IDs."""
        identity = self._identity(resource)
        if not identity or not isinstance(metadata, dict):
            return None
        observed = _timestamp(metadata.get("fetched_at"))
        if not self._fresh(observed, current) or metadata.get("requires_payment") is True:
            return None
        if metadata.get("fetch_status") != "fetched":
            return None
        status = metadata.get("catalog_fetch_status")
        catalog_invalid = status is not None and (not isinstance(status, str) or _BAD_STATUS.search(status))
        if isinstance(metadata.get("cache"), dict) and metadata["cache"].get("stale") is True:
            return None
        for field in ("url", "canonical_url", "resolved_url"):
            if metadata.get(field) and catalog_identity(metadata[field]) != identity:
                return None
        source_rows = metadata.get("chapters", [])
        if not isinstance(source_rows, list) or len(source_rows) > 1000 or catalog_invalid:
            source_rows = []
        # Payment may be stated for one chapter even when the course is unknown.
        eligible = [row for row in source_rows if isinstance(row, dict) and row.get("requires_payment") is not True]
        parsed = observed_chapters(resource, {**metadata, "chapters": eligible})
        chapters = []
        for chapter in parsed:
            stamp = chapter.get("observed_at") or metadata["fetched_at"]
            if not self._fresh(_timestamp(stamp), current):
                continue
            chapters.append({"title": chapter["title"], "url": chapter["url"],
                "source_url": chapter["source_url"], "source": chapter["source_kind"],
                "page_number": chapter["index"], "observed_at": stamp})
        cover = observed_cover(resource, metadata)
        if cover and not self._fresh(_timestamp(cover["observed_at"]), current):
            cover = None
        if not chapters and not cover:
            return None
        saved = {"url": metadata.get("url") or resource["url"], "fetched_at": metadata["fetched_at"],
                 "fetch_status": "fetched", "chapters": chapters}
        for field in ("resolved_url", "catalog_kind", "catalog_fetch_status"):
            if isinstance(metadata.get(field), str):
                saved[field] = metadata[field]
        if type(metadata.get("requires_payment")) is bool:
            saved["requires_payment"] = metadata["requires_payment"]
        if cover:
            saved["thumbnail_url"] = cover["thumbnail_url"]
            saved["field_provenance"] = {"thumbnail_url": {"source": cover["source"],
                "url": cover["source_url"], "fetched_at": cover["observed_at"],
                "original_thumbnail_url": cover["provenance"]["original_thumbnail_url"]}}
        return saved

    def _shared_row(self, resource):
        key = course_entry_key(resource.get("url"))
        if not key:
            return None
        try:
            return self.store.connection.execute(
                "SELECT entry_key,observed,expires,status,data FROM shared_mooc_courses WHERE entry_key=?", (key,)).fetchone()
        except Exception:
            return None

    @staticmethod
    def _revoked(row, observed, current):
        # Expiration of a negative observation never resurrects older facts.
        return bool(row is not None and row["status"] == "revoked" and _number(row["observed"])
                    and observed <= row["observed"] <= current)

    def _tag(self, metadata, source):
        return {**metadata, "catalog_cache": {"source": source, "observed_at": metadata["fetched_at"]}}

    def lookup(self, resource):
        if not self.ttl_seconds:
            return None
        identity = self._identity(resource)
        if not identity:
            return None
        current = time.time()
        # A known newer revocation applies even if positive library reuse is off.
        shared = self._shared_row(resource)
        try:
            row = self.store.connection.execute(
                "SELECT kind,created,expires,data FROM cache WHERE key=?", (_key(identity),)).fetchone()
            if row is not None and row["kind"] == _KIND and _number(row["expires"]) and row["expires"] > current:
                metadata = self._metadata(resource, json.loads(row["data"]), current)
                observed = _timestamp(metadata["fetched_at"]) if metadata else None
                if (metadata and row["created"] == observed and not self._revoked(shared, observed, current)):
                    return self._tag(metadata, "native_catalog_cache")
        except Exception:
            pass
        if self.shared_library_enabled and shared is not None:
            try:
                if (shared["status"] == "verified" and _number(shared["observed"])
                        and self._fresh(shared["observed"], current) and _number(shared["expires"])
                        and shared["expires"] > current):
                    payload = json.loads(shared["data"])
                    original, evidence = payload["resource"], payload["evidence"]
                    if (course_entry_key(original.get("url")) == shared["entry_key"]
                            and catalog_identity(original.get("url")) == identity
                            and _timestamp(original.get("fetched_at")) == shared["observed"]
                            and original.get("requires_payment") is not True):
                        snapshot = _snapshot(original, evidence)
                        metadata = self._metadata(resource, snapshot[0], current) if snapshot else None
                        if metadata:
                            return self._tag(metadata, "shared_course_library")
            except Exception:
                pass
        if self.page_lookup is not None:
            try:
                _cache_key, cached = self.page_lookup({"canonical_url": resource["url"], **resource})
                if (isinstance(cached, dict) and isinstance(cached.get("cache"), dict)
                        and cached["cache"].get("hit") is True and cached["cache"].get("stale") is False):
                    metadata = self._metadata(resource, cached.get("data"), current)
                    observed = _timestamp(metadata["fetched_at"]) if metadata else None
                    if metadata and not self._revoked(shared, observed, current):
                        return self._tag(metadata, "page_cache")
            except Exception:
                pass
        return None

    def observe(self, resource, metadata):
        """Persist only fresh source facts and retain their original expiry."""
        if not self.ttl_seconds:
            return
        current = time.time()
        try:
            identity = self._identity(resource)
            if (identity and isinstance(metadata, dict) and metadata.get("fetch_status") == "fetched"
                    and metadata.get("requires_payment") is not True
                    and not (isinstance(metadata.get("cache"), dict) and metadata["cache"].get("stale") is True)
                    and all(not metadata.get(field) or catalog_identity(metadata[field]) == identity
                            for field in ("url", "canonical_url", "resolved_url"))):
                homepage = metadata.get("resolved_url") or metadata.get("url")
                self.observe_homepage(resource, homepage, source_url=homepage,
                                      observed_at=metadata.get("fetched_at"))
            saved = self._metadata(resource, metadata, current)
            if not saved:
                return
            observed = _timestamp(saved["fetched_at"])
            if self._revoked(self._shared_row(resource), observed, current):
                return
            identity = self._identity(resource)
            previous = self.store.connection.execute(
                "SELECT kind,created,data FROM cache WHERE key=?", (_key(identity),)).fetchone()
            if previous is not None and previous["kind"] == _KIND:
                if previous["created"] > observed:
                    return
                old = self._metadata(resource, json.loads(previous["data"]), current)
                if old:
                    if previous["created"] == observed:
                        # Equal-time observations can add an absent field, but
                        # cannot rewrite a previously retained source fact.
                        base, supplement = old, saved
                    else:
                        base, supplement = saved, old
                    saved = dict(base)
                    if not saved.get("chapters") and supplement.get("chapters"):
                        saved["chapters"] = supplement["chapters"]
                    if not observed_cover(resource, saved) and observed_cover(resource, supplement):
                        saved["thumbnail_url"] = supplement["thumbnail_url"]
                        saved["field_provenance"] = supplement["field_provenance"]
            with self.store.connection:
                self.store.connection.execute("""INSERT INTO cache(key,kind,created,expires,data) VALUES(?,?,?,?,?)
                    ON CONFLICT(key) DO UPDATE SET kind=excluded.kind,created=excluded.created,
                    expires=excluded.expires,data=excluded.data WHERE cache.created <= excluded.created""",
                    (_key(identity), _KIND, observed, observed + self.ttl_seconds,
                     json.dumps(saved, ensure_ascii=False, sort_keys=True, separators=(",", ":"))))
        except Exception:
            # Optional reuse cannot make recommendation publication fail.
            return
