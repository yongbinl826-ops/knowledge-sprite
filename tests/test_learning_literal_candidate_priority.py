"""Inspection priority only: these tests never create a teaching claim."""
import copy
import json
from pathlib import Path

import pytest

from backend.app.service import _learning_literal_hits, _select_learning_candidates
from backend.app.teaching_match import prepare_pair
from backend.app.ranking import relevance


def pair(text, skills=None, body='', owner='Arduino'):
    skills = skills or ['Arduino analogWrite 占空比控制输出', '识别并选用支持 PWM 的数字引脚']
    return {'skills':[{'id':f'skill_{i+1}','text':s} for i,s in enumerate(skills)],'technology':owner,
            'observations':[{'basis':'title','segments':[text]}, {'basis':'description','segments':[body]}]}


def row(rid, p, scores):
    return (max(scores), rid, p, [], scores)


def old_select(candidates, skills):
    remaining=list(candidates);selected=[];covered=[0.]*len(skills)
    while remaining and len(selected)<4:
        def priority(r):
            gains=[max(0.,v-covered[i]) for i,v in enumerate(r[4])]
            return(-sum(gains),-sum(v>0 for v in gains),-r[0],r[1])
        chosen=min(remaining,key=priority);remaining.remove(chosen);selected.append(chosen)
        covered=[max(v,chosen[4][i]) for i,v in enumerate(covered)]
    return selected


def test_retained_actual_api_lesson_or_own_catalog_gets_bounded_slot():
    f=json.loads(Path(__file__).with_name('fixtures').joinpath('arduino-literal-candidates.json').read_text(encoding='utf-8'))
    p=f['point'];rows=[]
    for r in f['resources']:
        ev=[e for e in f['evidence'] if e['resource_id']==r['resource_id'] and e.get('knowledge_point_id') in [None,p['knowledge_point_id']]
            and not(e.get('kind')=='search' and e.get('source') in ['public_catalog','techwithtim_catalog','official_sitemap'])]
        ready=prepare_pair(p,r,ev,'beginner')
        if ready is None:continue
        text=' '.join(s for o in ready['observations'] for s in o['segments'])
        rows.append(row(r['resource_id'],ready,[relevance(s,text) for s in p['learning_skills']]))
    api={'res_fb0aa4e15e8b69c8cfa56b36','res_fdc83c8f764945b0bc9a1d43'}
    before=old_select(rows,p['learning_skills']);original=copy.deepcopy(rows)
    after=_select_learning_candidates(rows,p['learning_skills'])
    assert not api.intersection(r[1] for r in before)
    assert api.intersection(r[1] for r in after)
    assert len(after)==4 and rows==original
    assert all(r in rows for r in after)
    assert not any('supports' in r[2] for r in after)


@pytest.mark.parametrize('spelling',['analogWriter','preanalogWrite','analogWrite2','other.analogWrite','not_analogWrite','analogWrite.foo'])
def test_long_identifier_and_foreign_namespace_do_not_match(spelling):
    assert not any(_learning_literal_hits(pair('Arduino '+spelling)))


def test_wrong_owner_cannot_borrow_literal_leaf():
    p=pair('Unity analogWrite introduction',body='Unity.otherMethod is shown')
    assert not any(_learning_literal_hits(p))


@pytest.mark.parametrize('name',['pygame.display.set_model','other.pygame.display.set_mode','pygame.display.set_mode2'])
def test_complete_namespace_not_suffix_match(name):
    p=pair('pygame '+name,skills=['pygame.display.set_mode 创建窗口'],owner='pygame')
    assert not any(_learning_literal_hits(p))


def test_exact_namespace_can_supply_its_own_literal_owner():
    p=pair('pygame.display.set_mode creates the screen',skills=['pygame.display.set_mode 创建窗口'],owner='pygame')
    assert _learning_literal_hits(p)[0]


@pytest.mark.parametrize('body',['Prerequisites: analogWrite','Next lesson: analogWrite','This course does not teach analogWrite'])
def test_own_non_teaching_declaration_gets_no_api_priority(body):
    assert not any(_learning_literal_hits(pair('Arduino analogWrite',body=body)))


def test_second_skill_is_not_squeezed_by_many_distinct_first_skill_apis():
    skills=['Tool alphaAPI betaAPI gammaAPI deltaAPI','Tool secondAPI']
    rows=[row(str(i),pair('Tool '+api,skills,owner='Tool'),[.9-i*.01,0.]) for i,api in enumerate(['alphaAPI','betaAPI','gammaAPI','deltaAPI'])]
    rows.append(row('second',pair('Tool secondAPI',skills,owner='Tool'),[0.,.01]))
    selected=_select_learning_candidates(rows,skills)
    assert any(r[1]=='second' for r in selected[:2])


def test_repeat_api_names_do_not_consume_all_slots():
    skills=['Tool alphaAPI','Tool secondAPI']
    rows=[row(str(i),pair('Tool alphaAPI alphaAPI alphaAPI',skills,owner='Tool'),[.9-i*.01,0.]) for i in range(8)]
    rows.append(row('second',pair('Tool secondAPI',skills,owner='Tool'),[0.,.01]))
    assert any(r[1]=='second' for r in _select_learning_candidates(rows,skills)[:2])


def test_no_api_sources_preserve_existing_marginal_priority():
    skills=['Tool 数组索引','Tool 状态更新']
    rows=[row(str(i),pair('Tool 普通主题',skills,owner='Tool'),[i/10,(8-i)/10]) for i in range(8)]
    assert _select_learning_candidates(rows,skills)==old_select(rows,skills)


def test_search_query_url_and_payload_cannot_supply_api_priority():
    p=pair('Arduino general course')
    p['payload']={'query':'Arduino analogWrite','url':'https://example.com/analogWrite'}
    p['observations'].append({'basis':'search','segments':['Arduino analogWrite']})
    assert not any(_learning_literal_hits(p))


def test_deterministic_ties_and_unchanged_input():
    skills=['Tool specificAPI']
    rows=[row(rid,pair('Tool specificAPI',skills,owner='Tool'),[.5]) for rid in ['z','b','a','q','c']]
    frozen=copy.deepcopy(rows)
    assert [r[1] for r in _select_learning_candidates(rows,skills)]==['a','b','c','q']
    assert rows==frozen


def test_common_owner_and_function_words_are_not_api_priority():
    assert not any(_learning_literal_hits(pair('Arduino and using for',skills=['Arduino and using for'])))


def test_plain_lowercase_declared_identifier_has_no_api_vocabulary():
    p=pair('Tool custommethod example',skills=['Tool custommethod 操作'],owner='Tool')
    assert _learning_literal_hits(p)==[{'1:custommethod'}]
