"""Portable local transport/admission checks; no active settings or user DB."""
import asyncio
import importlib.util
import os
from pathlib import Path
import socket

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("local_load_harness", ROOT / "scripts" / "validate_local_load.py")
harness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(harness)


def test_percentiles_are_observed_nearest_rank_not_average():
    assert harness.percentile([], .95) is None
    assert harness.percentile([100, 1, 2, 3], .5) == 2
    assert harness.percentile([100, 1, 2, 3], .95) == 100


def test_metrics_preserve_expected_rejection_separately():
    measured = harness.aggregate([
        {"operation": "admission", "status": 202, "ms": 2},
        {"operation": "admission", "status": 429, "ms": 3},
        {"operation": "health", "status": 200, "ms": 1},
    ])
    assert measured["admission"]["status_counts"] == {"202": 1, "429": 1}
    assert measured["admission"]["requests"] == 2
    assert measured["health"]["p95_ms"] == 1


@pytest.mark.parametrize("host", ["example.com", "192.0.2.10", "10.1.2.3", "::ffff:192.0.2.10"])
def test_external_dns_and_connect_rejected_before_transport(host, monkeypatch):
    calls = []
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kw: calls.append(args))
    with harness.LoopbackOnly() as guard:
        with pytest.raises(PermissionError):
            socket.getaddrinfo(host, 443)
        with socket.socket() as sock:
            with pytest.raises(PermissionError):
                sock.connect((host, 443))
            with pytest.raises(PermissionError):
                sock.connect_ex((host, 443))
        with socket.socket(type=socket.SOCK_DGRAM) as udp:
            with pytest.raises(PermissionError):
                udp.sendto(b"synthetic", (host, 443))
        assert guard.blocked == 4
    assert calls == []


def test_loopback_guard_restores_socket_functions_on_error(monkeypatch):
    calls = []
    original = lambda *args, **kw: calls.append(args) or []
    monkeypatch.setattr(socket, "getaddrinfo", original)
    with pytest.raises(ValueError):
        with harness.LoopbackOnly():
            assert socket.getaddrinfo("127.0.0.1", 1234) == []
            assert socket.getaddrinfo("::1", 1234) == []
            raise ValueError("synthetic error")
    assert socket.getaddrinfo is original
    assert len(calls) == 2


def test_mock_transport_accepts_only_declared_synthetic_destinations():
    import httpx
    async def run():
        world = harness.MockWorld(httpx)
        with pytest.raises(AssertionError, match="unknown upstream"):
            await world.respond(httpx.Request("GET", "https://example.com/"))
        assert world.calls == []
    asyncio.run(run())


def test_finite_real_loopback_application_boundaries(tmp_path):
    source = Path(os.environ.get("LOCAL_LOAD_SOURCE_ROOT", ROOT)).resolve()
    assert (source / "backend/app/main.py").is_file(), "Set only public LOCAL_LOAD_SOURCE_ROOT when testing the standalone candidate"
    report = asyncio.run(harness.run_suite(source, tmp_path / "local-load"))
    failed = [row for row in report["checks"] if not row["pass"]]
    assert failed == [], failed
    assert report["passed"]
    assert report["scope"]["source_and_model_real_HTTP"] == 0
    assert report["source_before"] == report["source_after"]
    assert report["details"]["normal"]["projects"] == 4
    assert report["details"]["normal"]["maxima"]["analysis"] == 2
    assert report["details"]["restart"]["new_mock_calls"] == []
    assert report["details"]["SSE"]["statuses"] == [200] * 16 + [429] * 4
    assert report["real_loopback_HTTP_requests"] > 50


def test_existing_output_is_not_overwritten(tmp_path):
    output = tmp_path / "existing"
    output.mkdir()
    marker = output / "marker.txt"
    marker.write_text("immutable", encoding="utf8")
    with pytest.raises(FileExistsError):
        asyncio.run(harness.run_suite(ROOT, output, []))
    assert marker.read_text(encoding="utf8") == "immutable"
