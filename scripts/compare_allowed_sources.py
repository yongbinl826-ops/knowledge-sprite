"""Bounded paired source experiment; never discovers, seeds, or downloads media.

Run baseline before edits and current after freezing. Both use the same manifest,
four HTML pages, timeout, byte/redirect limits, DNS validation and zero retries.
The separate frozen-HTML comparison isolates extraction changes from page drift.
"""
from __future__ import annotations
import argparse
import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import importlib
import json
from pathlib import Path
import sys
import time
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
WORK = ROOT / "reports/adapter-evaluation-20261013"


def now():
    return datetime.now(timezone.utc).isoformat()


async def main(variant):
    out = WORK / f"{variant}-network.json"
    if out.exists():
        raise SystemExit("Refusing to overwrite a prior experiment")
    if variant == "baseline":
        package = types.ModuleType("baseline_app")
        package.__path__ = [str(WORK / "baseline-src/backend/app")]
        sys.modules["baseline_app"] = package
        module = importlib.import_module("baseline_app.fetcher")
    else:
        module = importlib.import_module("backend.app.fetcher")
    manifest = json.loads((WORK / "sample-manifest.json").read_text(encoding="utf-8"))
    config = module.FetcherConfig(timeout_seconds=8, max_retries=0, dns_resolver="cloudflare_doh")
    report = {"variant": variant, "started_at": now(), "mode": "real_http",
        "scope": "4 fixed allowed HTML pages; no search/SQLite/browser/media; zero retries; cache only robots within this run",
        "request_count_scope": "actual_http_requests counts target HTML and robots HTTP only; external DoH HTTP is not instrumented and total outbound requests is unknown",
        "budget": {"resource_pages": 4, "target_and_robots_http_requests": 10, "wall_seconds": 120},
        "config": asdict(config), "requests": [], "documents": []}
    real_http = module.PinnedHTTPClient(config)

    class Recorder:
        async def request(self, url, addresses, max_bytes):
            if len(report["requests"]) >= 10:
                raise module.FetchStopped("budget_exceeded", "Paired experiment HTTP budget exhausted")
            trace = {"url": url, "started_at": now(), "pinned_public_addresses": addresses, "max_bytes": max_bytes}
            report["requests"].append(trace)
            started = time.perf_counter()
            try:
                response = await real_http.request(url, addresses, max_bytes)
                trace.update(status=response.status_code, bytes=len(response.body), content_type=response.headers.get("content-type"),
                    sha256=hashlib.sha256(response.body).hexdigest())
                if response.status_code == 200 and "html" in response.headers.get("content-type", "").lower():
                    path = WORK / f"{variant}-source-{len(report['requests'])}.html"
                    path.write_bytes(response.body)
                    trace["file"] = str(path.relative_to(ROOT)).replace("\\", "/")
                return response
            except Exception as exc:
                trace["error_type"] = type(exc).__name__
                raise
            finally:
                trace["elapsed_seconds"] = round(time.perf_counter() - started, 6)

    fetcher = module.Fetcher(config, http_client=Recorder())
    start = time.perf_counter()
    try:
        async with asyncio.timeout(120):
            for sample in manifest["documents"]:
                before = len(report["requests"])
                page_start = time.perf_counter()
                result = await fetcher.enrich({"url": sample["url"], "source": "explicit_paired_probe", "title": "", "snippet": ""})
                report["documents"].append({"url": sample["url"], "document_role": sample["document_role"],
                    "elapsed_seconds": round(time.perf_counter() - page_start, 6), "actual_http_requests": len(report["requests"]) - before,
                    "metadata": result})
                out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                print(variant, sample["document_role"], result["fetch_status"], flush=True)
    except Exception as exc:
        report["error_type"] = type(exc).__name__
    report.update(finished_at=now(), elapsed_seconds=round(time.perf_counter() - start, 6))
    report["actual_http_requests"] = len(report["requests"])
    source_dir = Path(module.__file__).parent
    report["code_sha256"] = {str(p.relative_to(source_dir)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in source_dir.rglob("*.py")}
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(out), report["actual_http_requests"], report["elapsed_seconds"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("variant", choices=["baseline", "current"])
    asyncio.run(main(parser.parse_args().variant))
