"""Discovery-query constraints do not change the original target or source admission."""
from copy import deepcopy
import pytest
from backend.app.ai_video_fallback import video_recovery_required_literals
from backend.app.models import SearchRequest
from backend.app.queries import video_recovery_search_phrases_with_diagnostics


@pytest.mark.parametrize('point,owner,hint', [
    ('CSV转JSON与字段映射','Python','Python JSON to CSV mapping'),
    ('CSV转JSON与字段映射','Python','JSON to CSV mapping'),
    ('CSV转JSON','Python','Python JSON to CSV mapping'),
    ('CSV转JSON','Python','JSON to CSV mapping'),
    ('XML迁移到YAML与字段映射','Ruby','Ruby YAML to XML mapping'),
    ('XML迁移到YAML与字段映射','Ruby','YAML to XML mapping'),
    ('JSON转CSV与字段映射','Python','Python CSV to JSON mapping'),
    ('CSV转换为JSON与文本分段','Python','Python JSON read CSV text splitting'),
])
def test_untranslated_identifier_relationship_cannot_be_reversed(point,owner,hint):
    request=SearchRequest(knowledge_points=[point],topic_technologies={point:owner})
    before=deepcopy(request.model_dump())
    phrases,diag=video_recovery_search_phrases_with_diagnostics(point,request,[hint])
    assert diag['accepted_hints']==0
    assert diag['rejected_hints']['operation_not_preserved']==1
    assert request.model_dump()==before
    assert len(phrases)<=3


def test_verbatim_direction_is_allowed_without_guessing_translation():
    point='CSV转JSON与字段映射'
    request=SearchRequest(knowledge_points=[point],topic_technologies={point:'Python'})
    phrases,diag=video_recovery_search_phrases_with_diagnostics(point,request,['Python CSV转JSON 字段映射'])
    assert diag['accepted_hints']==0
    assert diag['rejected_hints']['duplicate']==1
    assert diag['rejected_hints']['operation_not_preserved']==0
    assert phrases[0]=='Python CSV转JSON与字段映射'


def test_multiple_separate_identifiers_are_not_mistaken_for_direction():
    point='getImageData 与 putImageData 像素更新'
    request=SearchRequest(knowledge_points=[point],topic_technologies={point:'JavaScript'})
    hint='JavaScript getImageData putImageData pixel updates'
    phrases,diag=video_recovery_search_phrases_with_diagnostics(point,request,[hint])
    assert hint in phrases and diag['accepted_hints']==1


@pytest.mark.parametrize('owner,hint', [
    ('.NET','asynchronous tasks cancellation'),
    ('.NET','.NET asynchronous tasks cancellation'),
    ('python-docx','paragraph styles page layout'),
    ('python-docx','python-docx paragraph styles page layout'),
    ('System.Threading.Tasks','asynchronous tasks cancellation'),
    ('C++','asynchronous tasks cancellation'),
    ('C#','asynchronous tasks cancellation'),
])
def test_restored_owner_preserves_original_complete_spelling(owner,hint):
    point='异步任务与取消机制'
    request=SearchRequest(knowledge_points=[point],topic_technologies={point:owner})
    before=request.model_dump()
    phrases,diag=video_recovery_search_phrases_with_diagnostics(point,request,[hint])
    assert diag['accepted_hints']==1
    assert phrases[-1].startswith(owner+' ')
    assert phrases[-1].split().count(owner)==1
    assert request.model_dump()==before
    assert len(phrases)<=3


@pytest.mark.parametrize('owner,wrong', [('.NET','NET'),('C++','C'),('C#','C++')])
def test_owner_spelling_qualifier_conflict_is_not_repaired(owner,wrong):
    point='异步任务与取消机制'
    request=SearchRequest(knowledge_points=[point],topic_technologies={point:owner})
    _,diag=video_recovery_search_phrases_with_diagnostics(point,request,[wrong+' asynchronous tasks cancellation'])
    assert diag['accepted_hints']==0


def test_shared_literal_helper_preserves_complete_identifier_tokens():
    assert video_recovery_required_literals('.NET python-docx System.Threading.Tasks C++ C# st.form 2D 3.13 .NET') == [
        '.NET','python-docx','System.Threading.Tasks','C++','C#','st.form','2D','3.13']


@pytest.mark.parametrize('hint',['python docx paragraph styles layout','Python paragraph styles layout'])
def test_original_hyphenated_api_owner_cannot_be_dropped(hint):
    point='python-docx 段落样式与版式管理'
    request=SearchRequest(knowledge_points=[point],topic_technologies={point:'python-docx'})
    _,diag=video_recovery_search_phrases_with_diagnostics(point,request,[hint])
    assert diag['accepted_hints']==0


@pytest.mark.parametrize('api',['model_validator','root_validator'])
def test_optional_observed_api_names_remain_discovery_leads(api):
    point='模型级校验与跨字段约束'
    request=SearchRequest(knowledge_points=[point],topic_technologies={point:'Pydantic'})
    hint=f'Pydantic {api} validation'
    phrases,diag=video_recovery_search_phrases_with_diagnostics(point,request,[hint])
    assert hint in phrases and diag['accepted_hints']==1


def test_qualified_owner_does_not_disable_explicit_version_conflict():
    point='异步任务与取消机制'
    request=SearchRequest(knowledge_points=[point],topic_technologies={point:'.NET'},technical_version='8.0')
    _,diag=video_recovery_search_phrases_with_diagnostics(point,request,['.NET asynchronous tasks cancellation 9.0'])
    assert diag['accepted_hints']==0 and diag['rejected_hints']['version_conflict']==1
