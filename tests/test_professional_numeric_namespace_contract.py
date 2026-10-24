"""Actual retained failure replays + synthetic boundaries; no paid/network calls."""
from copy import deepcopy
import json
from pathlib import Path

import httpx
import pytest
from tests.professional_contract_support import unrepaired_quality_response, flat_proposal

from backend.app import project_analysis as module
from backend.app.config import Settings
from backend.app.project_models import AnalysisDocument, ProjectInput

FIXTURES = Path(__file__).parent / "fixtures"


def retained(case):
    return json.loads((FIXTURES / f"{case}-actual.json").read_text("utf-8"))


def corrected(case, analysis):
    document = deepcopy(analysis)
    if case.startswith("arduino"):
        document["technical_plan"] = document["technical_plan"].replace(
            "注意 Uno 的 PWM 引脚与 ADC 均为板载 10 位，不采用 ESP32 接口。",
            "Uno 的 ADC 默认读取为 10 位（0–1023），analogWrite 的 PWM 默认为 8 位（0–255）；不采用 ESP32 接口。")
        assert document["technical_plan"] != analysis["technical_plan"]
    else:
        next(point for point in document["knowledge_points"] if point["id"] == "K3")["name"] = "DOM键盘事件与空格键检测"
    # Synthetic repaired response: independent concepts, original source file unchanged.
    labels = ({'analog_read':'模拟输入', 'linear_map':'线性映射', 'pwm_analogwrite':'脉宽调制',
        'input_pullup':'上拉电阻', 'millis_timing':'非阻塞定时', 'button_debounce':'按键消抖', 'serial_print':'串行通信'}
        if case.startswith('arduino') else {'K1':'DOM元素查询','K2':'事件回调','K3':'键盘事件','K4':'状态机',
            'K5':'本地存储','K6':'Flexbox布局','K7':'媒体查询','K8':'CSS变换'})
    for point in document['knowledge_points']:
        point['name'] = labels[point['id']]
        if not case.startswith('arduino') and point['id'] not in {'K6','K7','K8'}:
            point['technology'] = 'JavaScript'
    return document


def config():
    return Settings(llm_provider="openai_compatible",llm_base_url="https://offline.invalid/v1",llm_model="offline-synthetic",llm_api_key="SYNTHETIC_NOT_A_KEY",project_semantic_review_enabled=False)


def response(value):
    return httpx.Response(200,json={"choices":[{"message":{"content":json.dumps(value,ensure_ascii=False)}}]})


@pytest.mark.parametrize("case,code,location", [
    ("arduino_pot_button_beginner","numeric_api_contract",["technical_plan"]),
    ("browser_flashcards_intermediate","ambiguous_tool_namespace",["knowledge_points",2,"name"]),
])
@pytest.mark.asyncio
async def test_actual_failure_gets_one_repair_on_real_professional_branch(case,code,location):
    actual=retained(case);bad=deepcopy(actual["analysis"])
    # Missing-context control: the actual retained JavaScript technology now
    # legitimately disambiguates a canonical keyboard concept.
    if case.startswith('browser'):
        bad['knowledge_points'][2]['technology']=''
    good=corrected(case,bad);calls=[]
    def reply(request):
        calls.append(json.loads(request.content))
        proposal = flat_proposal(bad if len(calls)==1 else good)
        return response(proposal)
    project=ProjectInput.model_validate(actual["project"])
    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        result=await module.ProjectAnalyzer(config(),client).analyze(project)
    assert len(calls)==2
    repair=json.loads(calls[1]["messages"][1]["content"])
    assert repair["project"]==actual["project"]
    assert repair["previous_analysis"]["technical_plan"]==bad["technical_plan"]
    issue=next(row for row in repair["validation_feedback"] if row["code"]==code)
    assert issue["location"]==location
    assert not result.knowledge_points[0].learning_skills and result.learner_profile is None
    assert "learner_profile" not in repair["output_schema"]["properties"]
    assert not {"project_task","concepts","learning_skills","practice_check"}&repair["output_schema"]["$defs"]["GeneratedConcept"]["properties"].keys()
    if case.startswith("arduino"):
        assert result.technical_plan==good["technical_plan"]
        assert result.knowledge_points[5].name=="按键消抖"
    else:
        assert result.knowledge_points[2].name=="键盘事件"
        assert result.knowledge_points[2].technology=="JavaScript"
    assert actual==retained(case) # The retained fixture and input are never rewritten.


@pytest.mark.parametrize("case,code",[("arduino_pot_button_beginner","numeric_api_contract"),("browser_flashcards_intermediate","ambiguous_tool_namespace")])
@pytest.mark.asyncio
async def test_repeated_actual_failure_stops_bounded_with_safe_coordinates(case,code):
    actual=retained(case);calls=[];bad=deepcopy(actual['analysis'])
    if case.startswith('browser'):
        bad['knowledge_points'][2]['technology']=''
    def reply(request):
        calls.append(request)
        payload = json.loads(json.loads(request.content)["messages"][1]["content"])
        proposal = flat_proposal(bad)
        return response(unrepaired_quality_response(payload, proposal, actual["project"]))
    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        with pytest.raises(module.AnalysisError) as error:
            await module.ProjectAnalyzer(config(),client).analyze(ProjectInput.model_validate(actual["project"]))
    assert len(calls)==2 and error.value.code=="quality"
    assert any(row.get("code")==code for row in error.value.diagnostics)
    serialized=json.dumps(error.value.diagnostics,ensure_ascii=False)
    assert "previous_analysis" not in serialized and "均为板载" not in serialized and "SYNTHETIC_NOT_A_KEY" not in serialized
    history=error.value.diagnostics[-1]["attempts"]
    assert [row["phase"] for row in history] == ["generation", "repair"]
    assert [row["category"] for row in history] == ["quality", "quality"]
    assert all(any(issue["code"]==code for issue in row["issues"]) for row in history)


@pytest.mark.parametrize("text",[
    "Uno 的 PWM 引脚与 ADC 均为板载 10 位。",
    "PWM与ADC均为10位。",
    "PWM and ADC are both 10-bit.",
    "ADC 和 PWM 都为8位。",
    "analogWrite 是 10 位。",
    "analogRead 是 8 位。",
    "不是ESP32，Uno的PWM与ADC均为10位。",
])
def test_explicit_default_uno_wrong_positive_claims(text):
    data=retained("arduino_pot_button_beginner");doc=corrected("arduino",data["analysis"]);doc["technical_plan"]=text
    issues=module.professional_contract_issues(ProjectInput.model_validate(data["project"]),AnalysisDocument.model_validate(doc))
    assert any(row["code"]=="numeric_api_contract" and row["location"]==["technical_plan"] for row in issues)


@pytest.mark.parametrize("text",[
    "Uno ADC为10位，PWM为8位。",
    "不能说 Uno 的 PWM与ADC均为10位。",
    "PWM与ADC均为10位是错误说法。",
    "错误示例：PWM与ADC均为10位。应分别理解两种位宽。",
    "“Uno的PWM与ADC均为10位”是错误说法，ADC默认10位，PWM默认8位。",
    'Compare the quoted phrase "PWM and ADC are both 10-bit" with the separate domains.',
    "Do not claim PWM and ADC are both 10-bit.",
    "用10位ADC输入调节PWM，将0–1023映射到0–255。",
    "PWM按10位ADC读数映射为8位输出，不是同一个数值域。",
    "假设PWM与ADC都为10位，先检查这个错误前提。",
])
def test_correct_negated_quoted_or_comparison_claims_are_not_rejected(text):
    data=retained("arduino_pot_button_beginner");doc=corrected("arduino",data["analysis"]);doc["technical_plan"]=text
    assert not module.professional_contract_issues(ProjectInput.model_validate(data["project"]),AnalysisDocument.model_validate(doc))


@pytest.mark.parametrize("name,requirements,context",[
    ("ESP32 PWM","使用ESP32开发板配置PWM和ADC。",""),
    ("Arduino Uno R4","使用Uno R4指定分辨率处理模拟输入和PWM。",""),
    ("Arduino Uno WiFi Rev2","使用Uno WiFi Rev2。",""),
    ("Arduino UNO Q","使用UNO Q新板，按其文档的显式API配置处理。",""),
    ("Arduino Uno Timer1","Uno使用Timer1自定义10位PWM，输入输出均按0–1023处理。",""),
    ("Arduino 分辨率配置","使用Uno与analogWriteResolution(10)显式配置分辨率，按配置的数值域处理。",""),
    ("其他板卡","板卡型号未指定，不推断ADC与PWM默认分辨率。",""),
])
def test_nonclassic_or_explicit_custom_configuration_is_not_guessed(name,requirements,context):
    doc=retained("arduino_pot_button_beginner")["analysis"]
    project=ProjectInput(name=name,requirements=requirements,project_context=context)
    assert not module.professional_contract_issues(project,AnalysisDocument.model_validate(doc))


@pytest.mark.parametrize("name,requirements,context",[
    ("ESP32 调光","已迁移到ESP32，使用LEDC自定义10-bit PWM。","此前用过Arduino Uno。"),
    ("板卡迁移","将原Arduino Uno项目迁移到ESP32，使用LEDC配置10位PWM。",""),
    ("多板对照","对照Arduino Uno与ESP32，只在ESP32采用LEDC配置10位PWM。",""),
])
def test_previous_uno_or_multiboard_does_not_own_other_boards_numbers(name,requirements,context):
    raw=retained("arduino_pot_button_beginner")["analysis"];doc=corrected("arduino",raw)
    doc["technical_plan"]="ESP32 LEDC 的PWM为10位；这是明确配置的输出分辨率。"
    project=ProjectInput(name=name,requirements=requirements,project_context=context)
    assert not module.professional_contract_issues(project,AnalysisDocument.model_validate(doc))


@pytest.mark.parametrize("name",["DOM键盘事件与空格键检测","浏览器键盘事件","JavaScript键盘事件","Web keyboard handling","HTML键盘事件","KeyboardEvent键盘事件","React键盘事件"])
def test_explicit_web_names_are_self_contained_queries(name):
    actual=retained("browser_flashcards_intermediate");doc=deepcopy(actual["analysis"]);doc["knowledge_points"][2]["name"]=name
    assert not module.professional_contract_issues(ProjectInput.model_validate(actual["project"]),AnalysisDocument.model_validate(doc))


@pytest.mark.parametrize("description,goal",[
    ("通过event.key或event.code判断用户操作。","判断当前按键。"),
    ("使用Qt QKeyEvent读取按键。","识别空格键。"),
    ("反例：不使用 document 的 keydown 事件处理本单元。","使用已有抽象。"),
    ("引用“document.keydown”和“KeyboardEvent”比较不同生态。","比较设计思路。"),
    ("比较 `KeyboardEvent` 与其他框架事件。","理解不同输入抽象。"),
    ("用状态与稳定时间窗口实现按键去抖。","一次按下一次动作。"),
])
def test_ambiguous_event_key_general_method_or_quoted_namespace_not_upgraded(description,goal):
    actual=retained("browser_flashcards_intermediate");doc=deepcopy(actual["analysis"]);point=doc["knowledge_points"][2]
    point.update(description=description,learning_goal=goal)
    assert not module.professional_contract_issues(ProjectInput.model_validate(actual["project"]),AnalysisDocument.model_validate(doc))


@pytest.mark.parametrize("description",[
    "监听document的keydown事件，通过event.code判断空格。",
    "使用KeyboardEvent对象读取按键。",
    "不使用服务器，监听 document 的 keydown 事件。",
    "不采用Qt；监听document.keydown事件。",
])
def test_explicit_local_namespace_not_excused_by_unrelated_negation(description):
    actual=retained("browser_flashcards_intermediate");doc=deepcopy(actual["analysis"])
    doc["knowledge_points"][2]["description"]=description
    doc["knowledge_points"][2]["technology"]=""  # No explicit reviewed ecosystem in this negative control.
    issues=module.professional_contract_issues(ProjectInput.model_validate(actual["project"]),AnalysisDocument.model_validate(doc))
    assert any(row["code"]=="ambiguous_tool_namespace" for row in issues)


def test_nonweb_project_and_saved_legacy_analysis_are_not_rewritten():
    actual=retained("browser_flashcards_intermediate");document=AnalysisDocument.model_validate(actual["analysis"]);snapshot=document.model_dump()
    project=ProjectInput(name="Qt 桌面程序",requirements="使用PySide和Qt事件处理输入。")
    assert not module.professional_contract_issues(project,document)
    assert document.model_dump()==snapshot
    # Loading saved v1 data still accepts the historical text. The new rule is
    # invoked by fresh ProjectAnalyzer generation only, never model validation.
    ar=retained("arduino_pot_button_beginner");saved=AnalysisDocument.model_validate(ar["analysis"])
    before=saved.model_dump();assert module.professional_contract_issues(ProjectInput.model_validate(ar["project"]),saved)
    assert saved.model_dump()==before and AnalysisDocument.model_validate(before).model_dump()==before


def test_prompt_preserves_numeric_and_ecosystem_contract_without_expanded_fields():
    assert module.ANALYSIS_PROMPT_VERSION=="project-analysis-v8-compact-foundations"
    assert "types/units" in module.SYSTEM_PROMPT
    assert "relevant input/output conditions" in module.SYSTEM_PROMPT
    assert "interfaces, types, units, ordering, identity matching and data roles" in module.SYSTEM_PROMPT
    assert "technology is one short actual language/tool/framework identifier" in module.SYSTEM_PROMPT
    assert "or an empty string for a general concept" in module.SYSTEM_PROMPT
    assert module.ANALYSIS_MAX_MODEL_CALLS==2
    assert module.ANALYSIS_MAX_ATTEMPTS==2
