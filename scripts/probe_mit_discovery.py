"""Single bounded MIT discovery probe; no production/SQLite/search-engine writes."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import time
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import httpx
from bs4 import BeautifulSoup
from backend.app.fetcher import Fetcher, FetcherConfig, FetchStopped, PinnedHTTPClient
from backend.app.url_utils import UnsafeURL, normalize_url

WORK = ROOT / "reports/completion-20261013"
OUTPUT = WORK / "mit-discovery-probe.json"
SCOPE_PATH = WORK / "mit-discovery-probe-scope.json"


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def same_origin_url(base, value):
    try:
        url = normalize_url(urljoin(base, value))
        parts = urlsplit(url)
        if parts.scheme == "https" and parts.hostname == "ocw.mit.edu" and parts.port in (None, 443):
            return url
    except (UnsafeURL, ValueError, TypeError):
        pass
    return None


def inspect_html(body, url):
    soup = BeautifulSoup(body, "html.parser")
    courses = {}
    for link in soup.select("a[href]"):
        href = same_origin_url(url, link.get("href", ""))
        if href and re.fullmatch(r"/courses/[^/]+/?", urlsplit(href).path):
            courses.setdefault(href, link.get_text(" ", strip=True)[:500] or None)
    forms = []
    for form in soup.select("form"):
        action = same_origin_url(url, form.get("action") or url)
        controls = [{"name": node.get("name"), "type": node.get("type", "text"),
                     "placeholder": str(node.get("placeholder", ""))[:200]}
                    for node in form.select("input,textarea")]
        forms.append({"action": action, "method": str(form.get("method", "get")).lower(), "controls": controls})
    declarations = []
    for script in soup.select("script"):
        script_type = str(script.get("type", ""))
        if script_type in {"application/json", "application/ld+json"}:
            raw = script.string or script.get_text()
            try:
                value = json.loads(raw)
                declarations.append({"type": script_type, "id": script.get("id"), "bytes": len(raw.encode()),
                    "sha256": sha(raw.encode()), "top_level_keys": list(value)[:30] if isinstance(value, dict) else None})
            except (ValueError, TypeError):
                declarations.append({"type": script_type, "parse_status": "invalid_json"})
    return {"title": soup.title.get_text(" ", strip=True) if soup.title else None,
        "visible_course_link_count": len(courses), "visible_course_links": [{"url": k, "title": v} for k, v in list(courses.items())[:30]],
        "forms": forms[:20], "json_declarations": declarations[:20],
        "script_assets_observed_not_requested": [str(node.get("src"))[:1000] for node in soup.select("script[src]")][:20],
        "search_mounts": [{"id": node.get("id"), "class": node.get("class")} for node in soup.select("[id*='search']")][:20]}


async def main():
    if OUTPUT.exists():
        raise SystemExit("Refusing to overwrite or rerun the MIT discovery probe")
    scope = json.loads(SCOPE_PATH.read_text(encoding="utf-8"))
    budget = scope["budgets"]
    report = {"started_at": now(), "scope": scope, "scope_sha256": sha(SCOPE_PATH.read_bytes()),
        "code_sha256": {str(p.relative_to(ROOT)).replace("\\", "/"): sha(p.read_bytes()) for p in
            [Path(__file__), ROOT / "backend/app/fetcher.py", ROOT / "backend/app/url_utils.py"]},
        "requests": [], "documents": [], "events": [], "counts": {"target": 0, "doh": 0},
        "dynamic_discovery_verified": False, "production_changed": False}
    bodies = {}
    actual_client = httpx.AsyncClient
    active = 0
    config = FetcherConfig(global_concurrency=1, max_retries=0, timeout_seconds=10,
        max_bytes=budget["target_response_max_bytes"], max_redirects=2,
        min_interval_seconds=0.5, dns_resolver="cloudflare_doh")
    pinned = PinnedHTTPClient(config)

    def save():
        OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    async def before_request(request):
        nonlocal active
        is_doh = request.url.host == "1.1.1.1" and request.url.path == "/dns-query"
        kind = "doh" if is_doh else "target"
        limit = budget["doh_http"] if is_doh else budget["target_http_including_robots_html_xml_redirects"]
        if report["counts"][kind] >= limit or len(report["requests"]) >= budget["total_actual_http"]:
            raise FetchStopped("budget_exceeded", "Probe HTTP budget reached")
        if active:
            raise FetchStopped("concurrency_error", "Concurrent probe HTTP is prohibited")
        original = str(request.url) if is_doh else str(request.url.copy_with(host=request.headers["host"]))
        if not is_doh and not same_origin_url(scope["entry_url"], original):
            raise FetchStopped("scope_stop", "Redirect target outside the approved origin")
        record = {"sequence": len(report["requests"]) + 1, "kind": kind, "url": original,
            "started_at": now(), "status_code": None, "error_type": None, "truncated": False,
            "body_bytes_read": 0, "body_sha256": None, "body_complete": False}
        request.extensions["probe_record"] = record
        report["requests"].append(record)
        report["counts"][kind] += 1
        active += 1
        save()

    async def after_response(response):
        record = response.request.extensions["probe_record"]
        record.update(response_headers_at=now(), status_code=response.status_code, content_type=response.headers.get("content-type"),
            content_length=response.headers.get("content-length"), location=response.headers.get("location"))
        original_iter = response.aiter_raw
        async def observed_raw(*args, **kwargs):
            digest = hashlib.sha256()
            try:
                async for chunk in original_iter(*args, **kwargs):
                    digest.update(chunk)
                    record["body_bytes_read"] += len(chunk)
                    record["body_sha256"] = digest.hexdigest()
                    yield chunk
                record["body_complete"] = True
                record["body_sha256"] = digest.hexdigest()
                record["body_completed_at"] = now()
            finally:
                if record["body_bytes_read"] and not record["body_complete"]:
                    record["truncated"] = True
        response.aiter_raw = observed_raw

    class RecordedClient(actual_client):
        def __init__(self, *args, **kwargs):
            kwargs["event_hooks"] = {"request": [before_request], "response": [after_response]}
            super().__init__(*args, **kwargs)

        async def send(self, request, *args, **kwargs):
            nonlocal active
            try:
                return await super().send(request, *args, **kwargs)
            except BaseException as exc:
                record = request.extensions.get("probe_record")
                if record:
                    record["error_type"] = type(exc).__name__
                raise
            finally:
                # Each actual client is one sequential stream; no other request can
                # start before the calling stream context has consumed/closed it.
                if request.extensions.get("probe_record"):
                    active -= 1

        async def __aexit__(self, exc_type, exc, tb):
            result = await super().__aexit__(exc_type, exc, tb)
            for record in report["requests"]:
                if "finished_at" not in record:
                    record["finished_at"] = now()
                    if exc_type:
                        record["error_type"] = exc_type.__name__
                        record["stop_status"] = getattr(exc, "status", None)
                        if getattr(exc, "status", None) == "too_large":
                            record["truncated"] = True
            save()
            return result

    class Recorder:
        async def request(self, url, addresses, max_bytes):
            parts = urlsplit(url)
            cap = min(max_bytes, budget["sitemap_response_max_bytes"]) if parts.path.lower().endswith(".xml") else max_bytes
            result = await pinned.request(url, addresses, cap)
            record = next(r for r in reversed(report["requests"]) if r["kind"] == "target" and r["url"] == url)
            record["pinned_public_addresses"] = addresses
            record["max_bytes"] = cap
            if result.status_code == 200:
                suffix = ".xml" if "xml" in result.headers.get("content-type", "") or parts.path.endswith(".xml") else ".txt" if parts.path.endswith("robots.txt") else ".html"
                path = WORK / f"mit-discovery-source-{record['sequence']}{suffix}"
                path.write_bytes(result.body)
                record.update(source_file=str(path.relative_to(ROOT)).replace("\\", "/"), source_sha256=sha(result.body))
                bodies[url] = result.body
            save()
            return result

    httpx.AsyncClient = RecordedClient
    fetcher = Fetcher(config, http_client=Recorder())
    started = time.perf_counter()
    save()
    try:
        async with asyncio.timeout(budget["deadline_seconds"]):
            entry = scope["entry_url"]
            response = await fetcher.fetch(entry)
            if response.status_code != 200:
                raise FetchStopped("http_error", "Search entry did not return 200")
            access = fetcher.extractor.extract(response.body.decode("utf-8", errors="replace"), response.url, now())
            if access.get("fetch_status") in {"captcha", "access_denied", "login_required", "error_page", "not_found"}:
                raise FetchStopped(access["fetch_status"], "Search entry access restriction or error page")
            page = inspect_html(response.body, response.url)
            report["documents"].append({"role": "search_entry", "url": response.url, "observations": page})
            save()
            chosen = None
            for form in page["forms"]:
                if form["method"] != "get" or not form["action"]:
                    continue
                control = next((node for node in form["controls"] if node["name"] and
                    (node["type"] == "search" or re.search("search|query", str(node["name"]) + " " + node["placeholder"], re.I)
                     or node["name"] == "q" and "/search" in urlsplit(form["action"]).path)), None)
                if control:
                    parts = urlsplit(form["action"])
                    query = [(k, v) for k, v in parse_qsl(parts.query) if k != control["name"]]
                    chosen = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode([*query, (control["name"], scope["probe_topic"])]), ""))
                    report["selection"] = {"kind": "observed_get_search_form", "action": form["action"], "parameter": control["name"], "url": chosen}
                    break
            if chosen:
                response = await fetcher.fetch(chosen)
                if response.status_code != 200:
                    raise FetchStopped("http_error", "Observed search form did not return 200")
                observations = inspect_html(response.body, response.url)
                report["documents"].append({"role": "one_observed_form_query", "url": response.url, "observations": observations})
                report["dynamic_discovery_verified"] = False
                report["assessment"] = "A public GET form was queried once. Returned links alone do not establish arbitrary-topic relevance or complete provider feasibility; inspect preserved HTML."
            else:
                maps = []
                for url, body in bodies.items():
                    if urlsplit(url).path.endswith("robots.txt"):
                        for line in body.decode("utf-8-sig", errors="replace").splitlines():
                            if line.lower().startswith("sitemap:"):
                                observed = same_origin_url(url, line.split(":", 1)[1].strip())
                                if observed:
                                    maps.append({"url": observed, "declared_at": url, "source_sha256": sha(body)})
                report["robots_declared_sitemaps"] = maps
                if maps and report["counts"]["target"] < budget["target_http_including_robots_html_xml_redirects"]:
                    chosen = maps[0]["url"]
                    report["selection"] = {"kind": "first_robots_declared_sitemap", **maps[0]}
                    response = await fetcher.fetch(chosen)
                    if response.status_code != 200:
                        raise FetchStopped("http_error", "Declared sitemap did not return 200")
                    tree = ET.fromstring(response.body)
                    locations = [node.text for node in tree.iter() if node.tag.rsplit("}", 1)[-1] == "loc" and node.text]
                    report["documents"].append({"role": "declared_sitemap", "url": response.url,
                        "root_element": tree.tag.rsplit("}", 1)[-1], "location_count": len(locations), "locations_first_30": locations[:30], "recursive_followups": 0})
                    report["assessment"] = "One declared sitemap observed; indexing/query support and arbitrary-topic relevance remain unverified. No recursive crawl or course-page requests."
                else:
                    report["assessment"] = "No usable public GET form and no eligible robots-declared sitemap within budget. Dynamic official discovery is unverified."
    except BaseException as exc:
        report["stop"] = {"at": now(), "error_type": type(exc).__name__, "status": getattr(exc, "status", None),
            "message": "Stopped once; no fallback/retry/replacement request. Dynamic official discovery remains unverified."}
    finally:
        httpx.AsyncClient = actual_client
        report.update(finished_at=now(), elapsed_seconds=round(time.perf_counter() - started, 3),
            total_actual_http=len(report["requests"]), fetch_events=list(fetcher.request_trace),
            fetch_counts=dict(fetcher.trace_counts))
        report["budgets_respected"] = report["counts"]["target"] <= 4 and report["counts"]["doh"] <= 12 and len(report["requests"]) <= 16
        save()
        print(json.dumps({"report": str(OUTPUT), "counts": report["counts"], "elapsed_seconds": report["elapsed_seconds"],
            "stop": report.get("stop"), "assessment": report.get("assessment")}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
