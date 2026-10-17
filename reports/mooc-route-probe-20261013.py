"""Bounded read-only routing diagnosis; never imports or mutates the job service."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.providers import parse_candidates

STAMP = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
OUT = ROOT / "reports" / ("mooc-route-probe-" + STAMP)
OUT.mkdir()
report = {"started_at": datetime.now(timezone.utc).isoformat(), "scope": "read-only, eight requests maximum; no retry; only existing Bing and DuckDuckGo videos", "requests": [], "sources": {}}
for module in ("bing", "duckduckgo_extra"):
    result = subprocess.run(["docker", "exec", "knowledge-sprite-searxng-1", "cat", f"/usr/local/searxng/searx/engines/{module}.py"], capture_output=True, check=True)
    target = OUT / f"official-image-{module}.py"
    target.write_bytes(result.stdout)
    report["sources"][module] = {"file": target.name, "sha256": hashlib.sha256(result.stdout).hexdigest()}
report["image"] = "ghcr.io/searxng/searxng@sha256:ddd642cae6eac75412938fd846ddbf440a2df029cfeae8a562b8b205f4e35e25"
report["provider_sha256"] = hashlib.sha256((ROOT / "backend/app/providers.py").read_bytes()).hexdigest()
blocked = set()
with httpx.Client(timeout=15, trust_env=False, follow_redirects=False) as client:
    for topic, language in (("Python 列表与字典 课程", "zh-CN"), ("linear algebra eigenvalues course", "en")):
        for domain in ("icourse163.org", "xuetangx.com"):
            for engine in ("bing", "duckduckgo videos"):
                query = f"site:{domain} {topic}"
                case = {"query": query, "language": language, "engine": engine, "domain_filter": domain}
                report["requests"].append(case)
                if engine in blocked:
                    case["status"] = "skipped_after_access_restriction"
                    continue
                params = {"q": query, "format": "json", "language": language, "engines": engine}
                started = time.monotonic()
                try:
                    response = client.get("http://127.0.0.1:18780/search", params=params)
                    case.update(http_status=response.status_code, request_url=str(response.request.url), elapsed_seconds=round(time.monotonic()-started, 3))
                    raw_path = OUT / f"response-{len(report['requests']):02d}.json"
                    raw_path.write_bytes(response.content)
                    case["raw_file"] = raw_path.name
                    if response.status_code in {401, 403, 429}:
                        blocked.add(engine)
                    if response.status_code == 200:
                        body = response.json()
                        case["echoed_query"] = body.get("query")
                        case["unresponsive_engines"] = body.get("unresponsive_engines", [])
                        for failure in case["unresponsive_engines"]:
                            if isinstance(failure, list) and len(failure) > 1 and str(failure[1]).lower() in {"captcha", "access denied", "too many requests", "suspended"}:
                                blocked.add(engine)
                        raw = body.get("results", [])
                        accepted = parse_candidates(raw, "searxng", query, 100, [domain])
                        accepted_urls = {item.url for item in accepted}
                        case.update(raw_count=len(raw), accepted_count=len(accepted), results=[])
                        for item in raw:
                            url = item.get("url", "")
                            try:
                                parsed = urlsplit(url)
                                host = parsed.hostname
                            except ValueError:
                                host = None
                            reason = "accepted" if url in accepted_urls else "domain_mismatch" if host and not (host == domain or host.endswith("."+domain)) else "invalid_or_empty_title_url"
                            case["results"].append({"url": url, "title": item.get("title"), "hostname": host, "engines": item.get("engines"), "template": item.get("template"), "filter_reason": reason})
                except (httpx.HTTPError, ValueError) as error:
                    case["error_type"] = type(error).__name__
                (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                print(json.dumps({k:case.get(k) for k in ("engine", "query", "http_status", "raw_count", "accepted_count", "unresponsive_engines")}, ensure_ascii=False), flush=True)
                time.sleep(1)
report["finished_at"] = datetime.now(timezone.utc).isoformat()
(OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(OUT, flush=True)
