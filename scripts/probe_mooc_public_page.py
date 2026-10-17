"""One bounded production-Fetcher probe, separate from end-to-end acceptance."""
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.config import Settings
from backend.app.db import Store
from backend.app.fetcher import NETWORK_OBSERVER, FETCH_DEADLINE_AT
from backend.app.service import JobService

OUT = ROOT / "reports/mooc-public-read-20261017/direct-probe"
URL = "https://www.icourse163.org/course/PKU-1003479006"


async def main():
    OUT.mkdir(exist_ok=False)
    plan = {"at": datetime.now(timezone.utc).isoformat(), "url": URL,
            "source": "prior real search job 426f60d1-22cf-4b43-89fd-c0d805bfa974; diagnostic probe only",
            "max_target_requests": 4, "max_seconds": 60, "search_submissions": 0,
            "credentials": False, "private_api": False}
    (OUT / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf8")
    service = JobService(Settings.from_env(), Store(":memory:"))
    requests, records = 0, []
    async def before():
        nonlocal requests
        requests += 1
        if requests > 4:
            raise TimeoutError("diagnostic_request_budget")
    def response(result, kind):
        filename = f"{len(records)+1:02d}-{kind}.body"
        (OUT / filename).write_bytes(result.body)
        records.append({"url": result.url, "kind": kind, "http_status": result.status_code,
                        "body_bytes": len(result.body), "sha256": hashlib.sha256(result.body).hexdigest(),
                        "body_file": filename, "content_type": result.headers.get("content-type")})
    token = NETWORK_OBSERVER.set({"before_target_http": before, "response": response, "max_retries": 0})
    deadline = FETCH_DEADLINE_AT.set(asyncio.get_running_loop().time()+60)
    try:
        result = await service.fetcher.enrich({"url": URL, "title": "Python语言基础与应用",
                                              "source": "prior_live_search_diagnostic"})
    finally:
        NETWORK_OBSERVER.reset(token)
        FETCH_DEADLINE_AT.reset(deadline)
        service.store.close()
    output = {"at": datetime.now(timezone.utc).isoformat(), "result": result,
              "responses": records, "trace": list(service.fetcher.request_trace),
              "end_to_end_acceptance": False}
    (OUT / "result.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps({"fetch_status": result.get("fetch_status"), "error": result.get("fetch_error"),
                      "catalog_entries": len(result.get("chapters", [])), "responses": records}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
