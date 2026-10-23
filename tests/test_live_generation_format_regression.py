"""Replay recorded drafts against current checks; accepted repair is synthetic."""
from pathlib import Path
from copy import deepcopy
import json
import httpx
import pytest
from tests.professional_contract_support import flat_proposal
from backend.app.config import Settings
from backend.app.project_analysis import ProjectAnalyzer, AnalysisError, generation_schema, SYSTEM_PROMPT, professional_contract_issues
from backend.app.project_models import AnalysisDocument, ProjectInput

FIXTURES=Path(__file__).parent/'fixtures'/'professional-live-20261020'
def observed(number):return json.loads((FIXTURES/f'draft-{number}.json').read_text('utf8'))
def response(value):return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(value,ensure_ascii=False)}}]})

@pytest.mark.asyncio
async def test_original_invalid_technology_still_rejected_with_exact_safe_codes():
    calls=[]
    def reply(request):
        calls.append(json.loads(request.content));return response(flat_proposal(observed(6)))
    settings=Settings(llm_provider='openai_compatible',llm_base_url='https://offline.invalid/v1',llm_api_key='synthetic',llm_model='synthetic')
    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        with pytest.raises(AnalysisError) as error:
            await ProjectAnalyzer(settings,client).analyze(ProjectInput(name='pygame game',requirements='Move a paddle and catch falling coins; restart with R'))
    assert len(calls)==2 and error.value.code=='quality'
    history=next(item for item in error.value.diagnostics if item.get('type')=='attempt_history')
    codes={issue['code'] for attempt in history['attempts'] for issue in attempt['issues']}
    assert 'invalid_topic_technology' in codes
    assert 'compound_concept_name' not in codes
    # Diagnostics remain coordinate/code only, never raw model values.
    serialized=json.dumps(history,ensure_ascii=False)
    assert '画面绘制与屏幕刷新' not in serialized and 'Python random' not in serialized
    schema=json.loads(calls[1]['messages'][1]['content'])['output_schema']['$defs']['GeneratedConcept']['properties']
    assert schema['name']['maxLength']==80 and schema['technology']['maxLength']==48
    assert 'One short literal tool/language identifier' in schema['technology']['description']
    assert 'joined tools' in schema['technology']['description']

def test_synthetic_format_only_repair_does_not_change_requirements_or_relationships():
    original=observed(6);repaired=deepcopy(original)
    for point in repaired['knowledge_points']:
        if point['technology']=='Python random':point['technology']='Python'
    doc=AnalysisDocument.model_validate(repaired)
    assert doc.professional_concept_issues()==[]
    assert repaired['functions']==original['functions']
    for before,after in zip(original['knowledge_points'],repaired['knowledge_points']):
        assert {k:v for k,v in before.items() if k != 'technology'}=={k:v for k,v in after.items() if k != 'technology'}

def test_recorded_conjunction_name_does_not_require_a_synthetic_rename():
    original=observed(5)
    doc=AnalysisDocument.model_validate(original)
    assert any(point.name=='画面绘制与屏幕刷新' for point in doc.knowledge_points)
    assert doc.professional_concept_issues()==[]
    assert [point.name for point in doc.knowledge_points]==[point['name'] for point in original['knowledge_points']]

def test_model_contract_explains_single_concept_umbrella_and_student_starting_point():
    assert 'keep closely related facets of one mechanism together' in SYSTEM_PROMPT
    assert 'automatically deselect concepts' in SYSTEM_PROMPT
    schema=generation_schema()['$defs']['GeneratedConcept']['properties']
    assert 'learning_skills' not in schema and schema['technology']['maxLength']==48

@pytest.mark.parametrize('text',[
 '通过 pygame.time.Clock 与 tick 限制每帧时间间隔，使移动速度与刷新频率解耦。',
 '通过限制帧率保证运动速度与帧率无关。',
 'Use Clock.tick to ensure movement speed is frame-rate independent.',
])
def test_observed_clock_cap_independence_misconception_is_rejected(text):
    data=observed(6);data['knowledge_points'][7]['description']=text
    doc=AnalysisDocument.model_validate(data)
    found=professional_contract_issues(ProjectInput(name='pygame game',requirements='Use pygame'),doc)
    assert any(issue['code']=='frame_rate_independence' for issue in found)

@pytest.mark.parametrize('text',[
 '使用 pygame.time.Clock.tick 限制每秒最大帧数。',
 '仅靠 Clock.tick 不能使移动速度与帧率解耦。',
 'Clock.tick does not make movement speed independent of frame rate.',
 '使用 Clock.tick 获取 delta time，按速度乘 dt 更新位置，使移动速度与帧率解耦。',
 'Use Clock.tick to get elapsed time, update position using dt and ensure movement speed is independent of frame rate.',
 'Clock.tick返回dt，再按dt乘以速度更新位置，使移动速度与刷新频率解耦。',
 'Clock.tick用于时间基准，使移动速度与刷新频率解耦。使用返回的dt乘以速度更新位置。',
 'Clock.tick alone never makes movement speed independent of refresh rate.',
 'Clock.tick只是限制帧率，通过累积器按固定时间步长更新位置，使运动速度与帧率无关。',
 'Clock.tick用于限帧，使移动对象独立于摄像机。',
])
def test_modest_cap_negation_and_explicit_time_based_motion_are_allowed(text):
    data=observed(6);data['knowledge_points'][7]['description']=text
    doc=AnalysisDocument.model_validate(data)
    found=professional_contract_issues(ProjectInput(name='pygame game',requirements='Use pygame'),doc)
    assert not any(issue['code']=='frame_rate_independence' for issue in found)

@pytest.mark.parametrize('text,bad',[
 ('每帧用随机数生成金币的水平坐标并使其从顶部下移。',True),
 ('每一帧随机更新金币的横坐标。',True),
 ('每帧更新金币的纵坐标，仅在接住或漏接后随机确定水平位置。',False),
 ('仅在金币重生时随机生成水平坐标；每帧更新纵坐标。',False),
 ('不要每帧随机改变水平位置。',False),
 ('金币生成时随机选择初始水平坐标，之后每帧只更新其垂直坐标。',False),
 ('每帧更新现有纵坐标，金币生成时才重新随机设置水平坐标。',False),
 ('每帧不随机改变水平坐标。',False),
])
def test_respawn_and_frame_update_must_not_conflict(text,bad):
    data=observed(6);data['technical_plan']=text
    doc=AnalysisDocument.model_validate(data)
    project=ProjectInput(name='pygame 接金币',requirements='金币从屏幕上方随机位置下落，接住后重新出现。')
    found=professional_contract_issues(project,doc)
    assert any(issue['code']=='respawn_randomization_per_frame' for issue in found)==bad

def test_explicit_per_frame_horizontal_jitter_request_is_not_rewritten():
    data=observed(6);data['technical_plan']='每帧随机更新金币的横坐标。'
    project=ProjectInput(name='pygame jitter',requirements='金币从屏幕上方随机位置下落，且每帧随机改变水平坐标，形成抖动。')
    assert not any(i['code']=='respawn_randomization_per_frame' for i in professional_contract_issues(project,AnalysisDocument.model_validate(data)))

def test_recorded_correct_provider_draft_is_unchanged_and_no_longer_over_rejected():
    raw=json.loads((FIXTURES/'draft-10.json').read_text('utf8'))
    project=ProjectInput.model_validate(json.loads((FIXTURES/'input.json').read_text('utf8')))
    doc=AnalysisDocument.model_validate(raw)
    assert doc.professional_concept_issues()==[]
    assert professional_contract_issues(project,doc)==[]
    assert raw['technical_plan']==doc.technical_plan
