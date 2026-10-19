"""Local acceptance server for project analysis v1, with a fresh SQLite database.

Uses production configuration, analyzer, scheduler and search services. No model
fixture, candidate injection or saved-page replay is permitted in this runner.
The existing read-only request observer records newly performed search/fetches.
"""
from __future__ import annotations

import argparse
from contextlib import asynccontextmanager
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re
import sys
import time
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.config import Settings
from backend.app.models import now
import backend.app.main as main_module
import backend.app.llm as llm_module
import backend.app.project_analysis as analysis_module
import backend.app.analysis_review as review_module
import backend.app.teaching_match as teaching_module
import backend.app.teaching_review as teaching_review_module
from scripts import serve_platform_live_chain as audit


def _model_audit_failure(output: Path, registry: dict, operation: str, error: Exception):
    """Evidence failures invalidate acceptance without replacing model outcomes."""
    token = audit.CURRENT_AUDIT.set(registry)
    try:
        audit.audit_error(operation, error)
    finally:
        audit.CURRENT_AUDIT.reset(token)


def _append_model_event(output: Path, registry: dict, event: dict):
    try:
        with (output / "model-events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        registry["model_event_count"] = registry.get("model_event_count", 0) + 1
    except Exception as exc:
        _model_audit_failure(output, registry, "write_model_event", exc)


def _metadata_identifier(value, secret: str):
    # Provider metadata is untrusted. Exclude free text, credentials, URLs,
    # control characters and arbitrarily long provider-generated strings.
    if (not isinstance(value, str) or (secret and secret in value)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,159}", value)
            or "://" in value):
        return None
    return value


def _usage_numbers(value):
    if not isinstance(value, dict):
        return {}
    scalar_keys = {"prompt_tokens", "completion_tokens", "total_tokens", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens"}
    details_keys = {"prompt_tokens_details": {"cached_tokens", "audio_tokens", "text_tokens", "image_tokens"},
                    "completion_tokens_details": {"reasoning_tokens", "audio_tokens", "text_tokens", "accepted_prediction_tokens", "rejected_prediction_tokens"}}
    safe = {key: number for key, number in value.items()
            if key in scalar_keys and type(number) is int and 0 <= number <= 10**12}
    for key, allowed in details_keys.items():
        if isinstance(value.get(key), dict):
            safe[key] = {name: number for name, number in value[key].items()
                         if name in allowed and type(number) is int and 0 <= number <= 10**12}
    return safe


def _response_metadata(response: httpx.Response | ModelResponseObservation | None, secret: str):
    metadata = {"http_status": None, "response_body_sha256": None, "response_bytes": None,
                "message_content_sha256": None, "message_content_chars": None,
                "provider_response_id": None, "provider_model": None, "usage": {}, "finish_reason": None,
                "response_read_complete": False}
    if response is None:
        return metadata
    metadata["http_status"] = response.status_code
    if isinstance(response, ModelResponseObservation):
        body = response.body
        if body is None:
            return metadata
    else:
        try:
            body = response.content
        except httpx.ResponseNotRead:
            return metadata  # A genuine body timeout may follow an observed status.
    metadata.update(response_body_sha256=hashlib.sha256(body).hexdigest(), response_bytes=len(body), response_read_complete=True)
    try:
        envelope = json.loads(body)
    except (ValueError, UnicodeError):
        return metadata  # Non-JSON error pages are normal observable failures.
    if not isinstance(envelope, dict):
        return metadata
    metadata.update(provider_response_id=_metadata_identifier(envelope.get("id"), secret),
                    provider_model=_metadata_identifier(envelope.get("model"), secret),
                    usage=_usage_numbers(envelope.get("usage")))
    choices = envelope.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        metadata["finish_reason"] = _metadata_identifier(choices[0].get("finish_reason"), secret)
        message = choices[0].get("message")
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            content = message["content"]
            metadata.update(message_content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(), message_content_chars=len(content))
    return metadata


class ModelResponseObservation:
    """Independent bounded metadata source; never alter httpx private fields."""
    def __init__(self, status_code):
        self.status_code = status_code
        self.body: bytes | None = None


def observed_complete_json(output: Path, registry: dict, original, *, client_factory=httpx.AsyncClient):
    """Runner-only observation. No prompts, input data, headers or response text are saved."""
    async def complete(settings, system_prompt, data, client=None, *, timeout_seconds=15, max_content_chars=40_000):
        started_at, clock_start = now(), time.monotonic()
        task = ("project_analysis" if system_prompt == analysis_module.SYSTEM_PROMPT else
                  "project_analysis_review" if system_prompt == review_module.SYSTEM_REVIEW_PROMPT else
                  "teaching_skill_match" if system_prompt == teaching_module.SYSTEM_TEACHING_PROMPT else
                  "teaching_claim_review" if system_prompt == teaching_review_module.SYSTEM_REVIEW_PROMPT else
                "keyword_expansion" if 'Return {"keywords"' in system_prompt else
                "course_reranking" if 'Return {"rankings"' in system_prompt else "structured_model_call")
        identity = {"call_id": uuid4().hex, "task": task,
                    "system_prompt_sha256": hashlib.sha256(system_prompt.encode("utf-8")).hexdigest(), "started_at": started_at}
        _append_model_event(output, registry, {"event_type": "model_call_started", **identity})
        observed = {"response": None}
        failure_type = None

        async def on_response(response):
            # Headers have arrived. Do not read the body in the hook; the same
            # production stream will read it with the original timeout.
            observed["response"] = response

        class BorrowedClientObserver:
            def __init__(self, source):
                self.source = source

            async def post(self, *args, **kwargs):
                response = await self.source.post(*args, **kwargs)
                observed["response"] = response
                return response

            @asynccontextmanager
            async def stream(self, *args, **kwargs):
                async with self.source.stream(*args, **kwargs) as response:
                    observation = ModelResponseObservation(response.status_code)
                    observed["response"] = observation

                    class ObservedStream:
                        def __getattr__(self, name):
                            return getattr(response, name)

                        async def aiter_bytes(self, *iter_args, **iter_kwargs):
                            body = bytearray()
                            limit = max(250_000, max_content_chars * 6)
                            complete = True
                            async for chunk in response.aiter_bytes(*iter_args, **iter_kwargs):
                                if len(body) + len(chunk) <= limit:
                                    body.extend(chunk)
                                else:
                                    complete = False
                                yield chunk
                            if complete:
                                observation.body = bytes(body)

                    yield ObservedStream()

        try:
            if client is not None:
                return await original(settings, system_prompt, data, BorrowedClientObserver(client),
                                      timeout_seconds=timeout_seconds, max_content_chars=max_content_chars)
            # Match complete_json's normal owned-client settings exactly. This
            # adds a read-only hook without changing payload, auth or redirects.
            async with client_factory(timeout=httpx.Timeout(timeout_seconds, connect=5), follow_redirects=False,
                                      event_hooks={"response": [on_response]}) as owned_client:
                return await original(settings, system_prompt, data, BorrowedClientObserver(owned_client),
                                      timeout_seconds=timeout_seconds, max_content_chars=max_content_chars)
        except BaseException as exc:
            # Never serialize exception messages, URLs or provider error bodies.
            failure_type = type(exc).__name__
            raise
        finally:
            event = {"event_type": "model_call_finished", **identity, "finished_at": now(),
                     "elapsed_seconds": round(time.monotonic() - clock_start, 6),
                     "outcome": "failed" if failure_type else "json_returned", "failure_type": failure_type}
            try:
                event.update(_response_metadata(observed["response"], settings.llm_api_key))
            except Exception as exc:
                _model_audit_failure(output, registry, "observe_model_response", exc)
                event["metadata_observation_failed"] = True
            _append_model_event(output, registry, event)

    complete._unobserved_complete_json = getattr(original, "_unobserved_complete_json", original)
    return complete


def install_model_observer(output: Path, registry: dict):
    original = getattr(llm_module.complete_json, "_unobserved_complete_json", llm_module.complete_json)
    observer = observed_complete_json(output, registry, original)
    llm_module.complete_json = observer
    analysis_module.complete_json = observer
    review_module.complete_json = observer
    teaching_module.complete_json = observer
    teaching_review_module.complete_json = observer


def app_for(output: Path, port: int, *, resume: bool = False):
    output.mkdir(parents=True, exist_ok=True)
    database = output / "live.sqlite3"
    if database.exists() != resume:
        raise RuntimeError("Fresh runs require an empty database; --resume requires an existing database")
    settings = replace(Settings.from_env(), database_path=str(database))
    registry = {"output": str(output), "acceptance_valid": True, "audit_errors": [], "jobs": {}}
    install_model_observer(output, registry)
    main_module.JobService = audit.service_class(output, registry)
    # create_app closes over the module class during lifespan startup. Keep this
    # observer class installed for this isolated process only.
    app = main_module.create_app(settings)
    sources = [p for folder in (ROOT / "backend/app", ROOT / "frontend/dist")
               for p in folder.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    sources.append(Path(__file__).resolve())
    manifest = {
        "started_at": now(), "url": f"http://127.0.0.1:{port}",
        "fresh_database": not resume, "saved_page_replay": False,
        "candidate_injection": False, "mock_model": False,
        "model_observation": {"enabled": True, "log": "model-events.jsonl", "response_bodies_saved": False,
                              "requests_or_headers_saved": False, "production_request_semantics_changed": False},
        "llm_provider": settings.llm_provider, "llm_model": settings.llm_model,
        "model_configured": bool(settings.llm_provider == "openai_compatible" and
                                 settings.llm_api_key and settings.llm_model and settings.llm_base_url),
        "search_provider": settings.search_provider,
        "limits": {"points_per_job": settings.max_knowledge_points,
                   "search_requests_per_job": settings.max_search_requests,
                   "detail_pages_per_job": settings.max_detail_pages,
                   "seconds_per_job": settings.deadline_seconds},
        "bilibili_public_metadata": settings.bilibili_public_metadata,
        "environment_sha256": hashlib.sha256((ROOT / ".env").read_bytes()).hexdigest(),
        "source_hashes": {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
    }
    name = "resume-" + now().replace(":", "-") + ".json" if resume else "run.json"
    (output / name).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    @app.get("/api/live-audit", include_in_schema=False)
    async def live_audit():
        return registry

    return app


if __name__ == "__main__":
    import uvicorn
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "reports/project-analysis-v1-20261017/live")
    parser.add_argument("--port", type=int, default=18117)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    uvicorn.run(app_for(args.output.resolve(), args.port, resume=args.resume),
                host="127.0.0.1", port=args.port, workers=1)
