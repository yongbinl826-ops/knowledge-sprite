"""Bounded MOOC discovery experiment using the production Tavily adapter.

Dry run is the default. Examples (each output directory must be new):
  python scripts/test_tavily_mooc_recall.py --output reports/runtime/mooc-plan
  python scripts/test_tavily_mooc_recall.py --live --keyless --limit 2 --output reports/runtime/mooc-pilot
  python scripts/test_tavily_mooc_recall.py --live --keyless --offset 2 --limit 18 --output reports/runtime/mooc-rest

No course pages, Bilibili endpoints, database, LLM, fallbacks or retries are used.
A native course URL is discovery evidence only, never proof of teaching coverage.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import fields
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.config import Settings
from backend.app.providers import SearchError, TavilyProvider


CORPUS_VERSION = "mooc-knowledge-points-v1"
KNOWLEDGE_POINTS = (
    "Python 列表与字典",
    "pandas 数据分组与聚合",
    "Python 函数与参数",
    "Python 文件读写与异常处理",
    "NumPy 数组与矩阵运算",
    "pandas 缺失值处理与数据清洗",
    "Matplotlib 数据可视化",
    "SQL 多表连接与分组查询",
    "HTML 表单与网页结构",
    "CSS 布局与响应式网页",
    "JavaScript DOM 事件处理",
    "HTTP 请求与 REST API",
    "Flask Web 应用开发",
    "Git 版本控制与协作",
    "Arduino 数字输入输出",
    "Arduino 传感器与串口通信",
    "ESP32 物联网与 MQTT",
    "单片机 PWM 与电机控制",
    "机器学习 分类与交叉验证",
    "计算机网络 TCP/IP 基础",
)
DOMAINS = ["icourse163.org"]
RESULTS_PER_QUERY = 5
REQUEST_INTERVAL_SECONDS = 2


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def safe_text(value: object, secrets: tuple[str, ...], cap: int) -> str:
    if not isinstance(value, str):
        return ""
    for secret in secrets:
        if secret:
            value = value.replace(secret, "[credential redacted]")
    value = re.sub(r"https?://\S+", "[url redacted]", value, flags=re.I)
    value = re.sub(r"\b(?:authorization|proxy-authorization|cookie|set-cookie)\s*:[^\r\n]*",
                   "[credentials redacted]", value, flags=re.I)
    value = re.sub(r"\bBearer\s+\S+", "[credential redacted]", value, flags=re.I)
    value = re.sub(r"\b(?:api[_-]?key|token|password|secret)\s*[:=]\s*[^\s,;]+",
                   "[credential redacted]", value, flags=re.I)
    value = re.sub(r"\btvly-[A-Za-z0-9_-]+", "[credential redacted]", value, flags=re.I)
    return re.sub(r"[\x00-\x1f\x7f]", " ", value)[:cap]


def public_url(value: object, secrets: tuple[str, ...] = ()) -> str | None:
    """Keep only a bounded, credential-free official URL, without query/fragment."""
    if not isinstance(value, str) or len(value) > 4096:
        return None
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower()
        if (parsed.scheme not in {"http", "https"} or parsed.username or parsed.password
                or parsed.port not in {None, 80, 443}
                or not (host == "icourse163.org" or host.endswith(".icourse163.org"))
                or any(ord(character) < 32 for character in value)):
            return None
        path = parsed.path
        for secret in secrets:
            if secret:
                path = path.replace(secret, "redacted")
        return urlunsplit((parsed.scheme, host, path, "", ""))[:600]
    except ValueError:
        return None


def native_course_url(value: object) -> str | None:
    clean = public_url(value)
    if clean is None:
        return None
    parsed = urlsplit(clean)
    if parsed.hostname not in {"www.icourse163.org", "icourse163.org"}:
        return None
    if not re.fullmatch(r"/course/[A-Za-z0-9][A-Za-z0-9_-]{0,160}/?", parsed.path):
        return None
    return clean.rstrip("/")


def safe_trace(trace: dict, secrets: tuple[str, ...]) -> dict:
    """Allowlist observations; never persist provider headers or raw errors."""
    result = {"provider": "tavily"}
    for field in ("retry_index", "http_status", "response_bytes", "elapsed_seconds",
                  "raw_candidate_count", "candidate_count", "retry_after_seconds", "api_credits"):
        value = trace.get(field)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            result[field] = value
    for field in ("status", "error_code", "started_at", "access_mode", "auth_mode", "search_depth"):
        value = trace.get(field)
        if isinstance(value, str):
            result[field] = safe_text(value, secrets, 100)
    counts = trace.get("filter_counts")
    if isinstance(counts, dict):
        result["filter_counts"] = {safe_text(key, secrets, 60): value for key, value in list(counts.items())[:20]
                                   if isinstance(value, int) and not isinstance(value, bool)}
    return result


def isolated_settings(configured: Settings, mode: str | None) -> Settings:
    """Copy only the intended search credential into a fresh configuration."""
    values = dict(search_provider="tavily", tavily_api_key="" if mode == "keyless" else configured.tavily_api_key,
                  search_max_retries=0, search_min_interval_seconds=REQUEST_INTERVAL_SECONDS,
                  search_timeout_seconds=20, search_results_per_query=RESULTS_PER_QUERY,
                  fetch_enabled=False, llm_provider="none", teaching_match_enabled=False,
                  official_sitemap_fallback=False, public_catalog_fallback=False)
    available = {field.name for field in fields(Settings)}
    if "mooc_search_provider" in available:
        values["mooc_search_provider"] = "tavily"
    if "tavily_allow_keyless" in available:
        values["tavily_allow_keyless"] = mode == "keyless"
    return Settings(**values).validate()


def make_plan(limit: int, offset: int, live: bool, mode: str | None) -> dict:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= len(KNOWLEDGE_POINTS):
        raise ValueError("limit must be an integer between 1 and 20")
    if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset < len(KNOWLEDGE_POINTS):
        raise ValueError("offset must be an integer between 0 and 19")
    if offset + limit > len(KNOWLEDGE_POINTS):
        raise ValueError("offset + limit must not exceed the fixed corpus size of 20")
    if mode not in {None, "keyless", "configured_key"}:
        raise ValueError("unknown access mode")
    return {
        "schema_version": 1, "created_at": now(), "corpus_version": CORPUS_VERSION,
        "corpus_sha256": hashlib.sha256(json.dumps(KNOWLEDGE_POINTS, ensure_ascii=False).encode()).hexdigest(),
        "corpus": list(KNOWLEDGE_POINTS), "offset": offset, "limit": limit,
        "mode": "live" if live else "dry_run", "access_mode": mode or "not_selected",
        "domain_filters": DOMAINS, "search_depth": "basic", "results_per_query": RESULTS_PER_QUERY,
        "request_budget": limit, "per_query_request_budget": 1, "concurrency": 1,
        "request_interval_seconds": REQUEST_INTERVAL_SECONDS, "retries": 0,
        "fallbacks": False, "course_page_fetches": 0, "llm_calls": 0, "database_access": False,
        "configured_key_charge": "unknown; check your account plan before choosing configured-key mode",
        "query_plan": [{"corpus_index": index, "knowledge_point": KNOWLEDGE_POINTS[index],
                        "query": KNOWLEDGE_POINTS[index] + " 中国大学MOOC 课程"}
                       for index in range(offset, offset + limit)],
        "interpretation": "Discovery only. Native /course URLs do not establish syllabus coverage, suitability, playback, access, freshness, or production reliability.",
    }


async def run_recall(*, configured: Settings, output: Path, limit: int = 2, offset: int = 0,
                     live: bool = False, mode: str | None = None, provider_factory=None) -> dict:
    plan = make_plan(limit, offset, live, mode)
    # Exclusive creation prevents overwriting, resuming or mixing prior evidence.
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    atomic_json(output / "plan.json", plan)
    summary = {"schema_version": 1, "started_at": now(), "status": "planned", "stop_reason": None,
               "mode": plan["mode"], "access_mode": plan["access_mode"], "planned_queries": limit,
               "queries_attempted": 0, "queries_succeeded": 0, "queries_failed": 0,
               "http_requests_started": 0, "returned_candidate_count": 0,
               "native_course_candidate_count": 0, "native_unique_course_count": 0,
               "queries_with_native_course": 0, "native_course_query_hit_rate": None,
               "actual_api_credits": "unknown" if live else 0,
               "observed_api_credits": 0, "requests_with_reported_credits": 0,
               "account_credentials_sent": bool(live and mode == "configured_key"),
               "teaching_coverage": "unknown", "student_suitability": "unknown", "playback": "unknown",
               "production_reliability": "unknown", "queries": []}

    def save():
        # A denominator is recorded explicitly; this is search-hit rate, not a
        # gold-standard relevance/recall metric.
        succeeded = summary["queries_succeeded"]
        summary["native_course_query_hit_rate"] = (summary["queries_with_native_course"] / succeeded
                                                   if succeeded else None)
        atomic_json(output / "summary.json", summary)

    def finish(status, reason=None):
        summary.update(status=status, stop_reason=reason, finished_at=now())
        save()
        return summary

    save()
    if not live:
        summary["account_credentials_sent"] = False
        return finish("dry_run")
    if mode is None:
        summary["actual_api_credits"] = 0
        summary["account_credentials_sent"] = False
        return finish("preflight_blocked", "select_keyless_or_configured_key_mode")
    if mode == "configured_key" and not configured.tavily_api_key.strip():
        summary["actual_api_credits"] = 0
        summary["account_credentials_sent"] = False
        return finish("preflight_blocked", "TAVILY_API_KEY_not_configured")
    if mode == "keyless" and "tavily_allow_keyless" not in {field.name for field in fields(Settings)}:
        summary["actual_api_credits"] = 0
        return finish("preflight_blocked", "production_adapter_does_not_support_keyless")

    settings = isolated_settings(configured, mode)
    secrets = tuple(value for value in (configured.tavily_api_key, configured.llm_api_key) if value)
    provider = (provider_factory or TavilyProvider)(settings)
    seen_native: set[str] = set()
    summary["status"] = "running"
    save()
    for point in plan["query_plan"]:
        row = {**point, "status": "running", "started_at": now(), "http_requests_started": 0,
               "candidates": [], "provider_trace": [], "error_code": None}
        evidence_name = f"query-{point['corpus_index'] + 1:02d}.json"
        summary["queries_attempted"] += 1
        summary["queries"].append({"corpus_index": point["corpus_index"], "file": evidence_name, "status": "running"})

        def save_row():
            atomic_json(output / evidence_name, row)
            summary["queries"][-1]["status"] = row["status"]
            save()

        async def request_guard():
            if row["http_requests_started"] >= 1 or summary["http_requests_started"] >= limit:
                raise SearchError("harness_request_budget", "Bounded experiment request budget reached")
            row["http_requests_started"] += 1
            summary["http_requests_started"] += 1
            save_row()

        started = time.monotonic()
        save_row()
        try:
            with provider.query_scope(request_guard):
                try:
                    candidates = await provider.search(point["query"], "zh", RESULTS_PER_QUERY, DOMAINS.copy())
                finally:
                    row["provider_trace"] = [safe_trace(trace, secrets) for trace in provider.last_requests[:2]]
            for candidate in candidates[:RESULTS_PER_QUERY]:
                url = public_url(candidate.url, secrets)
                native = native_course_url(url)
                row["candidates"].append({"url": url, "title": safe_text(candidate.title, secrets, 300),
                    "snippet": safe_text(candidate.snippet, secrets, 800), "native_course_url": native,
                    "source": "tavily", "teaching_coverage": "unknown"})
                if native:
                    seen_native.add(native)
            native_count = sum(bool(candidate["native_course_url"]) for candidate in row["candidates"])
            row.update(status="completed", returned_candidate_count=len(row["candidates"]),
                       native_course_candidate_count=native_count)
            summary["queries_succeeded"] += 1
            summary["returned_candidate_count"] += len(row["candidates"])
            summary["native_course_candidate_count"] += native_count
            summary["native_unique_course_count"] = len(seen_native)
            summary["queries_with_native_course"] += int(native_count > 0)
        except SearchError as error:
            code = safe_text(error.code, secrets, 100)
            row.update(status="failed", error_code=code)
            summary["queries_failed"] += 1
            summary["stop_reason"] = code
        except (asyncio.CancelledError, KeyboardInterrupt):
            row.update(status="interrupted", error_code="interrupted")
            summary.update(status="interrupted", stop_reason="interrupted", finished_at=now())
            raise
        except Exception:
            # Deliberately omit exception messages: clients may include a key,
            # response body, private endpoint or authentication header in them.
            row.update(status="failed", error_code="unexpected_error")
            summary["queries_failed"] += 1
            summary["stop_reason"] = "unexpected_error"
        finally:
            reported = [trace["api_credits"] for trace in row["provider_trace"] if "api_credits" in trace]
            summary["observed_api_credits"] += sum(reported)
            summary["requests_with_reported_credits"] += len(reported)
            if summary["requests_with_reported_credits"] == summary["http_requests_started"]:
                summary["actual_api_credits"] = summary["observed_api_credits"]
            else:
                summary["actual_api_credits"] = "unknown"
            row.update(finished_at=now(), elapsed_seconds=round(time.monotonic() - started, 3))
            save_row()
        if summary["stop_reason"]:
            return finish("stopped", summary["stop_reason"])
    return finish("completed")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Actually call the production Tavily adapter")
    access = parser.add_mutually_exclusive_group()
    access.add_argument("--keyless", action="store_true", help="Explicitly use keyless access; never send a configured key")
    access.add_argument("--use-configured-key", action="store_true", help="Use TAVILY_API_KEY; verify free allowance in your account first")
    parser.add_argument("--limit", type=int, default=2, help="Number of fixed points (default 2; at most 20)")
    parser.add_argument("--offset", type=int, default=0, help="Zero-based corpus offset, for a non-overlapping follow-up")
    parser.add_argument("--output", type=Path, required=True, help="New evidence directory; existing paths are refused")
    args = parser.parse_args(argv)
    mode = "keyless" if args.keyless else "configured_key" if args.use_configured_key else None
    try:
        make_plan(args.limit, args.offset, args.live, mode)
        configured = Settings.from_env() if args.live else Settings()
        summary = asyncio.run(run_recall(configured=configured, output=args.output, limit=args.limit,
                                        offset=args.offset, live=args.live, mode=mode))
    except FileExistsError:
        print("Refusing to overwrite an existing output directory.", file=sys.stderr)
        return 2
    except ValueError:
        print("Invalid experiment arguments or environment configuration; no configuration values are printed.", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrupted. Existing plan and incremental evidence have been preserved.", file=sys.stderr)
        return 130
    print(json.dumps({key: summary[key] for key in ("status", "stop_reason", "queries_succeeded", "http_requests_started",
                                                   "native_unique_course_count")}, ensure_ascii=False))
    return 0 if summary["status"] in {"completed", "dry_run"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
