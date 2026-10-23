"""Explicit gap-path probe: empty initial discovery, live AI/search/page recovery.

Separate from full live API acceptance. Never injects known video URLs or pages.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.llm import OpenAICompatibleLLM
from backend.app.models import SearchRequest
from backend.app.service import JobService
from verify_grounded_video_live import coverage, save


class EmptyInitialDiscovery:
    name = "controlled-empty-initial"

    async def search(self, *_args):
        return []


class OneLiveDiscoveryBatch:
    def __init__(self, settings):
        self.model = OpenAICompatibleLLM(settings)
        self.hints = {}

    async def expand(self, *_args):
        return []

    async def suggest_video_discovery(self, *args, **kwargs):
        self.hints = await self.model.suggest_video_discovery(*args, **kwargs)
        return self.hints


async def run(output):
    output.mkdir(parents=True, exist_ok=False)
    settings = replace(Settings.from_env(), database_path=str(output / "probe.sqlite3"),
        search_provider="searxng", bilibili_search_provider="", mooc_search_provider="",
        searxng_failover_provider="", official_sitemap_fallback=False, public_catalog_fallback=False,
        shared_course_library_enabled=False, mooc_refresh_enabled=False, mooc_gap_search_enabled=False,
        parallel_platform_search=False, teaching_match_enabled=False, ai_video_fallback_enabled=True,
        max_search_requests=12, max_detail_pages=12, deadline_seconds=120)
    store = Store(settings.database_path)
    service = JobService(settings, store, provider=EmptyInitialDiscovery(), llm=OneLiveDiscoveryBatch(settings))
    try:
        request = SearchRequest(knowledge_points=["Python 列表", "pandas 分组聚合", "pygame 矩形碰撞检测"],
                                preferred_platforms=["bilibili"])
        jid = service.create(request)["job_id"]
        await service.run(jid)
        result, job = service.results(jid), store.get_job(jid)
        save(output / "job.json", job)
        save(output / "results.json", result)
        save(output / "model-hints.json", service.llm.hints)
        groups = coverage(result)
        report = {"scope": "controlled-empty initial discovery; live configured model, recovery search and public page fetches",
                  "initial_discovery_controlled_empty": True, "status": job["status"],
                  "fallback": job.get("ai_video_fallback"), "progress": job["progress"],
                  "covered_points": sum(bool(g["verified_videos"]) for g in groups), "groups": groups,
                  "playback_verified": False}
        save(output / "report.json", report)
        print(json.dumps(report, ensure_ascii=False), flush=True)
    finally:
        await service.stop()
        store.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    asyncio.run(run(parser.parse_args().output))
