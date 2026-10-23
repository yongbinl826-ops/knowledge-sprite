"""One live model batch and public-page fetches against a controlled empty search.

Run explicitly; this consumes the already configured model API. No production
database, ordinary search credits, page replay, or supplied candidate injection.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
import json
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.llm import OpenAICompatibleLLM
from backend.app.ai_video_fallback import normalize_video_suggestions
from backend.app.models import SearchRequest
from backend.app.service import JobService


class EmptySearch:
    name = "controlled-empty-discovery"

    async def search(self, *_args):
        return []


class OneLiveModelBatch:
    def __init__(self, settings):
        self.model = OpenAICompatibleLLM(settings)
        self.raw_hint_counts = []

    async def expand(self, *_args):
        return []

    async def suggest_video_urls(self, *args, **kwargs):
        def observed(body, *values, **options):
            self.raw_hint_counts = [{"point_id": row.get("point_id"), "url_count": len(row.get("urls", []))}
                for row in body.get("suggestions", []) if isinstance(row, dict) and isinstance(row.get("urls"), list)]
            return normalize_video_suggestions(body, *values, **options)
        with patch("backend.app.llm.normalize_video_suggestions", observed):
            return await self.model.suggest_video_urls(*args, **kwargs)


async def verify(output):
    output.mkdir(parents=True, exist_ok=False)
    settings = replace(Settings.from_env(), database_path=str(output / "probe.sqlite3"),
        search_provider="searxng", bilibili_search_provider="", mooc_search_provider="",
        searxng_failover_provider="", official_sitemap_fallback=False, public_catalog_fallback=False,
        shared_course_library_enabled=False, mooc_refresh_enabled=False, mooc_gap_search_enabled=False,
        parallel_platform_search=False, teaching_match_enabled=False, ai_video_fallback_enabled=True,
        max_search_requests=3, max_detail_pages=9, deadline_seconds=90, llm_max_output_tokens=2000)
    if not (settings.llm_provider == "openai_compatible" and settings.llm_api_key and settings.llm_model):
        raise RuntimeError("Configured model required")
    store = Store(settings.database_path)
    service = JobService(settings, store, provider=EmptySearch(), llm=OneLiveModelBatch(settings))
    try:
        request = SearchRequest(knowledge_points=["Python 列表", "pandas 分组聚合", "pygame 矩形碰撞检测"],
                                preferred_platforms=["bilibili"])
        jid = service.create(request)["job_id"]
        await service.run(jid)
        result, job = service.results(jid), store.get_job(jid)
        report = {"scope": "controlled empty search; live configured model and live public-page fetches",
                  "search_was_controlled_empty": True, "model": settings.llm_model,
                  "raw_model_hint_counts": service.llm.raw_hint_counts,
                  "status": job["status"], "fallback": job.get("ai_video_fallback"),
                  "progress": job["progress"], "warnings": job["warnings"], "errors": job["errors"],
                  "groups": [{"point": group["text"], "recommendations": [row["resource"] for row in
                    [*group.get("items", []), *group.get("partial_items", []), *group.get("related_recommendations", [])]]}
                    for group in result["groups"]],
                  "resources": [{key: resource.get(key) for key in (
                    "url", "title", "fetch_status", "video_evidence_status", "resource_type", "playback_verified")}
                    for resource in store.resources(jid).values()]}
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        await service.stop()
        store.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    asyncio.run(verify(parser.parse_args().output))
