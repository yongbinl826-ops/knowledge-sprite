"""Bilingual reference hints, never proof of teaching or complete coverage.

The selected concept enables each hint. A phrase/API must occur in the actual
bound source text with its technology context. No project, URL or source ID is
an admission rule, and a tool name alone never matches a learning concept.
"""
import re

_TEXT_SEGMENTATION_SOURCE = (
    # Course catalog headings commonly separate the object, API and operation.
    # Only punctuation and the explicit split() API may bridge these words;
    # arbitrary intervening prose would also admit unrelated classifications.
    r"(?:文本|字符串)(?:的)?[\s_:：/\-]{0,4}"
    r"(?:split\s*\(\s*\)[\s_:：/\-]{0,4})?(?:分段|分割|切分|切块)|"
    r"(?:分段|分割|切分|切块)[\s_:：/\-]{0,4}(?:文本|字符串)|"
    r"(?<![A-Za-z0-9_])(?:text|strings?)\s+(?:splitting|segmentation|chunking)(?![A-Za-z0-9_])|"
    r"(?<![A-Za-z0-9_])split(?:ting)?\s+(?:a\s+)?strings?(?![A-Za-z0-9_])|"
    r"(?<![A-Za-z0-9_])split(?:ting)?\s+(?:a\s+)?text\s+"
    r"(?:into\s+(?:paragraphs?|chunks?|lines?)|by)(?![A-Za-z0-9_])"
)

# These qualifiers change the mechanism, rather than merely its application.
# They constrain every lexical/alias admission path. A shared suffix such as
# "字段校验" or "事件处理" must not erase them; the source may use an equivalent
# professional term or API instead of repeating the selected Chinese wording.
_MECHANISM_RULES = [
    (r"(?:跨|多)\s*字段[^.;。；\n]{0,12}(?:校验|验证|约束)|字段(?:间|之间)[^.;。；\n]{0,12}(?:校验|验证|约束)|\b(?:cross|inter|multi)[ -]?field\s+validat|(?<![A-Za-z0-9_])(?:model_validator|root_validator)(?![A-Za-z0-9_])",
     "跨字段校验",
     r"(?:跨|多)\s*字段[^.;。；\n]{0,12}(?:校验|验证|约束)|字段(?:间|之间)[^.;。；\n]{0,12}(?:校验|验证|约束)|\b(?:cross|inter|multi)[ -]?field\s+validat(?:ion|ors?|ing|e)\b|\bmodel[ -]level\s+validat(?:ion|ors?|ing)\b|模型级(?:别)?(?:校验|验证)|(?<![A-Za-z0-9_])(?:model_validator|root_validator)(?![A-Za-z0-9_])"),
    (r"异步|\basync(?:hronous)?\b", "异步执行",
     r"异步|\b(?:async(?:hronous)?|asyncio|await)\b"),
    (r"(?<!异)同步|\bsynchronous\b", "同步执行",
     r"(?<!异)同步|\bsynchronous\b"),
]

_RULES = [
    (r"游戏主?循环|主循环|game loop", "游戏循环", r"\b(?:main|game|event)\s+loop\b|\bwhile\s+(?:run|running|not\s+(?:done|game_over))\b"),
    (r"(?:矩形(?:区域)?(?:表示|对象|坐标|位置|属性|结构)?|rectangle(?:\s+objects?)?|rect(?:\s+objects?)?)$", "矩形对象", r"\brectangles?\b|\bpygame\.Rect\s*\(|\brect\.(?:x|y|width|height|left|right|top|bottom)\b"),
    (r"碰撞(?:检测)?|collision", "碰撞检测", r"\bcollision\s+(?:detection|checks?)\b|\bcolliderect\s*\("),
    (r"键盘|按键|keyboard|key presses", "键盘输入", r"\bkey\s+press(?:es)?\b|\bkeyboard\s+(?:input|events?|handling)\b|\b(?:pygame\.)?key\.get_pressed\s*\(|\b(?:KEYDOWN|KEYUP)\b"),
    (r"边界|boundar", "边界限制", r"\b(?:boundar(?:y|ies)|screen\s+edges?|bounds\s+checking)\b|\b(?:x|y)\s*(?:>|<)\s*(?:screen_)?(?:width|height)\b"),
    (r"随机|random", "随机数", r"\brandom\.(?:randint|randrange|random|choice|uniform)\s*\(|\brandom\s+(?:numbers?|positions?|coordinates?)\b"),
    (r"列表.*(?:增|删|遍历)|list.*(?:append|remove|iterat)", "列表使用", r"\blist\s+(?:operations?|iteration|methods?|called)\b|\b(?:store|storing|contain|containing)\b[^.;\n]{0,80}\blist\b|\b(?:append|remove|pop)\s*\(|\bfor\s+\w+\s+in\s+(?:items|bullets|coins|enemies|objects)\b"),
    (r"有限状态机|状态机|finite state|\bfsm\b", "状态机", r"\bfinite[ -]state\s+machines?\b|\bstate\s+machines?\b|\bfsm\b"),
    (r"文本渲染|文字渲染|text render", "文本渲染", r"\btext\s+render(?:ing)?\b|\bfont\.render\s*\(|\b(?:display|render|draw)(?:ing)?\s+text\b"),
    (r"(?:文本|字符串)(?:分段|分割|切分)|text\s+(?:splitting|segmentation|chunking)", "文本分段", _TEXT_SEGMENTATION_SOURCE),
    (r"计数变量|计分|计数器|counter|score", "计分和计数", r"\b(?:score|counter|count)\s*\+?=|\b(?:increment|updat)(?:ing|e)?\s+(?:the\s+)?score\b|\bscoring\s*(?:&|and)\s*health\b"),
    (r"dataframe|数据框", "DataFrame", r"\bdataframes?\b|\bpd\.DataFrame\s*\("),
    (r"csv.*(?:读取|导入|read)|(?:读取|导入).*csv|read_csv", "CSV读取", r"\bread_csv\s*\(|\b(?:read|reading|load|loading|import|importing)\s+(?:a\s+)?(?:csv|comma.separated)\b|(?:读取|读入|加载|导入)\s*csv(?:\s*格式)?(?:\s*文件)?|csv(?:\s*格式)?(?:\s*文件)?(?:的)?(?:读取|导入)"),
    (r"数据类型转换|类型转换|astype|type conversion", "类型转换", r"\bastype\s*\(|\bto_numeric\s*\(|\b(?:data\s+)?type\s+(?:conversions?|casting)\b|\bconvert(?:ing)?\s+(?:data\s+)?types?\b"),
    (r"缺失值|空值|missing|null values", "缺失值", r"\b(?:missing|null|NaN|NaT)\s+(?:values?|data)\b|\b(?:dropna|fillna|isna|isnull)\s*\("),
    (r"日期时间|datetime|日期属性", "日期时间", r"\bdatetime\b|\bto_datetime\s*\(|\.dt\.(?:year|month|day|hour|date)\b"),
    (r"布尔.*(?:索引|过滤)|条件筛选|boolean index|boolean filter", "数据过滤", r"\bboolean\s+(?:indexing|mask(?:ing)?|filter(?:ing)?)\b|\bfilter(?:ing)?\s+(?:rows?|dataframes?|data)\b|\bfiltering\s+and\s+sorting\b|\.loc\s*\["),
    (r"分组聚合|groupby|group.by", "分组聚合", r"\bgroupby\s*\(|\bgroup(?:ing)?\s+and\s+aggregat(?:ion|ing)\b|\bgrouped\s+aggregat(?:ion|es)\b"),
    (r"交互控件|交互组件|widgets?", "交互控件", r"\bwidgets?\b|(?:用户)?输入控件|交互(?:式)?(?:控件|组件)|(?<![a-z])UI\s*组件|\b(?:st|streamlit)\.(?:selectbox|multiselect|slider|button|checkbox|radio|date_input|file_uploader)\s*\("),
    (r"表单输入|表单(?:数据)?(?:录入|收集)|form\s+input", "表单输入控件", r"(?:用户)?输入(?:类)?控件|控件\s*[-—:：]?\s*输入类|\b(?:form\s+)?input\s+(?:widgets?|controls?)\b|\b(?:email|contact|web|data(?:\s+entry)?)\s+forms?\b|\bforms?\s+(?:inputs?|widgets?|controls?|submission|handling|tutorials?)\b|\bstreamlit\s+forms?\b|(?<![A-Za-z0-9_.])(?:st|streamlit)\.form(?![A-Za-z0-9_])|(?<![A-Za-z0-9_.])(?:(?:st|streamlit)\.)?text_input(?![A-Za-z0-9_])"),
    (r"(?:word|docx|文档).{0,12}模板.{0,8}(?:填充|替换|更新)|(?:word|docx|document)\s+template\s+(?:fill(?:ing)?|replacement|update)", "文档模板填充", r"(?:更新|填充|替换)\s*(?:docx|word)\s*模板(?:文档)?|(?:docx|word|文档)\s*模板(?:文档)?(?:的)?(?:更新|填充|替换)|(?<![A-Za-z0-9_])(?:word|docx)\s*(?:报告|文档)[^.;。；\n]{0,12}(?:自动)?填充|模板(?:填充|替换)|\btemplate\s+(?:replacement|filling)\b"),
    (r"图表展示|图表|charts?|plotting", "图表展示", r"\bcharts?\b|(?:交互式)?图表|数据可视化|(?:柱状|条形|折线|面积|散点|饼)图|(?<![A-Za-z0-9_])(?:st|streamlit)\.(?:line_chart|bar_chart|area_chart|altair_chart|plotly_chart|pyplot)(?![A-Za-z0-9_])"),
    (r"(?:csv|文件).*(?:导出|下载)|export.*csv|download", "导出和下载", r"\bto_csv\s*\(|\b(?:export|download)(?:ing)?\s+(?:a\s+)?(?:csv|(?:(?:zip|text|binary|image|pdf|docx|word|excel)\s+)?files?|data)\b|\bdownload\s+buttons?\b|(?<![A-Za-z0-9_.])(?:st|streamlit)\.download_button(?![A-Za-z0-9_])|下载按钮|上传下载(?:大)?文件"),
    (r"(?:参数化|变量|参数)[^.;。；\n]{0,6}提示词|提示词模板|\bprompt\s+templates?\b|(?<![A-Za-z0-9_])(?:Chat)?PromptTemplate(?![A-Za-z0-9_])", "提示词模板",
     r"(?:参数化|变量|参数)[^.;。；\n]{0,6}提示词|提示词(?:模板|参数化)|\bprompt\s+templates?\b|(?<![A-Za-z0-9_])(?:Chat)?PromptTemplate(?![A-Za-z0-9_])"),
    (r"(?:对话|聊天)(?:补全|完成)[^.;。；\n]{0,12}(?:接口|调用)|\bchat[ _-]+completions?\b|(?<![A-Za-z0-9_])ChatCompletion(?![A-Za-z0-9_])", "对话补全接口",
     r"(?:对话|聊天)(?:补全|完成)(?:接口|API|调用)?|\bchat[ _-]+completions?\b|(?<![A-Za-z0-9_])chat\s*\.\s*completions(?![A-Za-z0-9_])|(?<![A-Za-z0-9_])ChatCompletion(?![A-Za-z0-9_])|/v1/chat/completions\b"),
]
_COMPILED=[(re.compile(point,re.I),label,re.compile(source,re.I)) for point,label,source in [*_RULES, _MECHANISM_RULES[0]]]
_CONSTRAINTS=[(re.compile(point,re.I),re.compile(source,re.I)) for point,_,source in _MECHANISM_RULES]
_NEGATED=re.compile(r"(?:\b(?:not|never|excluding|without)\b|不讲|未涉及|不包含)[^.;。；\n]{0,45}$",re.I)
_NEGATED_AFTER=re.compile(r"^[\s:—–-]*(?:(?:is|are|was|were|will\s+be)\s+)?(?:not|never)\s+(?:covered|taught|included|discussed|explained)\b",re.I)

def _denied(matches, content):
    return any(_NEGATED.search(content[max(0,hit.start()-70):hit.start()])
               or _NEGATED_AFTER.search(content[hit.end():hit.end()+80]) for hit in matches)


def reference_concept_denied(concept: str, content: str) -> bool:
    """Explicit noncoverage of a selected alias also vetoes lexical overlap."""
    return any(_denied(source.finditer(content), content)
               for point, _, source in _COMPILED if point.search(concept))


def reference_mechanism_compatible(concept: str, content: str) -> bool:
    """Preserve distinguishing mechanisms without requiring full instruction."""
    for selected, source in _CONSTRAINTS:
        if selected.search(concept):
            matches = list(source.finditer(content))
            if not matches or _denied(matches, content):
                return False
    return True


def reference_concept_hints(concept: str,content: str) -> list[str]:
    result=[]
    for point,label,source in _COMPILED:
        matches=list(source.finditer(content)) if point.search(concept) else []
        denied=_denied(matches, content)
        if matches and not denied:
            result.append(label)
    return result

def reference_technology_context(technology: str,content: str) -> bool:
    names=[technology]
    if technology.casefold()=='python':names+=['pygame','pandas','numpy','streamlit']
    if technology.casefold()=='openai api':names+=['openai']
    return bool(technology) and any(re.search(r'(?<![a-z0-9_])'+re.escape(name)+r'(?![a-z0-9_])',content,re.I) for name in names)
