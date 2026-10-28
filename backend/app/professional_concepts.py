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


_OPERATION_TITLE_END = re.compile(
    r".+(?:初始化|创建|配置|设置|更新|刷新|重置|清零|累加|赋值|绑定|销毁|定位|绘制)$|"
    r".+\s+(?:initialization|creation|configuration|update|refresh|reset|increment|assignment|binding|destruction|positioning|drawing)$",
    re.I,
)
_BOOKKEEPING_TITLE = re.compile(
    r".*(?:计数器|计数变量|标志变量|累计值)(?:的)?(?:累加|递增|更新|重置|清零|赋值)$|"
    r"(?:分数|得分)(?:的)?(?:积累|累计|累加|递增|更新|重置|清零|赋值)$|"
    r".*(?:对象|实例|变量|组件)(?:的)?(?:状态|属性|字段|成员)(?:的)?(?:初始化|更新|重置|复位|清零|赋值)$|"
    r"(?:可变|运行时|当前|初始)\s*(?:的\s*)?状态\s*(?:的\s*)?(?:初始化|更新|重置|复位|清零|赋值)$|"
    r"(?:(?:runtime|current|initial)\s+)?(?:counter|flag|counter variable|flag variable)\s+(?:increment|update|reset|assignment)$|"
    r"scores?\s+(?:accumulation|increment|update|reset|assignment)$|"
    r"(?:mutable|runtime|current|initial)\s+state\s+(?:initialization|update|reset|assignment)$|"
    r"(?:(?:runtime|current|initial)\s+)?(?:object|instance|variable|component)\s+(?:state|property|field)\s+(?:initialization|update|reset|assignment)$",
    re.I,
)
_QUANTITY_BASED_ACTION_TITLE = re.compile(
    r"(?:(?:基于|根据|按照|使用|利用).*)?(?:时间|时刻|帧|采样|位置|坐标|速度|数值)(?:的)?"
    r"(?:增量|差值|变化量|差|间隔|步长)(?:驱动)?(?:的)?"
    r"(?:(?:运动|移动|位移|变化|响应)(?:的)?(?:更新|计算|处理|控制|模拟)?|(?:位置|坐标|速度|状态|数值)?更新)$|"
    r"(?:time|frame|sampling|position|coordinate|velocity|value)[ -](?:delta|difference|interval|step)[ -]"
    r"(?:based|driven)\s+(?:(?:motion|movement)(?:\s+(?:updates?|calculation|simulation))?|updates?|(?:position|state|value)\s+updates?)$|"
    r"(?:motion|movement|updates?)\s+based\s+on\s+(?:elapsed\s+time|time\s+delta|(?:frame|sampling)\s+intervals?)$",
    re.I,
)
_REPRESENTATION_HEAD = re.compile(r".+(?:表示|表征|建模)$|.+\s+(?:representation|modelling|modeling)$", re.I)
_CONSTRAINT_HEAD = re.compile(r".+(?:约束|限幅|限制)$|.+\s+(?:constraints?|clamping|limits?)$", re.I)
_REPRESENTATION_USE = re.compile(
    r".*(?:检测|匹配|输入|输出|显示|绘制|比较|检索|排序|筛选|转换|运算)$|"
    r"(?:.+\s+)?(?:detection|matching|drawing|input|output|display|comparison|retrieval|sorting|filtering|conversion)$", re.I)
_MECHANISM_HEAD = re.compile(
    r".*(?:队列|缓冲区|渲染|序列化|反序列化|编码|解码|投影|聚合|归约|映射|校验)$|"
    r"(?:.+\s+)?(?:queue|buffer|rendering|serialization|encoding|decoding|projection|aggregation)$", re.I)
_APPLICATION_HEAD = re.compile(
    r".+(?:输入|输出|显示|展示|保存|读取|收集|接收|发送|更新|处理)$|"
    r".+\s+(?:input|output|display|presentation|storage|reading|collection|sending|updates?)$", re.I)
_INSTRUMENT_HEAD = re.compile(
    r".*(?:器|缓冲区|容器)$|(?:.+\s+)?(?:counter|accumulator|buffer|container|register|renderer)$", re.I)
_BARE_IMPLEMENTATION_ACTION = re.compile(
    r"(?:初始化|创建|配置|设置|更新|刷新|重置|清零|累加|递增|赋值|绑定|销毁|定位|绘制)|"
    r"(?:initialization|creation|configuration|update|refresh|reset|increment|accumulation|assignment|binding|destruction|positioning|drawing)", re.I)
_DOMAIN_STATE_OPERATION = re.compile(
    r".*状态(?:初始化|更新|重置|复位|清零|赋值)$|"
    r"(?:.+\s+)?state\s+(?:initialization|update|reset|assignment)$", re.I)
_RESTORE_ACTION_TITLE = re.compile(
    r".+(?:重置|复位|清零|还原|恢复|重新初始化)$|"
    r".+\s+(?:reset|restoration|reinitialization)$", re.I)
_PROGRAM_STATE = re.compile(
    r"变量|字段|属性|对象|实例|计数|(?:可变|运行时|应用|业务)(?:的)?(?:状态|数据|值)|存储(?:的)?值|"
    r"\b(?:variables?|fields?|properties|objects?|instances?|counters?)\b|"
    r"(?:mutable|runtime|application|business)\s+(?:state|data|values?)", re.I)
_INITIAL_VALUE_OPERATION = re.compile(
    r"(?:初始值|初始数值|默认值|归零|清零)|"
    r"(?:恢复|重置|设置|赋值|设定|设为).{0,36}(?:初始|默认|变量|字段|属性)|"
    r"(?:initial|default)\s+values?|(?:set|reset|restore).{0,36}(?:zero|initial|default|variables?|fields?|properties)", re.I)


def _representation_constraint_bundle(parts: list[str]) -> bool:
    """Recognize two learning heads, not every joined noun or constraint term.

    A representation/model and a separate restriction/limit warrant semantic
    repair when both are named as complete clauses. The model decides whether
    to split them or name an actual shared conventional concept. For example,
    representation-and-reasoning and constraint representation-and-solving do
    not match this grammar; neither a connector nor 'constraint' alone does.
    """
    if len(parts) < 2 or not all(parts):
        return False
    return any(_REPRESENTATION_HEAD.fullmatch(part) for part in parts) and any(
        _CONSTRAINT_HEAD.fullmatch(part) for part in parts)


def textbook_concept_name_issues(name: str) -> list[tuple[str, str]]:
    """Additional naming feedback for newly generated textbook-style topics.

    These deliberately bounded checks flag possible object-operation recipes,
    bookkeeping labels, quantity-based action descriptions and combinations
    of representation and separate constraints that the historical syntax
    contract allowed. They do
    not recognize an ontology, certify every unfamiliar term, or rewrite a
    stored name. Ordinary conjunctions, term length, and action-like words
    inside nouns are insufficient evidence on their own. The generation
    prompt still owns the semantic choice of a conventional concept name.
    A returned title heuristic is feedback, not proof of a bad concept. The
    point adapter below records whether its evidence can block generation.
    """
    value = unicodedata.normalize("NFKC", name).strip()
    parts = [part.strip() for part in re.split(r"与|、|以及|并且|\s+and\s+", value, flags=re.I)]
    # Joining several definite bookkeeping labels does not weaken the
    # evidence. Require every complete clause to match: one operation beside
    # a mechanism is still only a title heuristic, not proof of a bad concept.
    if len(parts) > 1 and all(_BOOKKEEPING_TITLE.fullmatch(part) for part in parts):
        return [("textbook_operation_label",
            "Every joined clause describes a counter/property/state assignment or update. Name the actual underlying concept and preserve these project operations in its description; do not promote each bookkeeping operation into a separate knowledge point.")]
    if len(parts) > 1 and all(parts) and (
            any(_OPERATION_TITLE_END.fullmatch(part) for part in parts)
            or any(_INSTRUMENT_HEAD.fullmatch(part) for part in parts)
            and any(_BARE_IMPLEMENTATION_ACTION.fullmatch(part) for part in parts)):
        return [("textbook_operation_bundle",
            "Review this operation-like title against its description before changing it. Use a conventional textbook concept as the name and keep project operations in the description. Preserve related facets of the same mechanism; separate genuinely independent concepts only when the explanation supports that distinction, without losing required behavior.")]
    if _BOOKKEEPING_TITLE.fullmatch(value):
        return [("textbook_operation_label",
            "This name describes a counter/property/state update rather than the concept being learned. Name the underlying conventional concept and explain this operation in its description, or incorporate it into an existing concept teaching the same mechanism. Do not turn each assignment, increment or reset into a separate knowledge point.")]
    if _QUANTITY_BASED_ACTION_TITLE.fullmatch(value):
        return [("textbook_descriptive_name",
            "This wording may describe an action driven by a runtime quantity rather than name the principle being taught. Check the established mathematical, programming or domain definition against the explanation, and retain the quantity and project behavior in the description. Do not change a valid name merely to evade a wording pattern or invent a technical-sounding term.")]
    if _representation_constraint_bundle(parts):
        return [("textbook_representation_constraint_bundle",
            "This title may combine a representation/model with a separate constraint or limit. Check their actual learning principles in the description: split independent concepts using conventional textbook names, or retain an established shared concept when its definition covers both. Keep every required project use, including relevant foundations; do not merely delete the conjunction or broaden the title.")]
    if len(parts) > 1 and all(parts) and (
            any(_REPRESENTATION_HEAD.fullmatch(part) for part in parts)
            and any(_REPRESENTATION_USE.fullmatch(part) for part in parts)
            or any(_MECHANISM_HEAD.fullmatch(part) for part in parts)
            and any(_APPLICATION_HEAD.fullmatch(part) for part in parts)):
        return [("textbook_mechanism_application_bundle",
            "This title may append an input/output application to a mechanism, or an operation to a representation. Determine what the description actually teaches: use the conventional concept name for one principle and keep its input/output/project uses in the description; split only genuinely independent principles with their own standard names. Preserve valid related facets and every required behavior.")]
    return []


_TITLE_HEURISTIC_CODES = frozenset({
    "textbook_operation_bundle", "textbook_descriptive_name",
    "textbook_representation_constraint_bundle", "textbook_mechanism_application_bundle",
})


def textbook_concept_issues(points: list[dict]) -> list[dict]:
    """Generation-only feedback with explicit evidence and disposition.

    Operation suffixes and joined topic labels cannot establish whether a
    name teaches independent principles. Retain those findings as advisory,
    rather than treating a name-only heuristic as a content error. Explicit
    bookkeeping labels and description-backed state assignment recipes still
    require repair. Other validators retain schema, imperative, duplicate and
    content checks; this function neither accepts a document nor edits it.
    Never attach it to stored-document validation.
    """
    issues = []
    for index, point in enumerate(points):
        feedback = textbook_concept_name_issues(point["name"])
        # A domain qualifier is not a mechanism. Use description evidence of
        # assigning/restoring values rather than blacklisting domain words or
        # rejecting genuine physical/protocol state operations by name alone.
        description = point.get("description", "")
        description_evidence = False
        state_recipe = _DOMAIN_STATE_OPERATION.fullmatch(point["name"]) or (
            _RESTORE_ACTION_TITLE.fullmatch(point["name"]) and _PROGRAM_STATE.search(description))
        if not feedback and state_recipe and _INITIAL_VALUE_OPERATION.search(description):
            description_evidence = True
            feedback = [("textbook_operation_label",
                "The description teaches restoring or assigning initial values, and the name only prefixes that implementation action with an application/domain state. Keep these uses under their actual established programming/state concept, or name a distinct standard mechanism if one is really taught. Do not invent a state-reset concept or omit the required restart/reset behavior.")]
        for code, message in feedback:
            advisory = code in _TITLE_HEURISTIC_CODES
            issues.append({"code": code, **({"point_id": point["id"]} if "id" in point else {}),
                           "location": ["knowledge_points", index, "name"], "message": message,
                           "disposition": "advisory" if advisory else "blocking",
                           "evidence": ("title_heuristic" if advisory else
                                        "state_assignment_description" if description_evidence else
                                        "explicit_bookkeeping_label"),
                           "severity": "low" if advisory else "medium"})
    # Every validated point (up to the document's 30-point ceiling) must take
    # part in the decision. Presentation/audit limits are applied afterwards;
    # early advisory findings must never hide a later blocking finding.
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

    Invalid optional annotations do not block reading or a new confirmation.
    The original generated or historical annotations remain unchanged.
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
    from .project_models import MAX_PROJECT_KNOWLEDGE_POINTS
    from .technical_prefix import canonical_search_name
    if not isinstance(value, dict) or len(value) > MAX_PROJECT_KNOWLEDGE_POINTS:
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
    """Build a safe retrieval projection without judging generated concepts.

    Unsafe optional technology text is omitted point by point, not repaired or
    written back. A canonical name shared by multiple points cannot bind a
    name-keyed retrieval context, so abstain on that name and retain other safe
    entries. This projection is not a concept-quality or correctness check.
    """
    from .technical_prefix import canonical_search_name
    points = analysis["knowledge_points"]
    names = [canonical_search_name(point["name"]) for point in points]
    identities = [name.casefold() for name in names]
    mapping = {}
    for point, name, identity in zip(points, names, identities):
        if identities.count(identity) != 1:
            continue
        try:
            technology = clean_topic_technology(point.get("technology", ""))
        except ValueError:
            continue
        if technology and len(contextual_concept_name(name, technology)) <= 180:
            mapping[name] = technology
    try:
        mapping = reviewed_technologies(mapping, points)
    except ValueError:
        return None
    return {"version": CONCEPT_POLICY_VERSION, "analysis_fingerprint": _context_fingerprint(analysis),
            "topic_technologies": mapping}


def bound_generated_context(version):
    proof = version.get("validated_concept_context")
    analysis = version.get("analysis") or {}
    if (not str(version.get("prompt_version") or "").startswith(("project-analysis-v5.", "project-analysis-v6.", "project-analysis-v7.", "project-analysis-v8-", "project-analysis-v9-"))
            or not isinstance(analysis.get("knowledge_points"), list)
            or not isinstance(proof, dict) or proof.get("version") != CONCEPT_POLICY_VERSION
            or proof.get("analysis_fingerprint") != _context_fingerprint(analysis)):
        return None
    try:
        return reviewed_technologies(proof.get("topic_technologies"), analysis["knowledge_points"])
    except (ValueError, KeyError, TypeError):
        return None
