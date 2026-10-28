"""Versioned project analysis and bounded, streaming video recommendations."""
from __future__ import annotations
from .learning_support import summarize_learning_support
from .platform_search import platform_budget

import asyncio
from contextlib import suppress
from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

from pydantic import ValidationError

from .config import Settings
from .db import Store
from .models import SearchRequest, now
from .project_db import ProjectStore
from .project_models import MAX_PROJECT_KNOWLEDGE_POINTS, AnalysisDocument, ProjectInput
from .project_analysis import (ANALYSIS_PROMPT_VERSION, ANALYSIS_MAX_MODEL_CALLS,
    ANALYSIS_TIMEOUT_SECONDS, ANALYSIS_TOTAL_TIMEOUT_SECONDS, AnalysisError, ProjectAnalyzer,
    concept_normalization_settings, project_analysis_settings)
from .project_search import searchable_unit_name
from .service import AdmissionRejected, JobService
from .technical_prefix import canonical_search_name, leading_technical_owner
from .professional_concepts import generated_context, bound_generated_context, reviewed_technologies, clean_topic_technology
from .ranking import summarize_collection_coverage
from .helpful_video_chapters import MAX_CATALOG_RESOURCES, MAX_CATALOG_HTTP_REQUESTS
from .snapshot_updates import CoalescedPublisher


def _safe_search_technology(value):
    """Keep query syntax safe without judging or rewriting saved analysis."""
    try:
        return clean_topic_technology(value)
    except (ValueError, TypeError):
        return ""


# Leave time for the terminal status write inside the advertised overall budget.
# This is an application deadline, not a real-time guarantee under a blocked OS
# or disk. Deadline checks also reject results returned after synchronous work.
ANALYSIS_PERSISTENCE_RESERVE_SECONDS = 0.5


class ProjectError(Exception):
    def __init__(self, code: str, message: str, status: int = 422, **details):
        self.code, self.message, self.status, self.details = code, message, status, details


class ProjectService:
    def __init__(self, settings: Settings, store: Store, jobs: JobService, analyzer=None):
        self.settings, self.store, self.jobs = settings, store, jobs
        self.db = ProjectStore(store)
        self.analyzer = analyzer or ProjectAnalyzer(settings)
        self.tasks: dict[tuple[str, int], asyncio.Task] = {}
        self.analysis_tasks: dict[tuple[str, int], asyncio.Task] = {}
        self.analysis_slots = asyncio.Semaphore(2)

    def start(self):
        self.db.recover_analysis()
        for project_id, version in self.db.pending_catalogs():
            data = self.db.version(project_id, version)
            self._finish_catalog(data, "interrupted")
            self.db.save(project_id, data)
        for project_id, version in self.db.running():
            # Recovery is a persistence transition, never new paid source work.
            # JobService has interrupted old queued/running jobs already. Do not
            # submit pending batches or resume deferred source followups here.
            _, data = self._version(project_id, version)
            for batch in data["batches"]:
                self._recover_batch_mapping(data, batch)
            self._refresh_batches(data)
            error = {"code": "process_restarted", "message": "服务重启已停止本轮检索，已取得的结果和预算记录保留；可手动重新检索这些知识点。"}
            for batch in data["batches"]:
                if batch["status"] == "pending":
                    batch.update(status="interrupted", error=error)
            data.update(status="interrupted", error=error)
            if data.get("fast_video_search"):
                data["fast_video_search"].update(status="interrupted", finished_at=now())
            if error["message"] not in data["warnings"]:
                data["warnings"].append(error["message"])
            self.db.save(project_id, data)

    @staticmethod
    def _catalog_pending(data):
        return (data.get("fast_video_search") or {}).get("catalog_enrichment", {}).get("status") == "running"

    @staticmethod
    def _finish_catalog(data, status):
        catalog = (data.get("fast_video_search") or {}).get("catalog_enrichment", {})
        if catalog.get("status") == "running":
            stamp = now()
            catalog.update(status=status, finished_at=stamp)
            if catalog.get("started_at"):
                catalog["elapsed_seconds"] = round(max(0, (datetime.fromisoformat(stamp) -
                    datetime.fromisoformat(catalog["started_at"])).total_seconds()), 3)

    def _recover_batch_mapping(self, data, batch):
        """Reconnect a previously committed job; never create or resume one."""
        if batch.get("job_id") or batch["status"] != "pending":
            return
        prior = self.store.idempotent_request(f"project:{batch['batch_id']}")
        job = self.store.get_job(prior["job_id"]) if prior else None
        snapshot = data.get("confirmation") or {}
        if (not job or snapshot.get("search_mode") != "professional_terms_v1" or
                not self.store.has_job_consumer(job["job_id"], f"project:{batch['batch_id']}")):
            return
        points = {point["id"]: point for point in snapshot["analysis"]["knowledge_points"]}
        try:
            names = self._professional_search_names([points[key] for key in batch["project_knowledge_point_ids"]])
        except (ValueError, KeyError):
            return
        stored = {point["text"]: point["knowledge_point_id"] for point in job["knowledge_points"]}
        if set(stored) != set(names.values()):
            return
        batch.update(job_id=job["job_id"], reused=True, status="submitted", error=None,
                     mappings=[{"project_knowledge_point_id": key, "knowledge_point_id": stored[name]}
                               for key, name in names.items()])

    async def stop(self):
        tasks = [*self.tasks.values(), *self.analysis_tasks.values()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.tasks.clear()
        self.analysis_tasks.clear()

    def capabilities(self) -> dict:
        from .fast_video_search import MAX_CATALOG_MODEL_CALLS, catalog_background_limits
        catalog = catalog_background_limits(self.settings)
        configured = bool(getattr(self.analyzer, "available", False))
        generation = project_analysis_settings(self.settings)
        repair = concept_normalization_settings(self.settings)
        total_timeout = min(60, ANALYSIS_TOTAL_TIMEOUT_SECONDS, self.settings.project_analysis_total_timeout_seconds)
        return {"project_analysis": {"status": "configured" if configured else "unconfigured",
                    "model": generation.llm_model or None, "prompt_version": ANALYSIS_PROMPT_VERSION,
                    "max_functions": 12, "max_knowledge_points": MAX_PROJECT_KNOWLEDGE_POINTS,
                    "mode": "professional_knowledge_points",
                    "analysis_format": "concept_list_v1",
                    "knowledge_point_fields": ["name", "description", "technology"],
                    "prerequisites_generated": False,
                    "learning_order_generated": False,
                    "semantic_review_enabled": False,
                    "coverage_review_enabled": False,
                    "implementation_inventory_enabled": False,
                    "coverage_completion_max_calls": 0,
                    "coverage_completion_max_output_tokens": 0,
                    "local_checks_enabled": False,
                    "schema_safety_checks_enabled": True,
                    "coverage_self_check": "disabled",
                    "semantic_completeness_certified": False,
                    "total_timeout_seconds": total_timeout,
                    "timeout_includes_queue": True,
                    "per_call_timeout_seconds": min(60, ANALYSIS_TIMEOUT_SECONDS,
                        self.settings.project_analysis_timeout_seconds, total_timeout),
                    "concept_normalization_enabled": False,
                    "normalization_max_calls": 0,
                    "reasoning_policy": self.settings.project_analysis_reasoning_effort,
                    "generation_thinking_mode": generation.llm_thinking_mode,
                    "generation_reasoning_effort": generation.llm_reasoning_effort,
                    "generation_max_output_tokens": generation.llm_max_output_tokens,
                    "conditional_repair_enabled": False,
                    "repair_shares_coverage_completion": False,
                    "repair_shares_total_deadline": False,
                    "repair_max_calls": 0,
                    "repair_thinking_mode": repair.llm_thinking_mode,
                    "repair_reasoning_effort": repair.llm_reasoning_effort,
                    "repair_max_output_tokens": repair.llm_max_output_tokens,
                    "generation_stages": ["compact_generation"],
                    "accepted_draft_immediate": True,
                    "concept_naming_policy": "generation_only",
                    "naming_advisories_preserved": False,
                    "repair_formats": [],
                    "max_model_calls": ANALYSIS_MAX_MODEL_CALLS,
                    "review_max_calls": 0,
                    "review_model": None,
                    "review_thinking_mode": None,
                    "review_reasoning_effort": None,
                    "review_max_output_tokens": 0,
                    "semantic_correction_max_calls": 0,
                    "semantic_correction_max_output_tokens": 0,
                    "message": "项目分析只生成一次，不进行名称或内容评判、不自动修正；排队与生成共用不超过一分钟的预算。" if configured else "项目分析不可用：服务端未配置模型；仍可直接搜索知识点"},
                "project_search": {"recommendation_policy": "helpful-video-v1" if self.settings.fast_video_recommendations_enabled else "related-reference-v1",
                    "match_policy": "targeted-video-v2" if self.settings.fast_video_recommendations_enabled else "related-reference-v1",
                    "max_batches": 1 if self.settings.fast_video_recommendations_enabled else self.settings.project_max_batches,
                    "max_search_requests": self.settings.project_max_search_requests,
                    "max_detail_pages": 0 if self.settings.fast_video_recommendations_enabled else self.settings.project_max_detail_pages,
                    "optional_catalog_resources": catalog["resources"] if self.settings.fast_video_recommendations_enabled else 0,
                    "catalog_http_requests": catalog["http_requests"] if self.settings.fast_video_recommendations_enabled else 0,
                    "recommendation_phase_catalog_resources": MAX_CATALOG_RESOURCES,
                    "recommendation_phase_catalog_http_requests": MAX_CATALOG_HTTP_REQUESTS,
                    "recommendation_phase_catalog_model_calls": MAX_CATALOG_MODEL_CALLS,
                    "catalog_required_for_recommendation": False,
                    "catalog_tail_wait_seconds": 0,
                    "catalog_background_seconds": catalog["seconds"],
                    "catalog_model_calls": catalog["model_calls"],
                    "catalog_resume_enabled": False,
                    "chapter_matching_enabled": False,
                    "cover_resume_enabled": True,
                    "cover_resume_resources": catalog["resources"],
                    "cover_resume_http_requests": catalog["http_requests"],
                    "cover_resume_model_calls": 0,
                    "cover_resume_seconds": catalog["seconds"],
                    "catalog_cache_enabled": True,
                    "catalog_resource_budget_scope": "network_only",
                    "deadline_seconds": self.settings.fast_video_deadline_seconds if self.settings.fast_video_recommendations_enabled else self.settings.project_deadline_seconds,
                    "batch_size": MAX_PROJECT_KNOWLEDGE_POINTS if self.settings.fast_video_recommendations_enabled else min(5, self.settings.max_knowledge_points),
                    "mode": "professional_terms_v1",
                    "budget_policy": "全部知识点共用检索预算，推荐数量不截断" if self.settings.fast_video_recommendations_enabled else "按每批完整单任务上限预留；超预算整体拒绝，不截断知识点",
                    "deadline_policy": "全部平台和知识点共用一次墙钟时限，边搜边展示" if self.settings.fast_video_recommendations_enabled else "预留各批完整执行时限之和；墙钟时限控制新批次启动，已提交共享任务继续至原任务时限",
                    "cancel_policy": "取消本版本正在进行的搜索和匹配，保留已展示推荐" if self.settings.fast_video_recommendations_enabled else "停止未提交批次并取消仅本项目使用的任务；共享或历史归属未知的任务继续，保留其结果"}}

    def _project(self, project_id):
        project = self.db.project(project_id)
        if project is None:
            raise ProjectError("not_found", "项目不存在", 404)
        return project

    def _version(self, project_id: str, version: int | None = None):
        project = self._project(project_id)
        version = project["current_version"] if version is None else version
        data = self.db.version(project_id, version)
        if data is None:
            raise ProjectError("version_not_found", "项目分析版本不存在", 404)
        return project, data

    def _expect_current(self, project: dict, expected: int | None):
        if expected is not None and expected != project["current_version"]:
            raise ProjectError("version_conflict", "项目已有更新，请刷新后再操作；旧版本结果仍可查看", 409)

    def create(self, input_data: ProjectInput):
        project_id = str(uuid4())
        self.db.create(project_id, input_data.model_dump())
        return self.view(project_id)

    def view(self, project_id: str, version: int | None = None, *, _job_results: dict | None = None):
        project = self._project(project_id)
        chosen = project["current_version"] if version is None else version
        data = self.db.version(project_id, chosen)
        if chosen and data is None:
            raise ProjectError("version_not_found", "项目分析版本不存在", 404)
        if data and data.get("batches"):
            self._refresh_batches(data, job_results=_job_results)
        return {**project, "versions": self.db.versions(project_id), "version": data}

    def _new_version(self, project: dict, input_data: dict, *, status: str, analysis=None, origin="analysis"):
        return {"version": project["current_version"] + 1, "input": input_data, "status": status,
                "analysis": analysis, "confirmation": None, "batches": [], "budgets": None,
                "error": None, "warnings": [], "created_at": now(), "model": project_analysis_settings(self.settings).llm_model or None,
                "prompt_version": ANALYSIS_PROMPT_VERSION, "origin": origin, "search_started_at": None,
                "cancel_requested": False}

    def analyze(self, project_id: str, expected_version: int | None = None, input_data: ProjectInput | None = None):
        loop = asyncio.get_running_loop()
        budget = min(60, ANALYSIS_TOTAL_TIMEOUT_SECONDS, self.settings.project_analysis_total_timeout_seconds)
        deadline = loop.time() + budget - min(ANALYSIS_PERSISTENCE_RESERVE_SECONDS, budget * 0.05)
        project = self._project(project_id)
        self._expect_current(project, expected_version)
        source = input_data.model_dump() if input_data is not None else project["input"]
        current = self.db.version(project_id, project["current_version"])
        if current and current["status"] == "analyzing" and current["input"] == source:
            return self.view(project_id)
        data = self._new_version(project, source, status="analyzing")
        data["analysis_timing"] = {"started_at": data["created_at"], "finished_at": None,
                                   "queue_wait_seconds": None, "processing_seconds": None,
                                   "elapsed_seconds": None, "budget_seconds": budget}
        self.db.save(project_id, data, new=True)
        key = project_id, data["version"]
        task = asyncio.create_task(self._analyze(project_id, data["version"], deadline=deadline))
        self.analysis_tasks[key] = task
        task.add_done_callback(lambda _: self.analysis_tasks.pop(key, None))
        return self.view(project_id)

    async def _analyze(self, project_id: str, version: int, *, deadline: float):
        _, data = self._version(project_id, version)
        data.setdefault("analysis_timing", {"started_at": data["created_at"], "finished_at": None,
                                           "queue_wait_seconds": None, "processing_seconds": None,
                                           "elapsed_seconds": None})

        def retain_rejection(entry: dict):
            # Version-private untrusted proposals, separate from usable analysis
            # and its normalized rows. Mobile uses its existing RAM store here;
            # these drafts must never be promoted into shared course facts.
            data.setdefault("rejected_analysis_attempts", []).append(
                {**deepcopy(entry), "project_id": project_id, "version": version})
            self.db.save(project_id, data)

        def retain_attempt(entry: dict):
            # Retain each attempted model response and its validation outcome.
            # Rejected candidates remain private; only validated results are usable.
            data.setdefault("analysis_attempts", []).append(
                {**deepcopy(entry), "project_id": project_id, "version": version})
            self.db.save(project_id, data)

        try:
            loop = asyncio.get_running_loop()
            if loop.time() >= deadline:
                raise TimeoutError
            async with asyncio.timeout_at(deadline):
                async with self.analysis_slots:
                    if loop.time() >= deadline:
                        raise TimeoutError
                    processing_started = now()
                    data["analysis_timing"]["processing_started_at"] = processing_started
                    data["analysis_timing"]["queue_wait_seconds"] = round((
                        datetime.fromisoformat(processing_started) -
                        datetime.fromisoformat(data["analysis_timing"]["started_at"])).total_seconds(), 6)
                    self.db.save(project_id, data)
                    if loop.time() >= deadline:
                        raise TimeoutError
                    audit_options = ({"on_rejected_attempt": retain_rejection, "on_analysis_attempt": retain_attempt,
                                      "deadline": deadline}
                                     if isinstance(self.analyzer, ProjectAnalyzer) else {})
                    analysis = await self.analyzer.analyze(ProjectInput.model_validate(data["input"]), **audit_options)
                # Synchronous validation or callbacks can exhaust a deadline
                # without giving asyncio's cancellation callback a turn to run.
                if loop.time() >= deadline:
                    raise TimeoutError
                document = AnalysisDocument.model_validate(analysis.model_dump() if hasattr(analysis, "model_dump") else analysis)
                serialized = document.model_dump()
                context = generated_context(serialized)
                if loop.time() >= deadline:
                    raise TimeoutError
                data.update(status="analyzed", analysis=serialized, error=None,
                            validated_concept_context=context)
        except asyncio.CancelledError:
            data.update(status="cancelled", analysis=None, cancel_requested=True,
                        error={"code": "cancelled", "message": "项目分析已中止，原始输入和历史版本已保留。"})
            raise
        except TimeoutError:
            data.update(status="analysis_failed", analysis=None,
                        error={"code": "timeout", "message": "项目分析已达到本次时间预算，原始输入和历史版本已保留。"})
        except AnalysisError as exc:
            data.update(status="analysis_failed", error={"code": exc.code, "message": exc.message})
            if exc.diagnostics:
                data["error"]["diagnostics"] = exc.diagnostics
        except Exception:
            data.update(status="analysis_failed", error={"code": "analysis_failed", "message": "项目分析失败，输入已保留；请稍后重试或使用直接知识点搜索。"})
        finally:
            finished_at = now()
            timing = data["analysis_timing"]
            timing.update(finished_at=finished_at, elapsed_seconds=round((
                datetime.fromisoformat(finished_at) - datetime.fromisoformat(timing["started_at"])).total_seconds(), 6))
            if timing.get("processing_started_at"):
                timing["processing_seconds"] = round((datetime.fromisoformat(finished_at) -
                    datetime.fromisoformat(timing["processing_started_at"])).total_seconds(), 6)
            else:
                timing["queue_wait_seconds"] = timing["elapsed_seconds"]
            self.db.save(project_id, data)

    def edit(self, project_id: str, expected_version: int, analysis: AnalysisDocument, input_data: ProjectInput | None = None):
        project = self._project(project_id)
        self._expect_current(project, expected_version)
        if not self.db.version(project_id, expected_version):
            raise ProjectError("version_not_found", "请先完成一次项目分析", 409)
        source = input_data.model_dump() if input_data else project["input"]
        prior = self.db.version(project_id, expected_version)
        if not prior.get("analysis"):
            raise ProjectError("analysis_required", "请先成功分析，再修改知识点", 409)
        data = self._new_version(project, source, status="analyzed", analysis=analysis.model_dump(), origin="student_edit")
        data.update(model=prior.get("model"), prompt_version=prior.get("prompt_version"), parent_version=expected_version)
        if bound_generated_context(prior) is not None:
            data["validated_concept_context"] = generated_context(analysis.model_dump())
        self.db.save(project_id, data, new=True)
        return self.view(project_id)

    def _budget(self, points: list[dict], platforms=None):
        if self.settings.fast_video_recommendations_enabled:
            from .fast_video_search import MAX_MODEL_CALLS, MAX_CATALOG_MODEL_CALLS, catalog_background_limits
            catalog = catalog_background_limits(self.settings)
            count = int(bool(points))
            return {"batch_size": max(1, len(points)), "batch_count": count,
                    "selected_count": len(points), "max_batches": 1,
                    "reserved_search_requests": self.settings.project_max_search_requests if points else 0,
                    "reserved_detail_pages": 0,
                    "reserved_model_calls": MAX_MODEL_CALLS + catalog["model_calls"] if points else 0,
                    "reserved_recommendation_model_calls": MAX_MODEL_CALLS if points else 0,
                    "reserved_catalog_model_calls": catalog["model_calls"] if points else 0,
                    "catalog_background_seconds": catalog["seconds"] if points else 0,
                    "reserved_task_seconds": self.settings.fast_video_deadline_seconds if points else 0,
                    "max_search_requests": self.settings.project_max_search_requests, "max_detail_pages": 0,
                    "optional_catalog_resources": catalog["resources"] if points else 0,
                    "catalog_http_requests": catalog["http_requests"] if points else 0,
                    "recommendation_phase_catalog_resources": MAX_CATALOG_RESOURCES if points else 0,
                    "recommendation_phase_catalog_http_requests": MAX_CATALOG_HTTP_REQUESTS if points else 0,
                    "recommendation_phase_catalog_model_calls": MAX_CATALOG_MODEL_CALLS if points else 0,
                    "deadline_seconds": self.settings.fast_video_deadline_seconds,
                    "per_batch_search_requests": self.settings.project_max_search_requests,
                    "per_batch_detail_pages": 0, "per_batch_deadline_seconds": self.settings.fast_video_deadline_seconds,
                    "search_policy": "helpful-video-v1", "first_pass_before_followups": False}
        size = min(5, self.settings.max_knowledge_points)
        count = (len(points) + size - 1) // size
        batch_requests = []
        batch_plans = []
        if self.settings.parallel_platform_search:
            try:
                for offset in range(0, len(points), size):
                    plan = platform_budget(self.settings, len(points[offset:offset + size]), platforms or [])
                    batch_requests.append(plan["max_search_requests"] if plan else self.settings.max_search_requests)
                    if plan:
                        batch_plans.append(plan)
            except ValueError as exc:
                raise ProjectError("search_budget_insufficient", str(exc)) from None
        budget = {"batch_size": size, "batch_count": count, "selected_count": len(points),
                  "reserved_search_requests": sum(batch_requests) if batch_requests else count * self.settings.max_search_requests,
                  "reserved_detail_pages": count * self.settings.max_detail_pages,
                  "reserved_task_seconds": count * self.settings.deadline_seconds,
                  "max_batches": self.settings.project_max_batches,
                  "max_search_requests": self.settings.project_max_search_requests,
                  "max_detail_pages": self.settings.project_max_detail_pages,
                  "deadline_seconds": self.settings.project_deadline_seconds,
                  "per_batch_search_requests": self.settings.max_search_requests,
                  "per_batch_deadline_seconds": self.settings.deadline_seconds,
                  "per_batch_detail_pages": self.settings.max_detail_pages}
        if batch_requests:
            budget.update(batch_search_requests=batch_requests,
                search_policy=batch_plans[0]["policy"] if batch_plans else "platform-rounds-v1",
                **({"platform_rounds": batch_plans[0]["platform_rounds"]} if batch_plans else {}),
                first_pass_before_followups=True)
        if count > budget["max_batches"] or budget["reserved_search_requests"] > budget["max_search_requests"] or budget["reserved_detail_pages"] > budget["max_detail_pages"] or budget["reserved_task_seconds"] > budget["deadline_seconds"]:
            raise ProjectError("project_budget_exceeded", "所选知识点超出项目总检索预算。请调整学习选择或分阶段分析；本次没有提交任何批次，也没有丢弃知识点。", budgets=budget)
        return budget

    @staticmethod
    def _professional_search_names(points):
        """Normalize literal names only; never infer from legacy annotations."""
        names, observed = {}, set()
        for point in points:
            name = canonical_search_name(point["name"])
            if not name or len(name) > 160:
                raise ProjectError("search_target_too_long", "知识点名称经空格规范化后不能为空或超过160字符，请修改名称后重新确认。")
            if name.casefold() in observed:
                raise ProjectError("search_target_collision", "规范化后的知识点名称重复，请区分名称后重新确认；所有原始知识点仍保留。")
            observed.add(name.casefold())
            names[point["id"]] = name
        try:
            values = list(names.values())
            for offset in range(0, len(values), 5):
                SearchRequest(knowledge_points=values[offset:offset + 5])
        except ValidationError:
            raise ProjectError("invalid_knowledge_points", "知识点名称不符合检索输入限制，请修改名称后重新确认；原分析已保留。") from None
        return names

    def confirm(self, project_id: str, version: int, acknowledged: list[str], *, reviewed_topic_technologies=None):
        project, data = self._version(project_id, version)
        self._expect_current(project, version)
        if data.get("confirmation"):
            if reviewed_topic_technologies is not None:
                try:
                    reviewed = reviewed_technologies(reviewed_topic_technologies, data["analysis"]["knowledge_points"])
                except ValueError:
                    raise ProjectError("invalid_topic_technologies", "检索技术语境必须绑定当前专业概念。") from None
                selected = set(data["confirmation"]["selected_ids"])
                names = self._professional_search_names([p for p in data["analysis"]["knowledge_points"] if p["id"] in selected])
                reviewed = {key: value for key, value in reviewed.items() if key in names.values()}
                if reviewed != data["confirmation"].get("topic_technologies", {}):
                    raise ProjectError("confirmation_conflict", "该版本已确认，请保存新版本后修改检索技术语境。", 409)
            return self.view(project_id, version)
        if not data.get("analysis") or data["status"] != "analyzed":
            raise ProjectError("analysis_required", "请先成功分析或保存修改后的知识点", 409)
        # Keep historical annotations in their immutable source snapshot, while
        # validating the chosen format on a detached projection. New flat
        # concepts keep their explicit technology and never acquire a graph.
        validation_analysis = deepcopy(data["analysis"])
        if validation_analysis.get("analysis_format") != "concept_list_v1":
            validation_analysis.pop("learner_profile", None)
            for point in validation_analysis.get("knowledge_points", []):
                for field in ("technology", "project_task", "concepts", "learning_skills", "practice_check"):
                    point.pop(field, None)
        document = AnalysisDocument.model_validate(validation_analysis)
        points = document.model_dump()["knowledge_points"]
        # The old acknowledgement input remains accepted for API compatibility
        # only. Selection and batching follow the stored array, never a graph
        # traversal, numeric learning order or checkbox click order.
        selected = [point for point in points if point["selection"] == "learn"]
        names = self._professional_search_names(selected)
        data["budgets"] = self._budget(selected, data["input"]["preferred_platforms"])
        data["confirmation"] = {"confirmation_version": version, "confirmed_at": now(), "search_mode": "professional_terms_v1",
            "selected_ids": [point["id"] for point in selected], "selections": {point["id"]: point["selection"] for point in points},
            "analysis": deepcopy(data["analysis"]), "input": deepcopy(data["input"])}
        try:
            technologies = (reviewed_technologies(reviewed_topic_technologies, data["analysis"]["knowledge_points"])
                if reviewed_topic_technologies is not None else bound_generated_context(data) or {})
        except ValueError:
            raise ProjectError("invalid_topic_technologies", "检索技术语境必须绑定当前专业概念，且只能包含简短的技术名称。") from None
        data["confirmation"]["topic_technologies"] = {key: value for key, value in technologies.items() if key in names.values()}
        data["status"] = "confirmed"
        self.db.save(project_id, data)
        return self.view(project_id, version)

    def search(self, project_id: str, version: int):
        project, data = self._version(project_id, version)
        if not data.get("confirmation"):
            raise ProjectError("confirmation_required", "必须先确认当前版本知识点，再启动课程检索", 409)
        if data.get("search_started_at") or data["status"] == "cancelled":
            return self.view(project_id, version)
        self._expect_current(project, version)
        snapshot = data["confirmation"]
        by_id = {point["id"]: point for point in snapshot["analysis"]["knowledge_points"]}
        selected = [by_id[point_id] for point_id in snapshot["selected_ids"]]
        names = self._professional_search_names(selected)
        # Existing confirmations do not inherit hidden historical annotations.
        # The explicit, immutable review or validated generation was bound at confirm.
        budget = self._budget(selected, snapshot["input"]["preferred_platforms"])
        # A first, explicitly requested search can adopt the current name-only
        # mode. Already-started historical jobs return above without migration.
        snapshot["search_mode"] = "professional_terms_v1"
        data["budgets"] = budget
        data["search_started_at"] = now()
        if self.settings.fast_video_recommendations_enabled:
            data["fast_video_search"] = {
                "policy": "helpful-video-v1", "status": "running" if selected else "completed",
                "started_at": data["search_started_at"], "finished_at": None, "elapsed_seconds": 0,
                "recommendations": {point["id"]: [] for point in selected},
                "progress": {"search_requests": 0, "model_calls": 0, "candidates": 0, "covered_points": 0},
                "diagnostics": {}}
            data["status"] = "running" if selected else "completed"
            self.db.save(project_id, data)
            if selected:
                self._schedule(project_id, version)
            return self.view(project_id, version)
        if not selected:
            data["status"] = "completed"
            data["warnings"].append("没有勾选知识点；已保存确认结果，没有创建检索任务。")
        else:
            size = data["budgets"]["batch_size"]
            for ordinal, offset in enumerate(range(0, len(selected), size), 1):
                data["batches"].append({"batch_id": f"{project_id}-v{version}-b{ordinal}", "ordinal": ordinal,
                    "project_knowledge_point_ids": [point["id"] for point in selected[offset:offset + size]],
                    "status": "pending", "job_id": None, "mappings": [], "error": None, "reused": False})
            data["status"] = "running"
        self.db.save(project_id, data)
        if selected:
            self._schedule(project_id, version)
        return self.view(project_id, version)

    def _schedule(self, project_id: str, version: int):
        key = project_id, version
        if key in self.tasks and not self.tasks[key].done():
            return
        task = asyncio.create_task(self._run_guarded(project_id, version))
        self.tasks[key] = task
        task.add_done_callback(lambda finished: self.tasks.pop(key, None)
                               if self.tasks.get(key) is finished else None)

    def resume_catalogs(self, project_id: str, version: int):
        # Existing clients may still use the catalog route. Chapter matching
        # was removed; only missing covers can be continued.
        return self._resume_metadata(project_id, version, cover_only=True)

    def resume_covers(self, project_id: str, version: int):
        return self._resume_metadata(project_id, version, cover_only=True)

    def _resume_metadata(self, project_id: str, version: int, *, cover_only=False):
        project, data = self._version(project_id, version)
        self._expect_current(project, version)
        fast = data.get("fast_video_search") or {}
        if not fast or not data.get("confirmation") or not any(fast.get("recommendations", {}).values()):
            raise ProjectError("catalog_results_required", "当前版本没有可补封面的视频", 409)
        key = project_id, version
        if key in self.tasks and not self.tasks[key].done():
            return self.view(project_id, version)
        if data["status"] in {"running", "analyzing", "cancelled"}:
            raise ProjectError("catalog_search_not_finished", "请先等待视频推荐完成", 409)
        run_id = str(uuid4())
        catalog = fast.setdefault("catalog_enrichment", {})
        catalog.update(status="running", run_id=run_id, started_at=now(), finished_at=None,
                       elapsed_seconds=0.0, mode="covers_only" if cover_only else "catalog_only")
        data["cancel_requested"] = False
        confirmation = data["confirmation"]
        selected_ids = set(confirmation["selected_ids"])
        selected = [point for point in confirmation["analysis"]["knowledge_points"] if point["id"] in selected_ids]
        current_budget = self._budget(selected, confirmation["input"].get("preferred_platforms"))
        # Existing video reservations and all actual counters stay untouched.
        if cover_only:
            data["budgets"].update(reserved_cover_resources=current_budget["optional_catalog_resources"],
                reserved_cover_http_requests=current_budget["catalog_http_requests"], reserved_cover_model_calls=0,
                cover_background_seconds=current_budget["catalog_background_seconds"])
        else:
            for field in ("reserved_model_calls", "reserved_catalog_model_calls", "catalog_background_seconds",
                          "optional_catalog_resources", "catalog_http_requests", "recommendation_phase_catalog_resources",
                          "recommendation_phase_catalog_http_requests", "recommendation_phase_catalog_model_calls"):
                data["budgets"][field] = current_budget[field]
        self.db.save(project_id, data)
        task = asyncio.create_task(self._run_catalogs_guarded(project_id, version, run_id, cover_only=cover_only))
        self.tasks[key] = task
        task.add_done_callback(lambda finished: self.tasks.pop(key, None)
                               if self.tasks.get(key) is finished else None)
        return self.view(project_id, version)

    async def _run_catalogs_guarded(self, project_id, version, run_id, *, cover_only=False):
        from .fast_video_search import resume_video_catalogs, resume_video_covers
        from .native_catalog_cache import NativeCatalogCache
        _, data = self._version(project_id, version)
        confirmation = data["confirmation"]
        points = [deepcopy(point) for point in confirmation["analysis"]["knowledge_points"]
                  if point["id"] in confirmation["selected_ids"]]
        for point in points:
            point["technology"] = _safe_search_technology(confirmation.get("topic_technologies", {}).get(
                canonical_search_name(point["name"]), point.get("technology", "")))

        def publish(snapshot):
            latest = self.db.version(project_id, version)
            prior = (latest or {}).get("fast_video_search") or {}
            catalog = prior.get("catalog_enrichment") or {}
            owner = self.tasks.get((project_id, version))
            if (not latest or latest.get("cancel_requested") or catalog.get("run_id") != run_id
                    or catalog.get("status") != "running" or (owner is not None and owner.cancelling())):
                return
            snapshot = deepcopy(snapshot)
            for field in ("status", "started_at", "finished_at", "elapsed_seconds"):
                snapshot[field] = prior.get(field)
            latest["fast_video_search"] = snapshot
            self.db.save(project_id, latest)

        coalesced = CoalescedPublisher(publish)
        try:
            resume = resume_video_covers if cover_only else resume_video_catalogs
            await resume(self.settings, points, data["fast_video_search"], publish=coalesced,
                catalog_cache=NativeCatalogCache(self.store, ttl_seconds=self.settings.page_cache_ttl,
                    page_lookup=self.jobs._page_cache,
                    shared_library_enabled=self.settings.shared_course_library_enabled))
        except asyncio.CancelledError:
            latest = self.db.version(project_id, version)
            if latest and ((latest.get("fast_video_search") or {}).get("catalog_enrichment") or {}).get("run_id") == run_id:
                catalog = latest["fast_video_search"]["catalog_enrichment"]
                if catalog.get("status") in {"running", "cancelled"}:
                    catalog.update(status="cancelled" if latest.get("cancel_requested") else "interrupted", finished_at=now())
                    self.db.save(project_id, latest)
            raise
        except Exception:
            with suppress(Exception):
                latest = self.db.version(project_id, version)
                if latest and ((latest.get("fast_video_search") or {}).get("catalog_enrichment") or {}).get("run_id") == run_id:
                    self._finish_catalog(latest, "failed")
                    self.db.save(project_id, latest)
        finally:
            coalesced.close()

    @staticmethod
    def _has_results(group):
        return bool(group and (group.get("items") or group.get("partial_items") or group.get("review_items") or group.get("discovery_items")))

    def _refresh_batches(self, data, *, job_results: dict | None = None):
        for batch in data["batches"]:
            if not batch.get("job_id"):
                continue
            job = self.store.get_job(batch["job_id"])
            if not job:
                batch.update(status="failed", error={"code": "missing_job", "message": "已提交的检索任务不存在；未自动重新发起"})
                continue
            status = job["status"]
            batch["job_status"] = status
            batch["progress"] = job.get("progress", {})
            batch["warnings"] = job.get("warnings", [])
            batch["errors"] = job.get("errors", [])
            if status in {"queued", "running"}:
                batch["status"] = "submitted"
            else:
                job_id = batch["job_id"]
                if job_results is not None and job_id in job_results:
                    results = job_results[job_id]
                else:
                    results = self.jobs.results(job_id)
                    if job_results is not None:
                        job_results[job_id] = results
                groups = (results or {}).get("groups", [])
                if groups and all(group.get("items") or group.get("discovery_items") for group in groups) and status == "completed":
                    batch["status"] = "completed"
                elif any(self._has_results(group) for group in groups):
                    batch["status"] = "partial"
                else:
                    batch["status"] = "no_results" if status == "completed" else status

    async def _run_guarded(self, project_id, version):
        try:
            _, data = self._version(project_id, version)
            if data.get("fast_video_search"):
                await self._run_fast(project_id, version)
            else:
                await self._run(project_id, version)
        except asyncio.CancelledError:
            with suppress(Exception):
                _, data = self._version(project_id, version)
                if self._catalog_pending(data):
                    self._finish_catalog(data, "cancelled" if data.get("cancel_requested") else "interrupted")
                    self.db.save(project_id, data)
                elif not data.get("cancel_requested"):
                    catalog = (data.get("fast_video_search") or {}).get("catalog_enrichment", {})
                    if catalog.get("status") == "cancelled":
                        catalog["status"] = "interrupted"
                        self.db.save(project_id, data)
            raise
        except Exception:
            with suppress(Exception):
                _, data = self._version(project_id, version)
                if data["status"] == "running":
                    data.update(status="failed", error={"code": "scheduler_failed", "message": "项目调度失败，已保存的检索任务和结果保留；未自动重复提交。"})
                    self._finish_catalog(data, "failed")
                    for batch in data["batches"]:
                        if batch["status"] == "pending":
                            batch.update(status="failed", error=data["error"])
                    self.db.save(project_id, data)
                elif self._catalog_pending(data):
                    self._finish_catalog(data, "failed")
                    self.db.save(project_id, data)

    async def _run_fast(self, project_id: str, version: int):
        from .fast_video_search import run_fast_video_search
        from .native_catalog_cache import NativeCatalogCache
        _, data = self._version(project_id, version)
        confirmation = data["confirmation"]
        selected_ids = set(confirmation["selected_ids"])
        points = [deepcopy(point) for point in confirmation["analysis"]["knowledge_points"]
                  if point["id"] in selected_ids]
        # Reviewed technical context stays bound to this immutable version.
        for point in points:
            point["technology"] = _safe_search_technology(confirmation.get("topic_technologies", {}).get(
                canonical_search_name(point["name"]), point.get("technology", "")))
        started = datetime.fromisoformat(data["search_started_at"])
        limit = min(data["budgets"]["deadline_seconds"], self.settings.fast_video_deadline_seconds)
        remaining = max(0, limit - (datetime.now(timezone.utc) - started).total_seconds())

        def publish(snapshot):
            latest = self.db.version(project_id, version)
            if not latest or latest.get("cancel_requested"):
                return
            prior = latest.get("fast_video_search") or {}
            already_finished = latest["status"] != "running"
            if already_finished and not self._catalog_pending(latest):
                return
            snapshot = deepcopy(snapshot)
            snapshot["started_at"] = data["search_started_at"]
            if already_finished:
                # Chapter updates belong to this immutable search version. They
                # cannot restart its progress bar or change recommendation timing.
                for field in ("status", "finished_at", "elapsed_seconds"):
                    snapshot[field] = prior.get(field)
            else:
                end = datetime.fromisoformat(snapshot["finished_at"]) if snapshot.get("finished_at") else datetime.now(timezone.utc)
                snapshot["elapsed_seconds"] = round(max(0, (end - started).total_seconds()), 3)
            latest["fast_video_search"] = snapshot
            latest["status"] = snapshot["status"]
            self.db.save(project_id, latest)

        coalesced = CoalescedPublisher(publish)
        try:
            await run_fast_video_search(self.settings, points, confirmation["input"],
                                        publish=coalesced, deadline_seconds=remaining, search_cache=self.store,
                                        catalog_cache=NativeCatalogCache(
                                            self.store, ttl_seconds=self.settings.page_cache_ttl,
                                            page_lookup=self.jobs._page_cache,
                                            shared_library_enabled=self.settings.shared_course_library_enabled))
        finally:
            coalesced.close()

    async def _run(self, project_id: str, version: int):
        while True:
            _, data = self._version(project_id, version)
            if data["cancel_requested"] or data["status"] != "running":
                return
            self._refresh_batches(data)
            pending = [batch for batch in data["batches"] if batch["status"] == "pending"]
            submitted = [batch for batch in data["batches"] if batch["status"] == "submitted"]
            budget = data["budgets"]
            if pending and (budget["batch_count"] > self.settings.project_max_batches
                    or budget["reserved_search_requests"] > self.settings.project_max_search_requests
                    or budget["reserved_detail_pages"] > self.settings.project_max_detail_pages
                    or budget["reserved_task_seconds"] > self.settings.project_deadline_seconds):
                for batch in pending:
                    batch.update(status="budget_exceeded", error={"code": "project_limits_changed", "message": "当前项目总预算已收紧，该批尚未执行；全部已选知识点及先前有效结果保留。"})
                pending = []
            elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(data["search_started_at"])).total_seconds()
            if pending and elapsed + self.settings.deadline_seconds > min(data["budgets"]["deadline_seconds"], self.settings.project_deadline_seconds):
                for batch in pending:
                    batch.update(status="budget_exceeded", error={"code": "project_deadline", "message": "项目调度时间预算已用尽，该批尚未执行；已提交批次保留。"})
                pending = []
            if not submitted and pending:
                batch = pending[0]
                budgets = data["budgets"]
                try:
                    live_plan = platform_budget(self.settings, len(batch["project_knowledge_point_ids"]),
                                                data["confirmation"]["input"]["preferred_platforms"])
                    live_search_requests = live_plan["max_search_requests"] if live_plan else self.settings.max_search_requests
                except ValueError as exc:
                    batch.update(status="budget_exceeded", error={"code": "search_budget_insufficient", "message": str(exc)})
                    self.db.save(project_id, data)
                    continue
                agreed_requests = (budgets["batch_search_requests"][batch["ordinal"] - 1]
                                   if budgets.get("batch_search_requests") else budgets["per_batch_search_requests"])
                agreed_rounds = budgets.get("platform_rounds") or {
                    platform: 2 for platform in data["confirmation"]["input"]["preferred_platforms"]}
                platform_allowance_grew = bool(live_plan and budgets.get("search_policy", "").startswith("platform-rounds-")
                    and any(rounds > agreed_rounds.get(platform, 0)
                            for platform, rounds in live_plan["platform_rounds"].items()))
                if (len(batch["project_knowledge_point_ids"]) > min(5, self.settings.max_knowledge_points)
                    or live_search_requests > agreed_requests
                    or platform_allowance_grew
                    or self.settings.max_detail_pages > budgets["per_batch_detail_pages"]
                    or self.settings.deadline_seconds > budgets["per_batch_deadline_seconds"]):
                    batch.update(status="budget_exceeded", error={"code": "runtime_limits_changed", "message": "运行配置已变更，不能在已确认预算内提交此批；请新建确认版本。"})
                else:
                    snapshot = data["confirmation"]
                    point_map = {point["id"]: point for point in snapshot["analysis"]["knowledge_points"]}
                    source = snapshot["input"]
                    context = "\n".join(part for part in [source["name"], source.get("project_context", ""), source["requirements"]] if part)
                    if len(context) > 1000:
                        warning = "原始用户背景超过1000字符，检索采用项目名称和背景摘要；完整原始输入与确认内容仍保留。"
                        if warning not in data["warnings"]:
                            data["warnings"].append(warning)
                    # The existing API's context field is a 1000-character summary, not the source archive.
                    search_names = self._professional_search_names([point_map[point_id]
                                    for point_id in batch["project_knowledge_point_ids"]])
                    request = SearchRequest(knowledge_points=list(search_names.values()),
                        topic_technologies={name: value for name, value in snapshot.get("topic_technologies", {}).items()
                                            if name in search_names.values()},
                        student_level=source["student_level"], language=source["language"], project_context=context[:1000],
                        technical_version=source["technical_version"], preferred_platforms=source["preferred_platforms"])
                    try:
                        options = {"defer_platform_followups": True} if live_plan else {}
                        result = self.jobs.create(request, idempotency_key=f"project:{batch['batch_id']}", consumer_key=f"project:{batch['batch_id']}", **options)
                        job = self.store.get_job(result["job_id"])
                        search_points = {point["text"]: point["knowledge_point_id"] for point in job["knowledge_points"]}
                        mappings = [{"project_knowledge_point_id": point_id,
                            "knowledge_point_id": search_points[search_names[point_id]]}
                            for point_id in batch["project_knowledge_point_ids"]]
                        batch.update(status="submitted", job_id=result["job_id"], reused=result["reused"], mappings=mappings, error=None)
                    except AdmissionRejected as exc:
                        # No automatic retry loop can bypass queue/rate/provider admission policy.
                        batch.update(status="failed", error={"code": exc.code, "message": exc.message})
                self.db.save(project_id, data)
                continue
            if not pending and not submitted and self.settings.parallel_platform_search:
                # Every selected batch has completed its initial platform pass.
                # Only now may any batch use the supplementary/retry allowance.
                resumed = False
                initial_jobs = [self.store.get_job(batch["job_id"]) if batch.get("job_id") else None for batch in data["batches"]]
                all_initial_complete = all(job and job.get("platform_search", {}).get("initial_done") for job in initial_jobs)
                if not all_initial_complete and any((job or {}).get("platform_search", {}).get("followup_pending") for job in initial_jobs):
                    notice = "部分批次首轮未完成，未使用其他批次的补搜额度；已取得的结果保留。"
                    if notice not in data["warnings"]:
                        data["warnings"].append(notice)
                for batch in data["batches"] if all_initial_complete else []:
                    if not batch.get("job_id") or batch.get("followup_error"):
                        continue
                    try:
                        resumed = self.jobs.resume_platform_search(batch["job_id"], consumer_key=f"project:{batch['batch_id']}")
                    except AdmissionRejected as exc:
                        batch["followup_error"] = {"code": exc.code, "message": exc.message}
                        data["warnings"].append(exc.message)
                    if resumed:
                        batch["status"] = "submitted"
                        self.db.save(project_id, data)
                        break
                if resumed:
                    continue
            if not pending and not submitted:
                statuses = {batch["status"] for batch in data["batches"]}
                data["status"] = ("completed" if statuses == {"completed"} else "no_results" if statuses == {"no_results"}
                    else "partial" if statuses & {"completed", "partial"} else "failed")
                if any(batch.get("followup_error") for batch in data["batches"]):
                    data["status"] = "partial"
                self.db.save(project_id, data)
                return
            self.db.save(project_id, data)
            await asyncio.sleep(0.3)

    async def cancel(self, project_id: str, version: int):
        _, data = self._version(project_id, version)
        if data.get("fast_video_search") and (data["status"] == "running" or self._catalog_pending(data)):
            # Persist cancellation first so in-flight callbacks cannot revive it.
            data["cancel_requested"] = True
            if data["status"] == "running":
                data["status"] = "cancelled"
                data["fast_video_search"].update(status="cancelled", finished_at=now())
            self._finish_catalog(data, "cancelled")
            self.db.save(project_id, data)
            task = self.tasks.get((project_id, version))
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            return self.view(project_id, version)
        if data["status"] in {"running", "confirmed"}:
            data.update(cancel_requested=True, status="cancelled")
            for batch in data["batches"]:
                if batch["status"] == "pending":
                    batch["status"] = "cancelled"
            data["warnings"].append("项目已取消：未提交批次停止；仅本项目使用的任务会取消。其他项目、直接搜索仍在使用或历史归属未知的任务继续，其有效结果保留。")
            self.db.save(project_id, data)
            for batch in data["batches"]:
                if batch.get("job_id"):
                    exclusive = self.store.release_job_consumer(batch["job_id"], f"project:{batch['batch_id']}")
                    if exclusive:
                        await self.jobs.cancel(batch["job_id"])
        return self.view(project_id, version)

    def results(self, project_id: str, version: int | None = None):
        # This dictionary lives for one synchronous results projection only.
        # Refresh still reads every batch's current job status; terminal ranking
        # results can serve both batch classification and the response body.
        job_results = {}
        view = self.view(project_id, version, _job_results=job_results)
        data = view["version"]
        if data and data.get("fast_video_search"):
            return self._fast_results(view)
        analysis = (data or {}).get("analysis") or {}
        batches = (data or {}).get("batches", [])
        point_to_batch = {point_id: batch for batch in batches for point_id in batch["project_knowledge_point_ids"]}
        for batch in batches:
            job_id = batch.get("job_id")
            if job_id and job_id not in job_results:
                job_results[job_id] = self.jobs.results(job_id)
        if data and data.get("budgets"):
            data["budgets"]["actual_search_requests"] = sum(batch.get("progress", {}).get("search_requests", 0) for batch in batches)
            data["budgets"]["actual_detail_pages"] = sum(batch.get("progress", {}).get("details_attempted", 0) + batch.get("progress", {}).get("catalog_pages_attempted", 0) for batch in batches)
        points = []
        for point in analysis.get("knowledge_points", []):
            batch = point_to_batch.get(point["id"])
            mapping = next((item for item in (batch or {}).get("mappings", []) if item["project_knowledge_point_id"] == point["id"]), None)
            result = next((group for group in ((job_results.get(batch["job_id"]) or {}).get("groups", []) if batch and batch.get("job_id") else [])
                           if mapping and group["knowledge_point_id"] == mapping["knowledge_point_id"]), None)
            scope_notice = ""
            technology = " ".join((point.get("technology") or "").split())
            professional = (data.get("confirmation") or {}).get("search_mode") == "professional_terms_v1"
            try:
                expected_name = canonical_search_name(point["name"]) if professional else searchable_unit_name(point, analysis.get("technical_plan", ""))
            except ValueError:
                expected_name = point["name"]  # Historic oversized targets stay readable.
            # Historic results may predate the explicit-leading-owner fix. Only
            # a single explicit identifier can be checked without guessing a
            # multi-tool scope. This is a detached read projection, not a write.
            explicit_owner = leading_technical_owner(technology + " unit")
            if (not professional and result and explicit_owner and explicit_owner.casefold() == technology.casefold()
                    and technology.casefold() not in {"general", "none", "not_applicable"}
                    and (leading_technical_owner(result.get("text") or "") or (result.get("text") or "")).strip().casefold() != technology.casefold()):
                scope_notice = "旧检索范围未以本单元声明的技术为前缀，结果已暂时隐藏；请重新检索该单元。"
                result = {**result,
                    **{key: [] for key in ("items", "partial_items", "review_items")},
                    **{key: {} for key in ("platform_items", "partial_platform_items", "review_platform_items", "platform_collection_coverage")},
                    **{key: 0 for key in ("total_matches", "total_partial_matches", "total_review_matches")},
                    "collection_coverage": summarize_collection_coverage(expected_name, [], point.get("concepts", [])),
                    **({"learning_coverage": summarize_learning_support(point, [])} if point.get("learning_skills") else {}),
                    "related_topic_pointers": [], "discovery_items": [], "discovery_platform_items": {},
                    "scope_status": "mismatch", "scope_notice": scope_notice, "expected_search_text": expected_name}
                data["warnings"] = list(dict.fromkeys([*data.get("warnings", []), scope_notice]))
            status = point["selection"] if point["selection"] != "learn" else (batch or {}).get("status", "not_started")
            if result and batch and batch["status"] not in {"pending", "submitted"}:
                status = "completed" if (result.get("items") or result.get("discovery_items")) and batch.get("job_status") == "completed" else "partial" if self._has_results(result) else "no_results" if batch.get("job_status") == "completed" else batch["status"]
            if scope_notice:
                status = "scope_mismatch"
            points.append({"project_knowledge_point_id": point["id"], "name": point["name"], "selection": point["selection"],
                "status": status, "batch_id": (batch or {}).get("batch_id"), "job_id": (batch or {}).get("job_id"),
                "knowledge_point_id": (mapping or {}).get("knowledge_point_id"), "result": result})
        return {**view, "points": points, "functions": analysis.get("functions", [])}

    @staticmethod
    def _fast_results(view):
        """Read-only projection; no model calls, fetches, or source submissions."""
        data = view["version"]
        fast = data["fast_video_search"]
        analysis = data.get("analysis") or {}
        selected = set((data.get("confirmation") or {}).get("selected_ids", []))
        points = []
        for point in analysis.get("knowledge_points", []):
            rows = fast.get("recommendations", {}).get(point["id"], []) if point["id"] in selected else []
            status = (point["selection"] if point["id"] not in selected else "running" if data["status"] == "running"
                      else "completed" if rows else data["status"] if data["status"] in {"cancelled", "failed", "interrupted"}
                      else "no_results")
            group = {"knowledge_point_id": point["id"], "text": point["name"],
                     "technology": point.get("technology", ""), "recommendation_policy": "helpful-video-v1",
                     "video_recommendations": rows, "section_limit": len(rows),
                     "items": [], "partial_items": [], "review_items": [],
                     "platform_items": {}, "partial_platform_items": {}, "review_platform_items": {},
                     "total_matches": 0, "total_partial_matches": 0, "total_review_matches": 0}
            points.append({"project_knowledge_point_id": point["id"], "name": point["name"],
                           "selection": point["selection"], "status": status, "batch_id": None,
                           "job_id": None, "knowledge_point_id": point["id"],
                           "result": group if point["id"] in selected else None})
        data["budgets"].update(actual_search_requests=fast.get("progress", {}).get("search_requests", 0),
                               actual_detail_pages=0, actual_model_calls=fast.get("progress", {}).get("model_calls", 0))
        catalog = fast.get("diagnostics", {}).get("chapters", {})
        data["budgets"].update(actual_catalog_resources=catalog.get("fetch_attempts", 0),
                               actual_catalog_model_calls=fast.get("progress", {}).get("catalog_model_calls", 0),
                               actual_recommendation_model_calls=fast.get("progress", {}).get("recommendation_model_calls", fast.get("progress", {}).get("model_calls", 0)),
                               actual_catalog_cache_hits=catalog.get("cache_hits", 0),
                               actual_catalog_http_requests=catalog.get("http_requests", 0))
        covers = fast.get("diagnostics", {}).get("covers", {})
        data["budgets"].update(actual_cover_resources=covers.get("fetch_attempts", 0),
                               actual_cover_http_requests=covers.get("http_requests", 0),
                               actual_cover_model_calls=0,
                               actual_cover_cache_hits=covers.get("cache_hits", 0))
        return {**view, "points": points, "functions": analysis.get("functions", [])}
