"""Already-fetched own teaching notes deserve a bounded inspection slot."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from backend.app.service import _learning_bound_notes_hint, _select_learning_candidates


def test_actual_scoring_notes_are_no_longer_crowded_out_by_metadata_only_candidates():
    fixture = json.loads((Path(__file__).parent / 'fixtures/pong_bound_notes_candidates.json').read_text(encoding='utf-8'))
    candidates = [(r['max_score'], r['resource_id'], r['pair'], [], r['scores']) for r in fixture['candidates']]
    before = deepcopy(candidates)
    selected = _select_learning_candidates(candidates, fixture['skills'], fixture['inspection_targets'])
    assert len(selected) == 4
    assert fixture['scoring_resource_id'] in [row[1] for row in selected]
    assert fixture['scoring_resource_id'] not in fixture['old_selected']
    assert candidates == before


def pair(basis='lesson_notes', text='pygame.font.Font is used in this own lesson.', technology='pygame'):
    return {'technology': technology, 'skills': [{'id': 'skill_1', 'text': 'pygame 字体渲染'}],
            'observations': [{'basis': basis, 'segments': [text]}]}


@pytest.mark.parametrize('basis,text,technology', [
    ('title', 'pygame.font.Font', 'pygame'),
    ('description', 'pygame.font.Font', 'pygame'),
    ('catalog', 'pygame.font.Font', 'pygame'),
    ('lesson_notes', 'pygamefoo.font.Font', 'pygame'),
    ('lesson_notes', 'other.pygame.font.Font', 'pygame'),
    ('lesson_notes', 'pygame.font.Font', 'OtherEngine'),
    ('lesson_notes', 'pygame.font.Font', ''),
])
def test_hint_does_not_borrow_titles_or_foreign_owner(basis, text, technology):
    assert not _learning_bound_notes_hint(pair(basis, text, technology))


def test_own_qualified_owner_notes_hint_is_not_a_teaching_decision():
    value = pair()
    before = deepcopy(value)
    assert _learning_bound_notes_hint(value)
    assert value == before
    assert 'supports' not in value and 'teaching_support' not in value
