"""Audited local fixture tests; the app's production transport is never used."""
import asyncio
from copy import deepcopy
import ctypes
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location("controlled_preflight", HERE / "preflight.py")
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)
from backend.app.extractor import MetadataExtractor
from backend.app.fetcher import FetchStopped, HTTPResult
from backend.app.url_utils import UnsafeURL

ATTEMPTS = []


@pytest.fixture(scope="session", autouse=True)
def report():
    yield
    report_path = preflight.ROOT / "reports/completion-20261013/controlled-renderer-offline.json"
    # Preserve preceding attempts if tests are rerun, including failed assertions.
    existing = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {"runs": []}
    existing["runs"].append({"at": datetime.now(timezone.utc).isoformat(), "mode": "audited_local_fixtures_only",
        "real_site_scripts_executed": False, "production_remote_enabled": False,
        "process_egress_isolation": "unknown", "webrtc_udp_isolation": "unknown", "attempts": ATTEMPTS})
    report_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")


def alive(pid):
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
    kernel = ctypes.windll.kernel32
    kernel.OpenProcess.restype = ctypes.c_void_p
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    code = ctypes.c_ulong()
    kernel.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code))
    kernel.CloseHandle(ctypes.c_void_p(handle))
    return code.value == 259


async def bridge(payload, *, cancel=False, communication_timeout=20):
    process, result = None, None
    prefix, output, errors = b"", b"", b""
    forced_cleanup = False
    harness_error_type = cleanup_error_type = None
    phase = "launch"
    try:
        process = await asyncio.create_subprocess_exec("node", str(HERE / "renderer.mjs"),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=preflight.ROOT)
        phase = "write_request"
        process.stdin.write((json.dumps(payload) + "\n").encode())
        await process.stdin.drain()
        if cancel:
            phase = "ready"
            prefix = await asyncio.wait_for(process.stdout.readline(), 15)
            assert json.loads(prefix)["event"] == "ready"
            process.stdin.write(b'{"cancel":true}\n')
            await process.stdin.drain()
        phase = "communicate"
        output, errors = await asyncio.wait_for(process.communicate(), communication_timeout)
        phase = "parse_result"
        messages = [json.loads(line) for line in (prefix + output).splitlines()]
        result = next(message for message in reversed(messages) if message["event"] == "result")
        phase = "verify_cleanup"
        assert process.returncode == 0 and not errors
        if result.get("browser_pid"):
            assert result["cleanup"] == {"context_closed": True, "browser_exit_observed": True}
            assert not alive(result["browser_pid"])
        phase = "complete"
        return result
    except BaseException as exc:
        harness_error_type = type(exc).__name__
        if process is not None and process.returncode is None:
            forced_cleanup = True
            try:
                # Only this owned child tree is eligible; never kill all Edge processes.
                if os.name == "nt":
                    await asyncio.to_thread(subprocess.run, ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                            capture_output=True, timeout=5)
                else:
                    process.kill()
                await asyncio.wait_for(process.wait(), 5)
            except BaseException as cleanup_exc:
                # Keep the original failure; cleanup uncertainty is separately recorded.
                cleanup_error_type = type(cleanup_exc).__name__
        raise
    finally:
        ATTEMPTS.append({"scenario": payload.get("scenario", "none"),
            "result": {key: value for key, value in result.items() if key != "html"} if result else None,
            "node_exit_code": process.returncode if process is not None else None,
            "owned_process_pid": process.pid if process is not None else None,
            "forced_cleanup": forced_cleanup, "phase": phase, "harness_error_type": harness_error_type,
            "cleanup_error_type": cleanup_error_type,
            "stderr": errors.decode(errors="replace")[:1000],
            "stdout_excerpt_on_failure": (prefix + output).decode(errors="replace")[-1000:] if harness_error_type else None})


def run(payload, **kwargs):
    return asyncio.run(bridge(payload, **kwargs))


def package(scenario="course"):
    return asyncio.run(preflight.prepare(scenario))


def test_audited_js_generates_course_and_directory_with_no_playback_claim():
    payload = package()
    assert payload["preflight"]["actual_network_requests"] == 0
    assert len(payload["preflight"]["fixture_http_requests"]) == 3  # robots + two resources.
    result = run(payload)
    assert result["ok"] and len(result["fulfilled"]) == 2
    extracted = MetadataExtractor().extract(result["html"], payload["entry_url"], "offline-fixed-clock")
    assert extracted["resource_type"] == "course" and len(extracted["chapters"]) == 2
    assert extracted["title"] == "Synthetic Python lists course"
    assert [chapter["title"] for chapter in extracted["chapters"]] == ["Lists", "Iteration"]
    assert [chapter["url"] for chapter in extracted["chapters"]] == [
        preflight.ORIGIN + "/lesson/lists", preflight.ORIGIN + "/lesson/iteration"]
    evidence_by_id = {entry["evidence_id"]: entry for entry in extracted["evidence"]}
    for index, chapter in enumerate(extracted["chapters"]):
        assert chapter["evidence_id"] in evidence_by_id
        assert evidence_by_id[chapter["evidence_id"]]["field"] == f"chapters.{index}"
        assert json.loads(evidence_by_id[chapter["evidence_id"]]["text"])["title"] == chapter["title"]
    assert extracted["video_evidence_status"] == "none"
    assert result["isolation"]["process_network_egress"] == result["isolation"]["webrtc_udp_egress"] == "unknown"
    ATTEMPTS[-1]["dom_extraction_assertions"] = {
        "assertions_passed": True, "fixture_only": True,
        "course_name": extracted["title"], "resource_type": extracted["resource_type"],
        "chapters": extracted["chapters"], "chapter_count": len(extracted["chapters"]),
        "per_chapter_evidence_binding_checked": True,
        "video_evidence_status": extracted["video_evidence_status"], "playback_verified": False}


@pytest.mark.parametrize(("scenario", "status"), [("missing", "resource_not_preapproved"), ("post", "non_get"),
    ("navigate", "navigation_or_frame"), ("guard", "forbidden_operation"), ("frame", "frame")])
def test_missing_and_forbidden_browser_operations_fail_closed(scenario, status):
    result = run(package(scenario))
    assert not result["ok"] and result["status"] == status
    assert len(result["fulfilled"]) == 2


def test_cancel_closes_owned_browser_and_node_processes():
    result = run(package("wait"), cancel=True)
    assert not result["ok"] and result["status"] == "cancelled"


def test_render_deadline_closes_browser():
    payload = package("wait")
    payload["budgets"]["timeout_ms"] = 200
    result = run(payload)
    assert not result["ok"] and result["status"] == "timeout"


@pytest.mark.parametrize("kind", ["remote", "bytes", "resources", "integrity", "unapproved_resource"])
def test_default_remote_refusal_and_input_budgets_before_browser_launch(kind):
    payload = package()
    if kind == "remote":
        payload["mode"] = "remote"
    elif kind == "bytes":
        payload["budgets"]["max_total_bytes"] = 1
    elif kind == "resources":
        payload["budgets"]["max_resources"] = 1
    elif kind == "integrity":
        payload["resources"][0]["body_b64"] = "YXJiaXRyYXJ5IHNjcmlwdA=="
    else:
        payload["resources"][0]["url"] = "http://127.0.0.1/secret"
    result = run(payload)
    assert not result["ok"] and "browser_pid" not in result


def test_preflight_private_dns_private_redirect_and_robots_rejected_without_network():
    origin = preflight.ORIGIN
    def responses(location=None, robots=b"User-agent: *\nAllow: /\n"):
        return {origin + "/robots.txt": HTTPResult(200, {}, robots, origin + "/robots.txt"),
                origin + "/start": HTTPResult(302 if location else 200, {"location": location} if location else {}, b"", origin + "/start")}
    async def audit():
        async def private_dns(url, timeout=8):
            return ["127.0.0.1"]
        fetcher, transport = preflight.fixture_fetcher(responses(), private_dns)
        with pytest.raises(UnsafeURL):
            await fetcher.fetch(origin + "/start")
        assert transport.requests == []
        fetcher, transport = preflight.fixture_fetcher(responses("http://127.0.0.1/private"))
        with pytest.raises(UnsafeURL):
            await fetcher.fetch(origin + "/start")
        assert all("127.0.0.1" not in url for url in transport.requests)
        fetcher, transport = preflight.fixture_fetcher(responses(robots=b"User-agent: *\nDisallow: /\n"))
        with pytest.raises(FetchStopped, match="robots"):
            await fetcher.fetch(origin + "/start")
        assert transport.requests == [origin + "/robots.txt"]
        fetcher, transport = preflight.fixture_fetcher({})
        with pytest.raises(FetchStopped) as error:
            await fetcher.fetch("https://www.bilibili.com/video/BV1ab411c7de")
        assert error.value.status == "site_policy_blocked" and transport.requests == []
    asyncio.run(audit())


def test_preflight_resource_and_byte_limits_are_enforced():
    with pytest.raises(ValueError, match="resource_count_budget"):
        asyncio.run(preflight.prepare(max_resources=1))
    with pytest.raises(ValueError, match="total_byte_budget"):
        asyncio.run(preflight.prepare(max_total_bytes=1))


def test_oversized_unterminated_stdin_is_rejected_before_browser_launch():
    completed = subprocess.run(["node", str(HERE / "renderer.mjs")], input=b'{"unused":"' + b"x" * 350_000,
                               capture_output=True, timeout=10, cwd=preflight.ROOT)
    result = json.loads(completed.stdout)
    assert completed.returncode == 0 and result == {"event": "result", "ok": False, "status": "input_byte_budget"}
    ATTEMPTS.append({"scenario": "oversized_unterminated_stdin", "result": result, "node_exit_code": completed.returncode})


@pytest.mark.parametrize("failure_kind", ["communication_timeout", "invalid_json"])
def test_harness_failures_are_recorded_without_masking_exception(monkeypatch, failure_kind):
    # Owned Python stand-in, deliberately no browser or network. Exercise the
    # harness's failure/cleanup ledger even when no renderer result can arrive.
    original_spawn = asyncio.create_subprocess_exec
    script = "import time; time.sleep(60)" if failure_kind == "communication_timeout" else "print('not-json')"
    async def spawn_standin(*args, **kwargs):
        return await original_spawn(sys.executable, "-c", script, **kwargs)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn_standin)
    expected = TimeoutError if failure_kind == "communication_timeout" else json.JSONDecodeError
    before = len(ATTEMPTS)
    with pytest.raises(expected):
        run({"scenario": "python_harness_standin_" + failure_kind}, communication_timeout=.2)
    assert len(ATTEMPTS) == before + 1
    recorded = ATTEMPTS[-1]
    assert recorded["result"] is None and recorded["harness_error_type"] == expected.__name__
    assert recorded["forced_cleanup"] == (failure_kind == "communication_timeout")
    assert recorded["phase"] == ("communicate" if failure_kind == "communication_timeout" else "parse_result")
    assert recorded["cleanup_error_type"] is None and recorded["node_exit_code"] is not None
    assert not alive(recorded["owned_process_pid"])
