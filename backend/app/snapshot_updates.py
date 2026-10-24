"""Bound progress-only persistence while immediately saving results and terminal states."""
from __future__ import annotations

import asyncio
import json


class CoalescedPublisher:
    def __init__(self, publish, *, interval=.5):
        self.publish = publish
        self.interval = interval
        self.loop = asyncio.get_running_loop()
        self.last_saved = float("-inf")
        self.last_material = None
        self.pending = None
        self.timer = None
        self.closed = False

    @staticmethod
    def material(snapshot):
        catalog = snapshot.get("catalog_enrichment") or {}
        return json.dumps([snapshot.get("status"), catalog.get("status"), catalog.get("run_id"),
                           snapshot.get("recommendations", {})], ensure_ascii=False, sort_keys=True)

    def __call__(self, snapshot):
        if self.closed:
            return
        self.pending = snapshot
        material = self.material(snapshot)
        terminal = snapshot.get("status") not in {"queued", "running"} and (
            snapshot.get("catalog_enrichment") or {}).get("status") != "running"
        if terminal or material != self.last_material or self.loop.time() - self.last_saved >= self.interval:
            self.flush()
        elif self.timer is None:
            self.timer = self.loop.call_later(self.interval - (self.loop.time() - self.last_saved), self.flush)

    def flush(self):
        if self.timer is not None:
            self.timer.cancel()
            self.timer = None
        if self.pending is not None:
            snapshot, self.pending = self.pending, None
            self.publish(snapshot)
            self.last_material = self.material(snapshot)
            self.last_saved = self.loop.time()

    def close(self):
        self.flush()
        self.closed = True
