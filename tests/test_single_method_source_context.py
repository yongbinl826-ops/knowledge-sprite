"""Single-method body interpretation is not Chinese-string equality or approval."""
import json
from pathlib import Path

from backend.app import teaching_match as match
from backend.app.learning_support import learning_skill_assessment
from backend.app.models import SearchRequest
from test_necessary_skill_components import point, lesson, verdict


def test_actual_movement_api_is_inspectable_but_unreviewed_claim_cannot_rank():
    row = json.loads((Path(__file__).parent / 'fixtures/phase3_necessary_components/retained_movement_bare_method.json').read_text(encoding='utf-8'))
    p, r, e = row['point'], row['resource'], row['evidence']
    pair = match.prepare_pair(p, r, e, 'intermediate')
    source = next(s for s in pair['observations'] if s['basis'] == 'lesson_notes')
    quote = 'keys = pygame.key.get_pressed()'
    assert any(quote in segment for segment in source['segments'])
    skill = next(s for s in pair['skills'] if 'get_pressed' in s['text'])
    core = {'fingerprint': pair['fingerprint'], 'supports': [{
        'skill_id': skill['id'], 'skill': skill['text'], 'evidence_id': source['evidence_id'],
        'quote': quote, 'basis': source['basis'], 'source_text_sha256': source['source_text_sha256']}]}
    # Necessary-source validation is deliberately separate from real judgment.
    assert match.validate_decision(p, r, e, core, 'intermediate')['supports']
    request = SearchRequest(knowledge_points=[p['text']], student_level='intermediate',
                            learning_skills={p['text']: p['learning_skills']})
    assert learning_skill_assessment({**p, '_teaching_decision': core}, r, e, request) is None


def test_body_scope_does_not_relax_explicit_compound_or_method_qualifier():
    for skill in ['QuillFlow flush_queue 队列操作与错误检查', 'QuillFlow 用状态机调用 flush_queue']:
        p = point([skill]); r, e = lesson('This lesson demonstrates QuillFlow.runtime.flush_queue with a worked example.')
        pair = match.prepare_pair(p, r, e)
        assert not match.validate_decision(p, r, e, verdict(pair))['supports']


def test_topic_default_keeps_implicit_method_depth_unknown():
    assert match.missing_skill_components('Arduino analogWrite 占空比控制输出', 'analogWrite', 'Arduino') == ['占空比控制输出']
    assert match.missing_skill_components('Arduino analogWrite 占空比控制输出', 'analogWrite', 'Arduino', strict_topic=False) == []
