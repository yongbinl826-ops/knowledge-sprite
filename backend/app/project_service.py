"""Project analysis/confirmation orchestration; all discovery stays in JobService."""
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
from .project_models import AnalysisDocument, ProjectInput
from .project_analysis import ANALYSIS_PROMPT_VERSION, AnalysisError, ProjectAnalyzer, concept_normalization_settings
from .project_search import searchable_unit_name
from .service import AdmissionRejected, JobService
from .technical_prefix import canonical_search_name, leading_technical_owner
from .professional_concepts import generated_context, bound_generated_context, reviewed_technologies
from .ranking import summarize_collection_coverage


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
            if error["message"] not in data["warnings"]:
                data["warnings"].append(error["message"])
            self.db.save(project_id, data)

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
        configured = bool(getattr(self.analyzer, "available", False))
        normalization = concept_normalization_settings(self.settings)
        return {"project_analysis": {"status": "configured" if configured else "unconfigured",
                    "model": self.settings.llm_model or None, "prompt_version": ANALYSIS_PROMPT_VERSION,
                    "max_functions": 12, "max_knowledge_points": 24,
                    "mode": "professional_knowledge_points",
                    "analysis_format": "concept_list_v1",
                    "knowledge_point_fields": ["name", "description", "technology"],
                    "prerequisites_generated": False,
                    "learning_order_generated": False,
                    "semantic_review_enabled": False,
                    "concept_normalization_enabled": True,
                    "normalization_max_calls": 1,
                    "normalization_thinking_mode": normalization.llm_thinking_mode,
                    "normalization_reasoning_effort": normalization.llm_reasoning_effort,
                    "normalization_max_output_tokens": normalization.llm_max_output_tokens,
                    "generation_stages": ["generation", "normalization"],
                    "max_model_calls": 2,
                    "review_max_calls": 0,
                    "review_max_output_tokens": 0,
                    "message": "项目分析使用独立提示词；内容需学生检查确认" if configured else "项目分析不可用：服务端未配置模型；仍可直接搜索知识点"},
                "project_search": {"max_batches": self.settings.project_max_batches,
                    "max_search_requests": self.settings.project_max_search_requests,
                    "max_detail_pages": self.settings.project_max_detail_pages,
                    "deadline_seconds": self.settings.project_deadline_seconds,
                    "batch_size": min(5, self.settings.max_knowledge_points),
                    "mode": "professional_terms_v1",
                    "budget_policy": "按每批完整单任务上限预留；超预算整体拒绝，不截断知识点",
                    "deadline_policy": "预留各批完整执行时限之和；墙钟时限控制新批次启动，已提交共享任务继续至原任务时限",
                    "cancel_policy": "停止未提交批次并取消仅本项目使用的任务；共享或历史归属未知的任务继续，保留其结果"}}

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
                "error": None, "warnings": [], "created_at": now(), "model": self.settings.llm_model or None,
                "prompt_version": ANALYSIS_PROMPT_VERSION, "origin": origin, "search_started_at": None,
                "cancel_requested": False}

    def analyze(self, project_id: str, expected_version: int | None = None, input_data: ProjectInput | None = None):
        project = self._project(project_id)
        self._expect_current(project, expected_version)
        source = input_data.model_dump() if input_data is not None else project["input"]
        current = self.db.version(project_id, project["current_version"])
        if current and current["status"] == "analyzing" and current["input"] == source:
            return self.view(project_id)
        data = self._new_version(project, source, status="analyzing")
        self.db.save(project_id, data, new=True)
        key = project_id, data["version"]
        task = asyncio.create_task(self._analyze(project_id, data["version"]))
        self.analysis_tasks[key] = task
        task.add_done_callback(lambda _: self.analysis_tasks.pop(key, None))
        return self.view(project_id)

    async def _analyze(self, project_id: str, version: int):
        _, data = self._version(project_id, version)

        def retain_rejection(entry: dict):
            # Version-private untrusted proposals, separate from usable analysis
            # and its normalized rows. Mobile uses its existing RAM store here;
            # these drafts must never be promoted into shared course facts.
            data.setdefault("rejected_analysis_attempts", []).append(
                {**deepcopy(entry), "project_id": project_id, "version": version})
            self.db.save(project_id, data)

        def retain_attempt(entry: dict):
            # Keep both model responses for diagnosis, including the draft that
            # passed local checks but was not yet normalized or delivered.
            data.setdefault("analysis_attempts", []).append(
                {**deepcopy(entry), "project_id": project_id, "version": version})
            self.db.save(project_id, data)

        try:
            async with self.analysis_slots:
                audit_options = ({"on_rejected_attempt": retain_rejection, "on_analysis_attempt": retain_attempt}
                                 if isinstance(self.analyzer, ProjectAnalyzer) else {})
                analysis = await self.analyzer.analyze(ProjectInput.model_validate(data["input"]), **audit_options)
            # Validate again at the persistence boundary, including injected test analyzers.
            document = AnalysisDocument.model_validate(analysis.model_dump() if hasattr(analysis, "model_dump") else analysis)
            data.update(status="analyzed", analysis=document.model_dump(), error=None)
            data["validated_concept_context"] = generated_context(document.model_dump())
        except asyncio.CancelledError:
            raise
        except AnalysisError as exc:
            data.update(status="analysis_failed", error={"code": exc.code, "message": exc.message})
            if exc.diagnostics:
                data["error"]["diagnostics"] = exc.diagnostics
        except Exception:
            data.update(status="analysis_failed", error={"code": "analysis_failed", "message": "项目分析失败，输入已保留；请稍后重试或使用直接知识点搜索。"})
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
        task.add_done_callback(lambda _: self.tasks.pop(key, None))

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
            await self._run(project_id, version)
        except asyncio.CancelledError:
            raise
        except Exception:
            with suppress(Exception):
                _, data = self._version(project_id, version)
                if data["status"] == "running":
                    data.update(status="failed", error={"code": "scheduler_failed", "message": "项目调度失败，已保存的检索任务和结果保留；未自动重复提交。"})
                    for batch in data["batches"]:
                        if batch["status"] == "pending":
                            batch.update(status="failed", error=data["error"])
                    self.db.save(project_id, data)

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
