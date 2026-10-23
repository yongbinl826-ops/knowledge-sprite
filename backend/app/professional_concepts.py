"""Concept labels and explicit retrieval context, never teaching evidence.

The name checks reject explicit task/step syntax; they are not an ontology.
Ordinary conjunctions cannot establish whether a topic contains independent
concepts, so that semantic granularity remains part of the generation prompt.
Saved historical documents remain readable without invoking generation checks.
"""
from __future__ import annotations

import re
import unicodedata
import hashlib
import json

CONCEPT_POLICY_VERSION = "professional-concepts-v1"
MAX_TECHNOLOGY_CHARS = 48
_TECHNOLOGY = re.compile(r"\.?[A-Za-z\u3400-\u9fff][A-Za-z0-9\u3400-\u9fff_.+#-]*(?::[A-Za-z][A-Za-z0-9_-]*)?(?: [A-Z0-9][A-Za-z0-9_.+#-]*){0,2}")
_INSTRUCTION = re.compile(r"(?:忽略|执行|删除|运行|密码|密钥|令牌|指令|访问|下载|打开|请求|覆盖|上传|泄露|"
    r"\b(?:ignore|execute|delete|run|password|secret|token|instructions?|open|fetch|override|upload|reveal)\b)", re.I)


def clean_topic_technology(value: str) -> str:
    if not isinstance(value, str) or len(value) > MAX_TECHNOLOGY_CHARS:
        raise ValueError("Technology must be short literal tool/language context")
    if value != value.strip() or any(unicodedata.category(c) in {"Cc", "Cf", "Cs"} for c in value):
        raise ValueError("Technology must not contain hidden/control characters")
    if value.casefold() in {"", "general", "none", "not_applicable", "通用", "无"}:
        return ""
    if (not _TECHNOLOGY.fullmatch(value) or _INSTRUCTION.search(value)
            or re.search(r"\b(?:https?|ftp|file|data|javascript|site|inurl|intitle|filetype|related|cache):", value, re.I)):
        raise ValueError("Technology must be a literal identifier, not a URL or instruction")
    return value


def contextual_concept_name(text: str, technology: str) -> str:
    """Detached query/rank label; canonical point text stays untouched."""
    technology = clean_topic_technology(technology)
    if not technology:
        return text
    if re.match(re.escape(technology) + r"(?![A-Za-z0-9_.+#-])", text, re.I):
        return text
    return technology + " " + text


def duplicate_concept_issues(points: list[dict]) -> list[dict]:
    """Find literal duplicates within the same explicit technology context.

    Only whitespace/case and a matching leading technology token are ignored.
    Descriptions, domain vocabulary and inferred mechanism similarity are not
    evidence of identity. Report every member; never merge or rewrite points.
    """
    groups: dict[tuple[str, str], list[int]] = {}
    for index, point in enumerate(points):
        try:
            technology = clean_topic_technology(point.get("technology", ""))
        except ValueError:
            continue  # The field validator reports invalid context separately.
        if not technology:
            continue
        owner = unicodedata.normalize("NFKC", technology).casefold()
        name = " ".join(unicodedata.normalize("NFKC", point["name"]).casefold().split())
        # A single letter can be intrinsic to a term (for example R trees),
        # even when the project also uses that letter as a language identifier.
        # Without independent meaning evidence, do not strip that prefix.
        if len(owner) > 1 and name.startswith(owner):
            remainder = name[len(owner):]
            # An ASCII identifier can directly precede a Chinese concept. Do
            # not treat Java in JavaScript, C in C++, or .NET in .NETCore as a
            # prefix token; punctuation is part of the technology identifier.
            if remainder and (remainder[0].isspace() or (
                    re.fullmatch(r"[a-z0-9_.+#-]", owner[-1])
                    and re.match(r"[\u3400-\u9fff]", remainder))):
                name = remainder.strip()
        groups.setdefault((owner, name), []).append(index)
    duplicate_indices = sorted(index for indices in groups.values() if len(indices) > 1 for index in indices)
    return [{"code": "duplicate_concept_name", **({"point_id": points[index]["id"]} if "id" in points[index] else {}),
             "location": ["knowledge_points", index, "name"],
             "message": "These names are identical after normalizing case/spacing and an explicit technology prefix. Review their learning mechanisms: merge repeated uses into one concept and retain all project applications. If a prefix belongs to a distinct established term, keep both mechanisms with precise, distinguishable professional names instead of merging them."}
            for index in duplicate_indices]


_TASK_ACTION = r"(?:读取|写入|上传|下载|导入|导出|清理|清洗|绘制|创建|编写|保存|加载|更新|删除|添加|设置|测量|绑定|实现|完成|制作|开发|搭建|处理|检测)"


def _explicit_task_bundle(value: str) -> bool:
    """Recognize a narrow Chinese verb-object recipe, not joined noun topics.

    Every joined clause must contain an action and an object. A conjunction,
    topic length, shared subject or an unfamiliar noun is never enough. Noun
    endings make the grammar ambiguous, so abstain rather than certify meaning.
    """
    parts = [part.strip() for part in re.split(r"与|、|以及|并(?:循环|继续|重复)?", value)]
    if len(parts) < 2:
        return False
    for part in parts:
        action = re.fullmatch(_TASK_ACTION + r"\s*(.+)", part)
        if not action:
            return False
        target = action.group(1).strip()
        if (not re.search(r"[A-Za-z0-9\u3400-\u9fff]", target)
                or re.search(r"(?:器|者|性|型|式|法|模式|机制|原理|方法|技术|语义|策略|理论|模型|算法|协议|接口|规则|操作)$", target)):
            return False
    return True


def _explicit_instruction(value: str) -> bool:
    """Require sentence evidence instead of interpreting a noun prefix as a verb.

    Chinese has no whitespace word boundary: a bare action or causative prefix
    can belong to a professional noun. Imperative markers, referential objects
    and purpose clauses provide stronger evidence without a noun allowlist.
    """
    return bool(
        re.match(r"^(?:请|务必|必须|应当|应该|先|首先)\s*(?:" + _TASK_ACTION + r"|让|使)", value)
        or re.match(_TASK_ACTION + r"\s*(?:[一这][个份项套张段条些]|该|指定的|所需的|所选的)\S", value)
        or re.match(r"^(?:如何|怎样|怎么|学会|能够|通过.+?来|用.+?来)\S", value)
        or re.match(r"^(?:(?:create|build|make|implement|develop|add|write)\s+(?:a|an|the|this|that|these|those|your|our)\s+|(?:how\s+to|learn\s+to)\s+)\S", value, re.I)
    )


def concept_name_issues(name: str) -> list[tuple[str, str]]:
    """Check explicit structure/imperative grammar, not semantic independence.

    Passing these checks does not certify a coherent concept or full coverage.
    A conjunction or punctuation such as 与/、/and alone is not a rejection.
    """
    value = unicodedata.normalize("NFKC", name).strip()
    issues = []
    if len(value) > 80:
        issues.append(("concept_name_too_long", "Use a concise professional concept name; keep project details in description/why_needed."))
    if re.match(r"^(?:第\s*[一二三四五六七八九十百0-9]+\s*[章节课]|chapter\s+\d+|lesson\s+\d+|step\s+\d+)", value, re.I):
        issues.append(("chapter_or_step_label", "Use the concept itself, without a chapter, lesson or implementation-step label."))
    task_recipe = _explicit_task_bundle(value)
    if (re.search(r"(?<!\+)\+(?!\+)|[;；\n]|然后|接着|再(?:进行|实现|创建|绘制)|并(?:实现|创建|处理|绘制|检测|更新)|\s+(?:and\s+then|then|followed\s+by)\s+", value, re.I)
            or task_recipe):
        issues.append(("task_bundle_name", "Do not concatenate implementation steps or independent concepts; name each reusable concept independently."))
    if task_recipe or _explicit_instruction(value):
        issues.append(("project_task_name", "Replace the instruction/task sentence with the reusable professional concept that enables it."))
    if re.search(r"(?:使得|用来|以便|从而|以实现|(?:并|以)避免|能够|即可|so\s+that|in\s+order\s+to)", value, re.I):
        issues.append(("project_purpose_name", "Keep intended project behavior in description/why_needed; the name is only the concept."))
    if re.search(r"(?:下落|上升|重开|重新开始|接住|获胜|漏接)$|(?:移动|下落|上升|重开|重新开始|接住|获胜|漏接)(?=与|、)", value):
        issues.append(("project_behavior_name", "Name the general technical concept; retain the object's requested behavior only in the project explanation."))
    if re.match(r"^(?:点击.{1,24}(?:显示|切换|打开|开始|更新|播放)|按\s*[A-Za-z0-9]+(?:键)?\s*(?:重开|退出|开始|切换))", value):
        issues.append(("project_interaction_name", "Use the reusable interaction concept, not a click/key action and its project outcome."))
    if re.fullmatch(r"[A-Za-z0-9+#.]+(?:开发|编程|程序设计)(?:基础|入门)", value, re.I):
        issues.append(("broad_subject", "Choose a specific professional concept rather than an entire development/programming foundation course."))
    return issues


def _independent_concept_family(name: str, technology: str) -> str | None:
    """Only simple mechanisms in the observed edge class; unknowns stay unknown.

    Random list sampling may need randomness; plain list traversal does not.
    A project's example/caller does not change the named concept's prerequisite.
    """
    value = unicodedata.normalize("NFKC", name).strip()
    if technology:
        value = re.sub(r"^" + re.escape(technology) + r"(?![A-Za-z0-9_.+#-])",
                       "", value, count=1, flags=re.I).strip()
    patterns = {
        "container_operations": r"(?:列表|数组)(?:操作|增删遍历|遍历|增删|元素操作|元素增删|元素遍历|访问|索引)|(?:list|array) (?:operations?|traversal|iteration|element (?:access|operations?))",
        "random_generation": r"(?:随机数|伪随机数)(?:生成)?|(?:random|pseudorandom)(?: number)? generation|random numbers?",
        "clamping": r"边界限制|边界约束|坐标限幅|坐标约束|数值限幅|区间限幅|clamping|coordinate clamping|boundary constraints?",
        "key_input": r"(?:键盘输入|键盘事件|按键输入|按键事件)(?:处理)?|持续按键状态查询|按键状态(?:查询|检测)|(?:keyboard|key) (?:input|events?|state)(?: handling| polling| query| detection)?",
    }
    return next((family for family, pattern in patterns.items()
                 if re.fullmatch(pattern, value, re.I)), None)


def concept_semantic_issues(points: list[dict]) -> list[dict]:
    """Bounded generation-only findings, never a stored-document validator.

    No mastery inference or arbitrary-domain certification. Detect application
    labels hiding primitive bookkeeping and two observed classes of independent
    concept edges. No concept, selection, edge or historical payload is changed.
    """
    issues = duplicate_concept_issues(points)
    by_id = {point["id"]: point for point in points}
    families = {identifier: _independent_concept_family(point["name"], point.get("technology", ""))
                for identifier, point in by_id.items()}
    storage_label = re.compile(
        r"(?:项目|游戏|应用|页面|界面|业务|系统).{0,12}(?:计数|标志)变量|"
        r"(?:project|game|application|page|interface|business|system) (?:[A-Za-z]+ ){0,3}(?:counter|flag) variables?", re.I)
    independent_pairs = {("container_operations", "random_generation"),
                         ("clamping", "key_input")}
    for index, point in enumerate(points):
        if storage_label.fullmatch(unicodedata.normalize("NFKC", point["name"]).strip()):
            issues.append({"code": "implementation_detail_as_concept", "point_id": point["id"],
                "location": ["knowledge_points", index, "name"],
                "message": "An application-qualified counter/flag variable is implementation bookkeeping, not a reusable professional concept. Name and explain the underlying mechanism, or keep the bookkeeping in the relevant concept's project explanation; do not merely shorten a project step."})
        for edge_index, prior in enumerate(point.get("prerequisite_ids", [])):
            if (families[point["id"]], families.get(prior)) in independent_pairs:
                issues.append({"code": "implementation_order_prerequisite", "point_id": point["id"],
                    "location": ["knowledge_points", index, "prerequisite_ids", edge_index],
                    "message": "These simple named concepts are independent. A caller, data-generation choice or input device used earlier in this project does not make it a necessary knowledge prerequisite. Remove the edge or identify the actual combined mechanism; preserve the original project requirements."})
    return issues[:24]


def topic_technologies(points: list[dict], names: dict[str, str]) -> dict[str, str]:
    """Use only the point's explicit safe context, never legacy concepts/plan.

    Invalid old optional annotations do not block reading or a new confirmation.
    Generation validates its own field separately and repairs it if invalid.
    """
    result = {}
    for point in points:
        try:
            technology = clean_topic_technology(point.get("technology", ""))
        except ValueError:
            continue
        name = names[point["id"]]
        if technology and len(contextual_concept_name(name, technology)) <= 180:
            result[name] = technology
    return result


def reviewed_technologies(value, points):
    """A visible, explicit student review, separate from old hidden metadata."""
    from .technical_prefix import canonical_search_name
    if not isinstance(value, dict) or len(value) > 24:
        raise ValueError("Reviewed context must be a bounded name map")
    names = [canonical_search_name(p["name"]) for p in points]
    if not set(value) <= set(names):
        raise ValueError("Reviewed context must bind exact current canonical concept names")
    result = {}
    for name, technology in value.items():
        if names.count(name) != 1:
            raise ValueError("Reviewed context cannot bind an ambiguous concept name")
        clean = clean_topic_technology(technology)
        if not clean or len(contextual_concept_name(name, clean)) > 180:
            raise ValueError("Reviewed context must be specific and bounded")
        result[name] = clean
    return result


def _context_fingerprint(analysis):
    return hashlib.sha256(json.dumps([{k: p.get(k, "") for k in ("id", "name", "technology")}
        for p in analysis["knowledge_points"]], sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def generated_context(analysis):
    """Called only at a successful generation or explicitly derived edit."""
    from .technical_prefix import canonical_search_name
    if any(concept_name_issues(p["name"]) for p in analysis["knowledge_points"]):
        return None
    try:
        mapping = {canonical_search_name(p["name"]): technology for p in analysis["knowledge_points"]
                   if (technology := clean_topic_technology(p.get("technology", "")))}
        mapping = reviewed_technologies(mapping, analysis["knowledge_points"])
    except ValueError:
        return None
    return {"version": CONCEPT_POLICY_VERSION, "analysis_fingerprint": _context_fingerprint(analysis),
            "topic_technologies": mapping}


def bound_generated_context(version):
    proof = version.get("validated_concept_context")
    analysis = version.get("analysis") or {}
    if (not str(version.get("prompt_version") or "").startswith("project-analysis-v5.")
            or not isinstance(analysis.get("knowledge_points"), list)
            or not isinstance(proof, dict) or proof.get("version") != CONCEPT_POLICY_VERSION
            or proof.get("analysis_fingerprint") != _context_fingerprint(analysis)):
        return None
    try:
        return reviewed_technologies(proof.get("topic_technologies"), analysis["knowledge_points"])
    except (ValueError, KeyError, TypeError):
        return None
