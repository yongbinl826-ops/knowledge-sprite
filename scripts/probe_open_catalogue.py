"""Two-page, sequential public HTML probe. No database, media or seeded search."""
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import urljoin, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bs4 import BeautifulSoup
from backend.app.fetcher import Fetcher, FetcherConfig, FetchStopped, PinnedHTTPClient
from backend.app.url_utils import normalize_url, UnsafeURL

WORK = ROOT / "reports/completion-20261013"


async def main():
    path = WORK / "openlearn-probe.json"
    if path.exists():
        raise SystemExit("Refusing to overwrite previous probe")
    config = FetcherConfig(global_concurrency=1, min_interval_seconds=1, max_retries=0, dns_resolver="cloudflare_doh")
    client = PinnedHTTPClient(config)
    report = {"started_at": datetime.now(timezone.utc).isoformat(), "requests": [], "documents": [],
        "scope": "2 HTML pages maximum; 10 target/robots requests; no retries; DoH not counted; zero database/media requests"}
    bodies = {}
    class Recorder:
        async def request(self, url, addresses, max_bytes):
            if len(report["requests"]) >= 10:
                raise FetchStopped("budget_exceeded", "Probe budget exhausted")
            record = {"url": url, "started_at": datetime.now(timezone.utc).isoformat()}
            report["requests"].append(record)
            try:
                response = await client.request(url, addresses, max_bytes)
                record.update(status=response.status_code, bytes=len(response.body), sha256=hashlib.sha256(response.body).hexdigest())
                if response.status_code == 200:
                    file = WORK / f"openlearn-source-{len(report['requests'])}.html"
                    file.write_bytes(response.body)
                    record["file"] = str(file.relative_to(ROOT)).replace("\\", "/")
                    bodies[url] = response.body
                return response
            except Exception as exc:
                record["error_type"] = type(exc).__name__
                raise
    fetcher = Fetcher(config, http_client=Recorder())
    entry = "https://www.open.edu/openlearn/free-courses/full-catalogue"
    try:
        async with asyncio.timeout(100):
            metadata = await fetcher.enrich({"url": entry, "source": "explicit_catalogue_probe"})
            report["documents"].append({"url": entry, "metadata": metadata})
            if metadata["fetch_status"] == "fetched" and entry in bodies:
                soup = BeautifulSoup(bodies[entry], "html.parser")
                links = []
                for a in soup.select("a[href]"):
                    try:
                        href = normalize_url(urljoin(entry, str(a['href'])))
                    except (UnsafeURL, ValueError):
                        continue
                    if urlsplit(href).hostname == "www.open.edu" and "/openlearn/" in href and "/content-section-overview" in href and a.get_text(" ", strip=True):
                        if href not in [x['url'] for x in links]:
                            links.append({"title": a.get_text(" ", strip=True), "url": href})
                report["visible_course_links"] = links[:20]
                if links:
                    selected = links[0]
                    metadata = await fetcher.enrich({**selected, "source": "observed_catalogue_link", "source_url": entry})
                    report["documents"].append({"url": selected['url'], "metadata": metadata})
    except Exception as exc:
        report["error_type"] = type(exc).__name__
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"documents": [{"url": d['url'], "status": d['metadata']['fetch_status']} for d in report['documents']], "target_and_robots_http":len(report['requests'])}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
