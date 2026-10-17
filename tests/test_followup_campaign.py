import pytest
from scripts.evaluate_evidence_followup import FollowupCampaign,FOLLOWUP_CAPS,section_counts
from backend.app.fetcher import FetchStopped

@pytest.mark.asyncio
async def test_followup_cap_rejects_before_durable_reservation(tmp_path):
    state={'counts':dict(FOLLOWUP_CAPS),'requests':[],'restrictions':{},'inflight':None,'active_case':'H06','cases':[]}
    campaign=FollowupCampaign(tmp_path,state)
    with pytest.raises(FetchStopped):await campaign.reserve('search_http',{})
    assert state['counts']==FOLLOWUP_CAPS and state['requests']==[]

def test_counts_keep_evidence_categories_separate():
    assert section_counts({'groups':[{'items':[1],'partial_items':[2,3],'review_items':[4]}]})=={'supported':1,'partial':2,'needs_review':1}
