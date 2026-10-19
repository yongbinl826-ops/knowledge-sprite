"""Retained own lesson teaching examples; offline, never execute source code."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from bs4 import BeautifulSoup
import pytest

from backend.app.extractor import MetadataExtractor
from backend.app.source_adapters.techwithtim import (
    INCREMENTAL_CODE_BYTES, INCREMENTAL_CODE_LIMIT, INCREMENTAL_CODE_LINES,
    SUMMARY_LIMIT, TechWithTimLessonAdapter, _incremental_demonstration,
    bound_video_topic_summary,
)

FIXTURES = Path(__file__).parent / 'fixtures/techwithtim'
MANIFEST = json.loads((FIXTURES / 'public-dom-v2-source-manifest.json').read_text(encoding='utf-8'))


def retained(index=0):
    entry = MANIFEST['pages'][index]
    raw = (FIXTURES / entry['fixture']).read_bytes()
    assert sha256(raw).hexdigest() == entry['fixture_sha256']
    return BeautifulSoup(raw.decode(), 'html.parser'), entry['source_url']


def extract(soup=None):
    actual, url = retained()
    result = MetadataExtractor().extract(str(actual if soup is None else soup), url, '2026-10-18T00:00:00Z')
    result.update(resource_id='retained-own-increment', url=url, canonical_url=url)
    return result


def test_actual_own_event_and_four_key_examples_survive_initializer_and_260_chars():
    result = extract()
    summary = bound_video_topic_summary(result, result['evidence'])
    assert summary and len(summary) <= SUMMARY_LIMIT == 6000
    assert 'pygame.event.get()' in summary
    assert 'pygame.key.get_pressed()' in summary
    assert all(key in summary for key in ['K_LEFT', 'K_RIGHT', 'K_UP', 'K_DOWN'])
    # These are visible incremental teaching examples, not inventions from later code.
    assert 'Inside the loop we will implement' in summary
    assert 'Now we can start checking for events' in summary
    assert '```python\nimport pygame\npygame.init()' in summary
    assert 'KEYDOWN' not in summary and 'K_r' not in summary
    assert 'READY/PLAYING/WIN' not in summary and 'Full Code' not in summary
    assert result['chapters'] == []
    proof = json.loads(next(e['text'] for e in result['evidence'] if e.get('field') == 'video_evidence_status'))
    assert proof['summary_sha256'] == sha256(summary.encode()).hexdigest()
    assert proof['dom_witness']['notes_sha256'] == sha256(summary.encode()).hexdigest()
    assert proof['dom_witness']['notes_characters'] == len(summary)
    assert next(e['text'] for e in result['evidence'] if e.get('field') == 'video_topic_summary') == summary


@pytest.mark.parametrize('index,expected', [(0,'pygame.key.get_pressed()'), (1,'clock.tick(10)')])
def test_actual_fixture_bytes_stay_immutable_and_old_single_function_survives(index, expected):
    soup, url = retained(index)
    facts = TechWithTimLessonAdapter().extract(soup, url)
    summary = next(f.value for f in facts.fields if f.field == 'video_topic_summary')
    assert expected in summary
    retained(index)  # Recheck immutable fixture SHA after extraction.


def example(code, prose='Inside the loop we will implement checking for keyboard events.'):
    block = BeautifulSoup('<pre></pre>', 'html.parser').pre
    block.string = code
    return _incremental_demonstration(block, prose)


SHORT = 'import pygame\npygame.init()\nfor event in pygame.event.get():\n    print(event)'


@pytest.mark.parametrize('prose', [
    'Now we implement this Full Code program for reference.',
    'Now we implement this Complete Program for reference.',
    'We implement this in the previous lesson.',
    'We will implement this in the next lesson.',
    'Our prerequisites explain how we implement checking events.',
    'We do not teach how to implement these events.',
    'We never explain how to implement these events.',
    'We cannot teach how to implement these events.',
    'TODO: we will implement checking events in a future lesson.',
    'Here is some code.',
    'Related tutorials: we implement checking events.',
])
def test_non_teaching_or_no_explicit_introduction_does_not_admit_code(prose):
    assert example(SHORT, prose) is None


@pytest.mark.parametrize('code', [
    'import pygame\nclass Game:\n    def run(self):\n        pygame.event.get()',
    'import pygame\ndef main():\n    pygame.event.get()\nmain()',
    'import os\nimport pygame\npygame.event.get()',
    'from pygame import event\nevent.get()',
    'import pygame as pg\npg.event.get()',
    'pygame = fake\npygame.event.get()',
    '# Full Code\nimport pygame\npygame.event.get()',
    '# Previous lesson\nimport pygame\npygame.event.get()',
    '# TODO next lesson\nimport pygame\npygame.event.get()',
    'keys = keyboard.get_pressed()',
    'import pygame\npygame.event.get(',
])
def test_cumulative_program_foreign_owner_or_unparseable_code_is_not_newly_admitted(code):
    assert example(code) is None


@pytest.mark.parametrize('heading', ['Full Code','Complete Program','Final Code','Source Code',
                                    'Prerequisites','Previous Lesson','Next Lesson','Related Tutorials',
                                    'FullCode','CompleteProgram','Full Code:','Previous','Next','Prerequisites:'])
def test_scope_boundary_blocks_even_small_owned_import_example(heading):
    soup, url = retained()
    body = soup.select_one('div[class*="markdown__Container-"]')
    body.clear()
    own = BeautifulSoup('<p>In this lesson we explain the visible keyboard handling example.</p>'
                        '<p>We introduce the own event handling concepts for this lesson.</p>'
                        f'<h2>{heading}</h2>'
                        '<p>Inside the loop we will implement checking for keyboard events.</p><pre></pre>', 'html.parser')
    own.pre.string = SHORT
    for child in list(own.children):
        body.append(child)
    facts = TechWithTimLessonAdapter().extract(soup, url)
    summary = next(f.value for f in facts.fields if f.field == 'video_topic_summary')
    assert 'pygame.event.get' not in summary


@pytest.mark.parametrize('damage', ['sidebar','second_video','hidden_code','no_own_notes'])
def test_new_code_path_does_not_borrow_other_container_or_video(damage):
    soup, url = retained()
    body = soup.select_one('div[class*="markdown__Container-"]')
    content = soup.select_one('div[class*="tutoriallayout__Content-"]')
    if damage == 'sidebar':
        soup.append(body.extract())
    elif damage == 'second_video':
        body.append(deepcopy(content.iframe))
    elif damage == 'no_own_notes':
        body.decompose()
    else:
        for pre in body.find_all('pre'):
            pre['hidden'] = ''
    facts = TechWithTimLessonAdapter().extract(soup, url)
    if damage == 'hidden_code':
        summary = next(f.value for f in facts.fields if f.field == 'video_topic_summary')
        assert 'pygame.key.get_pressed' not in summary
    else:
        assert not facts.fields


def test_character_byte_line_limits_before_parsing():
    assert example(SHORT)
    assert example(SHORT + '\n#' + 'a' * INCREMENTAL_CODE_LIMIT) is None
    assert example(SHORT + '\n#' + '界' * 1400) is None  # <1800 codepoints, >4096 UTF-8 bytes
    assert INCREMENTAL_CODE_BYTES == 4096
    assert example(SHORT + '\n' + '\n'.join('x = 1' for _ in range(INCREMENTAL_CODE_LINES))) is None


def test_summary_is_bounded_whole_blocks_not_query_dependent_slicing():
    soup, url = retained()
    result = extract(soup)
    summary = result['video_topic_summary']
    assert len(summary) <= SUMMARY_LIMIT
    assert summary.count('```') % 2 == 0
    # No model/query/target is passed to extraction. The same page yields identical provenance.
    assert extract(soup)['video_topic_summary'] == summary
    damaged = deepcopy(result)
    damaged['video_topic_summary'] = summary.replace('pygame.event.get()', 'pygame.event.poll()', 1)
    assert bound_video_topic_summary(damaged, result['evidence']) is None
