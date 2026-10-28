"""Bounded, schema-validated AI analysis; no fabricated analysis fallback."""
from __future__ import annotations

import asyncio
import ast
import hashlib
import json
import re
from copy import deepcopy
from dataclasses import replace
from typing import Annotated, Callable, Literal, get_args

import httpx
from pydantic import Field, ValidationError
from pydantic_core import ErrorType

from .config import Settings
from .llm import LLMCompletionTruncated, LLMResponseTooLarge, complete_json, LLM_OBSERVER
from .project_models import (
    AnalysisDocument, AnalysisTextModel,
    MAX_PROJECT_KNOWLEDGE_POINTS, ProjectInput, normalized_name,
)
from .professional_concepts import concept_semantic_issues, textbook_concept_issues
from .analysis_name_repair import (NAME_REPAIR_PROMPT, NameRepairNeedsContent,
                                   apply_name_repairs, name_repair_schema)
from .models import now

ANALYSIS_PROMPT_VERSION = "project-analysis-v9-textbook-single-generation"
# A single generation inside the shared queue/processing wall-clock budget.
ANALYSIS_TIMEOUT_SECONDS = 60
ANALYSIS_TOTAL_TIMEOUT_SECONDS = 60
ANALYSIS_MAX_ATTEMPTS = 1
ANALYSIS_MAX_MODEL_CALLS = 1
ANALYSIS_MIN_REPAIR_SECONDS = 5
# Retained for reading/testing historical review contracts, never scheduled.
SEMANTIC_REVIEW_MAX_OUTPUT_TOKENS = 16000

from .analysis_compact import COMPACT_SYSTEM_PROMPT, COMPACT_REPAIR_PROMPT
SYSTEM_PROMPT = GENERATION_PROMPT = COMPACT_SYSTEM_PROMPT
NORMALIZATION_PROMPT = COMPACT_REPAIR_PROMPT


def _title_key(value: str) -> str:
    return re.sub(r"[\s\W_]+", "", normalized_name(value))


def _single_statement_title(value: str) -> bool:
    """Recognize an entire assignment/call, never execute it or scan prose."""
    try:
        statements = ast.parse(value.strip(), mode="exec").body
    except (SyntaxError, ValueError):
        return False
    if len(statements) != 1:
        return False
    statement = statements[0]
    return isinstance(statement, (ast.Assign, ast.AugAssign)) or (
        isinstance(statement, ast.AnnAssign) and statement.value is not None
    ) or (
        isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call)
    )


def _unquoted_numeric_clauses(text: str) -> list[str]:
    """Only affirmative prose, never quoted examples, code or warnings."""
    text = re.sub(r'```[\s\S]*?```|`[^`\n]*`|“[^”]*”|「[^」]*」|『[^』]*』|"[^"\n]*"', " ", text)
    return re.split(r"[。！？!?；;，,\n]", normalized_name(text))


def _asserts_wrong_uno_resolution(text: str, *, require_local_uno: bool = False) -> bool:
    pwm = r"(?:pwm(?:\s*(?:引脚|输出|分辨率))?|analogwrite(?:\([^)]*\))?)"
    adc = r"(?:adc|analogread(?:\([^)]*\))?|模数转换|模拟输入)"
    pair = rf"(?:{pwm}.{{0,18}}(?:与|和|及|and|&).{{0,12}}{adc}|{adc}.{{0,18}}(?:与|和|及|and|&).{{0,12}}{pwm}).{{0,12}}(?:均|都|皆|both|each).{{0,12}}(?:8|10)\s*(?:位|[- ]?bit)"
    single_pwm = rf"{pwm}\s*(?:的\s*(?:默认\s*)?分辨率)?\s*(?:为|是|采用|均为|都为|is|uses?|has)\s*(?:板载\s*|默认\s*|default\s*)?10\s*(?:位|[- ]?bit)"
    single_adc = rf"{adc}\s*(?:的\s*(?:默认\s*)?分辨率)?\s*(?:为|是|采用|is|uses?|has)\s*(?:板载\s*|默认\s*|default\s*)?8\s*(?:位|[- ]?bit)"
    for clause in _unquoted_numeric_clauses(text):
        if require_local_uno and not re.search(r"(?<![a-z0-9_])uno(?![a-z0-9_])", clause):
            continue
        for match in re.finditer(rf"{pair}|{single_pwm}|{single_adc}", clause, re.I):
            left, right = clause[:match.start()], clause[match.end():]
            # A contrast ends a preceding warning's scope. Negating another
            # board must not excuse an affirmative resolution claim after it.
            left = re.split(r"但是|但|不过|然而|\bbut\b|\bhowever\b", left, flags=re.I)[-1]
            owners = list(re.finditer(rf"{pwm}|{adc}", match.group(), re.I))
            predicate = match.group()[owners[-1].end():] if owners else ""
            # The paired expression includes its predicate. Inspect negation
            # after its final API owner, never an unrelated earlier action.
            if re.search(r"并非|并不|不是|不应|不能|不可|不(?:都|均|皆|为|相同)|非(?:都|均|皆)|\bnot\b|\bnever\b", predicate, re.I):
                continue
            if re.search(r"(?:不(?:是|应|能|要)?|并非|不能说|不可认为|勿称|错误(?:说法|示例)?|误称|误写|反例|假设|如果|若|否定|not|never|incorrect|wrong|quoted)\s*.{0,25}$", left, re.I):
                continue
            if re.search(r"^.{0,12}(?:错误|不正确|不成立|并非事实|is\s+(?:false|wrong|incorrect)|not\s+true)", right, re.I):
                continue
            return True
    return False


def _asserts_clock_frame_duration_cap(text: str) -> bool:
    """Catch a finite cap-direction error, not general timing prose."""
    text = re.sub(r'```[\s\S]*?```|`[^`\n]*`|“[^”]*”|「[^」]*」|『[^』]*』|"[^"\n]*"', " ", text)
    duration = r"(?:每(?:一)?帧|单帧|帧间|帧)(?:的)?(?:执行)?(?:耗时|时长|时间|间隔)"
    upper = r"(?:上限|最长|最大|不超过|不高于|小于等于|至多)"
    en_duration = r"(?:frame[ -]?(?:duration|time)|duration\s+(?:of|for)\s+(?:each|a)\s+frame|each\s+frame)"
    en_upper = r"(?:maximum|upper\s+(?:bound|limit)|at\s+most|no\s+more\s+than)"
    claim_pattern = (
        rf"(?:限制|控制|约束|保证|确保|设定|设置)[^，,但而]{{0,18}}(?:{duration}.{{0,12}}{upper}|{upper}.{{0,8}}{duration})|"
        rf"(?:cap|bound|limit|guarantee|ensure|enforce)(?:s|d|ing)?[^,]{{0,35}}(?:{en_duration}.{{0,30}}{en_upper}|{en_upper}.{{0,20}}{en_duration})"
    )
    for clause in re.split(r"[。！？!?;；\n]", text):
        if not re.search(r"clock|tick|时钟(?:对象)?|延时|休眠", clause, re.I):
            continue
        for claim in re.finditer(claim_pattern, clause, re.I):
            left, right = clause[:claim.start()], clause[claim.end():]
            if re.search(r"不能|无法|不应|\b(?:not|never|cannot|doesn't)\b", claim.group(), re.I):
                continue
            # A contrast ends an earlier warning; only local negation counts.
            left = re.split(r"但是|但|不过|然而|\bbut\b|\bhowever\b", left, flags=re.I)[-1]
            if re.search(r"(?:不|未|不能|无法|并非|不会|不应|错误(?:地)?|误称|not|never|cannot|doesn't).{0,10}$", left, re.I):
                continue
            if re.search(r"^.{0,12}(?:不正确|不成立|错误|is\s+(?:false|wrong|incorrect)|not\s+true)", right, re.I):
                continue
            return True
    return False


def professional_contract_issues(project: ProjectInput, document: AnalysisDocument) -> list[dict]:
    """Narrow generation-only checks; do not validate/edit saved analyses."""
    source = normalized_name(" ".join([project.name, project.requirements, project.project_context, project.technical_version]))
    issues = concept_semantic_issues([point.model_dump() for point in document.knowledge_points])
    # An observed live misconception: a clock cap is not time-based movement.
    # This finite check does not certify every formula or unknown method.
    # The model may choose pygame for an input that only requested Python.
    # Include explicit tool identifiers and an affirmative chosen route, not
    # an arbitrary incidental mention in another concept's explanation.
    pygame_route = bool(re.search(r"pygame", source, re.I)) or any(
        re.fullmatch(r"pygame(?:\s*\d+(?:\.\d+)*)?", point.technology.strip(), re.I)
        for point in document.knowledge_points)
    if not pygame_route:
        for clause in _unquoted_numeric_clauses(document.technical_plan):
            chosen = re.search(r"(?:使用|采用|选用|基于|use|using|choose|built?\s+(?:on|with))\s*.{0,18}\bpygame\b", clause, re.I)
            if chosen and not re.search(r"(?:不|未|不能|避免|not|never|avoid).{0,8}$", clause[:chosen.start()], re.I):
                pygame_route = True
                break
    if pygame_route:
        timing_fields = [(["technical_plan"], None, document.technical_plan)]
        timing_fields += [(["knowledge_points", i, key], point.id, getattr(point, key))
            for i, point in enumerate(document.knowledge_points) for key in ("description", "learning_goal")]
        for location, point_id, text in timing_fields:
            if _asserts_clock_frame_duration_cap(text):
                issues.append({"code": "frame_duration_upper_bound", "location": location,
                    **({"point_id": point_id} if point_id is not None else {}),
                    "message": "Clock.tick delays fast frames to limit the upper frame rate, targeting a minimum frame duration. It does not impose a maximum frame duration or prevent slow computation. Describe frame-rate limiting or elapsed-time measurement accurately, without claiming an upper duration guarantee."})
        spawn_scope = re.search(r"随机.{0,12}(?:位置|坐标).{0,12}(?:下落|出现)|(?:顶部|上方).{0,12}随机", source)
        explicit_frame_random = re.search(r"每(?:一)?帧.{0,24}随机.{0,24}(?:水平|横|坐标)|(?:each|every) frame.{0,40}random", source, re.I)
        if spawn_scope and not explicit_frame_random:
            lifecycle_fields = [(["technical_plan"], document.technical_plan)]
            lifecycle_fields += [(["knowledge_points", i, key], getattr(point, key))
                for i, point in enumerate(document.knowledge_points) for key in ("description", "learning_goal")]
            for location, text in lifecycle_fields:
                for clause in re.split(r"[。！？!?;；\n]", text):
                    frame = re.search(r"每(?:一)?帧|每次(?:循环|更新)|(?:each|every) frame", clause, re.I)
                    random = re.search(r"随机|random", clause, re.I)
                    if not frame or not random or frame.start() >= random.start() or not re.search(r"水平|横(?:向|坐标)|(?<![A-Za-z0-9_])x(?![A-Za-z0-9_])", clause[random.start():], re.I):
                        continue
                    if re.search(r"(?:不|不能|并非|不是|避免|not|never).{0,8}$", clause[:frame.start()], re.I):
                        continue
                    if re.search(r"(?:不|不能|并非|不是|避免|not|never).{0,8}$", clause[frame.end():random.start()], re.I):
                        continue
                    if re.search(r"仅在|只在|只有.{0,16}时|(?:生成|出生|重生|重新出现)(?:之)?(?:时|后)|(?:接住|漏接|重生|重新出现).{0,10}(?:后|时)|when.{0,20}(?:spawn|respawn)|on (?:spawn|respawn)", clause, re.I):
                        continue
                    issues.append({"code": "respawn_randomization_per_frame", "location": location,
                        "message": "The requested object spawns at a random horizontal coordinate and then falls. Randomize x only on spawn/respawn; update the existing y per frame. Do not replace vertical falling with per-frame horizontal jitter."})
        for location, point_id, text in timing_fields:
            method_context = text
            if point_id is not None:
                point = document.knowledge_points[location[1]]
                method_context = point.description + " " + point.learning_goal
            # Bind mechanism and method within this explanation, allowing
            # adjacent sentences. Do not borrow another point's elapsed time.
            # A clock cap can be described without its API name: "limit the
            # number of loop iterations per second" is the same mechanism.
            if not re.search(r"clock|tick|限帧|限制帧率|帧率(?:控制|限制|上限)|"
                             r"时钟.{0,28}(?:限制|控制).{0,24}(?:帧|每秒|循环)|"
                             r"(?:限制|控制).{0,14}每秒.{0,12}(?:次数|帧数|循环)|"
                             r"frame[ -]?rate[ -]?(?:cap|limit)|"
                             r"(?:cap(?:s|ping)?|limit(?:s|ing)?)\s+(?:(?:the|render(?:ing)?|maximum)\s+)?frame[ -]?rate|"
                             r"(?:cap|limit).{0,30}(?:loop|iterations?).{0,20}per\s+second", method_context, re.I):
                continue
            delta = re.search(r"delta[ -]?time|elapsed[ -]?time|(?<![A-Za-z0-9_])dt(?![A-Za-z0-9_])|时间差|时间增量|经过(?:的)?时间|帧间隔时间|实际(?:帧间)?(?:时间|间隔)", method_context, re.I)
            # A fixed number of pixels per rendered frame is not a decoupled
            # fixed simulation timestep. Require an actual time accumulator.
            fixed_simulation = (re.search(r"固定(?:仿真|模拟|时间)?步长|fixed[ -]?(?:(?:simulation|time)[ -]?)?step", method_context, re.I)
                                and re.search(r"(?:时间)?累(?:积|加|计)器|累(?:积|加|计)(?:实际)?(?:经过)?时间|(?:time[ -]?)?accumulator", method_context, re.I))
            applied = re.search(r"(?:位移|位置|移动|运动).{0,28}(?:乘|\*|×|按|根据|计算|更新|积分)|"
                                r"(?:乘|\*|×|按|根据|计算|更新|积分).{0,28}(?:位移|位置|移动|运动)|"
                                r"(?:position|movement|motion).{0,30}(?:multiply|\*|update|using|integrat)|"
                                r"(?:multiply|\*|apply|using|update|integrat).{0,30}(?:position|movement|motion)", method_context, re.I)
            for clause in re.split(r"[。！？!?;；\n]", text):
                claim = re.search(r"(?:使|让|确保|保证).{0,32}(?:移动|运动|速度).{0,40}(?:解耦|无关|独立|不受.{0,18}影响|(?:基本|近似)?一致|相同|恒定)|"
                                  r"(?:make|ensure|guarantee).{0,32}(?:movement|speed|motion).{0,45}(?:independent|decoupl|unaffected|consistent|identical|the\s+same)|"
                                  r"(?:移动|运动|动画|速度).{0,40}(?:在|跨|across).{0,24}(?:不同|different).{0,24}(?:基本一致|一致|相同|不变|恒定|consistent|the\s+same)", clause, re.I)
                if not claim:
                    continue
                left = re.split(r"但是|但|不过|然而|\bbut\b|\bhowever\b", clause[:claim.start()], flags=re.I)[-1]
                if re.search(r"(?:不|未|不能|无法|并非|不会|not|never|cannot|doesn't).{0,10}$", left, re.I):
                    continue
                if re.search(r"^.{0,12}(?:不正确|不成立|错误|is\s+(?:false|wrong|incorrect)|not\s+true)", clause[claim.end():], re.I):
                    continue
                if not re.search(r"帧率|刷新频率|帧频|硬件|机器|设备|计算机|电脑|处理器|CPU|\bfps\b|frame[ -]?rate|refresh rate|\b(?:hardware|machines?|devices?|computers?|processors?|cpu)\b", clause[claim.start():claim.start() + 180], re.I):
                    continue
                if not ((delta or fixed_simulation) and applied):
                    issues.append({"code": "frame_rate_independence", "location": location,
                        **({"point_id": point_id} if point_id is not None else {}),
                        "message": "Clock.tick or limiting loop iterations per second only caps the upper frame rate. It does not make motion independent of achieved frame rate or keep movement speed consistent across different machines by itself. Apply elapsed/delta time to position updates or use a time-accumulated fixed simulation timestep; a fixed distance per rendered frame is insufficient. Otherwise remove the speed-independence/consistency claim and describe only the frame-rate cap."})
    # Classic Uno defaults only. Do not generalize them to R4/new boards or a
    # user-declared custom timer/resolution. Model prose cannot invent an override.
    primary = normalized_name(" ".join([project.name, project.requirements, project.technical_version]))
    classic_uno = bool(re.search(r"(?<![a-z0-9_])uno(?![a-z0-9_])", primary)) and not re.search(
        r"(?<![a-z0-9_])uno\s*[- ]?(?:r\s*[4-9]|q(?![a-z0-9_])|wifi\s*rev\s*2)|analog(?:read|write)resolution\s*\(|"
        r"(?:自定义|定制|重新配置|custom|reconfigur).{0,35}(?:pwm|timer|定时器|分辨率)|"
        r"(?:pwm|timer|定时器|分辨率).{0,35}(?:自定义|定制|重新配置|custom|reconfigur)", source, re.I)
    mixed_board_context = False
    for clause in _unquoted_numeric_clauses(source):
        for owner in re.finditer(r"(?<![a-z0-9_])esp32(?![a-z0-9_])", clause):
            if not re.search(r"(?:不(?:采用|使用|要|是)|不能.{0,8}(?:为|用)|而非|避免).{0,12}$", clause[:owner.start()]):
                mixed_board_context = True
    fields = [("scope", document.scope), ("technical_plan", document.technical_plan)]
    fields += [(["assumptions", i], value) for i, value in enumerate(document.assumptions)]
    fields += [(["functions", i, "acceptance_criteria"], value.acceptance_criteria) for i, value in enumerate(document.functions)]
    fields += [(["knowledge_points", i, field], getattr(point, field))
               for i, point in enumerate(document.knowledge_points)
               for field in ("name", "description", "why_needed", "learning_goal")]
    if classic_uno:
        for location, value in fields:
            if _asserts_wrong_uno_resolution(value, require_local_uno=mixed_board_context):
                issues.append({"code": "numeric_api_contract", "location": [location] if isinstance(location, str) else location,
                    "message": "Keep the classic Uno default ADC input (10-bit, 0-1023) separate from analogWrite PWM output (8-bit, 0-255). Preserve the project's original ranges; remove a contradictory shared-width claim instead of changing the requirements."})
    browser_project = bool(re.search(r"浏览器|网页|javascript|\b(?:browser|web|dom|html)\b", source, re.I))
    web_name = r"浏览器|网页|javascript|ecmascript|keyboardevent|(?<![a-z0-9_])(?:js|dom|web|html|browser|react|vue|svelte|angular)(?![a-z0-9_])|document\."
    if browser_project:
        for i, point in enumerate(document.knowledge_points):
            if re.search(web_name, normalized_name(point.name + " " + point.technology), re.I):
                continue
            own_keyboard_namespace = False
            for clause in _unquoted_numeric_clauses(" ".join([point.description, point.learning_goal])):
                match = re.search(r"(?<![a-z0-9_])keyboardevent(?![a-z0-9_])|(?<![a-z0-9_])document\s*(?:的|\.)\s*(?:keydown|keyup|onkeydown|onkeyup)(?![a-z0-9_])|"
                    r"(?<![a-z0-9_])document\s*\.\s*addeventlistener(?![a-z0-9_]).{0,100}(?:keydown|keyup|键盘|空格)|"
                    r"(?:keydown|keyup|键盘|空格).{0,100}(?<![a-z0-9_])document\s*\.\s*addeventlistener(?![a-z0-9_])", clause, re.I)
                if match and not re.search(r"(?:不(?:使用|采用|应|要)|而非|反例|错误示例|假设|do\s+not|instead\s+of).{0,30}$", clause[:match.start()], re.I):
                    own_keyboard_namespace = True
                    break
            # Do not infer a browser namespace from event.key/event.code alone.
            if own_keyboard_namespace:
                issues.append({"code": "ambiguous_tool_namespace", "point_id": point.id, "location": ["knowledge_points", i, "name"],
                    "message": "This point explicitly teaches browser DOM/KeyboardEvent keyboard handling. Make the generated query name identify that browser ecosystem (for example DOM or JavaScript), retaining the original topic. General methods without ecosystem-specific APIs need no prefix."})
    return issues[:20]


def _raw_edge_as_debounce(text: str) -> bool:
    """Reject an observed concrete misconception, allowing real stable-input methods."""
    for sentence in re.split(r"[。；;\n]", text):
        if not re.search(r"去抖|消抖|过滤抖动|消除抖动|滤除抖动|debounc", sentence, re.I):
            continue
        if re.search(r"(?:不能|不应|不可|不足以|不是|不等于|并非).{0,18}(?:独立|单独)?(?:去抖|消抖)|"
                     r"(?:状态比较|电平比较|边沿检测|边沿触发).{0,12}(?:不能|不足以|不等于|不是)", sentence):
            continue
        raw = re.search(r"状态比较|(?:当前|前次|前后|原始).{0,8}电平.{0,8}比较|比较.{0,10}(?:当前|前次|前后).{0,8}电平|边沿检测|边沿触发|状态变化立即触发", sentence)
        if not raw:
            continue
        # Actual stable-input conditions or an explicitly separate debounce
        # circuit/library make subsequent edge detection entirely valid.
        if re.search(r"稳定.{0,16}(?:毫秒|ms|时间窗|采样|确认|后)|连续.{0,10}(?:采样|稳定)|"
                     r"(?:硬件|电路|RC|Bounce2|去抖库|消抖库).{0,20}(?:去抖|消抖|之后|以后|后再)|"
                     r"(?:去抖|消抖).{0,12}(?:后的|后再|后才|后检测)", sentence, re.I):
            continue
        if re.search(r"二选一|只需|仅需|即可|便能|就能|用.{0,18}(?:时间窗|时间戳|millis).{0,12}(?:或|或者).{0,12}(?:状态比较|边沿检测)|"
                     r"(?:时间窗|时间戳|millis).{0,12}(?:或|或者).{0,12}(?:状态比较|边沿检测)", sentence, re.I):
            return True
    return False


# Exact, deliberately small stop lists reject clear subject labels without
# claiming that a keyword heuristic can prove educational relevance. Titles
# such as 'Python lists and loops for game state' remain valid.
_BROAD_TITLES = {
    "python", "javascript", "java", "sql", "html", "css", "c++", "c#",
    "数据库", "人工智能", "编程", "前端", "后端", "数据分析", "网页开发",
    "python基础", "python入门", "python基础视频", "python基础教程", "python编程基础",
    "python基础知识", "英语基础", "englishbasics",
    "javascript基础", "javascript入门", "java基础", "html基础", "css基础",
    "pythonbasics", "pythonfundamentals", "introductiontopython", "programmingbasics",
    "webdevelopment", "dataanalysis", "databasebasics", "arduinobasics", "arduino基础",
}
_MICRO_TITLES = {
    "变量", "变量名", "变量命名", "赋值语句", "if语句", "print语句", "分号",
    "python变量", "python变量名", "python赋值语句", "pythonprint语句",
    "pythonif语句", "pythonfor语法", "for循环语法",
    "variablename", "assignmentstatement", "printstatement", "semicolon",
}
_BROAD_KEYS = {_title_key(name) for name in _BROAD_TITLES}
_MICRO_KEYS = {_title_key(name) for name in _MICRO_TITLES}
# Exact generic labels only; targeted control names remain valid. This does not
# infer whether an arbitrary phrase actually teaches a method.
_BROAD_SKILL_KEYS = _BROAD_KEYS | {_title_key(name) for name in (
    "通用控件族", "通用控件", "UI控件", "UI组件", "表单控件", "Streamlit 控件", "Streamlit widgets",
)}


def _stops_whole_game_loop(text: str) -> bool:
    """Detect a concrete restart contradiction, allowing state-update pauses.

    Keep this narrowly tied to explicit instructions to end the loop. It does
    not interpret arbitrary variable names, reject hypothetical warnings, or
    require a particular game architecture.
    """
    text = normalized_name(text)
    pattern = (r"(?:停止|终止|退出|结束|跳出|暂停)\s*(?:整个|全部|当前)?\s*"
               r"(?:游戏主循环|主游戏循环|游戏循环|主循环)|"
               r"(?:stop|exit|terminate|break out of|leave)\s+(?:the\s+)?(?:entire\s+)?(?:main\s+)?game\s+loop")
    for match in re.finditer(pattern, text):
        prefix, suffix = text[max(0, match.start() - 30):match.start()], text[match.end():]
        # Interpret only the current clause. A legitimate quit path elsewhere
        # must never excuse stopping the playing loop while awaiting restart.
        left = re.split(r"[。!?！？;；，,\n]", text[:match.start()])[-1]
        right = re.split(r"[。!?！？;；，,\n]", suffix, maxsplit=1)[0]
        # A learning goal can contrast stopping the loop with pausing updates;
        # naming the unsafe alternative does not instruct the student to do it.
        if ((re.search(r"(?:区分|比较|对比|辨别).{0,80}(?:与|和|及|、)\s*$", left)
             and re.fullmatch(r"\s*(?:的)?(?:区别|差异|不同)?\s*", right))
                or (re.search(r"(?:区分|比较|对比|辨别)\s*$", left)
                    and re.match(r"\s*(?:与|和|及|、)", right))):
            continue
        # Esc/window-close exit is an application-quit path, not game-over
        # restart. Require a local explicit trigger and no wait-for-restart.
        # The suffix after the quit trigger may contain only key/event syntax.
        # Another loop instruction or game-over condition cannot borrow Esc.
        quit_trigger = re.search(
            r"(?:按(?:下)?|点击|收到|处理|响应)\s*(?:pygame\.)?"
            r"(?:esc(?:ape)?|quit)(?![a-z0-9_])\s*(?:键|按键|事件)?\s*(?:时|后)?\s*$|"
            r"(?:关闭窗口|窗口关闭)\s*(?:事件)?\s*(?:时|后)?\s*$|"
            r"(?:when|on|if)\s+(?:the\s+)?(?:esc(?:ape)?(?:\s+key)?"
            r"(?:\s+is\s+pressed)?|window\s+(?:closes|is\s+closed)|quit(?:\s+event)?)\s*$",
            left, re.I)
        quit_suffix = re.fullmatch(
            r"\s*(?:when|on|if)\s+(?:the\s+)?(?:esc(?:ape)?(?:\s+key)?"
            r"(?:\s+is\s+pressed)?|window\s+(?:closes|is\s+closed)|quit(?:\s+event)?)\s*\.?\s*",
            right, re.I)
        if ((quit_trigger or quit_suffix)
                and not re.search(r"(?:等待|然后|再).{0,25}(?:重开|重新开始)|"
                                  r"(?:wait|then).{0,25}restart|"
                                  r"等待\s*(?:按(?:下)?\s*)?(?:[a-z](?![a-z0-9_])(?:\s*键)?|空格(?:键)?)|"
                                  r"wait\s+(?:for\s+)?(?:the\s+)?(?:[a-z](?![a-z0-9_])\s+key|space\s+key)",
                                  right, re.I)):
            continue
        if re.search(r"(?:不(?:应|能|要|可|会|必)?|避免|禁止|而非|而不是|不是|并非|"
                     r"do not|don't|never|must not|should not|rather than|instead of|avoid)\s*(?:直接|完全)?\s*$", prefix):
            continue
        if re.search(r"(?:如果|若|一旦|假如|if)\s*$", prefix):
            continue
        if re.match(r"\s*(?:会导致|将导致|会使|会让).{0,35}(?:无法|不能|不再)", suffix):
            continue
        if re.match(r"\s*(?:与|和).{0,35}(?:区别|差异|对比)", suffix):
            continue
        # 'Stop the main loop's physics updates' does not stop event handling.
        if re.match(r"\s*(?:(?:中|内)(?:的)?|的|'s)?\s*(?:物理|下落|移动|运动|坐标|计分|游戏状态更新|状态更新|逻辑更新|physics|scoring)", suffix):
            continue
        # A separately stated outer event loop may legitimately survive an
        # inner gameplay loop; do not prescribe a single-loop architecture.
        if ("主循环" not in match.group() and "main" not in match.group()
                and re.search(r"外层.{0,20}(?:事件)?循环.{0,30}(?:继续|仍|保持).{0,30}(?:事件|按键|空格|绘制)", text)):
            continue
        return True
    return False


def learning_quality_issues(project: ProjectInput, document: AnalysisDocument, *,
                            require_expanded: bool = True) -> list[dict]:
    """Conservative generation guard; never used to invalidate saved v1 data.

    This checks observable contract failures, not semantic correctness inferred
    from arbitrary keyword overlap. Representative acceptance and human review
    must still assess whether the chosen skills implement the requirements.
    Messages are server-authored and contain no untrusted model field values.
    """
    issues = []

    def add(code: str, message: str, point_id: str = "", *, location: list | None = None,
            rule: str | None = None) -> None:
        issue = {"code": code, "point_id": point_id, "message": message}
        if location is not None:
            issue["location"] = location
        if rule is not None:
            issue["rule"] = rule
        issues.append(issue)

    if require_expanded:
        if document.learner_profile is None:
            add("missing_learner_profile", "Provide learner_profile with explicit adjustable background assumptions.")
        elif document.learner_profile.student_level != project.student_level:
            add("learner_level_mismatch", "Use the exact student_level from the project input.")
    source = normalized_name(" ".join([project.name, project.requirements, project.project_context]))
    mechanical_button = bool(re.search(r"arduino|esp32|gpio|单片机|硬件", source)
                             and re.search(r"按钮|按键|button", source))
    debounce_message = "Raw current/previous level comparison or edge detection alone does not debounce a mechanical button. Require a stable-time window, repeated stable samples or explicit hardware/library debounce, then detect one press from the debounced state."
    if mechanical_button:
        for field in ("technical_plan", "assumptions"):
            value = getattr(document, field)
            if _raw_edge_as_debounce("\n".join(value) if isinstance(value, list) else value):
                issues.append({"code": "raw_edge_is_not_debounce", "field": field, "message": debounce_message})
    restart_with_key = bool(re.search(r"游戏|pygame|\bgame\b", source)
                            and re.search(r"重开|重新开始|restart", source)
                            and re.search(r"键|空格|按|\bkey|space", source)
                            and not re.search(r"(?:不需要|无需|不做|不实现|禁止)\s*(?:重开|重新开始|restart)", source))
    restart_message = "Game over must pause playing-state physics/scoring while event handling and rendering continue for the restart key; do not stop or exit the whole game loop."
    if restart_with_key:
        for index, function in enumerate(document.functions):
            if _stops_whole_game_loop(function.acceptance_criteria):
                issues.append({"code": "unresponsive_game_restart", "function_id": function.id,
                               "location": ["functions", index, "acceptance_criteria"],
                               "rule": "whole_game_loop_stop", "message": restart_message})
        for field in ("scope", "technical_plan"):
            if _stops_whole_game_loop(getattr(document, field)):
                issues.append({"code": "unresponsive_game_restart", "field": field,
                               "location": [field], "rule": "whole_game_loop_stop",
                               "message": restart_message})
    responsive_input = bool(re.search(
        r"non[\s-]?block|without blocking|remain responsive|非阻塞|"
        r"(?:采样|定时).{0,60}(?:仍|同时).{0,40}(?:响应|输入|调整)", source))
    for point in document.knowledge_points:
        key = _title_key(point.name)
        if key in _BROAD_KEYS or re.fullmatch(
            r"(?:python|javascript|java|sql|html|css|arduino|编程|前端|后端|数据库)"
            r"(?:基础(?:语法|知识|教程|视频)?|入门(?:教程|视频)?|概述|概论|全套教程|从入门到精通)", key):
            add("broad_subject", "Replace the whole-subject title with the concrete searchable skills for one project subtask.", point.id)
        if key in _MICRO_KEYS:
            add("syntax_fragment", "Combine this isolated syntax detail with the related skills needed to complete a project subtask.", point.id)
        if point.selection != "learn":
            add("model_selected_mastery", "Propose learn for every unit; the student chooses mastery or skip later.", point.id)
        if require_expanded and (not point.project_task or not point.practice_check or not 2 <= len(point.concepts) <= 6):
            add("incomplete_learning_unit", "Provide project_task, 2-6 concrete concepts and an observable practice_check for every unit.", point.id)
        if require_expanded and not 2 <= len(point.learning_skills) <= 4:
            add("incomplete_learning_skills", "Provide 2-4 specific transferable learning_skills; keep project constants and acceptance rules in project_task/concepts/practice_check.", point.id)
        if require_expanded:
            for skill in point.learning_skills:
                if _title_key(skill) in _BROAD_SKILL_KEYS:
                    add("broad_learning_skill", "Name the specific reusable skill for this project subtask, not an entire language or subject.", point.id)
                if _title_key(skill) in _MICRO_KEYS:
                    add("fragmented_learning_skill", "Combine syntax or variable-name fragments into a coherent teachable skill.", point.id)
        if require_expanded and any(_title_key(text) == key for text in
                                    (point.project_task, point.learning_goal, point.practice_check) if text):
            add("repeated_title", "Explain the task, learning goal and check instead of copying the unit title.", point.id)
        if restart_with_key:
            point_index = document.knowledge_points.index(point)
            paths = [(["knowledge_points", point_index, field], getattr(point, field) or "")
                     for field in ("description", "why_needed", "learning_goal", "project_task", "practice_check")]
            paths.extend((["knowledge_points", point_index, field, index], text)
                         for field in ("concepts", "learning_skills")
                         for index, text in enumerate(getattr(point, field)))
            for location, text in paths:
                if _stops_whole_game_loop(text):
                    add("unresponsive_game_restart", restart_message, point.id,
                        location=location, rule="whole_game_loop_stop")
                    break
        # A specific, source-verified contradiction seen in real acceptance:
        # AVR Stream parsing waits for input by default. Only apply when the
        # student explicitly needs responsiveness, and allow explanations that
        # teach a buffered alternative or an explicit bounded timeout.
        teaching = " ".join([point.name, point.description, point.learning_goal,
                             point.project_task or "", " ".join(point.concepts), point.practice_check or ""])
        if mechanical_button and (_raw_edge_as_debounce(teaching) or any(
                _raw_edge_as_debounce(skill) for skill in point.learning_skills)):
            add("raw_edge_is_not_debounce", debounce_message, point.id)
        if require_expanded and re.search(r"[()（）,，;；\n]", point.technology):
            add("explanatory_technology", "Use only a short canonical tool name in technology. Move API lists, algorithms and explanatory parentheses into concepts.", point.id)
        # New skill labels cannot excuse a contradictory project path (or the
        # reverse). Check each separately using the same bounded-input rule.
        if responsive_input and any(
                re.search(r"Serial\.(?:parseInt|readString(?:Until)?)(?![A-Za-z0-9_])", path, re.I)
                and not re.search(r"Serial\.read(?![A-Za-z0-9_])|setTimeout|逐字|按字节|字符缓冲|缓冲区|有界超时|bounded timeout", path, re.I)
                for path in [teaching, *point.learning_skills]):
            add("blocking_input_for_responsive_task", "The project requires responsive input: teach incremental buffered Serial.read parsing or an explicit bounded-time input strategy, not default blocking Stream parsing.", point.id)
    return issues[:20]


class GeneratedConcept(AnalysisTextModel):
    """Model-facing content only; identity and selection belong to the product."""
    allow_empty_analysis_fields = frozenset({"technology"})
    name: str = Field(min_length=1, max_length=80,
        description="Established textbook concept, principle or standard method derived from the learning mechanism, named as a familiar subject noun phrase. Include necessary foundational concepts without assumed mastery. Project objects, purposes, API calls and execution steps belong in description, not this name. Keep established teaching combinations together; do not invent a title by joining concept and project use.")
    description: str = Field(min_length=1, max_length=800,
        description="Mechanism first, application second, in two compact sentences: define the named textbook concept and explain how it works, then its concrete project uses. Combine repeated uses; include essential conditions and tool/API details here when needed. Aim for 60-120 Chinese characters or similarly concise wording in other languages, expanding for essential detail without dropping concepts.")
    technology: str = Field(default="", max_length=48,
        description="One short literal tool/language identifier, or empty for a general concept. Use a single name such as HTML, CSS or JavaScript; never combine names as HTML/CSS or HTML+CSS. No instructions, URLs, prose or joined tools.")


class GeneratedConceptList(AnalysisTextModel):
    scope: str = Field(min_length=1, max_length=1600, description="One short statement of the requested scope.")
    technical_plan: str = Field(min_length=1, max_length=2000,
        description="Two short sentences naming the chosen route and essential interfaces. No code listing or repeated per-point explanations.")
    assumptions: list[Annotated[str, Field(min_length=1, max_length=500)]] = Field(max_length=8)
    knowledge_points: list[GeneratedConcept] = Field(min_length=1, max_length=MAX_PROJECT_KNOWLEDGE_POINTS)

    def to_document(self) -> AnalysisDocument:
        return AnalysisDocument.model_validate({
            "analysis_format": "concept_list_v1", "scope": self.scope,
            "technical_plan": self.technical_plan, "assumptions": self.assumptions,
            "knowledge_points": [{"id": f"k{index + 1}", **point.model_dump(), "selection": "learn"}
                                 for index, point in enumerate(self.knowledge_points)]})


def generation_schema() -> dict:
    """Strict flat generation schema, distinct from retained historical data."""
    return GeneratedConceptList.model_json_schema()


def project_analysis_settings(settings: Settings) -> Settings:
    """Explicit project-only policy; shared search calls retain global settings."""
    settings.validate_project_analysis_settings()
    if settings.project_analysis_base_url:
        settings = replace(settings, llm_provider="openai_compatible",
                           llm_base_url=settings.project_analysis_base_url,
                           llm_api_key=settings.project_analysis_api_key)
    if settings.project_analysis_model:
        settings = replace(settings, llm_model=settings.project_analysis_model)
    if settings.project_analysis_thinking_mode == "disabled":
        return replace(settings, llm_thinking_mode="disabled", llm_reasoning_effort="provider_default",
                       llm_max_output_tokens=settings.project_analysis_max_output_tokens)
    if settings.project_analysis_reasoning_effort == "inherit":
        return settings
    return replace(settings, llm_thinking_mode="enabled", llm_reasoning_effort="low",
                   llm_max_output_tokens=settings.project_analysis_max_output_tokens)


def concept_normalization_settings(settings: Settings) -> Settings:
    """Bound the optional local-error repair without escalating reasoning.

    Keep the existing export and configuration key for compatibility. Repair
    uses the same project JSON/thinking policy as generation; explicit operator
    choices remain intact. Both stages share the same total deadline.
    """
    return replace(project_analysis_settings(settings),
                   llm_max_output_tokens=settings.project_analysis_normalization_max_output_tokens)


def semantic_review_settings(settings: Settings) -> Settings:
    """A compact independent report using the same project model/policy."""
    return replace(project_analysis_settings(settings),
                   llm_max_output_tokens=SEMANTIC_REVIEW_MAX_OUTPUT_TOKENS)


class AnalysisError(Exception):
    def __init__(self, code: str, message: str, *, diagnostics: list[dict] | None = None):
        super().__init__(message)
        self.code, self.message = code, message
        self.diagnostics = diagnostics or []


class AnalysisProblem(AnalysisTextModel):
    status: Literal["needs_clarification", "too_large"]
    message: str = Field(min_length=1, max_length=800)


def _schema_field_names(schema: object) -> frozenset[str]:
    """Only server-owned schema names may appear in diagnostic field paths."""
    fields: set[str] = set()
    if isinstance(schema, dict):
        properties = schema.get("properties")
        if isinstance(properties, dict):
            fields.update(properties)
        for value in schema.values():
            fields.update(_schema_field_names(value))
    elif isinstance(schema, list):
        for value in schema:
            fields.update(_schema_field_names(value))
    return frozenset(fields)


_DIAGNOSTIC_SCHEMA_FIELDS = (_schema_field_names(AnalysisDocument.model_json_schema()) |
                             _schema_field_names(generation_schema()) |
                             _schema_field_names(name_repair_schema()))
_DIAGNOSTIC_ERROR_TYPES = frozenset(get_args(ErrorType))


def _safe_schema_error_details(exc: ValidationError) -> list[dict]:
    # Pydantic's extra-key locations can contain provider-supplied text. Retain
    # useful schema coordinates, never arbitrary keys, input values or context.
    details = []
    for error in exc.errors(include_input=False, include_context=False, include_url=False)[:20]:
        location = [part if (type(part) is int and 0 <= part <= 120_000) or
                    (isinstance(part, str) and part in _DIAGNOSTIC_SCHEMA_FIELDS)
                    else "<unknown_field>" for part in error["loc"][:8]]
        error_type = error["type"] if error["type"] in _DIAGNOSTIC_ERROR_TYPES else "validation_error"
        details.append({"location": location, "type": error_type})
    return details


_QUALITY_DIAGNOSTIC_CODES = frozenset({
    "missing_learner_profile", "learner_level_mismatch", "raw_edge_is_not_debounce",
    "unresponsive_game_restart", "broad_subject", "syntax_fragment", "model_selected_mastery",
    "incomplete_learning_unit", "incomplete_learning_skills", "broad_learning_skill",
    "fragmented_learning_skill", "repeated_title", "explanatory_technology",
    "blocking_input_for_responsive_task", "scope", "behavior", "numeric_boundary",
    "learner_stage", "prerequisite", "technical_consistency",
    "numeric_api_contract", "ambiguous_tool_namespace",
    "concept_name_too_long", "chapter_or_step_label", "task_bundle_name", "compound_concept_name",
    "textbook_operation_label", "textbook_operation_bundle", "textbook_descriptive_name", "textbook_representation_constraint_bundle", "textbook_mechanism_application_bundle",
    "project_task_name", "project_purpose_name", "project_behavior_name", "project_interaction_name",
    "invalid_topic_technology", "frame_rate_independence", "frame_duration_upper_bound", "respawn_randomization_per_frame",
    "implementation_detail_as_concept", "implementation_order_prerequisite", "duplicate_concept_name",
})


def _safe_issue_location(value: object, document: AnalysisDocument) -> list:
    """Resolve only real schema paths/known IDs; never preserve free model text."""
    if isinstance(value, str):
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*|\.\d+|\[\d+\])*", value):
            return ["<unknown_field>"]
        parts = re.findall(r"[A-Za-z_][A-Za-z0-9_]*|\d+", value)
    elif isinstance(value, list):
        parts = value
    else:
        return ["<unknown_field>"]
    if not 1 <= len(parts) <= 8:
        return ["<unknown_field>"]
    current = document.model_dump()
    result = []
    for part in parts:
        if isinstance(current, dict) and isinstance(part, str) and part in _DIAGNOSTIC_SCHEMA_FIELDS and part in current:
            result.append(part)
            current = current[part]
        elif isinstance(current, list):
            if type(part) is int or (isinstance(part, str) and part.isdecimal()):
                index = int(part)
            else:
                index = next((i for i, row in enumerate(current)
                              if isinstance(row, dict) and row.get("id") == part), -1)
            if not 0 <= index < len(current):
                return ["<unknown_field>"]
            result.append(index)
            current = current[index]
        else:
            return ["<unknown_field>"]
    return result


def _quality_repair_targets(issues: list[dict], previous_analysis: dict,
                            document: AnalysisDocument) -> list[dict]:
    """Locate rejected candidate values, solely as bounded untrusted payload data.

    Generated proposals have no point IDs. Resolve server feedback against the
    document, then use its zero-based coordinate in the actual previous draft.
    This only adds context: it never edits values or relaxes their validation.
    """
    targets = []
    schema_fields = GeneratedConcept.model_json_schema()["properties"]
    fields = {field: schema_fields[field] for field in ("name", "technology", "description")}
    points = previous_analysis.get("knowledge_points", [])
    if not isinstance(points, list):
        return targets
    for issue in issues[:MAX_PROJECT_KNOWLEDGE_POINTS]:
        code, message = issue.get("code"), issue.get("message")
        if code not in _QUALITY_DIAGNOSTIC_CODES or not isinstance(message, str) or len(message) > 2000:
            continue
        location = issue.get("location")
        point_id = issue.get("point_id")
        if location is None:
            # Only these point-only checks unambiguously name a generated field.
            field = {"broad_subject": "name", "syntax_fragment": "name",
                     "invalid_topic_technology": "technology"}.get(code)
            if field is None or not isinstance(point_id, str):
                continue
            location = ["knowledge_points", point_id, field]
        location = _safe_issue_location(location, document)
        if len(location) != 3 or location[0] != "knowledge_points" or location[2] not in fields:
            continue
        index, field = location[1], location[2]
        if type(index) is not int or not 0 <= index < len(points):
            continue
        if point_id is not None and document.knowledge_points[index].id != point_id:
            continue
        point = points[index]
        value = point.get(field) if isinstance(point, dict) else None
        if not isinstance(value, str) or len(value) > fields[field]["maxLength"]:
            continue
        targets.append({"location": location, "current_value": value,
                        "code": code, "message": message})
    return targets


def _safe_quality_issue_details(issues: list[dict], document: AnalysisDocument, *, limit: int = 20) -> list[dict]:
    """Bounded diagnostic coordinates, never rejected drafts/messages/values."""
    details = []
    for issue in issues[:min(limit, MAX_PROJECT_KNOWLEDGE_POINTS)]:
        code = issue.get("code")
        if code not in _QUALITY_DIAGNOSTIC_CODES:
            code = "quality_issue"
        location = issue.get("location")
        if location is None and issue.get("field") in _DIAGNOSTIC_SCHEMA_FIELDS:
            location = [issue["field"]]
        if location is None:
            for collection, key in (("knowledge_points", "point_id"), ("functions", "function_id")):
                rows = getattr(document, collection)
                index = next((i for i, row in enumerate(rows) if row.id == issue.get(key)), -1)
                if index >= 0:
                    location = [collection, index]
                    break
        severity = issue.get("severity", "medium")
        detail = {"code": code, "severity": severity if severity in {"high", "medium", "low"} else "medium",
                  "location": _safe_issue_location(location, document)}
        if issue.get("rule") == "whole_game_loop_stop":
            detail["rule"] = "whole_game_loop_stop"
        if issue.get("disposition") in {"blocking", "advisory"}:
            detail["disposition"] = issue["disposition"]
        if issue.get("evidence") in {"title_heuristic", "explicit_bookkeeping_label", "state_assignment_description"}:
            detail["evidence"] = issue["evidence"]
        details.append(detail)
    return details


_ADVISORY_NAME_CODES = frozenset({
    "textbook_operation_bundle", "textbook_descriptive_name",
    "textbook_representation_constraint_bundle", "textbook_mechanism_application_bundle",
})


def _partition_quality_issues(issues: list[dict]) -> tuple[list[dict], list[dict]]:
    """Only known, locally produced title heuristics are nonblocking.

    Missing/unknown evidence fails closed. Facts, explicit task syntax,
    duplicates and structural errors cannot be downgraded by severity alone.
    """
    blocking, advisory = [], []
    for issue in issues:
        is_advisory = (issue.get("code") in _ADVISORY_NAME_CODES and
                       issue.get("disposition") == "advisory" and
                       issue.get("evidence") == "title_heuristic")
        (advisory if is_advisory else blocking).append(issue)
    return blocking, advisory


def _name_repair_context(blocking: list[dict], advisory: list[dict],
                         draft: dict, document: AnalysisDocument) -> dict | None:
    """A small output contract only for complete drafts with localized names.

    Problems explicitly requiring a merge/split or a factual/content change
    retain the full repair path. The name-only model may also decline when
    the existing explanation cannot support an honest replacement name.
    """
    if not blocking or any(issue.get("code") in {
            "duplicate_concept_name", "task_bundle_name", "compound_concept_name",
            "implementation_detail_as_concept"} for issue in blocking):
        return None
    targets = _quality_repair_targets(blocking, draft, document)
    if len(targets) != len(blocking) or any(
            len(t["location"]) != 3 or t["location"][0] != "knowledge_points" or
            t["location"][2] != "name" for t in targets):
        return None
    optional = _quality_repair_targets(advisory, draft, document)
    optional = [t for t in optional if len(t["location"]) == 3 and
                t["location"][0] == "knowledge_points" and t["location"][2] == "name"]
    required = {t["location"][1] for t in targets}
    allowed = required | {t["location"][1] for t in optional}
    return {"draft": deepcopy(draft), "required": required, "allowed": allowed}


def _local_quality_issues(project: ProjectInput, result: AnalysisDocument) -> list[dict]:
    """Finite local guards; passing them is not a semantic completeness proof."""
    issues = []
    for point in result.knowledge_points:
        key = _title_key(point.name)
        if key in _BROAD_KEYS:
            issues.append({"code": "broad_subject", "point_id": point.id,
                "message": "Use a specific relevant professional topic, not an entire language, discipline or introductory course."})
        elif key in (_MICRO_KEYS - {_title_key("变量")}) or _single_statement_title(point.name):
            issues.append({"code": "syntax_fragment", "point_id": point.id,
                "message": "Use a coherent professional topic, not a variable name or isolated syntax statement."})
        if point.selection != "learn":
            issues.append({"code": "model_selected_mastery", "point_id": point.id,
                "message": "Keep generated points selected as learn; only the student chooses mastery or skipping."})
    issues.extend(result.professional_concept_issues())
    issues.extend(professional_contract_issues(project, result))
    issues.extend(textbook_concept_issues([point.model_dump() for point in result.knowledge_points]))
    return issues


class ProjectAnalyzer:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings, self.client = settings, client

    @property
    def available(self) -> bool:
        effective = project_analysis_settings(self.settings)
        return bool(effective.llm_provider == "openai_compatible" and effective.llm_base_url.strip()
                    and effective.llm_model.strip() and effective.llm_api_key.strip())

    async def analyze(self, project: ProjectInput, *, deadline: float | None = None,
                      on_rejected_attempt: Callable[[dict], None] | None = None,
                      on_analysis_attempt: Callable[[dict], None] | None = None) -> AnalysisDocument:
        """One generation, with format/safety/limit checks only.

        No naming/content judgement, advisory or automatic repair is run.
        An upstream service may shorten the deadline to include queue time.
        """
        if not self.available:
            raise AnalysisError("unconfigured", "项目分析不可用：尚未配置服务端模型。仍可直接输入知识点查找课程。")
        # Revalidation also protects callers constructing models without validation.
        project = ProjectInput.model_validate(project.model_dump())
        generation_settings = project_analysis_settings(self.settings)
        payload = {"project": project.model_dump(), "output_schema": generation_schema(),
                   "limits": {"knowledge_points": MAX_PROJECT_KNOWLEDGE_POINTS}}
        per_attempt = min(ANALYSIS_TIMEOUT_SECONDS, self.settings.project_analysis_timeout_seconds)
        loop = asyncio.get_running_loop()
        local_deadline = loop.time() + min(ANALYSIS_TOTAL_TIMEOUT_SECONDS,
                                          self.settings.project_analysis_total_timeout_seconds)
        deadline = min(local_deadline, deadline) if deadline is not None else local_deadline
        final_code = "schema"
        feedback = []
        attempt_history: list[dict] = []
        candidate = None
        source_hash = hashlib.sha256(json.dumps(project.model_dump(), ensure_ascii=False,
            sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        omitted_reason = "no_complete_json_response"
        timing: dict = {}
        acceptance_recorded = False
        attempt_started_monotonic = loop.time()
        validation_started_monotonic: float | None = None

        def finish_attempt() -> dict:
            if timing.get("finished_at") is None:
                finished = loop.time()
                timing["finished_at"] = now()
                timing["elapsed_seconds"] = round(max(0.0, finished - attempt_started_monotonic), 6)
                if validation_started_monotonic is not None:
                    timing["validation_finished_at"] = timing["finished_at"]
                    timing["validation_elapsed_seconds"] = round(max(0.0, finished - validation_started_monotonic), 6)
            return dict(timing)

        def audit_entry(attempt: int, phase: str, outcome: str, **details: object) -> dict:
            return {"attempt": attempt + 1, "phase": phase, "outcome": outcome,
                    **finish_attempt(), **details, "recorded_at": now(),
                    "prompt_version": ANALYSIS_PROMPT_VERSION, "model": call_settings.llm_model,
                    "validation_scope": "schema_safety_limits",
                    "analysis": deepcopy(candidate),
                    "source_sha256": source_hash,
                    "omitted_reason": omitted_reason if candidate is None else None}

        def record_failure(attempt: int, phase: str, category: str, **details: object) -> None:
            # Call sites supply fixed categories and sanitized structural data.
            # Never include exception strings, model text, rejected proposals or
            # user/project contents. One failed outcome per bounded attempt.
            entry = {"attempt": attempt + 1, "phase": phase, **finish_attempt(),
                     "category": category, **details}
            attempt_history.append(entry)
            if on_analysis_attempt is not None and not acceptance_recorded:
                on_analysis_attempt(audit_entry(attempt, phase, "rejected", category=category, **details))
            if on_rejected_attempt is not None and not acceptance_recorded:
                # Separate, explicitly untrusted version audit data, never an
                # accepted analysis or public error diagnostic. Persist each
                # rejection so cancellation cannot lose the diagnostic.
                on_rejected_attempt({**deepcopy(entry), "recorded_at": now(),
                    "prompt_version": ANALYSIS_PROMPT_VERSION, "model": call_settings.llm_model,
                    "analysis": deepcopy(candidate),
                    "omitted_reason": omitted_reason if candidate is None else None})

        def failure(code: str, message: str, diagnostics: list[dict] | None = None) -> AnalysisError:
            retained = list(diagnostics or [])
            if attempt_history:
                retained.append({"type": "attempt_history", "attempts": list(attempt_history)})
            return AnalysisError(code, message, diagnostics=retained)

        for attempt in range(ANALYSIS_MAX_ATTEMPTS):
            phase = "generation"
            candidate = None
            acceptance_recorded = False
            omitted_reason = "no_complete_json_response"
            attempt_started_monotonic = loop.time()
            validation_started_monotonic = None
            call_settings = generation_settings
            timing = {"started_at": now(), "finished_at": None, "elapsed_seconds": None,
                      "model_started_at": None, "model_finished_at": None, "model_elapsed_seconds": None,
                      "validation_started_at": None, "validation_finished_at": None,
                      "validation_elapsed_seconds": None,
                      "max_output_tokens": call_settings.llm_max_output_tokens,
                      "thinking_mode": call_settings.llm_thinking_mode,
                      "reasoning_effort": call_settings.llm_reasoning_effort}
            try:
                # HTTP read timeouts bound idle periods, not a slowly streaming
                # response. Also cap the full attempt with a wall-clock timeout.
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise TimeoutError
                timeout = min(per_attempt, remaining)
                async with asyncio.timeout(timeout):
                    model_started_monotonic = loop.time()
                    timing["model_started_at"] = now()
                    observation_token = LLM_OBSERVER.set(lambda value: timing.update(completion=value))
                    try:
                        body = await complete_json(call_settings, GENERATION_PROMPT, payload, self.client,
                                                   timeout_seconds=timeout, max_content_chars=120_000)
                    finally:
                        LLM_OBSERVER.reset(observation_token)
                        timing["model_finished_at"] = now()
                        timing["model_elapsed_seconds"] = round(max(0.0, loop.time() - model_started_monotonic), 6)
                validation_started_monotonic = loop.time()
                timing["validation_started_at"] = now()
                # Provider responses are untrusted too. Never persist or display a
                # configured key even if an upstream accidentally echoes headers.
                serialized_body = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
                if any(secret and (secret in serialized_body or
                                   json.dumps(secret, ensure_ascii=False)[1:-1] in serialized_body) for secret in
                       (self.settings.llm_api_key, self.settings.project_analysis_api_key,
                        generation_settings.llm_api_key, self.settings.tavily_api_key,
                        self.settings.tavily_backup_api_key, self.settings.serper_api_key)):
                    omitted_reason = "sensitive_model_output"
                    raise ValueError("Sensitive model output")
                # The transport is already bounded. Keep an independent bound
                # for audit storage, including alternate/injected transports.
                if len(serialized_body) <= 120_000:
                    candidate = body
                else:
                    omitted_reason = "audit_size_limit"
                    raise LLMResponseTooLarge()
                if isinstance(body, dict) and body.get("status") in {"needs_clarification", "too_large"}:
                    problem = AnalysisProblem.model_validate(body)
                    raise AnalysisError(problem.status, problem.message)
                if (isinstance(body, dict) and isinstance(body.get("knowledge_points"), list)
                        and len(body["knowledge_points"]) > MAX_PROJECT_KNOWLEDGE_POINTS):
                    raise AnalysisError("too_large", f"项目分析超出 {MAX_PROJECT_KNOWLEDGE_POINTS} 个知识点的安全上限，请缩小范围或分阶段分析。")
                # Deprecated model fields are schema errors, not silently kept
                # as a new graph. Historical documents use their own read path.
                proposal = GeneratedConceptList.model_validate(body)
                result = proposal.to_document()
                # Deliver the model's original content. No semantic or naming
                # validators, rewrite heuristics or advisory passes run here.
                if loop.time() >= deadline:
                    raise TimeoutError
                if on_analysis_attempt is not None:
                    # Accepted here means readable/safe structure, not content
                    # delivery. A late audit save may still time out the task;
                    # never count the same provider request twice in that case.
                    acceptance_recorded = True
                    on_analysis_attempt(audit_entry(attempt, phase, "accepted"))
                # Synchronous validation/audit hooks must not allow late results
                # to escape as successes even when no await yielded to a timer.
                if loop.time() >= deadline:
                    raise TimeoutError
                return result
            except AnalysisError as exc:
                record_failure(attempt, phase, exc.code)
                raise failure(exc.code, exc.message, exc.diagnostics) from None
            except asyncio.CancelledError:
                record_failure(attempt, phase, "cancelled")
                raise
            except (httpx.ConnectTimeout, httpx.ConnectError):
                record_failure(attempt, phase, "connection_unavailable")
                raise failure("unavailable", "无法连接模型服务，原始输入和历史版本已保留，请稍后重试。") from None
            except (httpx.TimeoutException, TimeoutError):
                record_failure(attempt, phase, "timeout")
                raise failure("timeout", "项目分析已达到时间上限，原始输入和历史版本已保留，请稍后重试。") from None
            except httpx.HTTPError:
                record_failure(attempt, phase, "http_unavailable")
                raise failure("unavailable", "模型服务暂时不可用，原始输入已保留。请检查服务端模型配置或稍后重试。") from None
            except LLMCompletionTruncated:
                record_failure(attempt, phase, "output_truncated")
                raise failure("output_truncated", "模型输出被供应商截断，原始需求已保留。请稍后重试；若反复出现，请联系管理员检查服务端生成额度和推理强度配置。") from None
            except LLMResponseTooLarge:
                record_failure(attempt, phase, "response_too_large")
                raise failure("response_too_large", "模型响应超过服务端安全上限，原始需求已保留，未保存不完整结果。请联系管理员检查模型响应额度与服务配置后重试。") from None
            except json.JSONDecodeError as exc:
                final_code = "invalid_json"
                feedback = [{"type": "invalid_json", "message": "Return exactly a valid JSON object without Markdown fences."}]
                record_failure(attempt, phase, "invalid_json", exception_type="JSONDecodeError",
                               line=exc.lineno, column=exc.colno, position=exc.pos)
            except ValidationError as exc:
                final_code = "schema"
                # Never send values or provider exceptions back as trusted repair
                # instructions, and never expose their potentially sensitive text.
                schema_feedback = [{"location": list(error["loc"]), "type": error["type"], "message": error["msg"]}
                                   for error in exc.errors(include_input=False, include_context=False, include_url=False)][:20]
                details = _safe_schema_error_details(exc)
                for item, safe in zip(schema_feedback, details):
                    item.update(safe)
                feedback = schema_feedback
                record_failure(attempt, phase, final_code, exception_type="ValidationError", errors=details)
            except (ValueError, TypeError, KeyError, IndexError):
                final_code = "schema"
                feedback = [{"type": "invalid_analysis", "message": "Follow the flat concept-list schema: scope, technical_plan, assumptions and knowledge_points; each point contains only name, description and optional technology."}]
                record_failure(attempt, phase, "invalid_analysis")
        message = "模型返回的分析格式无法读取，原始输入已保留，本次未自动重试。"
        raise failure(final_code, message, diagnostics=feedback)
