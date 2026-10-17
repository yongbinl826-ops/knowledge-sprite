"""One explicitly authorized phased-transport run; importing never accesses network."""
from __future__ import annotations

import asyncio
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
from backend.app.fetcher import Fetcher, FetcherConfig, NETWORK_OBSERVER, PinnedHTTPClient
from backend.app.models import SearchRequest
from backend.app.ranking import has_course_page, has_video_evidence
from backend.app.service import JobService
from scripts.live_acceptance_revision import audit_resource_evidence
from scripts.verify_official_discovery import AuditedDNS, AuditedHTTP, NetworkAudit, now, sha

WORK = ROOT / "reports/completion-20261013"
SCOPE = WORK / "mit-transport-revision-scope.json"


class PhasedAuditedHTTP(AuditedHTTP):
    """Same independent run-wide guard, plus phase record and XML byte cap."""
    def __init__(self, audit, transport, xml_max_bytes=500000):
        super().__init__(audit, transport)
        self.xml_max_bytes = xml_max_bytes

    async def request(self, url, addresses, max_bytes):
        if urlsplit(url).path.lower().endswith(".xml"):
            max_bytes = min(max_bytes, self.xml_max_bytes)
        parent = NETWORK_OBSERVER.get() or {}
        observed = []
        def trace(record):
            # super.request reserves the target row before invoking the transport.
            # Attach the same mutable record so cancellation retains partial bytes.
            self.audit.target[-1]["transport"] = record
            observed.append((self.audit.target[-1], record))
            if parent.get("transport_trace"):
                parent["transport_trace"](record)
            self.audit.save()
        token = NETWORK_OBSERVER.set({**parent, "transport_trace": trace})
        try:
            return await super().request(url, addresses, max_bytes)
        finally:
            NETWORK_OBSERVER.reset(token)
            for row, record in observed:
                row.update(body_complete=record["body_complete"], bytes_read=record["bytes_read"])
                if row["status_code"] is None:
                    row["status_code"] = record.get("http_status")
                if record.get("partial_body"):
                    row["partial_body_sha256"] = record.get("body_sha256")
            self.audit.save()


def source_hashes():
    paths = sorted((ROOT / "backend/app").rglob("*.py")) + [Path(__file__),
        ROOT / "scripts/verify_official_discovery.py", ROOT / "scripts/live_acceptance_revision.py", SCOPE]
    return {str(path.relative_to(ROOT)).replace("\\", "/"): sha(path.read_bytes()) for path in paths}


async def main():
    scope = json.loads(SCOPE.read_text(encoding="utf-8"))
    output, database, sources = (ROOT / scope[key] for key in ("output", "database", "source_directory"))
    if output.exists() or database.exists() or sources.exists():
        raise SystemExit("Refusing to overwrite or rerun the MIT transport revision")
    preserved = {name: sha((WORK / name).read_bytes()) for name in
        ("mit-discovery-probe.json", "official-repair-live.json", "held-out-live.json")}
    sources.mkdir()
    report = {"started_at": now(), "classification": scope["classification"], "scope": scope,
        "scope_sha256": sha(SCOPE.read_bytes()), "source_hashes_before": source_hashes(),
        "preserved_reports_before": preserved, "target_requests": [], "doh_requests": [], "errors": []}
    def save():
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    audit = NetworkAudit(scope["target_http_max"], scope["doh_http_max"], save, sources)
    report["target_requests"], report["doh_requests"] = audit.target, audit.dns
    settings = Settings(database_path=str(database), search_provider="official_sitemap", global_concurrency=1,
        max_search_requests=scope["target_http_max"], max_detail_pages=scope["target_http_max"],
        deadline_seconds=scope["deadline_seconds"], search_max_retries=0,
        fetch_timeout_seconds=scope["first_response_timeout_seconds"], dns_resolver="cloudflare_doh",
        official_sitemap_children_per_query=1, llm_provider="none")
    config = FetcherConfig(global_concurrency=1, max_retries=0, max_bytes=scope["target_max_bytes"],
        timeout_seconds=scope["first_response_timeout_seconds"], dns_resolver="cloudflare_doh", min_interval_seconds=0.5,
        phased_timeouts=True, body_idle_timeout_seconds=scope["body_idle_timeout_seconds"],
        body_min_bytes_per_second=scope["body_min_bytes_per_second"],
        body_timeout_cap_seconds=scope["body_timeout_cap_seconds"])
    fetcher = Fetcher(config, resolver=AuditedDNS(audit),
        http_client=PhasedAuditedHTTP(audit, PinnedHTTPClient(config), scope["xml_max_bytes"]))
    store = Store(str(database))
    service = JobService(settings, store, fetcher=fetcher)
    started = time.monotonic()
    save()
    jid = None
    try:
        async with asyncio.timeout(scope["deadline_seconds"]):
            service.start()
            payload = SearchRequest(knowledge_points=scope["knowledge_points"], language="en",
                student_level="any", preferred_platforms=[])
            report["create_response"] = service.create(payload, "mit-transport-revision-single-run")
            jid = report["job_id"] = report["create_response"]["job_id"]
            report["capabilities"] = service.capabilities()
            save()
            await service.queue.join()
    except BaseException as exc:
        report["errors"].append({"type": type(exc).__name__, "message": "Stopped without replacement or retry"})
        audit.stopped = audit.stopped or "run_deadline_or_cancellation"
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
        report["preserved_reports_unchanged"] = all(value == sha((WORK / name).read_bytes()) for name, value in preserved.items())
        report["source_unchanged"] = report["source_hashes_before"] == report["source_hashes_after"]
        report["budget_checks"] = {"target": len(audit.target) <= scope["target_http_max"],
            "doh": len(audit.dns) <= scope["doh_http_max"],
            "total": len(audit.target) + len(audit.dns) <= scope["total_http_max"]}
        report["network_stop_reason"] = audit.stopped
        report["interpretation"] = "Inspect actual stage/partial-byte telemetry and independent source/page/catalog evidence. Completion is not acceptance; original failed stage remains unknown."
        save()
        print(json.dumps({"report": str(output), "job_id": jid, "status": report.get("final_job", {}).get("status"),
            "target_http": len(audit.target), "doh_http": len(audit.dns), "errors": report["errors"]}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
