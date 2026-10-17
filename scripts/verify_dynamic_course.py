"""One bounded real entry-to-DOM verification; no search or playback claim."""
import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.config import Settings
from backend.app.db import Store
from backend.app.fetcher import Fetcher, FetcherConfig, PinnedHTTPClient, CloudflareDoHResolver, FetchStopped, NETWORK_OBSERVER
from backend.app.service import JobService
from backend.app.ranking import has_course_page, has_video_evidence

OUT = ROOT / "reports/runtime-revision-20261013"
SCOPE_PATH = OUT / "dynamic-course-scope.json"


def stamp():
    return datetime.now(timezone.utc).isoformat()


def sha(body):
    return hashlib.sha256(body).hexdigest()


def hashes():
    return {str(path.relative_to(ROOT)): sha(path.read_bytes()) for path in
        [*sorted((ROOT / "backend/app").rglob("*.py")), ROOT / "backend/renderer_worker/worker.mjs", Path(__file__), SCOPE_PATH]}


async def main():
    scope = json.loads(SCOPE_PATH.read_text(encoding="utf-8"))
    output = OUT / "dynamic-course-live.json"
    source_dir = OUT / "dynamic-course-sources"
    if output.exists() or source_dir.exists():
        raise SystemExit("Refusing to overwrite or automatically rerun dynamic acceptance")
    source_dir.mkdir()
    report = {"scope": scope, "started_at": stamp(), "source_hashes_before": hashes(),
        "targets": [], "dns": [], "sources": [], "stop_reason": None}
    started = time.monotonic()
    def save():
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    def guard(url):
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.port not in (None, 443) or parts.hostname not in scope["hosts"]:
            raise FetchStopped("verification_scope", "Outside exact HTTPS host scope")
        if report["stop_reason"]:
            raise FetchStopped("verification_stopped", "Prior request stopped this run")
        if len(report["targets"]) >= scope["target_http_max"] or complete_bytes >= scope["max_total_bytes"]:
            raise FetchStopped("verification_budget", "Target or total byte limit reached before DNS")
    complete_bytes = 0
    class HTTP:
        def __init__(self, transport):
            self.transport, self.active = transport, False
        async def request(self, url, addresses, max_bytes):
            nonlocal complete_bytes
            guard(url)
            if self.active or len(report["targets"]) >= scope["target_http_max"]:
                raise FetchStopped("verification_budget", "Target concurrency or request limit")
            remaining = scope["max_total_bytes"] - complete_bytes
            if remaining <= 0:
                raise FetchStopped("verification_bytes", "Total byte limit")
            self.active = True
            row = {"url": url, "started_at": stamp(), "pinned_public_addresses": addresses}
            report["targets"].append(row)
            parent = NETWORK_OBSERVER.get() or {}
            def transport_trace(value):
                row["transport"] = value
                if parent.get("transport_trace"):
                    parent["transport_trace"](value)
            token = NETWORK_OBSERVER.set({**parent, "transport_trace": transport_trace})
            save()
            try:
                result = await self.transport.request(url, addresses, min(max_bytes, remaining))
                complete_bytes += len(result.body)
                row.update(status=result.status_code, bytes=len(result.body), sha256=sha(result.body), content_type=result.headers.get("content-type"))
                if result.status_code in {401, 403, 429} or result.status_code >= 500:
                    report["stop_reason"] = "http_" + str(result.status_code)
                filename = "source-" + str(len(report["sources"]) + 1) + ".txt"
                (source_dir / filename).write_bytes(result.body)
                report["sources"].append(dict(row, file=filename))
                if result.url == scope["entry"] and result.status_code == 200:
                    report["static_extraction"] = fetcher.extractor.extract(result.body.decode("utf-8"), result.url, stamp())
                return result
            except BaseException as exc:
                row["error"] = type(exc).__name__
                report["stop_reason"] = report["stop_reason"] or getattr(exc, "status", type(exc).__name__)
                raise
            finally:
                self.active = False
                NETWORK_OBSERVER.reset(token)
                row["finished_at"] = stamp()
                save()
    class DNS(CloudflareDoHResolver):
        async def __call__(self, url, timeout=8):
            guard(url)
            parent = NETWORK_OBSERVER.get() or {}
            async def before():
                guard(url)
                if len(report["dns"]) >= scope["doh_http_max"]:
                    raise FetchStopped("verification_budget", "DoH limit")
                if parent.get("before_dns_http"):
                    await parent["before_dns_http"]()
            def trace(value):
                report["dns"].append(value)
                if parent.get("dns_trace"):
                    parent["dns_trace"](value)
                save()
            token = NETWORK_OBSERVER.set({**parent, "before_dns_http": before, "dns_trace": trace})
            try:
                return await super().__call__(url, timeout)
            except BaseException as exc:
                report["stop_reason"] = type(exc).__name__
                raise
            finally:
                NETWORK_OBSERVER.reset(token)
    settings = Settings(search_provider="searxng", global_concurrency=1, fetch_phased_timeouts=True,
        fetch_timeout_seconds=10, fetch_body_timeout_cap_seconds=10, js_render_enabled=True,
        js_render_allowed_hosts=("microsoft.github.io",), js_render_asset_hosts=("cdn.jsdelivr.net",),
        js_render_timeout_seconds=90, js_render_max_resources=6, js_render_max_target_requests=10,
        js_render_max_doh_requests=20, js_render_max_total_bytes=2_000_000, dns_resolver="cloudflare_doh")
    config = FetcherConfig(global_concurrency=1, max_retries=0, timeout_seconds=10, phased_timeouts=True,
        body_timeout_cap_seconds=10, max_bytes=500_000, dns_resolver="cloudflare_doh")
    fetcher = Fetcher(config, resolver=DNS(), http_client=HTTP(PinnedHTTPClient(config)))
    store = Store(":memory:")
    service = JobService(settings, store, fetcher=fetcher)
    report["capabilities"] = service.capabilities()
    save()
    try:
        async with asyncio.timeout(scope["deadline_seconds"]):
            resource = await fetcher.enrich({"url": scope["entry"], "source": "direct_public_entry_validation"})
            report["resource"] = resource
            result = fetcher.renderer.last_result
            if result and result.html:
                (source_dir / "rendered-dom.html").write_text(result.html, encoding="utf-8")
            report["acceptance"] = {
                "rendered": bool(result and result.status == "rendered"),
                "real_course_page": has_course_page(resource, resource["evidence"]),
                "static_chapters": len(report.get("static_extraction", {}).get("chapters", [])),
                "dynamic_chapters": len(resource.get("chapters", [])),
                "video_structure": has_video_evidence(resource, resource["evidence"]),
                "search_discovery": "not_tested_direct_entry_scope", "playback": "not_tested"}
    except BaseException as exc:
        report["error"] = {"type": type(exc).__name__, "status": getattr(exc, "status", None)}
    finally:
        store.close()
        report.update(finished_at=stamp(), elapsed_seconds=round(time.monotonic()-started, 3),
            target_http_count=len(report["targets"]), doh_http_count=len(report["dns"]),
            complete_response_bytes=complete_bytes, trace=list(fetcher.request_trace), source_hashes_after=hashes())
        report["source_unchanged"] = report["source_hashes_before"] == report["source_hashes_after"]
        save()
    print(json.dumps({k:report.get(k) for k in ("acceptance", "error", "stop_reason", "target_http_count", "doh_http_count", "elapsed_seconds")}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
