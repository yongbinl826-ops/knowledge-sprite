"""Independent protocol-driver safety checks; app controls are separate."""
import base64
import importlib.util
import json
from pathlib import Path
import sqlite3
import socket
import sys
from uuid import UUID
import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("mobile_boundary_probe", ROOT / "scripts/validate_mobile_boundary.py")
probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = probe
SPEC.loader.exec_module(probe)


def test_test_capabilities_are_ephemeral_canonical_32_bytes_and_not_repr():
    tickets = [probe.Ticket.fresh() for _ in range(8)]
    assert len({ticket.cap for ticket in tickets}) == 8
    assert len({ticket.task_id for ticket in tickets}) == 8
    for ticket in tickets:
        assert UUID(ticket.task_id).version == 4
        assert len(ticket.cap) == 43
        raw = base64.urlsafe_b64decode(ticket.cap + "=")
        assert len(raw) == 32
        assert base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii") == ticket.cap
        assert ticket.cap not in repr(ticket)
        assert ticket.cap not in ticket.path
        assert ticket.headers == {"Authorization": "Bearer " + ticket.cap}


def test_receipt_records_no_request_headers_payload_or_query_token():
    import asyncio
    import httpx
    ticket = probe.Ticket.fresh()
    async def run():
        async def respond(request):
            assert request.headers["Authorization"] == "Bearer " + ticket.cap
            return httpx.Response(404, json={"detail": "not found"})
        checks = probe.Checks()
        async with httpx.AsyncClient(base_url="http://127.0.0.1", transport=httpx.MockTransport(respond), trust_env=False) as client:
            await checks.request(client, "GET", ticket.path + "?token=" + ticket.cap, "query_token_no_auth", headers=ticket.headers)
        encoded = json.dumps(checks.receipt())
        assert ticket.cap not in encoded
        assert ticket.task_id not in encoded
        assert "Authorization" not in encoded
        assert set(checks.requests[0]) == {"label", "method", "status", "milliseconds", "retry_after"}
    asyncio.run(run())


def test_private_marker_scan_checks_all_synthetic_persistent_columns():
    # This in-memory test DB is not the application or any user database.
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("CREATE TABLE public_courses(id TEXT, metadata TEXT)")
        connection.execute("CREATE TABLE daily_aggregates(day TEXT, counter INTEGER)")
        connection.execute("INSERT INTO public_courses VALUES(?,?)", ("public-id", '{"title":"Public course"}'))
        connection.execute("INSERT INTO daily_aggregates VALUES(?,?)", ("2026-10-20", 2))
        assert probe.public_rows_do_not_contain_private_markers(connection, ["PRIVATE_SENTINEL"])
        connection.execute("INSERT INTO public_courses VALUES(?,?)", ("other", "PRIVATE_SENTINEL"))
        assert not probe.public_rows_do_not_contain_private_markers(connection, ["PRIVATE_SENTINEL"])
    finally:
        connection.close()


def test_transport_guard_denies_external_before_dns_tcp_or_udp(monkeypatch):
    seen = []
    original = lambda *args, **kwargs: seen.append(args)
    monkeypatch.setattr(socket, "getaddrinfo", original)
    with probe.LoopbackOnly() as guard:
        with pytest.raises(PermissionError): socket.getaddrinfo("example.com", 443)
        with socket.socket() as sock:
            with pytest.raises(PermissionError): sock.connect(("192.0.2.1", 443))
            with pytest.raises(PermissionError): sock.connect_ex(("192.0.2.1", 443))
        with socket.socket(type=socket.SOCK_DGRAM) as udp:
            with pytest.raises(PermissionError): udp.sendto(b"synthetic", ("192.0.2.1", 53))
        assert guard.blocked == 4
    assert seen == []
    assert socket.getaddrinfo is original
