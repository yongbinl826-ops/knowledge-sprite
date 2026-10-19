"""Instance-local, bounded cache of pure read-path rank outputs only."""
from collections import OrderedDict
from copy import deepcopy
import hashlib
import json

from .ranking import rank_resource


class ReadRankCache:
    def __init__(self, ranker=rank_resource, *, max_entries=1024, max_output_bytes=8 * 1024 * 1024,
                 max_input_bytes=1024 * 1024):
        if min(max_entries, max_output_bytes, max_input_bytes) < 1:
            raise ValueError("Cache limits must be positive")
        self.ranker = ranker
        self.max_entries = max_entries
        self.max_output_bytes = max_output_bytes
        self.max_input_bytes = max_input_bytes
        self.entries = OrderedDict()
        self.output_bytes = 0
        self.hits = self.misses = self.bypasses = self.evictions = 0

    def rank(self, point, resource, observed, request, *, require_type=True, eligibility_evidence=None):
        # Raw inputs are used transiently to hash their complete canonical value;
        # neither keys nor entries retain a DB connection or the original input.
        key = None
        try:
            raw = json.dumps({"point": point, "resource": resource, "observed": observed,
                "eligibility_evidence": eligibility_evidence,
                "request": request.model_dump(), "require_type": require_type},
                ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
            if len(raw) <= self.max_input_bytes:
                key = hashlib.sha256(raw).hexdigest()
        except (TypeError, ValueError, OverflowError, RecursionError):
            pass
        if key is None:
            self.bypasses += 1
            return self.ranker(point, resource, observed, request, require_type=require_type,
                eligibility_evidence=eligibility_evidence)
        if key in self.entries:
            self.hits += 1
            value, _ = self.entries[key]
            self.entries.move_to_end(key)
            return deepcopy(value)
        self.misses += 1
        # Exceptions are deliberately not cached. Writer ranks never call here.
        value = self.ranker(point, resource, observed, request, require_type=require_type,
            eligibility_evidence=eligibility_evidence)
        try:
            size = len(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8"))
        except (TypeError, ValueError, OverflowError, RecursionError):
            self.bypasses += 1
            return value
        if size > self.max_output_bytes:
            self.bypasses += 1
            return value
        while self.entries and (len(self.entries) >= self.max_entries or self.output_bytes + size > self.max_output_bytes):
            _, (_, old_size) = self.entries.popitem(last=False)
            self.output_bytes -= old_size
            self.evictions += 1
        self.entries[key] = (deepcopy(value), size)
        self.output_bytes += size
        return value

    def stats(self):
        return {"entries": len(self.entries), "output_bytes": self.output_bytes,
            "hits": self.hits, "misses": self.misses, "bypasses": self.bypasses, "evictions": self.evictions}
