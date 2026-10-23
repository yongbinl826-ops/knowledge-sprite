"""Bounded, instance-local reuse of pure related-reference projections."""
from collections import OrderedDict
from copy import deepcopy
import hashlib
import json

from .related_recommendations import related_recommendation


class ReadRelatedCache:
    def __init__(self, projector=related_recommendation, *, max_entries=4096,
                 max_output_bytes=8 * 1024 * 1024, max_input_bytes=1024 * 1024):
        if min(max_entries, max_output_bytes, max_input_bytes) < 1:
            raise ValueError("Cache limits must be positive")
        self.projector = projector
        self.max_entries, self.max_output_bytes = max_entries, max_output_bytes
        self.max_input_bytes = max_input_bytes
        self.entries = OrderedDict()
        self.output_bytes = 0
        self.hits = self.misses = self.bypasses = self.evictions = 0

    def project(self, point, resource, evidence, request, *, qualified_outline=None, grounded_decision=None):
        # Seal every input, including evidence order, ownership, freshness and
        # positive payment facts. Inputs and DB objects never live in the cache.
        key = None
        try:
            raw = json.dumps({"point": point, "resource": resource, "evidence": evidence,
                "request": request.model_dump(), "qualified_outline": qualified_outline,
                "grounded_decision": grounded_decision},
                ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
            if len(raw) <= self.max_input_bytes:
                key = hashlib.sha256(raw).hexdigest()
        except (TypeError, ValueError, OverflowError, RecursionError):
            pass
        optional = {"grounded_decision": grounded_decision} if grounded_decision is not None else {}
        if key is None:
            self.bypasses += 1
            return self.projector(point, resource, evidence, request, qualified_outline=qualified_outline, **optional)
        if key in self.entries:
            self.hits += 1
            value, _ = self.entries[key]
            self.entries.move_to_end(key)
            return deepcopy(value)
        self.misses += 1
        # Faults are not cached; None is a valid pure negative projection.
        value = self.projector(point, resource, evidence, request, qualified_outline=qualified_outline, **optional)
        try:
            size = len(json.dumps(value, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"), allow_nan=False).encode("utf-8"))
        except (TypeError, ValueError, OverflowError, RecursionError):
            self.bypasses += 1
            return value
        if size > self.max_output_bytes:
            self.bypasses += 1
            return value
        while self.entries and (len(self.entries) >= self.max_entries
                or self.output_bytes + size > self.max_output_bytes):
            _, (_, old_size) = self.entries.popitem(last=False)
            self.output_bytes -= old_size
            self.evictions += 1
        self.entries[key] = (deepcopy(value), size)
        self.output_bytes += size
        return value

    def recommendations(self, point, resources, evidence, request, limit, *, qualified_outlines=None, grounded_decisions=None):
        qualified_outlines = qualified_outlines or {}
        grounded_decisions = grounded_decisions or {}
        candidates = [value for rid, resource in resources.items()
                      if (value := self.project(point, resource, evidence.get(rid, []), request,
                                                 qualified_outline=qualified_outlines.get(rid),
                                                 grounded_decision=grounded_decisions.get(rid)))]
        # Preserve the uncached policy's ordering, URL deduplication and per-
        # platform limits. These cheap operations always use the current pool.
        candidates.sort(key=lambda row: (-row["reference"]["ranking_score"], row["resource"]["canonical_url"]))
        unique = list({row["resource"]["canonical_url"]: row for row in reversed(candidates)}.values())
        unique.sort(key=lambda row: (-row["reference"]["ranking_score"], row["resource"]["canonical_url"]))
        platforms = sorted({row["resource"]["platform"] for row in unique})
        return unique[:limit], {platform: [row for row in unique if row["resource"]["platform"] == platform][:limit]
                               for platform in platforms}

    def stats(self):
        return {"entries": len(self.entries), "output_bytes": self.output_bytes,
                "hits": self.hits, "misses": self.misses, "bypasses": self.bypasses,
                "evictions": self.evictions}
