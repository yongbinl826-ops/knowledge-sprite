"""Three additionally authorized adaptive search requests; no injected URLs."""
import asyncio
import json
import sys
from dataclasses import replace
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from backend.app.config import Settings
from backend.app.providers import build_provider,SearchError,SearchBudgetReached
OUT=Path(__file__).resolve().parent
async def main():
    settings=replace(Settings.from_env(),search_max_retries=0)
    report={"scope":"three additionally authorized adaptive real searches","search_requests":0,"queries":[]}
    async def budget():
        if report["search_requests"]>=3: raise SearchBudgetReached()
        report["search_requests"]+=1
    providers={name:build_provider(settings,provider_name=name) for name in ("serper","tavily")}
    for provider in providers.values(): provider.request_hook=budget
    for name,query in [("serper","pygame 碰撞检测 site:bilibili.com/video/"),("serper","pygame colliderect site:bilibili.com/video/"),("tavily","pygame 碰撞检测 site:bilibili.com/video/")]:
        provider=providers[name]
        row={"provider":name,"point":"pygame 矩形碰撞检测","query":query}
        try:
            candidates=await provider.search(query,"zh",10,["bilibili.com"])
            row.update(status="success",candidates=[c.model_dump() for c in candidates])
        except SearchError as exc: row.update(status="failed",error_code=exc.code)
        row["requests"]=provider.last_requests
        row["warnings"]=provider.last_warnings
        report["queries"].append(row)
        (OUT/"pygame-search-report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps({"provider":name,"query":query,"status":row["status"],"candidate_count":len(row.get("candidates",[]))},ensure_ascii=False),flush=True)
        if provider.access_denied or getattr(provider,"quota_exhausted",False) or row.get("error_code")=="rate_limited": break
if __name__=="__main__": asyncio.run(main())
