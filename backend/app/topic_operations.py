"""Conservative partial support for a small Chinese operation grammar.

The caller supplies already filtered, instructional observations. This module
does not classify resources, weaken evidence filters, or claim whole-topic
support. Unproved input/environment qualifications remain explicitly unknown.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .models import TopicEvidenceAssessment


_TECH = r"[A-Za-z][A-Za-z0-9_.+#-]*"
_POINT = re.compile(rf"^\s*(?P<context>{_TECH}(?:\s+{_TECH})*)\s*(?P<task>[\u4e00-\u9fff].{{1,120}}?)\s*$")
_OUTPUT = re.compile(
    r"^(?P<subject>[\u4e00-\u9fff]{2,30}?)(?P<action>保存|导出|写入)"
    r"(?:为|到|成|至)?\s*(?P<object>[A-Za-z][A-Za-z0-9._+-]{0,20}|[\u4e00-\u9fff]{2,12})$"
)
# These are grammatical noun heads, not project/topic names or API aliases.
_SUBJECT_HEAD = re.compile(r"(?:结果|数据|表格|图表|文件|数组|记录|内容)$")
_LOCAL = re.compile(r"^本地(?P<object>[\u4e00-\u9fff]{2,20})处理$")
_NEGATION = re.compile(
    r"不(?:讲|教|涵盖|涉及|支持|包括|包含)|未(?:讲解|涉及|实现)|"
    r"(?:不(?:会)?|未|无需|不需要|不能|不要|无法|禁止)\s*(?:保存|导出|写入|处理)|"
    r"\b(?:not|never|don[\x27’]t|doesn[\x27’]t|won[\x27’]t)\s+(?:cover|teach|save|export|write)\b|\bwithout\s+(?:saving|exporting|writing)\b",
    re.I,
)
_DIFFERENT_OPERATION = re.compile(r"下载|截图|截屏|抓取|爬虫|\b(?:download|screenshot|scrap\w*)\b", re.I)
_REMOTE = re.compile(r"远程|云端|网络路径|网页路径|URL\s*路径|https?://|\b(?:remote|cloud|URL|URI)\b", re.I)
_CLAUSE = re.compile(r"[，,。！？!?；;\n]|\.(?=\s|$)")
_DIRECTION = re.compile(r"为|到|成|至|->|→")
_SOURCE_SUBJECT = re.compile(r"^(?:数据|表格|文件|图表|数组|内容|结果)\s*")


@dataclass(frozen=True)
class _Operation:
    context: tuple[str, ...]
    action: str
    object: str
    qualification: str
    local: bool = False
    kind: str = "output"

    @property
    def core(self) -> str:
        if self.kind != "output":
            task = {"input": "读取 " + self.object, "deduplicate": "数据去重", "datetime": "日期时间转换",
                    "group_count": "分组计数", "bar_plot": "条形图绘制", "csv_output": "CSV 写出"}[self.kind]
            return " ".join((*self.context, task))
        task = self.object + self.action if self.local else self.action + " " + self.object
        return " ".join((*self.context, task))


def _parse_output(point: str) -> _Operation | None:
    match = _POINT.fullmatch(point)
    if not match:
        return None
    context = tuple(match["context"].split())
    task = match["task"]
    local = _LOCAL.fullmatch(task)
    if local:
        return _Operation(context, "处理", local["object"], "本地", True)
    output = _OUTPUT.fullmatch(task)
    if not output or not _SUBJECT_HEAD.search(output["subject"]):
        return None
    # Do not silently demote an additional requested action/security requirement
    # into an input noun. Ambiguous or compound prose keeps the strict matcher.
    if re.search(r"读取|导入|清洗|保存|导出|写入|加密|解密|认证|并发|无损|[与及和、]", output["subject"]):
        return None
    return _Operation(context, output["action"], output["object"], output["subject"])


def _has_context(context: tuple[str, ...], text: str) -> bool:
    # Exact technology boundaries distinguish Java/JavaScript and C/C++/C#.
    # No API ownership, synonym, language, or library is inferred here.
    return all(re.search(rf"(?<![A-Za-z0-9_.+#-]){re.escape(term)}(?![A-Za-z0-9_.+#-])", text, re.I)
               for term in context)


def _has_target(target: str, text: str) -> bool:
    if not text.casefold().startswith(target.casefold()):
        return False
    rest = text[len(target):].lstrip()
    if re.match(r"[A-Za-z0-9_.+#-]", rest):
        return False
    # An image URL or encoding is not an image file, and a subsequent output
    # direction means this occurrence was the source rather than the target.
    if re.match(r"\s*(?:链接|地址|编码|摘要|URL|URI|到|为|成|至|->|→)", rest, re.I):
        return False
    if re.match(r"[\u4e00-\u9fff]", rest) and not re.match(
        r"^(?:文件)?(?:教程|方法|操作|示例|详解|基础|入门|指南|课程|视频)?(?=$|[\s，。！？;；:：()（）])", rest
    ):
        return False
    return True


# Six finite operations, not a dictionary of project fields/examples. Residual
# source wording is retained verbatim as an unproved qualification.
_PROJECT_POINT = re.compile(rf"^\s*(?P<tool>{_TECH})\s*(?P<task>.{{2,140}}?)\s*$")
_FORMAT = r"CSV|Excel|JSON|TSV"
_INPUT_TASK = re.compile(rf"(?P<verb>读取|读入|导入|加载)(?P<noun>[\u4e00-\u9fffA-Za-z0-9_ ]{{0,24}}?)\s*(?P<format>{_FORMAT})(?![A-Za-z0-9_])", re.I)
# Only the explicitly requested output operation is decomposed. The complete
# remaining task wording stays an unknown target, not a discarded modifier.
_CSV_OUTPUT_TASK = re.compile(
    r"CSV(?:文件)?\s*(?:写出|导出|保存|写入)|"
    r"(?:写出|导出|保存|写入)(?:为|成|到|至)?\s*CSV(?![A-Za-z0-9_])", re.I)
_CORE_TASKS = {
    "deduplicate": re.compile(r"去重|删除重复(?:行|记录|数据)?"),
    "datetime": re.compile(r"(?P<datehead>日期时间|日期|时间)(?P<operand>列|字段|字符串|数据)?(?:解析|转换)|字符串转(?:为)?日期时间"),
    "group_count": re.compile(r"分组(?:后)?(?:计数|统计数量)"),
    "bar_plot": re.compile(r"(?:绘制|画|生成)?(?:条形图|柱状图)(?:绘制|绘图)?"),
}
_CORE_OWNERS = {"deduplicate": "pandas", "datetime": "pandas", "group_count": "pandas", "bar_plot": "matplotlib"}
_CORE_APIS = {"CSV": "read_csv", "Excel": "read_excel", "JSON": "read_json", "TSV": "read_table"}
_CORE_EXCLUDE = re.compile(
    r"先修|前置|预先|需要(?:掌握|熟悉|了解)|已(?:掌握|学会)|API\s*(?:列表|清单|list|reference)|(?:函数|方法)列表|"
    r"不(?:讲|教|演示|实现|支持|包含|读取|导入|转换|去重|绘制)|未(?:讲|教|演示|实现)|"
    r"\b(?:prerequisites?|prior\s+knowledge|requires?|assumes?|not\s+(?:cover|teach|read|convert|plot)|without\s+(?:reading|converting|plotting))\b", re.I)
_KNOWN_LIBRARY = re.compile(r"(?<![A-Za-z0-9_.+#-])(?:pandas|numpy|polars|matplotlib|openpyxl|pillow|scipy|tensorflow|pytorch|torch)(?![A-Za-z0-9_.+#-])", re.I)
_CORE_NEGATED_ACTION = re.compile(r"(?:不|无需|无须|不要|禁止|避免|不得)(?:执行|进行|需要)?\s*(?:读取|读入|导入|加载|去重|删除重复|转换|解析|分组|计数|绘制|生成|画)")


def _residual(task: str, match: re.Match, noun: str = "") -> str:
    value = (task[:match.start()] + noun + task[match.end():]).strip()
    # Generic file/data nouns are part of the core, not invented requirements.
    if re.fullmatch(r"(?:数据|文件|格式|表格|的|\s|与|及|和|并)*", value):
        return ""
    return value


def _parse_project_operation(point: str) -> _Operation | None:
    match = _PROJECT_POINT.fullmatch(point)
    if not match:
        return None
    context, task = (match["tool"],), match["task"]
    # No fallback is derived from a negated request or URL/operator payload.
    if (re.search(r"https?://|www\.|[<>\n]", task, re.I) or _CORE_EXCLUDE.search(task)
            or _CORE_NEGATED_ACTION.search(task)):
        return None
    output = _CSV_OUTPUT_TASK.search(task) if context[0].casefold() == "pandas" else None
    if output and (qualification := _residual(task, output)):
        return _Operation(context, "写出", "CSV", qualification, kind="csv_output")
    read = _INPUT_TASK.search(task)
    if read:
        qualification = _residual(task, read, read["noun"])
        if qualification:
            format_name = next(name for name in _CORE_APIS if name.casefold() == read["format"].casefold())
            return _Operation(context, "读取", format_name, qualification, kind="input")
    for kind, pattern in _CORE_TASKS.items():
        if context[0].casefold() != _CORE_OWNERS[kind]:
            continue
        found = pattern.search(task)
        retained_operand = ((found["datehead"] or "") + found["operand"]
                            if found and kind == "datetime" and found["operand"] else "")
        if found and (qualification := _residual(task, found, retained_operand)):
            return _Operation(context, "", "", qualification, kind=kind)
    return None


def _parse(point: str) -> _Operation | None:
    return _parse_project_operation(point) or _parse_output(point)


def operation_decomposition(point_text: str) -> dict | None:
    """A stable requested target, never evidence that either part is taught."""
    operation = _parse(point_text)
    if operation is None:
        return None
    return {"decomposition_status": "applied", "shared_context": list(operation.context), "subtopics": [
        {"id": "operation_core", "text": operation.core},
        {"id": "operation_qualification", "text": operation.qualification}]}


def _local_owner(operation: _Operation, text: str, position: int) -> bool:
    window = text[max(0, position - 600):position]
    if not _has_context(operation.context, window):
        return False
    libraries = list(_KNOWN_LIBRARY.finditer(window))
    return not libraries or libraries[-1][0].casefold() == operation.context[0].casefold()


def _owned_api(operation: _Operation, text: str, pattern: str) -> bool:
    owner = operation.context[0].casefold()
    for found in re.finditer(pattern, text, re.I):
        prefix = text[max(0, found.start() - 100):found.start()]
        if _CORE_EXCLUDE.search(prefix):
            continue
        token = found[0].lstrip().casefold()
        if operation.kind == "input":
            separator = re.search(r"sep\s*=\s*(['\"])(.*?)\1", token)
            if separator and ((operation.object == "CSV" and separator[2] in {r"\t", "\t"})
                              or (operation.object == "TSV" and separator[2] not in {r"\t", "\t"})):
                continue
        canonical = token.startswith("pandas.") if owner == "pandas" else token.startswith("matplotlib.pyplot.")
        alias = "pd" if owner == "pandas" else "plt"
        explicit_import = bool(re.search(r"\bimport\s+" + (r"pandas" if owner == "pandas" else r"matplotlib\.pyplot") + r"\s+as\s+" + alias + r"\b", text[:found.start()], re.I))
        wrong_alias = re.search(r"\bimport\s+(?!" + (r"pandas\b" if owner == "pandas" else r"matplotlib\.pyplot\b") + r")[A-Za-z0-9_.]+\s+as\s+" + alias + r"\b|\b" + alias + r"\s*=", text[:found.start()], re.I)
        if not wrong_alias and (canonical or explicit_import or _local_owner(operation, text, found.start())):
            return True
    return False



def _csv_output_clause(operation: _Operation, clause: str) -> bool:
    """Bind CSV to this clause's explicit write target, never its read source."""
    action = re.compile(r"读写|写出|导出|保存|写入|(?<![A-Za-z0-9_.])write\b", re.I)
    formats = re.compile(
        r"\s*(?:为|成|到|至)?\s*(?P<formats>(?:CSV|Excel)(?![A-Za-z0-9_])"
        r"(?:[\s/、,&与和]+(?:CSV|Excel)(?![A-Za-z0-9_]))*)"
        r"\s*(?:文件|files?)?", re.I)
    for found in action.finditer(clause):
        if not _local_owner(operation, clause, found.start()):
            continue
        target = formats.match(clause, found.end())
        if target and re.search(r"\bCSV\b", target["formats"], re.I):
            remainder = clause[target.end():].strip()
            if (not re.match(r"(?:到|为|成|至|->|→|\b(?:to|into)\b)", remainder, re.I)
                    and _has_target("CSV", "CSV" + remainder)):
                return True
    # A named output operation such as 'CSV导出教程' is also explicit, but
    # '读取CSV导出Excel' is not: its following format establishes direction.
    for found in re.finditer(r"(?<![A-Za-z0-9_])CSV(?:文件)?\s*(?:写出|导出|保存|写入)", clause, re.I):
        tail = clause[found.end():].strip()
        if (_local_owner(operation, clause, found.start())
                and (not tail or re.match(r"^(?:教程|教学|课程|方法|示例|实例|详解|用法|[。；;:：()（）])", tail))):
            return True
    return False


def _supports_project_core(operation: _Operation, text: str) -> bool:
    text = re.sub(r"https?://\S+", " ", text)
    owner = operation.context[0].casefold()
    qualified_owner = (owner in {"pandas", "matplotlib"}
                       and re.search(r"(?<![A-Za-z0-9_.])" + re.escape(owner) + r"\.", text, re.I))
    if (not (_has_context(operation.context, text) or qualified_owner) or _CORE_EXCLUDE.search(text)
            or _CORE_NEGATED_ACTION.search(text)):
        return False
    if operation.kind == "bar_plot" and _DIFFERENT_OPERATION.search(text):
        return False
    for clause in _CLAUSE.split(text):
        if _CORE_EXCLUDE.search(clause) or _NEGATION.search(clause):
            continue
        # Natural-language claims must own their context in this clause.
        if _has_context(operation.context, clause):
            if operation.kind == "csv_output":
                if _csv_output_clause(operation, clause):
                    return True
            elif operation.kind == "input":
                for found in _INPUT_TASK.finditer(clause):
                    middle = found["noun"]
                    if (found["format"].casefold() == operation.object.casefold()
                            and not re.search(r"读取|导出|输出|写入|保存|转换|转为|到|至|为|CSV|Excel|JSON|TSV", middle, re.I)
                            and _local_owner(operation, clause, found.start())):
                        return True
            else:
                # "时间处理"/"聚合"/"pandas基础" alone are not these actions.
                natural = {"deduplicate": r"数据去重|(?:删除|移除)重复(?:数据|记录|行)",
                           "datetime": r"(?:字符串|日期|时间).{0,8}(?:转换为|转换成|解析为|转为)(?:日期|时间)|日期时间转换",
                           "group_count": r"分组(?:后)?(?:计数|统计数量)",
                           "bar_plot": r"(?:绘制|画|生成)(?:条形图|柱状图)|(?:条形图|柱状图)(?:绘制|绘图|教程)"}[operation.kind]
                for found in re.finditer(natural, clause, re.I):
                    if _local_owner(operation, clause, found.start()):
                        return True
    if operation.context[0].casefold() not in {"pandas", "matplotlib"}:
        return False
    boundary = r"(?<![A-Za-z0-9_.])"
    suffix = r"\s*(?:\([^)]*[^\s)]\)|(?:函数|方法)?(?:用法|教程|详解|示例))"
    if operation.kind == "input" and operation.context[0].casefold() != "pandas":
        return False
    if operation.kind == "input":
        pattern = boundary + r"(?:(?:pandas|pd)\.)?" + _CORE_APIS[operation.object] + suffix
    elif operation.kind == "csv_output":
        pattern = boundary + r"(?:(?:pandas\.)?(?:DataFrame|Series)\.)?to_csv" + suffix
    elif operation.kind == "deduplicate":
        pattern = boundary + r"(?:(?:(?:pandas|pd)\.)?DataFrame\.)?drop_duplicates" + suffix
    elif operation.kind == "datetime":
        pattern = boundary + r"(?:(?:pandas|pd)\.)?to_datetime" + suffix
    elif operation.kind == "group_count":
        pattern = boundary + r"(?:(?:pandas|pd)\.)?(?:DataFrame|Series)\.groupby\([^)]*\)\s*\.\s*(?:count|size)\([^)]*\)"
    else:
        pattern = boundary + r"(?:matplotlib\.pyplot\.|plt\.)bar" + suffix
    if _owned_api(operation, text, pattern):
        return True
    return False


def _supports(operation: _Operation, text: str) -> bool:
    if operation.kind != "output":
        return _supports_project_core(operation, text)
    if not _has_context(operation.context, text) or _NEGATION.search(text):
        return False
    if (operation.local and _REMOTE.search(text)) or (not operation.local and _DIFFERENT_OPERATION.search(text)):
        return False
    for clause in _CLAUSE.split(text):
        # A different sentence's technology cannot label this operation. Parent
        # chapter context is already supplied within the same cleaned clause.
        if not _has_context(operation.context, clause):
            continue
        if operation.local:
            if operation.object + operation.action in clause:
                return True
            continue
        for action in re.finditer(re.escape(operation.action), clause):
            tail = clause[action.end():].strip()
            # Explicit direction takes precedence, so "导出 Excel 数据到 CSV"
            # never counts as exporting to Excel just because Excel occurs first.
            direction = _DIRECTION.search(tail)
            if direction:
                subject = tail[:direction.start()].strip()
                # Bind the output direction to this action, allowing only an
                # explicit input noun. Never jump across "CSV再导入到Excel".
                if subject and subject != operation.qualification and not _SOURCE_SUBJECT.fullmatch(subject):
                    continue
                target = tail[direction.end():].strip()
            else:
                target = _SOURCE_SUBJECT.sub("", tail, count=1)
            if _has_target(operation.object, target):
                return True
    return False


def assess_operation_fallback(point_text: str, observations: list[dict]) -> dict | None:
    """Return only evidence-backed partial support, or no fallback.

    Each observation must contain its own complete technical context, action,
    target and nonempty evidence_ids. Use ``text`` for the caller's cleaned
    instructional text; no words or IDs are stitched between observations.
    """
    operation = _parse(point_text)
    if operation is None:
        return None
    supported = []
    for row in observations:
        identifiers = [identifier for identifier in row.get("evidence_ids", []) if isinstance(identifier, str) and identifier]
        text = row.get("text")
        if not isinstance(text, str):
            text = " ".join(str(row.get(field) or "") for field in ("title", "body"))
        if identifiers and _supports(operation, text):
            supported.extend(identifiers)
    identifiers = list(dict.fromkeys(supported))
    if not identifiers:
        return None
    message = f"仅证明“{operation.core}”；原知识点的“{operation.qualification}”限定尚未确认，不能视为完整覆盖。"
    return TopicEvidenceAssessment(
        topic_evidence_status="partial",
        topic_evidence_reasons=[{"code": "bounded_operation_partial", "message": message, "evidence_ids": identifiers}],
        supporting_evidence_ids=identifiers,
        subtopic_coverage=[
            {"id": "operation_core", "text": operation.core, "status": "supported", "evidence_ids": identifiers,
             "reason": "同一条真实观察明确包含技术上下文、操作与作用对象。"},
            {"id": "operation_qualification", "text": operation.qualification, "status": "unknown", "evidence_ids": [],
             "reason": f"操作证据不能证明“{operation.qualification}”这一原始限定。"},
        ],
    ).model_dump()
