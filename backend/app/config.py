from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
from dotenv import load_dotenv


def boolean(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes"}


def number(name: str, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(os.getenv(name, str(default)))))
    except ValueError:
        return default


def security_number(name: str, default: int, low: int, high: int) -> int:
    """Security limits must not silently turn a typo into a different policy."""
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name} must be an integer") from None
    if not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return value


def local_only_setting() -> bool:
    raw = os.getenv("LOCAL_ONLY", "true").strip().lower()
    if raw not in {"1", "true", "yes", "0", "false", "no"}:
        raise ValueError("LOCAL_ONLY must be true or false")
    return raw in {"1", "true", "yes"}


def semantic_review_setting() -> bool:
    raw = os.getenv("PROJECT_SEMANTIC_REVIEW_ENABLED", "true").strip().lower()
    if raw not in {"1", "true", "yes", "0", "false", "no"}:
        raise ValueError("PROJECT_SEMANTIC_REVIEW_ENABLED must be true or false")
    return raw in {"1", "true", "yes"}


def valid_origin(value: str) -> bool:
    """An exact browser origin, never a wildcard, URL path or credentials."""
    try:
        parts = urlsplit(value)
        return bool(parts.scheme in {"http", "https"} and parts.hostname and
                    parts.username is None and parts.password is None and
                    parts.path == "" and not parts.query and not parts.fragment and
                    parts.port != 0 and value == f"{parts.scheme}://{parts.netloc}" and
                    not any(char.isspace() or ord(char) < 32 for char in value))
    except ValueError:
        return False


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
    app_mode: str = "legacy"
    mobile_public_database_path: str = "data/mobile-public.sqlite3"
    mobile_origins: tuple[str, ...] = ("https://localhost", "capacitor://localhost")
    mobile_task_ttl_seconds: int = 7200
    mobile_cleanup_interval_seconds: int = 5
    mobile_max_tasks: int = 64
    mobile_max_active_tasks: int = 8
    mobile_per_ip_tasks_per_minute: int = 6
    mobile_per_ip_requests_per_minute: int = 120
    mobile_max_ip_buckets: int = 1024
    mobile_max_tombstones: int = 10000
    mobile_daily_tasks: int = 200
    mobile_daily_analysis_calls: int = 40
    mobile_daily_model_calls: int = 200
    mobile_daily_search_requests: int = 1000
    mobile_daily_detail_pages: int = 500
    mobile_daily_detail_http: int = 20000
    mobile_public_ttl_seconds: int = 604800
    mobile_public_max_courses: int = 10000
    mobile_budget_retention_days: int = 31
    database_path: str = "data/discovery.sqlite3"
    search_provider: str = "searxng"
    bilibili_search_provider: str = ""
    mooc_search_provider: str = ""
    searxng_url: str = ""
    searxng_engines: tuple[str, ...] = ()
    searxng_video_engines: tuple[str, ...] = ()
    searxng_fallback_engines: tuple[str, ...] = ()
    searxng_failover_provider: str = ""
    open_course_domains: tuple[str, ...] = ()
    official_sitemap_fallback: bool = False
    public_catalog_fallback: bool = False
    official_sitemap_cache_ttl: int = 21600
    official_sitemap_children_per_query: int = 1
    tavily_api_key: str = ""
    tavily_allow_keyless: bool = False
    serper_api_key: str = ""
    shared_course_library_enabled: bool = True
    shared_course_library_ttl_seconds: int = 604800
    shared_course_library_max_candidates: int = 100
    mooc_gap_search_enabled: bool = True
    mooc_target_courses_per_point: int = 3
    mooc_gap_check_wait_seconds: int = 20
    mooc_refresh_enabled: bool = True
    mooc_refresh_interval_seconds: int = 86400
    llm_provider: str = "none"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = ""
    llm_max_output_tokens: int = 6000
    llm_reasoning_effort: str = "auto"
    llm_thinking_mode: str = "auto"
    ai_video_fallback_enabled: bool = True
    ai_video_search_provider: str = "auto"
    # Programmatic callers can retain legacy jobs; normal app startup opts in.
    fast_video_recommendations_enabled: bool = False
    fast_video_deadline_seconds: int = 110
    # Catalog work expands only after video recommendations are terminal.
    catalog_background_seconds: int = 600
    catalog_background_max_resources: int = 96
    catalog_background_max_http_requests: int = 288
    catalog_background_max_model_calls: int = 24
    teaching_match_max_calls_per_job: int = 2
    teaching_match_enabled: bool = True
    parallel_platform_search: bool = False
    open_web_search_enabled: bool = True
    bilibili_search_rounds: int = 2
    mooc_search_rounds: int = 2
    max_search_requests: int = 30
    max_detail_pages: int = 40
    max_knowledge_points: int = 5
    max_results_per_point: int = 5
    global_concurrency: int = 5
    deadline_seconds: int = 180
    max_pending_jobs: int = 20
    submission_limit_per_minute: int = 30
    max_queue_wait_seconds: int = 300
    project_max_batches: int = 6
    project_max_search_requests: int = 180
    project_max_detail_pages: int = 240
    project_deadline_seconds: int = 1800
    project_analysis_timeout_seconds: int = 90
    project_analysis_total_timeout_seconds: int = 120
    project_analysis_normalization_max_output_tokens: int = 12000
    project_semantic_review_enabled: bool = True
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
    bilibili_public_metadata: bool = False
    bilibili_public_metadata_max_bytes: int = 8_000_000
    denied_fetch_hosts: tuple[str, ...] = ()
    cors_origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")
    local_only: bool = True
    allowed_hosts: tuple[str, ...] = ("localhost", "127.0.0.1", "::1")
    max_request_body_bytes: int = 512_000
    request_body_timeout_seconds: int = 10
    api_write_limit_per_minute: int = 60
    max_pending_analyses: int = 8
    max_pending_project_searches: int = 20
    max_event_streams: int = 16

    def search_provider_for(self, platform: str) -> str:
        override = {"bilibili": self.bilibili_search_provider,
                    "icourse163": self.mooc_search_provider}.get(platform, "")
        return override or self.search_provider

    def uses_official_deepseek_model(self) -> bool:
        try:
            endpoint = urlsplit(self.llm_base_url)
            return bool(endpoint.scheme == "https" and endpoint.hostname == "api.deepseek.com" and
                endpoint.port in (None, 443) and endpoint.username is None and endpoint.password is None and
                self.llm_model in {"deepseek-flash", "deepseek-v4-pro"})
        except ValueError:
            return False

    def validate(self) -> "Settings":
        if not isinstance(self.app_mode, str) or self.app_mode not in {"legacy", "mobile"}:
            raise ValueError("APP_MODE must be legacy or mobile")
        if (not isinstance(self.mobile_public_database_path, str) or not self.mobile_public_database_path.strip()
                or "\x00" in self.mobile_public_database_path or self.mobile_public_database_path == ":memory:"
                or Path(self.mobile_public_database_path).suffix != ".sqlite3"):
            raise ValueError("MOBILE_PUBLIC_DATABASE_PATH must be a separate sqlite3 file")
        if (not isinstance(self.mobile_origins, tuple) or len(self.mobile_origins) > 3 or any(
                not isinstance(origin, str) or origin not in {"https://localhost", "capacitor://localhost", "http://localhost"} for origin in self.mobile_origins)):
            raise ValueError("MOBILE_ORIGINS requires exact supported native localhost origins")
        if self.app_mode == "mobile":
            if not self.teaching_match_enabled or not self.parallel_platform_search:
                raise ValueError("Mobile mode requires TEACHING_MATCH_ENABLED and PARALLEL_PLATFORM_SEARCH")
            if Path(self.mobile_public_database_path).resolve() == Path(self.database_path).resolve():
                raise ValueError("Mobile public database must be separate from the legacy database")
        for name, value, low, high in (
            ("BILIBILI_PUBLIC_METADATA_MAX_BYTES", self.bilibili_public_metadata_max_bytes, 4096, 16_000_000),
            ("MOBILE_TASK_TTL_SECONDS", self.mobile_task_ttl_seconds, 60, 7200),
            ("MOBILE_CLEANUP_INTERVAL_SECONDS", self.mobile_cleanup_interval_seconds, 1, 30),
            ("MOBILE_MAX_TASKS", self.mobile_max_tasks, 1, 256),
            ("MOBILE_MAX_ACTIVE_TASKS", self.mobile_max_active_tasks, 1, 32),
            ("MOBILE_PER_IP_TASKS_PER_MINUTE", self.mobile_per_ip_tasks_per_minute, 1, 60),
            ("MOBILE_PER_IP_REQUESTS_PER_MINUTE", self.mobile_per_ip_requests_per_minute, 10, 600),
            ("MOBILE_MAX_IP_BUCKETS", self.mobile_max_ip_buckets, 16, 4096),
            ("MOBILE_MAX_TOMBSTONES", self.mobile_max_tombstones, 100, 100000),
            ("MOBILE_DAILY_TASKS", self.mobile_daily_tasks, 1, 10000),
            ("MOBILE_DAILY_ANALYSIS_CALLS", self.mobile_daily_analysis_calls, 1, 10000),
            ("MOBILE_DAILY_MODEL_CALLS", self.mobile_daily_model_calls, 1, 100000),
            ("MOBILE_DAILY_SEARCH_REQUESTS", self.mobile_daily_search_requests, 1, 100000),
            ("MOBILE_DAILY_DETAIL_PAGES", self.mobile_daily_detail_pages, 1, 100000),
            ("MOBILE_DAILY_DETAIL_HTTP", self.mobile_daily_detail_http, 1, 4000000),
            ("MOBILE_PUBLIC_TTL_SECONDS", self.mobile_public_ttl_seconds, 60, 2592000),
            ("MOBILE_PUBLIC_MAX_COURSES", self.mobile_public_max_courses, 1, 100000),
            ("MOBILE_BUDGET_RETENTION_DAYS", self.mobile_budget_retention_days, 1, 365),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
                raise ValueError(f"{name} must be an integer between {low} and {high}")
        if self.mobile_max_active_tasks > self.mobile_max_tasks:
            raise ValueError("MOBILE_MAX_ACTIVE_TASKS must not exceed MOBILE_MAX_TASKS")
        if not isinstance(self.parallel_platform_search, bool):
            raise ValueError("PARALLEL_PLATFORM_SEARCH must be true or false")
        if not isinstance(self.open_web_search_enabled, bool):
            raise ValueError("OPEN_WEB_SEARCH_ENABLED must be true or false")
        if not isinstance(self.teaching_match_enabled, bool):
            raise ValueError("TEACHING_MATCH_ENABLED must be true or false")
        if not isinstance(self.ai_video_fallback_enabled, bool):
            raise ValueError("AI_VIDEO_FALLBACK_ENABLED must be true or false")
        if not isinstance(self.fast_video_recommendations_enabled, bool):
            raise ValueError("FAST_VIDEO_RECOMMENDATIONS_ENABLED must be true or false")
        if (not isinstance(self.fast_video_deadline_seconds, int)
                or isinstance(self.fast_video_deadline_seconds, bool)
                or not 1 <= self.fast_video_deadline_seconds <= 120):
            raise ValueError("FAST_VIDEO_DEADLINE_SECONDS must be an integer between 1 and 120")
        for name, value, minimum, maximum in (
            ("CATALOG_BACKGROUND_SECONDS", self.catalog_background_seconds, 1, 900),
            ("CATALOG_BACKGROUND_MAX_RESOURCES", self.catalog_background_max_resources, 12, 96),
            ("CATALOG_BACKGROUND_MAX_HTTP_REQUESTS", self.catalog_background_max_http_requests, 18, 384),
            ("CATALOG_BACKGROUND_MAX_MODEL_CALLS", self.catalog_background_max_model_calls, 3, 32),
        ):
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError(f"{name} must be an integer between {minimum} and {maximum}")
        if self.ai_video_search_provider not in {"auto", "default", "serper", "tavily"}:
            raise ValueError("AI_VIDEO_SEARCH_PROVIDER must be auto, default, serper or tavily")
        if not isinstance(self.local_only, bool):
            raise ValueError("LOCAL_ONLY must be true or false")
        if not isinstance(self.public_catalog_fallback, bool):
            raise ValueError("PUBLIC_CATALOG_FALLBACK must be true or false")
        if not isinstance(self.project_semantic_review_enabled, bool):
            raise ValueError("PROJECT_SEMANTIC_REVIEW_ENABLED must be true or false")
        if not self.database_path.strip() or "\x00" in self.database_path:
            raise ValueError("DATABASE_PATH must name a database file")
        if self.search_provider not in {"searxng", "tavily", "serper", "official_sitemap"}:
            raise ValueError("SEARCH_PROVIDER must be searxng, tavily, serper or official_sitemap")
        for name, value in (("BILIBILI_SEARCH_PROVIDER", self.bilibili_search_provider),
                            ("MOOC_SEARCH_PROVIDER", self.mooc_search_provider)):
            if value not in {"", "searxng", "tavily", "serper"}:
                raise ValueError(f"{name} must be empty, searxng, tavily or serper")
            if value and self.search_provider == "official_sitemap":
                raise ValueError(f"{name} cannot override the MIT-only official_sitemap mode")
        if not isinstance(self.tavily_allow_keyless, bool):
            raise ValueError("TAVILY_ALLOW_KEYLESS must be true or false")
        if not isinstance(self.searxng_failover_provider, str) or self.searxng_failover_provider not in {"", "tavily"}:
            raise ValueError("SEARXNG_FAILOVER_PROVIDER must be empty or tavily")
        if not isinstance(self.shared_course_library_enabled, bool) or not isinstance(self.mooc_gap_search_enabled, bool):
            raise ValueError("Library and gap search flags must be boolean")
        if not isinstance(self.mooc_refresh_enabled, bool):
            raise ValueError("MOOC_REFRESH_ENABLED must be boolean")
        for name, value, low, high in (("SHARED_COURSE_LIBRARY_TTL_SECONDS", self.shared_course_library_ttl_seconds, 60, 2592000),
                ("SHARED_COURSE_LIBRARY_MAX_CANDIDATES", self.shared_course_library_max_candidates, 1, 500),
                ("MOOC_TARGET_COURSES_PER_POINT", self.mooc_target_courses_per_point, 1, 10),
                ("MOOC_GAP_CHECK_WAIT_SECONDS", self.mooc_gap_check_wait_seconds, 1, 60)):
            if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
                raise ValueError(f"{name} is outside its allowed range")
        if (not isinstance(self.mooc_refresh_interval_seconds, int) or isinstance(self.mooc_refresh_interval_seconds, bool)
                or not 300 <= self.mooc_refresh_interval_seconds <= 2592000):
            raise ValueError("MOOC_REFRESH_INTERVAL_SECONDS is outside its allowed range")
        if self.llm_provider not in {"none", "openai_compatible"}:
            raise ValueError("LLM_PROVIDER must be none or openai_compatible")
        if not isinstance(self.llm_reasoning_effort, str) or self.llm_reasoning_effort not in {"auto", "provider_default", "low", "medium", "high", "max"}:
            raise ValueError("LLM_REASONING_EFFORT must be auto, provider_default, low, medium, high or max")
        if not isinstance(self.llm_thinking_mode, str) or self.llm_thinking_mode not in {"auto", "provider_default", "enabled", "disabled"}:
            raise ValueError("LLM_THINKING_MODE must be auto, provider_default, enabled or disabled")
        thinking_disabled = self.llm_thinking_mode == "disabled" or (
            self.llm_thinking_mode == "auto" and self.uses_official_deepseek_model())
        if thinking_disabled and self.llm_reasoning_effort not in {"auto", "provider_default"}:
            raise ValueError("LLM_THINKING_MODE disables thinking; use enabled or provider_default before setting explicit LLM_REASONING_EFFORT")
        for name, value in (("SEARXNG_URL", self.searxng_url), ("LLM_BASE_URL", self.llm_base_url)):
            if not value:
                continue  # Unconfigured integrations remain an explicit capability state.
            try:
                parts = urlsplit(value)
                valid = (parts.scheme in {"http", "https"} and parts.hostname and
                         parts.username is None and parts.password is None and
                         not parts.query and not parts.fragment and parts.port != 0 and
                         not any(char.isspace() or ord(char) < 32 for char in value))
            except ValueError:
                valid = False
            if not valid:
                raise ValueError(f"{name} must be an HTTP(S) base URL without credentials, query or fragment")
        if any(not valid_origin(origin) for origin in self.cors_origins):
            raise ValueError("CORS_ORIGINS must contain exact HTTP(S) origins without paths or wildcards")
        if not self.allowed_hosts or any(not host or host != host.lower() or
            not re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?|::1)", host) or
            ".." in host for host in self.allowed_hosts):
            raise ValueError("ALLOWED_HOSTS must contain exact lowercase hostnames or loopback IPs, without ports or wildcards")
        for name, value, low, high in (
            ("MAX_REQUEST_BODY_BYTES", self.max_request_body_bytes, 1024, 2_000_000),
            ("REQUEST_BODY_TIMEOUT_SECONDS", self.request_body_timeout_seconds, 1, 60),
            ("API_WRITE_LIMIT_PER_MINUTE", self.api_write_limit_per_minute, 1, 300),
            ("MAX_PENDING_ANALYSES", self.max_pending_analyses, 1, 32),
            ("MAX_PENDING_PROJECT_SEARCHES", self.max_pending_project_searches, 1, 100),
            ("MAX_EVENT_STREAMS", self.max_event_streams, 1, 128),
            ("PROJECT_ANALYSIS_TIMEOUT_SECONDS", self.project_analysis_timeout_seconds, 1, 120),
            ("PROJECT_ANALYSIS_TOTAL_TIMEOUT_SECONDS", self.project_analysis_total_timeout_seconds, 1, 180),
            ("PROJECT_ANALYSIS_NORMALIZATION_MAX_OUTPUT_TOKENS", self.project_analysis_normalization_max_output_tokens, 256, 16000),
            ("LLM_MAX_OUTPUT_TOKENS", self.llm_max_output_tokens, 256, 16000),
            ("TEACHING_MATCH_MAX_CALLS_PER_JOB", self.teaching_match_max_calls_per_job, 0, 2),
            ("BILIBILI_SEARCH_ROUNDS", self.bilibili_search_rounds, 1, 6),
            ("MOOC_SEARCH_ROUNDS", self.mooc_search_rounds, 1, 10),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
                raise ValueError(f"{name} must be an integer between {low} and {high}")
        if self.project_analysis_total_timeout_seconds < self.project_analysis_timeout_seconds:
            raise ValueError("PROJECT_ANALYSIS_TOTAL_TIMEOUT_SECONDS must be at least PROJECT_ANALYSIS_TIMEOUT_SECONDS")
        return self

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
        return cls(
            app_mode=os.getenv("APP_MODE", "legacy").strip().lower(),
            mobile_public_database_path=os.getenv("MOBILE_PUBLIC_DATABASE_PATH", "data/mobile-public.sqlite3"),
            mobile_origins=tuple(x.strip() for x in os.getenv("MOBILE_ORIGINS", "https://localhost,capacitor://localhost").split(",") if x.strip()),
            mobile_task_ttl_seconds=security_number("MOBILE_TASK_TTL_SECONDS", 7200, 60, 7200),
            mobile_cleanup_interval_seconds=security_number("MOBILE_CLEANUP_INTERVAL_SECONDS", 5, 1, 30),
            mobile_max_tasks=security_number("MOBILE_MAX_TASKS", 64, 1, 256),
            mobile_max_active_tasks=security_number("MOBILE_MAX_ACTIVE_TASKS", 8, 1, 32),
            mobile_per_ip_tasks_per_minute=security_number("MOBILE_PER_IP_TASKS_PER_MINUTE", 6, 1, 60),
            mobile_per_ip_requests_per_minute=security_number("MOBILE_PER_IP_REQUESTS_PER_MINUTE", 120, 10, 600),
            mobile_max_ip_buckets=security_number("MOBILE_MAX_IP_BUCKETS", 1024, 16, 4096),
            mobile_max_tombstones=security_number("MOBILE_MAX_TOMBSTONES", 10000, 100, 100000),
            mobile_daily_tasks=security_number("MOBILE_DAILY_TASKS", 200, 1, 10000),
            mobile_daily_analysis_calls=security_number("MOBILE_DAILY_ANALYSIS_CALLS", 40, 1, 10000),
            mobile_daily_model_calls=security_number("MOBILE_DAILY_MODEL_CALLS", 200, 1, 100000),
            mobile_daily_search_requests=security_number("MOBILE_DAILY_SEARCH_REQUESTS", 1000, 1, 100000),
            mobile_daily_detail_pages=security_number("MOBILE_DAILY_DETAIL_PAGES", 500, 1, 100000),
            mobile_daily_detail_http=security_number("MOBILE_DAILY_DETAIL_HTTP", 20000, 1, 4000000),
            mobile_public_ttl_seconds=security_number("MOBILE_PUBLIC_TTL_SECONDS", 604800, 60, 2592000),
            mobile_public_max_courses=security_number("MOBILE_PUBLIC_MAX_COURSES", 10000, 1, 100000),
            mobile_budget_retention_days=security_number("MOBILE_BUDGET_RETENTION_DAYS", 31, 1, 365),
            database_path=os.getenv("DATABASE_PATH", "data/discovery.sqlite3"),
            search_provider=os.getenv("SEARCH_PROVIDER", "searxng").lower(),
            bilibili_search_provider=os.getenv("BILIBILI_SEARCH_PROVIDER", "").strip().lower(),
            mooc_search_provider=os.getenv("MOOC_SEARCH_PROVIDER", "").strip().lower(),
            searxng_url=os.getenv("SEARXNG_URL", "").rstrip("/"),
            searxng_engines=tuple(x.strip() for x in os.getenv("SEARXNG_ENGINES", "").split(",") if x.strip()),
            searxng_video_engines=tuple(x.strip() for x in os.getenv("SEARXNG_VIDEO_ENGINES", "").split(",") if x.strip()),
            searxng_fallback_engines=tuple(x.strip() for x in os.getenv("SEARXNG_FALLBACK_ENGINES", "").split(",") if x.strip()),
            searxng_failover_provider=os.getenv("SEARXNG_FAILOVER_PROVIDER", "").strip().lower(),
            open_course_domains=course_domains(os.getenv("OPEN_COURSE_DOMAINS", "")),
            official_sitemap_fallback=boolean("OFFICIAL_SITEMAP_FALLBACK"),
            public_catalog_fallback=boolean("PUBLIC_CATALOG_FALLBACK"),
            official_sitemap_cache_ttl=number("OFFICIAL_SITEMAP_CACHE_TTL_SECONDS", 21600, 0, 86400),
            official_sitemap_children_per_query=number("OFFICIAL_SITEMAP_CHILDREN_PER_QUERY", 1, 1, 2),
            tavily_api_key=os.getenv("TAVILY_API_KEY", ""),
            tavily_allow_keyless=boolean("TAVILY_ALLOW_KEYLESS"),
            serper_api_key=os.getenv("SERPER_API_KEY", ""),
            shared_course_library_enabled=boolean("SHARED_COURSE_LIBRARY_ENABLED", True),
            shared_course_library_ttl_seconds=security_number("SHARED_COURSE_LIBRARY_TTL_SECONDS", 604800, 60, 2592000),
            shared_course_library_max_candidates=security_number("SHARED_COURSE_LIBRARY_MAX_CANDIDATES", 100, 1, 500),
            mooc_gap_search_enabled=boolean("MOOC_GAP_SEARCH_ENABLED", True),
            mooc_target_courses_per_point=security_number("MOOC_TARGET_COURSES_PER_POINT", 3, 1, 10),
            mooc_gap_check_wait_seconds=security_number("MOOC_GAP_CHECK_WAIT_SECONDS", 20, 1, 60),
            mooc_refresh_enabled=boolean("MOOC_REFRESH_ENABLED", True),
            mooc_refresh_interval_seconds=security_number("MOOC_REFRESH_INTERVAL_SECONDS", 86400, 300, 2592000),
            llm_provider=os.getenv("LLM_PROVIDER", "none"),
            llm_base_url=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            llm_api_key=os.getenv("LLM_API_KEY", ""), llm_model=os.getenv("LLM_MODEL", ""),
            llm_max_output_tokens=security_number("LLM_MAX_OUTPUT_TOKENS", 6000, 256, 16000),
            llm_reasoning_effort=os.getenv("LLM_REASONING_EFFORT", "auto").strip().lower(),
            llm_thinking_mode=os.getenv("LLM_THINKING_MODE", "auto").strip().lower(),
            ai_video_fallback_enabled=boolean("AI_VIDEO_FALLBACK_ENABLED", True),
            ai_video_search_provider=os.getenv("AI_VIDEO_SEARCH_PROVIDER", "auto").strip().lower(),
            fast_video_recommendations_enabled=boolean("FAST_VIDEO_RECOMMENDATIONS_ENABLED", True),
            fast_video_deadline_seconds=security_number("FAST_VIDEO_DEADLINE_SECONDS", 110, 1, 120),
            catalog_background_seconds=security_number("CATALOG_BACKGROUND_SECONDS", 600, 1, 900),
            catalog_background_max_resources=security_number("CATALOG_BACKGROUND_MAX_RESOURCES", 96, 12, 96),
            catalog_background_max_http_requests=security_number("CATALOG_BACKGROUND_MAX_HTTP_REQUESTS", 288, 18, 384),
            catalog_background_max_model_calls=security_number("CATALOG_BACKGROUND_MAX_MODEL_CALLS", 24, 3, 32),
            teaching_match_max_calls_per_job=security_number("TEACHING_MATCH_MAX_CALLS_PER_JOB", 2, 0, 2),
            teaching_match_enabled=boolean("TEACHING_MATCH_ENABLED", True),
            parallel_platform_search=boolean("PARALLEL_PLATFORM_SEARCH", True),
            open_web_search_enabled=boolean("OPEN_WEB_SEARCH_ENABLED", True),
            bilibili_search_rounds=security_number("BILIBILI_SEARCH_ROUNDS", 2, 1, 6),
            mooc_search_rounds=security_number("MOOC_SEARCH_ROUNDS", 2, 1, 10),
            max_search_requests=number("MAX_SEARCH_REQUESTS", 30, 1, 120),
            max_detail_pages=number("MAX_DETAIL_PAGES", 40, 0, 120),
            max_knowledge_points=number("MAX_KNOWLEDGE_POINTS", 5, 1, 5),
            max_results_per_point=number("MAX_RESULTS_PER_POINT", 5, 1, 5),
            global_concurrency=number("GLOBAL_CONCURRENCY", 5, 1, 5),
            deadline_seconds=number("TASK_DEADLINE_SECONDS", 180, 5, 600),
            max_pending_jobs=number("MAX_PENDING_JOBS", 20, 1, 100),
            submission_limit_per_minute=number("SUBMISSION_LIMIT_PER_MINUTE", 30, 1, 300),
            max_queue_wait_seconds=number("MAX_QUEUE_WAIT_SECONDS", 300, 1, 3600),
            project_max_batches=number("PROJECT_MAX_BATCHES", 6, 1, 24),
            project_max_search_requests=number("PROJECT_MAX_SEARCH_REQUESTS", 180, 1, 720),
            project_max_detail_pages=number("PROJECT_MAX_DETAIL_PAGES", 240, 0, 960),
            project_deadline_seconds=number("PROJECT_DEADLINE_SECONDS", 1800, 5, 14400),
            project_analysis_timeout_seconds=security_number("PROJECT_ANALYSIS_TIMEOUT_SECONDS", 90, 1, 120),
            project_analysis_total_timeout_seconds=security_number("PROJECT_ANALYSIS_TOTAL_TIMEOUT_SECONDS", 120, 1, 180),
            project_analysis_normalization_max_output_tokens=security_number("PROJECT_ANALYSIS_NORMALIZATION_MAX_OUTPUT_TOKENS", 12000, 256, 16000),
            project_semantic_review_enabled=semantic_review_setting(),
            search_timeout_seconds=number("SEARCH_TIMEOUT_SECONDS", 12, 1, 30),
            search_max_retries=number("SEARCH_MAX_RETRIES", 1, 0, 1),
            search_min_interval_seconds=number("SEARCH_MIN_INTERVAL_SECONDS", 1, 0, 5),
            search_results_per_query=number("SEARCH_RESULTS_PER_QUERY", 6, 1, 20),
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
            bilibili_public_metadata=boolean("BILIBILI_PUBLIC_METADATA", False),
            bilibili_public_metadata_max_bytes=security_number("BILIBILI_PUBLIC_METADATA_MAX_BYTES", 8_000_000, 4096, 16_000_000),
            denied_fetch_hosts=tuple(x.strip().lower() for x in os.getenv("DENIED_FETCH_HOSTS", "").split(",") if x.strip()),
            cors_origins=tuple(x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if x.strip()),
            local_only=local_only_setting(),
            allowed_hosts=tuple(x.strip().lower() for x in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1,::1").split(",") if x.strip()),
            max_request_body_bytes=security_number("MAX_REQUEST_BODY_BYTES", 512_000, 1024, 2_000_000),
            request_body_timeout_seconds=security_number("REQUEST_BODY_TIMEOUT_SECONDS", 10, 1, 60),
            api_write_limit_per_minute=security_number("API_WRITE_LIMIT_PER_MINUTE", 60, 1, 300),
            max_pending_analyses=security_number("MAX_PENDING_ANALYSES", 8, 1, 32),
            max_pending_project_searches=security_number("MAX_PENDING_PROJECT_SEARCHES", 20, 1, 100),
            max_event_streams=security_number("MAX_EVENT_STREAMS", 16, 1, 128),
        ).validate()
