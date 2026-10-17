from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv


def boolean(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes"}


def number(name: str, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(os.getenv(name, str(default)))))
    except ValueError:
        return default


def course_domains(value: str) -> tuple[str, ...]:
    """Trusted server search scopes, limited and incapable of adding query syntax."""
    domains = (part.strip().lower() for part in value.split(","))
    return tuple(dict.fromkeys(domain for domain in domains if len(domain) <= 253 and
        re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", domain)))[:2]


def render_hosts(value: str) -> tuple[str, ...]:
    """Explicit server-owned hostnames; no URLs, ports, wildcards or IP literals."""
    hosts = (part.strip().lower() for part in value.split(","))
    return tuple(dict.fromkeys(host for host in hosts if len(host) <= 253 and
        re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", host)))[:16]


def render_entries(value: str) -> tuple[str, ...]:
    # Invalid nonempty configuration must fail closed instead of becoming an
    # empty optional restriction and silently broadening to a whole hostname.
    from urllib.parse import urlsplit
    from .url_utils import normalize_url
    entries = []
    for raw in value.split(","):
        if not raw.strip(): continue
        url = normalize_url(raw.strip())
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.port not in (None, 443) or parts.query or parts.fragment:
            raise ValueError("JS_RENDER_ALLOWED_ENTRIES requires exact public HTTPS URLs without query or fragment")
        entries.append(url)
    if len(entries) > 16: raise ValueError("Too many exact renderer entries")
    if value.strip() and not entries: raise ValueError("Empty renderer entry restriction")
    return tuple(dict.fromkeys(entries))


@dataclass(frozen=True)
class Settings:
    database_path: str = "data/discovery.sqlite3"
    search_provider: str = "searxng"
    searxng_url: str = ""
    searxng_engines: tuple[str, ...] = ()
    searxng_video_engines: tuple[str, ...] = ()
    searxng_fallback_engines: tuple[str, ...] = ()
    open_course_domains: tuple[str, ...] = ()
    official_sitemap_fallback: bool = False
    official_sitemap_cache_ttl: int = 21600
    official_sitemap_children_per_query: int = 1
    tavily_api_key: str = ""
    llm_provider: str = "none"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = ""
    max_search_requests: int = 30
    max_detail_pages: int = 40
    max_knowledge_points: int = 5
    max_results_per_point: int = 5
    global_concurrency: int = 5
    deadline_seconds: int = 180
    search_timeout_seconds: int = 12
    search_max_retries: int = 1
    search_min_interval_seconds: int = 1
    search_results_per_query: int = 6
    search_cache_ttl: int = 21600
    page_cache_ttl: int = 86400
    allow_stale_cache: bool = False
    fetch_enabled: bool = True
    fetch_timeout_seconds: int = 8
    fetch_min_interval_seconds: float = 0.5
    fetch_phased_timeouts: bool = False
    fetch_body_idle_timeout_seconds: int = 5
    fetch_body_min_bytes_per_second: int = 32768
    fetch_body_timeout_cap_seconds: int = 20
    js_render_enabled: bool = False
    js_render_allowed_hosts: tuple[str, ...] = ()
    js_render_allowed_entries: tuple[str, ...] = ()
    js_render_asset_hosts: tuple[str, ...] = ()
    js_render_timeout_seconds: int = 20
    js_render_max_resources: int = 6
    js_render_max_target_requests: int = 12
    js_render_max_doh_requests: int = 24
    js_render_max_total_bytes: int = 2_000_000
    js_render_max_dom_bytes: int = 1_000_000
    js_render_settle_ms: int = 500
    js_render_max_observed_data_resources: int = 2
    dns_resolver: str = "system"
    allowed_restricted_hosts: tuple[str, ...] = ()
    denied_fetch_hosts: tuple[str, ...] = ()
    cors_origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
        return cls(
            database_path=os.getenv("DATABASE_PATH", "data/discovery.sqlite3"),
            search_provider=os.getenv("SEARCH_PROVIDER", "searxng").lower(),
            searxng_url=os.getenv("SEARXNG_URL", "").rstrip("/"),
            searxng_engines=tuple(x.strip() for x in os.getenv("SEARXNG_ENGINES", "").split(",") if x.strip()),
            searxng_video_engines=tuple(x.strip() for x in os.getenv("SEARXNG_VIDEO_ENGINES", "").split(",") if x.strip()),
            searxng_fallback_engines=tuple(x.strip() for x in os.getenv("SEARXNG_FALLBACK_ENGINES", "").split(",") if x.strip()),
            open_course_domains=course_domains(os.getenv("OPEN_COURSE_DOMAINS", "")),
            official_sitemap_fallback=boolean("OFFICIAL_SITEMAP_FALLBACK"),
            official_sitemap_cache_ttl=number("OFFICIAL_SITEMAP_CACHE_TTL_SECONDS", 21600, 0, 86400),
            official_sitemap_children_per_query=number("OFFICIAL_SITEMAP_CHILDREN_PER_QUERY", 1, 1, 2),
            tavily_api_key=os.getenv("TAVILY_API_KEY", ""),
            llm_provider=os.getenv("LLM_PROVIDER", "none"),
            llm_base_url=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            llm_api_key=os.getenv("LLM_API_KEY", ""), llm_model=os.getenv("LLM_MODEL", ""),
            max_search_requests=number("MAX_SEARCH_REQUESTS", 30, 1, 30),
            max_detail_pages=number("MAX_DETAIL_PAGES", 40, 0, 40),
            max_knowledge_points=number("MAX_KNOWLEDGE_POINTS", 5, 1, 5),
            max_results_per_point=number("MAX_RESULTS_PER_POINT", 5, 1, 5),
            global_concurrency=number("GLOBAL_CONCURRENCY", 5, 1, 5),
            deadline_seconds=number("TASK_DEADLINE_SECONDS", 180, 5, 600),
            search_timeout_seconds=number("SEARCH_TIMEOUT_SECONDS", 12, 1, 30),
            search_max_retries=number("SEARCH_MAX_RETRIES", 1, 0, 1),
            search_min_interval_seconds=number("SEARCH_MIN_INTERVAL_SECONDS", 1, 0, 5),
            search_results_per_query=number("SEARCH_RESULTS_PER_QUERY", 6, 1, 10),
            search_cache_ttl=number("SEARCH_CACHE_TTL_SECONDS", 21600, 0, 604800),
            page_cache_ttl=number("PAGE_CACHE_TTL_SECONDS", 86400, 0, 604800),
            allow_stale_cache=boolean("ALLOW_STALE_CACHE"), fetch_enabled=boolean("FETCH_ENABLED", True),
            fetch_timeout_seconds=number("FETCH_TIMEOUT_SECONDS", 8, 1, 30),
            fetch_min_interval_seconds=number("FETCH_MIN_INTERVAL_MS", 500, 100, 10000) / 1000,
            fetch_phased_timeouts=boolean("FETCH_PHASED_TIMEOUTS"),
            fetch_body_idle_timeout_seconds=number("FETCH_BODY_IDLE_TIMEOUT_SECONDS", 5, 1, 30),
            fetch_body_min_bytes_per_second=number("FETCH_BODY_MIN_BYTES_PER_SECOND", 32768, 1024, 1_048_576),
            fetch_body_timeout_cap_seconds=number("FETCH_BODY_TIMEOUT_CAP_SECONDS", 20, 1, 60),
            js_render_enabled=boolean("JS_RENDER_ENABLED"),
            js_render_allowed_hosts=render_hosts(os.getenv("JS_RENDER_ALLOWED_HOSTS", "")),
            js_render_allowed_entries=render_entries(os.getenv("JS_RENDER_ALLOWED_ENTRIES", "")),
            js_render_asset_hosts=render_hosts(os.getenv("JS_RENDER_ASSET_HOSTS", "")),
            js_render_timeout_seconds=number("JS_RENDER_TIMEOUT_SECONDS", 20, 1, 120),
            js_render_max_resources=number("JS_RENDER_MAX_RESOURCES", 6, 1, 20),
            js_render_max_target_requests=number("JS_RENDER_MAX_TARGET_REQUESTS", 12, 1, 40),
            js_render_max_doh_requests=number("JS_RENDER_MAX_DOH_REQUESTS", 24, 1, 80),
            js_render_max_total_bytes=number("JS_RENDER_MAX_TOTAL_BYTES", 2_000_000, 4096, 8_000_000),
            js_render_max_dom_bytes=number("JS_RENDER_MAX_DOM_BYTES", 1_000_000, 4096, 2_000_000),
            js_render_settle_ms=number("JS_RENDER_SETTLE_MS", 500, 0, 2000),
            js_render_max_observed_data_resources=number("JS_RENDER_MAX_OBSERVED_DATA_RESOURCES", 2, 0, 2),
            dns_resolver=os.getenv("DNS_RESOLVER", "system"),
            allowed_restricted_hosts=tuple(x.strip() for x in os.getenv("ALLOWED_RESTRICTED_HOSTS", "").split(",") if x.strip()),
            denied_fetch_hosts=tuple(x.strip().lower() for x in os.getenv("DENIED_FETCH_HOSTS", "").split(",") if x.strip()),
            cors_origins=tuple(x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if x.strip()),
        )
