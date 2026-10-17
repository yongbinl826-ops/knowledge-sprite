from __future__ import annotations

import os
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


@dataclass(frozen=True)
class Settings:
    database_path: str = "data/discovery.sqlite3"
    search_provider: str = "searxng"
    searxng_url: str = ""
    searxng_engines: tuple[str, ...] = ()
    searxng_video_engines: tuple[str, ...] = ()
    searxng_fallback_engines: tuple[str, ...] = ()
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
    dns_resolver: str = "system"
    allowed_restricted_hosts: tuple[str, ...] = ()
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
            dns_resolver=os.getenv("DNS_RESOLVER", "system"),
            allowed_restricted_hosts=tuple(x.strip() for x in os.getenv("ALLOWED_RESTRICTED_HOSTS", "").split(",") if x.strip()),
            cors_origins=tuple(x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if x.strip()),
        )
