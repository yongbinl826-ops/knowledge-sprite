"""Bounded real configured-source diagnosis; no database writes or injected candidates."""
import asyncio
import json
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from backend.app.config import Settings
from backend.app.providers import build_provider, SearchError, SearchBudgetReached

OUT = Path(__file__).resolve().parent
QUERIES = [
    ("Python 列表", "Python 列表 教程 site:bilibili.com/video/"),
    ("pandas 分组聚合", "pandas groupby 分组聚合 site:bilibili.com/video/"),
    ("pygame 矩形碰撞检测", "pygame Rect colliderect 碰撞检测 site:bilibili.com/video/"),
]

async def main():
    settings = replace(Settings.from_env(), search_max_retries=0)
    report = {"observed_at": datetime.now(timezone.utc).isoformat(),
        "scope": "six real provider requests at most; standard ten-result tier; no database mutation or candidate injection",
        "configuration": {"default": settings.search_provider, "bilibili": settings.bilibili_search_provider,
            "mooc": settings.mooc_search_provider, "tavily_configured": bool(settings.tavily_api_key),
            "serper_configured": bool(settings.serper_api_key), "bilibili_public_metadata": settings.bilibili_public_metadata},
        "search_requests": 0, "queries": []}
    async def budget():
        if report["search_requests"] >= 6:
            raise SearchBudgetReached()
        report["search_requests"] += 1
    for name in ("serper", "tavily"):
        provider = build_provider(settings, provider_name=name)
        provider.request_hook = budget
        for point, query in QUERIES:
            row = {"point": point, "query": query, "provider": name}
            try:
                candidates = await provider.search(query, "zh", 10, ["bilibili.com"])
                row.update(status="success", candidates=[c.model_dump() for c in candidates])
            except SearchError as exc:
                row.update(status="failed", error_code=exc.code)
            except SearchBudgetReached:
                row.update(status="budget_exhausted")
            row["requests"] = provider.last_requests
            row["warnings"] = provider.last_warnings
            report["queries"].append(row)
            (OUT / "search-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"provider": name, "point": point, "status": row["status"], "error_code":row.get("error_code"),
                "candidate_count": len(row.get("candidates", [])), "request_count":len(row["requests"])}, ensure_ascii=False), flush=True)
            if getattr(provider, "quota_exhausted", False) or provider.access_denied or row.get("error_code") == "rate_limited":
                break

if __name__ == "__main__":
    asyncio.run(main())
