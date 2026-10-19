"""Reproducible learning-unit acceptance, with offline and bounded live modes.

Offline fixtures exercise the rubric; they are not generated analyses and are
never imported by the app. Live mode calls the configured provider, records the
actual documents and latency, and never prints credentials or provider errors.
Automated coverage checks are necessary checks, not a claim of expert review.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.config import Settings
from backend.app.project_analysis import (
    ANALYSIS_PROMPT_VERSION, AnalysisError, ProjectAnalyzer, learning_quality_issues,
)
from backend.app.project_models import AnalysisDocument, ProjectInput


@dataclass(frozen=True)
class AcceptanceCase:
    id: str
    name: str
    requirements: str
    # OR alternatives per behavior. Match against the explained units, not only
    # one mandatory technology spelling or a single chosen framework.
    coverage: tuple[tuple[str, str], ...]
    units: tuple[tuple[str, str, tuple[str, ...], str], ...]


CASES = (
    AcceptanceCase(
        "python_game", "Python 接金币小游戏",
        "使用 Python 和 pygame 在本地做接金币小游戏：左右键控制角色，金币从上方落下；碰到金币加分，漏接三次结束；支持开始和重新开始。不做联网排行榜。",
        (("角色控制和循环", r"事件|主循环|游戏循环|按键|键盘|event|game loop"),
         ("碰撞和计分", r"碰撞|collision"), ("开始结束重开", r"状态|重新开始|重开|state|restart")),
        (("pygame 窗口与游戏循环", "搭建能持续刷新和正确退出的游戏窗口", ("窗口初始化", "事件队列", "帧率与刷新"), "窗口稳定刷新，关闭按钮能退出，帧率不依赖无限快速循环。"),
         ("pygame 键盘移动与屏幕坐标", "用左右键移动角色并限制在窗口范围内", ("按键状态", "坐标与矩形", "速度和边界"), "持续按键可平滑移动，松开停止，角色不会越过屏幕边界。"),
         ("pygame 下落物体碰撞与计分", "生成下落金币并处理接到和漏接", ("物体集合更新", "矩形碰撞", "分数与漏接次数"), "接到一枚金币只加一次分，漏接会累计且物体被移除。"),
         ("pygame 开始结束与重开状态", "让开始、游戏中、结束和重新开始各自正确运行", ("游戏状态转换", "条件更新", "重置游戏数据"), "漏接三次进入结束状态，重开后分数和物体恢复初始值。")),
    ),
    AcceptanceCase(
        "data_dashboard", "销售数据分析看板",
        "用 Python、pandas 和 Streamlit 上传本地销售 CSV，检查缺失和非法金额；按日期和产品筛选，显示月销售额趋势和产品销售对比，导出当前筛选数据。不需要登录或云部署。",
        (("读入和清洗", r"缺失|清洗|校验|clean|validat"), ("筛选和聚合", r"筛选|聚合|groupby|filter|aggregat"),
         ("图表", r"图表|趋势|可视化|chart|plot"), ("导出", r"导出|下载|export|download")),
        (("pandas CSV 读取与数据校验", "将上传的销售 CSV 转为可信的分析数据", ("CSV 编码与列名", "日期和数值转换", "缺失与非法值"), "包含非法金额或缺列的文件获得明确提示，清洗后行数可核对。"),
         ("pandas 日期筛选与月度聚合", "根据日期和产品生成当前范围的销售汇总", ("布尔筛选", "日期分组", "groupby 汇总"), "切换产品和月份后，汇总金额与小样例手算一致。"),
         ("Streamlit 筛选控件与销售图表", "把筛选结果绘成趋势和产品比较图", ("筛选控件", "图表数据绑定", "空数据提示"), "控件改变时两张图同步更新，空范围显示解释而不是报错。"),
         ("Streamlit 筛选数据 CSV 导出", "让用户下载正在查看的数据", ("DataFrame 序列化", "CSV 编码", "下载按钮"), "下载文件仅含当前筛选行，中文产品名可正确读取。")),
    ),
    AcceptanceCase(
        "web_app", "本地学习待办网站 APP",
        "使用 HTML、CSS、JavaScript 做本地学习待办网页：添加、完成、删除任务，按完成状态筛选，刷新后任务仍保留；手机上可用，键盘能操作表单和按钮。不做账号或后端。",
        (("表单和交互", r"表单|事件|DOM|form|event"), ("任务状态和筛选", r"状态|筛选|state|filter"),
         ("持久化", r"localStorage|本地存储|持久|persist"), ("移动端和键盘", r"响应|键盘|可访问|语义|responsive|keyboard|accessib")),
        (("HTML 语义表单与响应式布局", "构建手机和键盘均可操作的待办界面", ("语义标签与表单标签", "焦点和键盘", "响应式 CSS"), "窄屏无横向溢出，Tab 可依次到达添加与各任务操作。"),
         ("JavaScript 表单事件与安全 DOM 更新", "从表单新增任务并渲染到列表", ("提交事件", "输入校验", "textContent 安全渲染"), "空白任务无法添加，输入尖括号文本仍按文字显示。"),
         ("JavaScript 任务状态与筛选渲染", "完成、删除任务并切换完成状态筛选", ("任务数组与标识", "状态更新", "筛选视图"), "完成和删除仅影响目标任务，切换筛选后统计与列表一致。"),
         ("JavaScript localStorage 持久化与恢复", "刷新后恢复任务并处理损坏的本地数据", ("JSON 序列化", "localStorage 读写", "恢复与错误处理"), "刷新能恢复任务，损坏数据不会使页面无法使用。")),
    ),
    AcceptanceCase(
        "arduino", "Arduino 土壤湿度提醒器",
        "用 Arduino Uno 和模拟土壤湿度传感器读取干湿变化，在串口监视器观察并校准读数，低于可调阈值时用 LED 提示；定时采样时仍可响应阈值调整。不接水泵或市电，说明低压接线和 LED 限流。",
        (("安全接线", r"接线|限流|低压|wiring|resistor"), ("采样和校准", r"采样|校准|analogRead|calibrat|sensor"),
         ("阈值和输出", r"阈值|LED|threshold"), ("非阻塞定时", r"非阻塞|millis|定时|non.block")),
        (("Arduino 低压传感器接线与 LED 限流", "连接模拟传感器和带限流电阻的提示 LED", ("Uno 电源与共地", "模拟输入引脚", "LED 极性和限流电阻"), "断电核对接线后上电，无短路，传感器与 LED 各自可单独测试。"),
         ("Arduino 模拟采样与串口校准", "观察传感器干湿读数并建立阈值参考", ("analogRead", "串口输出", "干湿端点与读数波动"), "分别记录干湿条件的读数范围，能解释阈值适用范围。"),
         ("Arduino 湿度阈值与 LED 输出控制", "低于可调阈值时提示并避免边界频繁闪烁", ("阈值比较", "数字输出", "滞回区间"), "模拟干湿变化时 LED 按规则切换，边界轻微波动不持续闪烁。"),
         ("Arduino millis 非阻塞采样与串口输入", "定时采样同时接收阈值调整命令", ("millis 时间差", "非阻塞循环", "串口命令解析"), "等待下一次采样时仍可修改阈值，输入非法值会被拒绝。")),
    ),
)


def case_input(case: AcceptanceCase, level: str) -> ProjectInput:
    context = ("没有做过完整项目，希望每次学完一个小任务就能动手验证。" if level == "beginner" else
               "已有所选语言基础和简单项目经验，希望聚焦本项目的实现和调试。")
    return ProjectInput(name=case.name, requirements=case.requirements, student_level=level, project_context=context)


def offline_reference_document(case: AcceptanceCase, level: str) -> AnalysisDocument:
    """Synthetic rubric fixture only. This is never an app fallback."""
    # Explicit fixture targets for each subtask, not inferred video coverage.
    technologies = {
        "python_game": ("pygame", "pygame", "pygame", "pygame"),
        "data_dashboard": ("pandas", "pandas", "Streamlit", "Streamlit"),
        "web_app": ("HTML/CSS", "JavaScript", "JavaScript", "JavaScript"),
        "arduino": ("Arduino", "Arduino", "Arduino", "Arduino"),
    }[case.id]
    # Explicit synthetic teaching goals, not a mechanical copy of concepts or
    # a production migration. Project constants/checks stay in the original data.
    skills = {
        "python_game": (
            ("pygame 事件处理与窗口刷新", "pygame 帧率约束与正常退出"),
            ("pygame 持续按键与矩形位移", "pygame 屏幕边界限制"),
            ("pygame 多物体更新与碰撞判定", "Python 事件计数与对象移除"),
            ("pygame 状态驱动更新与绘制", "Python 游戏数据初始化与重置"),
        ),
        "data_dashboard": (
            ("pandas CSV读取与列结构检查", "pandas 日期数值解析与有效记录筛选"),
            ("pandas 多条件布尔筛选", "pandas 日期分组与数值聚合"),
            ("Streamlit 日期输入返回值", "Streamlit 多选返回值与重运行", "Streamlit 图表数据绑定与条件展示"),
            ("pandas DataFrame序列化为CSV", "Streamlit 文件下载按钮"),
        ),
        "web_app": (
            ("HTML 语义化表单与可访问标签", "CSS 响应式布局与焦点样式"),
            ("JavaScript 表单事件与输入验证", "JavaScript 安全DOM文本渲染"),
            ("JavaScript 数组对象状态更新", "JavaScript 过滤视图与集中渲染"),
            ("JavaScript JSON序列化与解析", "JavaScript localStorage存储和错误恢复"),
        ),
        "arduino": (
            ("Arduino 低压输入电路与共地", "Arduino LED极性与限流"),
            ("Arduino 模拟输入与串口观察", "Arduino 传感器读值校准与映射"),
            ("Arduino 阈值比较与输出控制", "Arduino 状态变化与提示策略"),
            ("Arduino millis时间差定时", "Arduino 逐字串口缓冲输入"),
        ),
    }[case.id]
    functions, points = [], []
    for index, (title, task, concepts, check) in enumerate(case.units, 1):
        functions.append({"id": f"f{index}", "name": task, "original_requirement": case.requirements,
                          "acceptance_criteria": check})
        points.append({"id": f"k{index}", "name": title, "description": task,
                       "function_ids": [f"f{index}"], "why_needed": f"该任务用于完成{case.name}的对应功能。",
                       "learning_goal": (f"理解{concepts[0]}与{concepts[1]}如何协作，并完成这个子任务。" if level == "beginner" else
                                         f"能实现并调试{concepts[0]}与{concepts[1]}的边界情况。"),
                       "technology": technologies[index - 1],
                       "project_task": task, "concepts": list(concepts), "learning_skills": list(skills[index - 1]), "practice_check": check,
                       "necessity": "required", "prerequisite_ids": [f"k{index - 1}"] if index > 1 else [],
                       "learning_order": index, "selection": "learn"})
    return AnalysisDocument.model_validate({"scope": case.requirements, "technical_plan": "采用需求中明确指定的本地技术方案。",
        "assumptions": ["所有任务均限定在给出的项目范围；练习使用本地样例。"],
        "learner_profile": {"student_level": level,
            "assumed_knowledge": ["默认初学者，无完整项目经验。" if level == "beginner" else "已有语言基础和简单项目经验。"],
            "adjustment_note": "可以修改阶段和已有经验后重新分析，也可以将已掌握单元标为已掌握。"},
        "functions": functions, "knowledge_points": points})


def assess(case: AcceptanceCase, project: ProjectInput, document: AnalysisDocument) -> dict:
    issues = learning_quality_issues(project, document)
    text = "\n".join(" ".join([p.name, p.description, p.project_task or "", p.learning_goal,
                                   " ".join(p.concepts), p.practice_check or ""]) for p in document.knowledge_points)
    coverage = [{"criterion": label, "passed": bool(re.search(pattern, text, re.I))}
                for label, pattern in case.coverage]
    # This small-project range is specific to this acceptance set, not a global
    # API cap for projects with genuinely different scope.
    size_passed = 3 <= len(document.knowledge_points) <= (9 if project.student_level == "beginner" else 8)
    return {"automated_passed": not issues and all(item["passed"] for item in coverage) and size_passed,
            "quality_issues": issues, "required_behaviors": coverage, "scope_size_passed": size_passed,
            "unit_count": len(document.knowledge_points), "function_count": len(document.functions),
            "manual_review_required": True,
            "manual_review_criteria": ["Every stated requirement is actually implemented by the mapped units.",
                                       "Each unit is a coherent project subtask with stage-appropriate skills and an observable practice check.",
                                       "Prerequisites include the genuinely necessary skills, not only a structurally valid graph.",
                                       "No unrelated feature or broad subject substitutes for project skills.",
                                       "The actual techniques satisfy behavioral constraints and do not promise unsupported technical results."]}


def replay_evidence(paths: list[Path]) -> dict:
    """Reassess saved responses without repeating a possibly charged request."""
    records, original_requests = [], 0
    cases = {case.id: case for case in CASES}
    for path in paths:
        source = json.loads(path.read_text(encoding="utf-8"))
        original_requests += source.get("provider_requests", 0)
        for saved in source["records"]:
            record = {"source": str(path), "source_prompt_version": source.get("prompt_version"),
                      "case": saved["case"], "level": saved["level"], "source_status": saved["status"],
                      "source_elapsed_seconds": saved.get("elapsed_seconds"), "provider_requests": 0}
            if saved["status"] == "completed":
                project = ProjectInput.model_validate(saved["input"])
                document = AnalysisDocument.model_validate(saved["analysis"])
                record.update(status="rechecked", assessment=assess(cases[saved["case"]], project, document))
            else:
                record.update(status="source_failed", error_code=saved.get("error_code", "unknown"))
            records.append(record)
    return {"mode": "saved_evidence_replay", "prompt_version": ANALYSIS_PROMPT_VERSION,
            "network_used": False, "run_complete": True, "provider_requests": 0,
            "source_provider_requests": original_requests, "records": records,
            "automated_passed": bool(records) and all(record.get("assessment", {}).get("automated_passed", False)
                                                       for record in records)}


async def run(args: argparse.Namespace) -> dict:
    cases = [case for case in CASES if not args.case or case.id in args.case]
    pairs = [(case, level) for case in cases for level in args.levels]
    if args.live:
        pairs = pairs[:args.max_cases]
        load_dotenv(args.env_file, override=False)
    settings = Settings.from_env() if args.live else Settings()
    requests = 0
    exhausted = False

    async def count_request(_: httpx.Request) -> None:
        nonlocal requests, exhausted
        if requests >= args.max_requests:
            exhausted = True
            raise httpx.RequestError("Live acceptance request budget exhausted")
        requests += 1

    evidence = {"mode": "live_provider" if args.live else "offline_synthetic_fixtures",
                "started_at": datetime.now(timezone.utc).isoformat(), "prompt_version": ANALYSIS_PROMPT_VERSION,
                "limits": {"max_live_analyses": args.max_cases, "max_provider_requests": args.max_requests,
                           "max_output_tokens_per_request": settings.llm_max_output_tokens if args.live else None},
                "network_used": False, "run_complete": False, "records": []}
    def checkpoint() -> None:
        output = getattr(args, "output", None)
        if output is not None:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")

    async with httpx.AsyncClient(timeout=httpx.Timeout(getattr(settings, "project_analysis_timeout_seconds", 90), connect=5), follow_redirects=False,
                                 event_hooks={"request": [count_request]}) as client:
        analyzer = ProjectAnalyzer(settings, client)
        for case, level in pairs:
            started, before = time.monotonic(), requests
            project = case_input(case, level)
            record = {"case": case.id, "level": level, "input": project.model_dump()}
            try:
                document = await analyzer.analyze(project) if args.live else offline_reference_document(case, level)
                record.update(status="completed", assessment=assess(case, project, document), analysis=document.model_dump())
            except AnalysisError as exc:
                record.update(status="failed", error_code="request_budget_exhausted" if exhausted else exc.code)
            except Exception as exc:
                # Exception messages may contain upstream headers/URLs. Record
                # only the exception class, never a raw provider error body.
                record.update(status="failed", error_code=type(exc).__name__)
            record.update(elapsed_seconds=round(time.monotonic() - started, 3), provider_requests=requests - before)
            evidence["records"].append(record)
            evidence.update(provider_requests=requests, network_used=requests > 0)
            checkpoint()
            print(json.dumps({key: record[key] for key in ("case", "level", "status", "elapsed_seconds", "provider_requests")}, ensure_ascii=True), flush=True)
            if exhausted:
                break
    evidence.update(run_complete=True, provider_requests=requests, network_used=requests > 0, automated_passed=bool(evidence["records"]) and all(
        record.get("assessment", {}).get("automated_passed", False) for record in evidence["records"]))
    checkpoint()
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="Call existing configured provider; never creates credentials")
    mode.add_argument("--replay", action="append", type=Path, help="Recheck saved evidence without calling a provider; repeat for several files")
    parser.add_argument("--env-file", type=Path, default=Path(r"D:\项目制知识引导小精灵\.env"))
    parser.add_argument("--case", action="append", choices=[case.id for case in CASES])
    parser.add_argument("--levels", nargs="+", choices=["beginner", "intermediate"])
    parser.add_argument("--max-cases", type=int, choices=range(1, 7), default=4)
    parser.add_argument("--max-requests", type=int, choices=range(1, 7), default=6)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    # Default live pass covers all four project families. Explicit levels remain
    # intact and the requested maximum still bounds the number of analyses.
    args.levels = args.levels or (["beginner"] if args.live else ["beginner", "intermediate"])
    args.output = args.output or ROOT / "evidence" / ("learning_units_recheck.json" if args.replay else
                                                     "learning_units_live.json" if args.live else "learning_units_offline.json")
    evidence = replay_evidence(args.replay) if args.replay else asyncio.run(run(args))
    output = args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"evidence": str(output), "records": len(evidence["records"]),
                      "provider_requests": evidence["provider_requests"], "automated_passed": evidence["automated_passed"]}))
    return 0 if evidence["automated_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
