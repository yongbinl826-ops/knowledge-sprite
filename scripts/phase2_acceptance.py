"""Independent phase-2 analysis acceptance through the configured local API.

Default mode only writes the plan. Live mode submits each synthetic case once,
never confirms/searches, never reads credentials, and checkpoints before writes.
An uncertain mutation is not retried. Observe mode only reads known projects.
Machine observations do not replace the separate manual semantic review.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.project_analysis import learning_quality_issues
from backend.app.project_models import AnalysisDocument, ProjectInput


CASES = [
    {
        "id": "web_pomodoro_beginner",
        "input": {
            "name": "离线番茄钟学习网页",
            "requirements": "用 HTML、CSS、JavaScript 做本机浏览器可用的番茄钟网页。专注固定25分钟、休息固定5分钟，能开始、暂停、继续和重置；倒计时结束后切换到下一阶段并暂停等待用户开始；每完成一个专注阶段次数加1。切到后台标签页再回来，剩余时间仍应准确，不能只靠setInterval每次减1。显示当前阶段、剩余时间和已完成次数，手机窄屏可用，键盘能操作所有按钮。不需要账号、联网、通知、音效或后端。",
            "student_level": "beginner",
            "project_context": "会基础 HTML/CSS 和 JavaScript 变量、if，还没有做过完整交互项目；希望每个单元有可验证的小成果。",
        },
        "coverage": [
            ("页面状态与可访问按钮", r"按钮|语义|键盘|button|accessib"),
            ("倒计时与后台时间准确性", r"时间戳|截止|deadline|date\.now|performance\.now|实际.{0,8}时间|目标.{0,5}时间"),
            ("暂停继续重置", r"暂停|继续|重置|pause|resume|reset"),
            ("阶段切换与完成次数", r"阶段|专注|休息|phase|session"),
            ("手机与键盘", r"响应式|窄屏|手机|键盘|responsive|keyboard"),
        ],
        "manual_checks": [
            "暂停后剩余时长不再下降，继续后应基于新的截止时间恢复。",
            "后台标签页计时用实际时钟而不是定时回调次数；允许回前台后重算。",
            "阶段完成只累计一次，进入下一阶段后暂停，不自动连续启动。",
            "不把尚未学过的事件/时间 API 误当已有经验，不添加通知权限或后端。",
        ],
    },
    {
        "id": "bicycle_csv_advanced",
        "input": {
            "name": "共享单车出行 CSV 分析报告",
            "requirements": "用 Python、pandas 和 Matplotlib 在本机分析一份合成骑行 CSV，列为trip_id、start_time、end_time、start_station；时间均为同一城市本地时间。按trip_id去重并记录删行数，解析时间，单独记录缺失或结束早于开始的无效行；对有效行计算分钟时长，按出发小时汇总骑行次数，绘制出发站次数Top10条形图。导出清洗后含时长的CSV、按小时汇总CSV和PNG图；图要有标题、轴标签。不要预测、仪表盘、地图、账号或云部署。",
            "student_level": "advanced",
            "project_context": "已有 Python 函数、文件读写、调试和统计基础，但第一次用 pandas 处理出行数据，也不熟悉 Matplotlib 的API。希望重点理解时间清洗、分组与可复核的数据口径，不要重新上通用 Python 入门课，也不要假定高级标签就代表熟悉所有库。",
        },
        "coverage": [
            ("载入与去重审计", r"read_csv|去重|duplicat"),
            ("时间解析与无效行", r"to_datetime|时间.{0,5}解析|无效|invalid"),
            ("分钟时长", r"分钟|total_seconds|duration|时长"),
            ("出发小时计数", r"小时|\.dt\.hour|hour|分组|groupby"),
            ("出发站Top10与图标签", r"top.?10|前.?10|前十|条形|bar|nlargest"),
            ("CSV及PNG导出", r"to_csv|savefig|导出|png"),
        ],
        "manual_checks": [
            "缺失/无法解析时间及结束早于开始的行有可审计处理，不混入有效行时长。",
            "分钟时长采用时间差总秒数/60，避免使用忽略天数的 seconds 属性。",
            "小时口径为出发小时；站点Top10按次数排序，CSV与图来自相同有效数据。",
            "尊重已有 Python/统计基础，同时教授首次使用 pandas/Matplotlib 必需API。",
        ],
    },
    {
        "id": "arduino_reaction_beginner",
        "input": {
            "name": "Arduino LED 按钮反应时间小游戏",
            "requirements": "用 Arduino Uno、一个带限流电阻的LED和一个按钮做低压反应时间小游戏。按钮使用INPUT_PULLUP接地，串口监视器显示提示和结果；按一下开始一轮，先随机等待2到5秒再亮LED，亮灯后按按钮显示反应毫秒数。等待期间若提前按下则判抢按，之后可按按钮开始新一轮。全程仍能识别按钮，不能用delay阻塞随机等待；按钮需要去抖，长按不能连续启动多轮。说明断电接线、LED极性和共地，不接市电、电机或继电器。",
            "student_level": "beginner",
            "project_context": "做过一次点亮 LED，知道上传Arduino程序，但没有做过按钮输入和状态机项目。希望先完成安全接线和单个输入输出，再整合游戏。",
        },
        "coverage": [
            ("安全低压LED按钮接线", r"限流|电阻|极性|共地|断电|resistor|wiring"),
            ("INPUT_PULLUP低电平输入", r"INPUT_PULLUP|低电平|上拉|pull.up"),
            ("去抖与单次按下", r"去抖|边沿|按下沿|debounc|edge"),
            ("随机等待与非阻塞计时", r"millis|非阻塞|时间差|non.block"),
            ("抢按与状态转换", r"抢按|状态|false.start|state"),
            ("反应毫秒与串口结果", r"反应|毫秒|串口|serial|reaction"),
        ],
        "manual_checks": [
            "按钮接地且INPUT_PULLUP按下为LOW；LED串联限流电阻，共地、断电接线。",
            "随机等待用millis/状态机，不用阻塞delay；等待时也持续检测抢按。",
            "去抖后检测一次按下边沿，长按不被用作结束旧轮并重复开始新轮。",
            "反应时间从实际亮灯时刻起算；每轮清理计时和判定状态。",
        ],
    },
    {
        "id": "pygame_maze_intermediate",
        "input": {
            "name": "pygame 单屏迷宫寻出口",
            "requirements": "用 Python 和 pygame 做单屏8乘8固定迷宫小游戏。地图用二维列表表示墙、路和出口；方向键每次按下移动一格，不能穿墙或越出地图。到达出口后显示胜利和本轮耗时，按R可重置玩家位置与计时，Esc或关闭窗口可退出。开始前和胜利后都必须能处理按键与关窗，使用帧率上限，耗时依据真实时间而非帧数。不需要自动生成迷宫、寻路提示、敌人、联网或计分排行。",
            "student_level": "intermediate",
            "project_context": "会 Python 列表、循环、函数，做过 pygame 窗口和绘图，但没写过网格地图和完整胜利/重置状态。希望聚焦网格坐标、阻挡、输入边沿和时间/状态处理。",
        },
        "coverage": [
            ("二维地图与网格映射", r"二维|网格|行列|tile|grid"),
            ("逐格输入与墙边界阻挡", r"KEYDOWN|逐格|墙|越界|碰撞|wall"),
            ("出口胜利状态", r"出口|胜利|状态|win|state"),
            ("真实耗时与帧率", r"get_ticks|tick|真实时间|时间差|帧率|elapsed"),
            ("R重置与退出事件", r"重置|复位|reset|退出|quit"),
        ],
        "manual_checks": [
            "先校验目标行列边界再访问二维列表，并检查墙；不把像素坐标与格坐标混淆。",
            "单次KEYDOWN移动一格，避免每帧连续按键造成一按跨多格。",
            "耗时按真实时钟差计算，与帧率限制分开；胜利后冻结最终耗时。",
            "胜利/开始前保持事件和绘制，R重置位置/计时/胜利状态，退出始终可用。",
        ],
    },
]


STANDARDS = {
    "scope": "Four synthetic, previously unseen projects and three learner stages; no video-search submission by this script.",
    "coverage": "Every stated behavior needs a concrete implementing unit or useful prerequisite. Keyword observations only flag areas for manual review.",
    "granularity": "One coherent buildable subtask per unit, not a full language course or isolated syntax. Four to eight units is a soft observation range; fewer is acceptable when prior knowledge justifies it.",
    "prerequisites": "No cycles or missing references, prerequisites earlier, and manual verification of genuinely necessary skills.",
    "relevance": "Per-unit tool matches the chosen approach; no unrelated mandatory features or generic tutorials substituting for project skills. A tool field is not video-coverage evidence.",
    "technical_accuracy": "No unresolved high/medium behavioral contradiction in manual review. Hardware review is static, not execution validation.",
    "background": "Honor exact requested stage and actual stated experience; do not equate advanced with knowledge of an unfamiliar library.",
    "latency": {"client_goal_seconds": 60, "client_failure_threshold_seconds": 90, "p95_limit_seconds": 90, "observation_deadline_seconds": 150},
    "bounds": {"max_analysis_api_submissions": 4, "max_program_provider_attempts_per_analysis": 2, "external_search_submissions": 0},
    "pass_policy": "All four complete with manual rubric passed and no known high/medium issue. Report latency goal misses and failures separately; never convert a keyword hit into a semantic pass.",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def dump(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def local_url(value: str) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
        raise ValueError("The acceptance runner only allows a loopback API origin.")
    return value.rstrip("/")


def input_for(case: dict) -> dict:
    return ProjectInput.model_validate(case["input"]).model_dump()


def observations(case: dict, view: dict, elapsed: float) -> dict:
    version = view.get("version") or {}
    body = version.get("analysis")
    if not body:
        return {"analysis_available": False}
    project = ProjectInput.model_validate(version["input"])
    document = AnalysisDocument.model_validate(body)
    explained = "\n".join(" ".join([p.name, p.description, p.project_task or "", p.learning_goal,
                                    " ".join(p.concepts), p.practice_check or ""]) for p in document.knowledge_points)
    count = len(document.knowledge_points)
    return {
        "analysis_available": True,
        "input_preserved": version["input"] == input_for(case),
        "schema_valid": True,
        "quality_guard_issues": learning_quality_issues(project, document),
        "function_count": len(document.functions), "unit_count": count,
        "soft_unit_range_4_to_8": 4 <= count <= 8,
        "technology_targets": [{"id": p.id, "name": p.name, "technology": p.technology} for p in document.knowledge_points],
        "coverage_observations": [{"criterion": label, "keyword_observed": bool(re.search(pattern, explained, re.I))}
                                  for label, pattern in case["coverage"]],
        "latency_goal_met": elapsed <= 60,
        "latency_hard_limit_met": elapsed <= 90,
        "manual_review_required": True,
        "manual_semantic_pass": None,
        "analysis_sha256": hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
    }


def new_analysis_events(path: Path | None, start_line: int) -> list[dict]:
    if not path or not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines()[start_line:]:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("task") in {"project_analysis", "project_analysis_review"}:
            events.append(event)
    return events


def event_count(path: Path | None) -> int:
    return len(path.read_text(encoding="utf-8").splitlines()) if path and path.exists() else 0


def summarize(run: dict) -> dict:
    completed = [r for r in run["records"] if r.get("status") == "analyzed"]
    latencies = sorted(r["client_analysis_elapsed_seconds"] for r in completed)
    events = [e for r in run["records"] for e in r.get("model_events", [])]
    started = {e.get("call_id") for e in events if e.get("event_type") == "model_call_started"}
    finished = [e for e in events if e.get("event_type") == "model_call_finished"]
    completed_call_ids = {e.get("call_id") for e in finished}
    counts_complete = bool(run.get("model_events_source")) and bool(started) and None not in started \
        and started == completed_call_ids and len(completed_call_ids) == len(finished)
    return {
        "api_analysis_submissions": sum(bool(r.get("analysis_submission_attempted")) for r in run["records"]),
        "completed_analyses": len(completed),
        "failed_analyses": sum(r.get("status") == "analysis_failed" for r in run["records"]),
        "uncertain_or_pending": sum(r.get("status") not in {"analyzed", "analysis_failed"} for r in run["records"]),
        "client_median_seconds": statistics.median(latencies) if latencies else None,
        "client_p95_nearest_rank_seconds": latencies[math.ceil(len(latencies) * .95) - 1] if latencies else None,
        "latency_goal_misses": [r["case_id"] for r in completed if r["client_analysis_elapsed_seconds"] > 60],
        "latency_hard_limit_misses": [r["case_id"] for r in completed if r["client_analysis_elapsed_seconds"] > 90],
        "provider_finished_events": len(finished),
        "provider_completion_tokens": sum((e.get("usage") or {}).get("completion_tokens", 0) for e in finished),
        "provider_total_tokens": sum((e.get("usage") or {}).get("total_tokens", 0) for e in finished),
        "provider_counts_are_complete": counts_complete,
        "provider_tasks_included": ["project_analysis", "project_analysis_review"],
        "provider_usage_is_complete": counts_complete and bool(finished)
            and all(isinstance(e.get("usage"), dict)
                    and all(type(e["usage"].get(key)) is int and e["usage"][key] >= 0
                            for key in ("completion_tokens", "total_tokens")) for e in finished),
        "manual_review_required": True,
        "semantic_acceptance_pass": None,
        "search_api_submissions": 0,
    }


def observe(client: httpx.Client, run: dict, record: dict, case: dict, output: Path, deadline: float) -> None:
    started = time.monotonic()
    while time.monotonic() - started < deadline:
        try:
            response = client.get(f"/api/projects/{record['project_id']}")
            response.raise_for_status()
            view = response.json()
        except (httpx.HTTPError, ValueError):
            record["last_poll_error"] = "local_api_read_failed"
            dump(output / "run.json", run)
            time.sleep(1)
            continue
        version = view.get("version") or {}
        status = version.get("status")
        if status in {"analyzed", "analysis_failed"}:
            elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(record["analysis_submitted_at"])).total_seconds()
            record.update(status=status, version=version.get("version"), client_analysis_elapsed_seconds=round(elapsed, 6), completed_at=now())
            record["persisted_view"] = view
            record["observations"] = observations(case, view, elapsed)
            record["error"] = version.get("error")
            return
        time.sleep(1)
    record["status"] = "observation_deadline_pending"
    record["note"] = "No additional analysis was submitted. Inspect the known project before any retry."


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--observe-only", action="store_true")
    parser.add_argument("--base-url")
    parser.add_argument("--expected-prompt", default="project-analysis-v2.4-explicit-technology")
    parser.add_argument("--runtime-pid", type=int)
    parser.add_argument("--model-events", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "evidence" / "phase2-learning")
    parser.add_argument("--max-analyses", type=int, default=4, choices=range(1, 5))
    parser.add_argument("--deadline", type=float, default=150)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT) or not 1 <= args.deadline <= 180:
        parser.error("Output must stay inside the workspace and the observation deadline must be 1-180 seconds.")
    dump(output / "plan.json", {"classification": "synthetic_non_sensitive_inputs", "standards": STANDARDS,
         "cases": [{**c, "input": input_for(c)} for c in CASES]})
    if not args.live and not args.observe_only:
        print(json.dumps({"mode": "plan_only", "cases": len(CASES), "provider_requests": 0, "plan": str(output / "plan.json")}))
        return 0
    if not args.base_url:
        parser.error("An explicitly confirmed local service --base-url is required.")
    base = local_url(args.base_url)
    path = output / "run.json"
    if args.live and path.exists():
        parser.error("run.json already exists. Do not repeat uncertain submissions; use --observe-only or review the existing evidence.")
    run = json.loads(path.read_text(encoding="utf-8")) if args.observe_only else {
        "mode": "live_local_api", "started_at": now(), "base_url": base,
        "runtime_pid_parent_confirmed": args.runtime_pid,
        "model_events_source": str(args.model_events) if args.model_events else None,
        "model_event_attribution": "Exclusive sequential project_analysis time windows, confirmed by the parent task. No other branch submits model analyses during this run.",
        "max_analysis_submissions": args.max_analyses, "records": [],
    }
    with httpx.Client(base_url=base, timeout=10, follow_redirects=False, trust_env=False) as client:
        capability = client.get("/api/capabilities")
        capability.raise_for_status()
        analysis_capability = capability.json()["project_analysis"]
        if analysis_capability.get("prompt_version") != args.expected_prompt or analysis_capability.get("status") != "configured":
            raise RuntimeError("The local analysis service does not match the confirmed prompt/configuration.")
        run["analysis_capability"] = analysis_capability
        dump(path, run)
        if args.observe_only:
            for record in run["records"]:
                if record.get("project_id") and record.get("status") not in {"analyzed", "analysis_failed"}:
                    case = next(c for c in CASES if c["id"] == record["case_id"])
                    observe(client, run, record, case, output, args.deadline)
                    dump(output / f"{case['id']}.json", record)
        else:
            for case in CASES[:args.max_analyses]:
                record = {"case_id": case["id"], "input": input_for(case), "status": "project_creation_pending", "created_at": now()}
                run["records"].append(record)
                dump(path, run)
                try:
                    created = client.post("/api/projects", json=record["input"])
                    created.raise_for_status()
                    view = created.json()
                    record.update(project_id=view["project_id"], created_project_view=view, status="created")
                except (httpx.HTTPError, ValueError, KeyError):
                    record.update(status="project_creation_uncertain", note="Creation outcome may be uncertain; do not retry automatically.")
                    dump(path, run)
                    break
                dump(path, run)
                offset = event_count(args.model_events)
                record.update(status="analysis_submission_pending", analysis_submission_attempted=True,
                              analysis_submitted_at=now(), model_event_start_line=offset)
                dump(path, run)
                try:
                    submitted = client.post(f"/api/projects/{record['project_id']}/analyze", json={"expected_version": view["current_version"]})
                    record["analysis_http_status"] = submitted.status_code
                    submitted.raise_for_status()
                    record["analysis_submission_response"] = submitted.json()
                except (httpx.HTTPError, ValueError):
                    record["submission_outcome_uncertain"] = True
                # Read the known project even after an uncertain POST, never POST again.
                observe(client, run, record, case, output, args.deadline)
                record["model_events"] = new_analysis_events(args.model_events, offset)
                dump(output / f"{case['id']}.json", record)
                run["summary"] = summarize(run)
                dump(path, run)
                print(json.dumps({"case": case["id"], "project_id": record["project_id"], "status": record["status"],
                                  "version": record.get("version"), "elapsed_seconds": record.get("client_analysis_elapsed_seconds")}), flush=True)
                if record["status"] not in {"analyzed", "analysis_failed"}:
                    break
    run["finished_at"] = now()
    run["summary"] = summarize(run)
    dump(path, run)
    events = [e for r in run["records"] for e in r.get("model_events", [])]
    (output / "model-events.jsonl").write_text("".join(json.dumps(e,ensure_ascii=False) + "\n" for e in events),encoding="utf-8")
    print(json.dumps(run["summary"],ensure_ascii=False))
    return 0 if run["summary"]["completed_analyses"] == args.max_analyses else 1


if __name__ == "__main__":
    raise SystemExit(main())
