"""Offline fixture preflight using production Fetcher guards, never real transport.

This module is deliberately not a production renderer adapter. All DNS and HTTP
responses are fixed in memory; missing entries fail and cannot fall back online.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.app.fetcher import Fetcher, FetcherConfig, HTTPResult
from backend.app.url_utils import UnsafeURL, normalize_url

FIXTURES = Path(__file__).parent / "fixtures"
ORIGIN = "https://renderer.example.org"
SCENARIOS = {"course", "missing", "post", "navigate", "guard", "frame", "wait"}


class FixtureHTTP:
    def __init__(self, responses):
        self.responses = responses
        self.requests = []

    async def request(self, url, addresses, max_bytes):
        self.requests.append(url)
        if url not in self.responses:
            raise RuntimeError("fixture_resource_missing_no_network_fallback")
        result = self.responses[url]
        if len(result.body) > max_bytes:
            raise ValueError("resource_byte_budget")
        return result


async def public_fixture_dns(url, timeout=8):
    # Synthetic public DNS answer, not a real DNS lookup.
    normalize_url(url)
    return ["93.184.216.34"]


def fixture_fetcher(responses, resolver=public_fixture_dns):
    transport = FixtureHTTP(responses)
    fetcher = Fetcher(FetcherConfig(max_bytes=100_000, max_retries=0, min_interval_seconds=0),
                      resolver=resolver, http_client=transport)
    return fetcher, transport


async def prepare(scenario="course", *, max_resources=8, max_total_bytes=100_000):
    if scenario not in SCENARIOS:
        raise ValueError("unknown_audited_fixture")
    entry = ORIGIN + "/course?scenario=" + scenario
    requested = [(entry, "course.html", "text/html"), (ORIGIN + "/course.js", "course.js", "application/javascript")]
    if len(requested) > max_resources:
        raise ValueError("resource_count_budget")
    responses = {ORIGIN + "/robots.txt": HTTPResult(200, {}, b"User-agent: *\nAllow: /\n", ORIGIN + "/robots.txt")}
    for url, name, mime in requested:
        responses[url] = HTTPResult(200, {"content-type": mime}, (FIXTURES / name).read_bytes(), url)
    fetcher, transport = fixture_fetcher(responses)
    resources, consumed = [], 0
    for url, name, mime in requested:
        response = await fetcher.fetch(url)
        if response.status_code != 200:
            raise ValueError("fixture_http_not_success")
        consumed += len(response.body)
        if consumed > max_total_bytes:
            raise ValueError("total_byte_budget")
        resources.append({"url": response.url, "fixture_file": name, "content_type": mime,
                          "body_b64": base64.b64encode(response.body).decode(),
                          "sha256": hashlib.sha256(response.body).hexdigest()})
    return {"mode": "audited_fixture_only", "scenario": scenario, "entry_url": entry, "resources": resources,
            "preflight": {"source": "Fetcher_with_in_memory_transport_and_DNS", "actual_network_requests": 0,
                          "fixture_http_requests": transport.requests, "bytes": consumed},
            "budgets": {"max_resources": max_resources, "max_total_bytes": max_total_bytes, "timeout_ms": 5000}}


if __name__ == "__main__":
    print(json.dumps(asyncio.run(prepare(sys.argv[1] if len(sys.argv) > 1 else "course"))))
