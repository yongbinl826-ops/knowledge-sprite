"""Verify the first real candidate for each successful Serper query."""
import asyncio
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from backend.app.config import Settings
from backend.app.fetcher import Fetcher, FetcherConfig, NETWORK_OBSERVER, FETCH_DEADLINE_AT

OUT = Path(__file__).resolve().parent
async def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--source",default="search-report.json")
    parser.add_argument("--out",default="details-report.json")
    parser.add_argument("--pygame",action="store_true")
    parser.add_argument("--pandas",action="store_true")
    args=parser.parse_args()
    s = Settings.from_env()
    fetcher = Fetcher(FetcherConfig(enabled=s.fetch_enabled, timeout_seconds=s.fetch_timeout_seconds,
        max_retries=0, global_concurrency=s.global_concurrency, min_interval_seconds=s.fetch_min_interval_seconds,
        allowed_restricted_hosts=s.allowed_restricted_hosts, denied_hosts=s.denied_fetch_hosts,
        bilibili_public_metadata=s.bilibili_public_metadata, dns_resolver=s.dns_resolver,
        phased_timeouts=s.fetch_phased_timeouts, body_idle_timeout_seconds=s.fetch_body_idle_timeout_seconds,
        body_min_bytes_per_second=s.fetch_body_min_bytes_per_second, body_timeout_cap_seconds=s.fetch_body_timeout_cap_seconds))
    report = {"scope":"unchanged configured safe fetcher; first observed candidates; no database writes or candidate injection", "physical_requests":0,"details":[]}
    async def before():
        if report["physical_requests"] >= 10:
            raise TimeoutError("diagnostic_request_budget")
        report["physical_requests"] += 1
    observer=NETWORK_OBSERVER.set({"before_target_http":before,"max_retries":0})
    deadline=FETCH_DEADLINE_AT.set(asyncio.get_running_loop().time()+90)
    try:
        searches=json.loads((OUT/args.source).read_text(encoding="utf-8"))["queries"]
        selections=[(row,row["candidates"][0]) for row in searches[:2]] if not args.pygame else [(searches[0],c) for c in searches[0]["candidates"][:3]]
        if args.pandas:
            selections=[(searches[1],searches[1]["candidates"][1]),(searches[1],searches[1]["candidates"][2])]
        for row,candidate in selections:
            result=await fetcher.enrich(candidate)
            report["details"].append({"point":row["point"],"candidate":candidate,"result":result})
            print(json.dumps({"point":row["point"],"fetch_status":result.get("fetch_status"),"title":result.get("title"),"chapters":len(result.get("chapters",[])),"video_evidence_status":result.get("video_evidence_status"),"url":result.get("url")},ensure_ascii=False),flush=True)
    finally:
        NETWORK_OBSERVER.reset(observer)
        FETCH_DEADLINE_AT.reset(deadline)
        report["trace"]=list(fetcher.request_trace)
        (OUT/args.out).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")

if __name__=="__main__":
    asyncio.run(main())
