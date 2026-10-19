"""Exact, non-executing Pygame Clock flow for one independently requested skill.

Reference: https://www.pygame.org/docs/ref/time.html#pygame.time.Clock.tick
Positive framerate limits a Clock's update rate. This proves no elapsed-time,
get_ticks, pause, restart or application-state behavior.
"""
from __future__ import annotations

import ast
import math
import re


_TARGET = re.compile(r"(?:(?:pygame\s+)?clock\.tick|pygame\.time\.Clock\.tick)\s*(?:限帧|限制帧率|帧率限制)", re.I)
_FENCE = re.compile(r"(?m)^```python[ \t]*\n(?P<code>[\s\S]*?)\n```[ \t]*(?=\n|$)")
_NONTEACHING = re.compile(
    r"\b(?:todo|future\s+lesson|next\s+lesson|coming\s+soon|prerequisites?|api\s+(?:list|reference))\b|"
    r"先修|前置要求|未来课程|下节课|API\s*(?:列表|清单)|"
    r"\b(?:not|never|cannot|can['’]t|don['’]t|doesn['’]t|won['’]t)\s+(?:be\s+)?(?:cover(?:ed)?|teach|taught|use[ds]?|call(?:ed)?|limit(?:ed)?|cap(?:ped)?|control(?:led)?)\b|"
    r"\bwithout\s+(?:calling|using|limiting)\b|不(?:教|讲|演示|调用|使用|限制)|禁止", re.I)


def _dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _dotted(node.value)
        return prefix + "." + node.attr if prefix else ""
    return ""


def _positive(node):
    if not isinstance(node, ast.Constant) or type(node.value) not in {int, float}:
        return False
    try:
        return math.isfinite(node.value) and node.value > 0
    except (OverflowError, ValueError):
        return False


def _frame_loop(node, assignments):
    if isinstance(node, ast.While):
        if isinstance(node.test, ast.Constant):
            return node.test.value is True
        if isinstance(node.test, ast.Name):
            value = assignments.get(node.test.id)
            return bool(value and value[0] < node.lineno and isinstance(value[1], ast.Constant) and value[1].value is True)
    if isinstance(node, ast.For) and isinstance(node.iter, ast.Call):
        iterator = node.iter
        return (isinstance(iterator.func, ast.Name) and iterator.func.id == "range"
                and len(iterator.args) == 1 and not iterator.keywords and _positive(iterator.args[0]))
    return False


def _code_proves_limit(code):
    if len(code) > 1500 or len([line for line in code.splitlines() if line.strip()]) > 35:
        return False
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError, RecursionError):
        return False
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
        return False
    function = tree.body[0]
    if (function.decorator_list or function.args.defaults or function.args.kw_defaults
            or any(argument.arg == "pygame" for argument in [*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs])):
        return False
    descendants = list(ast.walk(function))
    if any(isinstance(node, (ast.Import, ast.ImportFrom, ast.ClassDef, ast.AsyncFunctionDef))
           or (isinstance(node, ast.FunctionDef) and node is not function) for node in descendants):
        return False
    stores = {}
    for node in descendants:
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            stores[node.id] = stores.get(node.id, 0) + 1
    if stores.get("pygame"):
        return False
    assignments, clocks = {}, {}
    for node in function.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if stores.get(name) != 1:
                continue
            assignments[name] = (node.lineno, node.value)
            if (isinstance(node.value, ast.Call) and _dotted(node.value.func) == "pygame.time.Clock"
                    and not node.value.args and not node.value.keywords):
                clocks[name] = node.lineno
    if any(isinstance(node, ast.Attribute) and isinstance(node.ctx, (ast.Store, ast.Del))
           and _dotted(node).split(".")[0] in {*clocks, "pygame"} for node in descendants):
        return False
    for loop in function.body:
        if not _frame_loop(loop, assignments):
            continue
        # A call inside an unknown if/try/function is not an unconditional
        # per-iteration update. The finite proof deliberately accepts less.
        for statement in loop.body:
            call = statement.value if isinstance(statement, ast.Expr) else None
            if (not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute)
                    or call.func.attr != "tick" or not isinstance(call.func.value, ast.Name)):
                continue
            owner = call.func.value.id
            if owner not in clocks or clocks[owner] >= loop.lineno:
                continue
            argument = (call.args[0] if len(call.args) == 1 and not call.keywords else
                        call.keywords[0].value if not call.args and len(call.keywords) == 1
                        and call.keywords[0].arg == "framerate" else None)
            if isinstance(argument, ast.Name):
                value = assignments.get(argument.id)
                argument = value[1] if value and value[0] < loop.lineno else None
            if _positive(argument):
                return True
    return False


def is_pygame_clock_frame_limit(target: str, own_body: str) -> bool:
    """Only the exact Clock.tick frame-limit target; never whole-unit support.

    Caller must already bind this complete body to the same resource's verified
    own page field. This helper neither classifies resources nor supplies IDs.
    Keep complete context and indentation; do not feed sentence-flattened text.
    """
    if (not isinstance(target, str) or not _TARGET.fullmatch(target.strip())
            or not isinstance(own_body, str) or len(own_body) > 6000 or _NONTEACHING.search(own_body)):
        return False
    return any(_code_proves_limit(match["code"]) for match in _FENCE.finditer(own_body))
