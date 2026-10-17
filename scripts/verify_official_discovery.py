"""Single real repair verification, with independent transport/DNS hard budgets.

Never run automatically from tests. The saved scope is development verification,
not an independent held-out case. Refuses prior outputs or an existing database.
"""
from __future__ import annotations

import asyncio
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
from backend.app.fetcher import CloudflareDoHResolver, Fetcher, FetcherConfig, FetchStopped, NETWORK_OBSERVER, PinnedHTTPClient
from backend.app.models import SearchRequest
from backend.app.official_sitemap import official_url
from backend.app.ranking import has_course_page, has_video_evidence
from backend.app.service import JobService
from scripts.live_acceptance_revision import audit_resource_evidence

WORK = ROOT / "reports/completion-20261013"
SCOPE = WORK / "official-repair-scope.json"


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(data):
    return hashlib.sha256(data).hexdigest()


class NetworkAudit:
    """Independent run-wide counters, not overwritten by provider task context."""
    def __init__(self, target_limit=12, dns_limit=24, save=lambda: None, source_dir=None):
        self.target_limit, self.dns_limit = target_limit, dns_limit
        self.target, self.dns = [], []
        self.save = save
        self.source_dir = source_dir
        self.stopped = None

    def check_target(self):
        if self.stopped:
            raise FetchStopped("verification_stopped", "Repair verification has already stopped")
        if len(self.target) >= self.target_limit:
            raise FetchStopped("verification_budget", "Repair verification target HTTP budget reached")

    def check_dns(self):
        if len(self.dns) >= self.dns_limit:
            raise FetchStopped("verification_budget", "Repair verification DoH HTTP budget reached")


class AuditedHTTP:
    def __init__(self, audit, transport):
        self.audit, self.transport = audit, transport
        self.active = 0

    async def request(self, url, addresses, max_bytes):
        self.audit.check_target()
        if not official_url(url):
            self.audit.stopped = "outside_approved_origin"
            raise FetchStopped("verification_scope", "Repair verification only permits same-origin MIT HTTPS")
        if self.active:
            raise FetchStopped("verification_concurrency", "Concurrent target requests are outside scope")
        self.active += 1
        record = {"sequence": len(self.audit.target) + 1, "url": url, "started_at": now(),
            "status_code": None, "error_type": None, "truncated": False,
            "max_bytes": min(max_bytes, 2_000_000), "pinned_public_addresses": list(addresses)}
        self.audit.target.append(record)
        started = time.monotonic()
        self.audit.save()
        try:
            response = await self.transport.request(url, addresses, record["max_bytes"])
            record.update(status_code=response.status_code, bytes=len(response.body), source_sha256=sha(response.body),
                content_type=response.headers.get("content-type"), location=response.headers.get("location"))
            if response.status_code in {401, 403, 429} or response.status_code == 503 and "retry-after" in response.headers:
                self.audit.stopped = f"target_http_{response.status_code}"
                record["retry_after"] = response.headers.get("retry-after")
            if self.audit.source_dir and response.status_code == 200:
                suffix = ".xml" if "xml" in response.headers.get("content-type", "") else ".txt" if urlsplit(url).path.endswith("robots.txt") else ".html"
                path = self.audit.source_dir / f"official-repair-source-{record['sequence']}{suffix}"
                path.write_bytes(response.body)
                record["source_file"] = str(path.relative_to(ROOT)).replace("\\", "/")
            return response
        except BaseException as exc:
            record.update(error_type=type(exc).__name__, stop_status=getattr(exc, "status", None),
                truncated=getattr(exc, "status", None) == "too_large")
            self.audit.stopped = self.audit.stopped or "target_error"
            raise
        finally:
            record.update(finished_at=now(), elapsed_seconds=round(time.monotonic() - started, 3))
            self.active -= 1
            self.audit.save()


class AuditedDNS(CloudflareDoHResolver):
    def __init__(self, audit):
        self.audit = audit

    async def __call__(self, url, timeout=8):
        # Runs inside every real resolution, after the Provider has installed its
        # observer. Thus no outer observer can be silently replaced or bypassed.
        self.audit.check_target()
        if not official_url(url):
            self.audit.stopped = "outside_approved_origin"
            raise FetchStopped("verification_scope", "Repair verification only permits same-origin MIT HTTPS")
        parent = NETWORK_OBSERVER.get() or {}
        async def before_dns():
            self.audit.check_target()
            self.audit.check_dns()
            if parent.get("before_dns_http"):
                await parent["before_dns_http"]()
        def dns_trace(record):
            self.audit.dns.append(record)
            if parent.get("dns_trace"):
                parent["dns_trace"](record)
            self.audit.save()
        token = NETWORK_OBSERVER.set({**parent, "before_dns_http": before_dns, "dns_trace": dns_trace, "max_retries": 0})
        try:
            return await super().__call__(url, timeout)
        except BaseException:
            self.audit.stopped = self.audit.stopped or "dns_error"
            raise
        finally:
            NETWORK_OBSERVER.reset(token)
            self.audit.save()


def source_hashes():
    paths = sorted((ROOT / "backend/app").rglob("*.py")) + [Path(__file__), SCOPE]
    return {str(path.relative_to(ROOT)).replace("\\", "/"): sha(path.read_bytes()) for path in paths}


async def main():
    scope = json.loads(SCOPE.read_text(encoding="utf-8"))
    output, database = ROOT / scope["output"], ROOT / scope["database"]
    if output.exists() or database.exists():
        raise SystemExit("Refusing to overwrite or rerun a repair verification")
    heldout = WORK / "held-out-live.json"
    old_hash = sha(heldout.read_bytes()) if heldout.exists() else None
    report = {"started_at": now(), "classification": scope["classification"], "scope": scope,
        "scope_sha256": sha(SCOPE.read_bytes()), "source_hashes_before": source_hashes(),
        "previous_heldout_sha256": old_hash, "target_requests": [], "doh_requests": [], "errors": []}
    def save():
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    audit = NetworkAudit(scope["target_http_max"], scope["doh_http_max"], save, WORK)
    report["target_requests"], report["doh_requests"] = audit.target, audit.dns
    settings = Settings(database_path=str(database), search_provider="official_sitemap", global_concurrency=1,
        max_search_requests=12, max_detail_pages=12, deadline_seconds=scope["deadline_seconds"],
        search_max_retries=0, fetch_timeout_seconds=10, dns_resolver="cloudflare_doh",
        official_sitemap_children_per_query=1, llm_provider="none")
    config = FetcherConfig(global_concurrency=1, max_retries=0, max_bytes=scope["target_max_bytes"],
        timeout_seconds=10, dns_resolver="cloudflare_doh", min_interval_seconds=0.5)
    fetcher = Fetcher(config, resolver=AuditedDNS(audit), http_client=AuditedHTTP(audit, PinnedHTTPClient(config)))
    store = Store(str(database))
    service = JobService(settings, store, fetcher=fetcher)
    started = time.monotonic()
    save()
    jid = None
    try:
        service.start()
        payload = SearchRequest(knowledge_points=scope["knowledge_points"], language=scope["language"],
            student_level=scope["student_level"], preferred_platforms=scope["preferred_platforms"])
        report["create_response"] = service.create(payload, "official-repair-single-development-run")
        jid = report["job_id"] = report["create_response"]["job_id"]
        report["capabilities"] = service.capabilities()
        save()
        await asyncio.wait_for(service.queue.join(), scope["deadline_seconds"] + 10)
    except BaseException as exc:
        report["errors"].append({"type": type(exc).__name__, "message": "Stopped; retained original inputs/results, no retry"})
        if jid and store.get_job(jid)["status"] in {"queued", "running"}:
            await service.cancel(jid)
    finally:
        if jid:
            report["final_job"] = store.get_job(jid)
            report["results"] = service.results(jid)
            resources = {item["resource"]["resource_id"]: item for group in report["results"]["groups"]
                for item in [*group["items"], *(item for rows in group["platform_items"].values() for item in rows)]}
            report["resource_audits"] = [{"resource_id": rid, "url": item["resource"]["url"],
                "real_course_page": has_course_page(item["resource"], item["evidence"]),
                "video_evidence": has_video_evidence(item["resource"], item["evidence"]),
                **audit_resource_evidence(item)} for rid, item in resources.items()]
            report["stored_resources"] = list(store.resources(jid).values())
            report["stored_evidence"] = {rid: store.evidence(jid, rid) for rid in store.resources(jid)}
        await service.stop()
        store.close()
        report.update(finished_at=now(), elapsed_seconds=round(time.monotonic() - started, 3),
            actual_target_http=len(audit.target), actual_doh_http=len(audit.dns),
            total_actual_http=len(audit.target) + len(audit.dns), source_hashes_after=source_hashes(), playback_verified=False)
        report["previous_heldout_unchanged"] = old_hash == (sha(heldout.read_bytes()) if heldout.exists() else None)
        report["source_unchanged"] = report["source_hashes_before"] == report["source_hashes_after"]
        report["budget_checks"] = {"target": len(audit.target) <= 12, "doh": len(audit.dns) <= 24,
            "total": len(audit.target) + len(audit.dns) <= 36}
        report["network_stop_reason"] = audit.stopped
        report["interpretation"] = "Run collection completed; task status, actual source families and independently validated page/catalog fields determine the result. No independent-heldout or playback claim."
        save()
        print(json.dumps({"report": str(output), "job_id": jid, "status": report.get("final_job", {}).get("status"),
            "target_http": len(audit.target), "doh_http": len(audit.dns), "errors": report["errors"]}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
