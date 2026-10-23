"""Independent fixed multilingual oracle on preserved real source metadata."""
from pathlib import Path
from copy import deepcopy
import json
import pytest
from backend.app.models import SearchRequest
from backend.app.related_recommendations import related_recommendation

DATA=json.loads((Path(__file__).parent/'fixtures/related-policy-20261020/bilingual-reference-cases.json').read_text('utf8'))
PAGES={row['key']:row for row in DATA['pages']}
PAIRS=[row for row in DATA['pairs'] if row['expected_related_reference'] is not None]

@pytest.mark.parametrize('pair',PAIRS,ids=[r['point_key']+'-'+r['source_key'] for r in PAIRS])
def test_preserved_public_metadata_against_independent_relevance_oracle(pair):
    page=PAGES[pair['source_key']];before=deepcopy(page)
    point={'knowledge_point_id':pair['point_key'],**DATA['points'][pair['point_key']]}
    request=SearchRequest(knowledge_points=[point['text']],topic_technologies={point['text']:point['technology']})
    result=related_recommendation(point,page['resource'],page['evidence'],request)
    assert bool(result) is pair['expected_related_reference'],pair['reason']
    assert page==before
    if result:
        assert result['reference']['exact_teaching_verified'] is False
        assert set(result['reference']['evidence_ids'])=={e['evidence_id'] for e in result['evidence']}
        assert all(e in page['evidence'] for e in result['evidence'])
