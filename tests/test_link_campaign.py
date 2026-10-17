import json
import time
from datetime import datetime, timezone
from types import SimpleNamespace
import pytest
from scripts.evaluate_link_discovery import Campaign, assert_resume_safe, CAPS, campaign_lock, save, prepare_repeat_rows
from pathlib import Path
from backend.app.providers import SearXNGProvider, SearchError
from backend.app.config import Settings

def state():
    return {'counts':dict.fromkeys(CAPS,0),'restrictions':{},'requests':[], 'inflight':None,
        'active_case':'D01','cases':[{'id':f'D{i:02}','state':'pending'} for i in range(1,41)]}

def service():
    return SimpleNamespace(provider=SearXNGProvider(Settings()),official_fallback=None,
        fetcher=SimpleNamespace(_blocked_hosts={},_paused_until={}))

def test_holdout_repeat_requires_explicit_consumption_and_retains_prior():
    row={'id':'H14','state':'terminal','purpose':'holdout','split':'holdout','language':'en','negative_control':False,'request_sha256':'same','job_id':'original'}
    with pytest.raises(AssertionError,match='only_consumed'):prepare_repeat_rows([row],{'H14'},set())
    result=prepare_repeat_rows([row],{'H14'},{'H14'})
    assert row['state']=='terminal' and row['purpose']=='holdout'
    assert result[0]['purpose']=='development_consumed' and result[0]['state']=='pending'
    assert result[0]['previous_attempts']==[row]
    with pytest.raises(AssertionError,match='must_be_repeated'):prepare_repeat_rows([row],set(),{'H14'})
    with pytest.raises(AssertionError,match='positive'):prepare_repeat_rows([{**row,'negative_control':True}],{'H14'},{'H14'})

def test_checkpoint_fail_closed_and_config_drift():
    data=state();assert_resume_safe(data,{'hash':'a'},{'hash':'a'})
    with pytest.raises(RuntimeError,match='drift'):assert_resume_safe(data,{'hash':'a'},{'hash':'b'})
    data['inflight']=1
    with pytest.raises(RuntimeError,match='uncertain'):assert_resume_safe(data,{}, {})
    data['inflight']=None;data['cases'][2]['state']='started'
    with pytest.raises(RuntimeError,match='uncertain'):assert_resume_safe(data,{}, {})

def test_campaign_lock_rejects_concurrent_writer(tmp_path):
    with campaign_lock(tmp_path):
        with pytest.raises(OSError):
            with campaign_lock(tmp_path):pass
    with campaign_lock(tmp_path):pass

def test_windows_reader_collision_retries_only_atomic_replace(tmp_path,monkeypatch):
    original=Path.replace;attempts=[]
    def transient(path,target):
        attempts.append(1)
        if len(attempts)<3:raise PermissionError('synthetic reader collision')
        return original(path,target)
    monkeypatch.setattr(Path,'replace',transient)
    save(tmp_path/'state.json',{'reserved_http':2})
    assert len(attempts)==3
    assert json.loads((tmp_path/'state.json').read_text())=={'reserved_http':2}

@pytest.mark.asyncio
async def test_second_instance_restores_denial_before_any_transport(tmp_path):
    campaign=Campaign(tmp_path,state());campaign.service=service()
    campaign.service.provider.access_denied=True;campaign.snapshot()
    restored=Campaign(tmp_path,json.loads((tmp_path/'checkpoint.json').read_text(encoding="utf-8")))
    restored.service=service();restored.restore()
    called=[]
    async def forbidden(*args,**kwargs):called.append(1)
    restored.service.provider._bounded_response=forbidden
    with pytest.raises(SearchError):await restored.service.provider.request('GET','http://test.invalid')
    assert called==[] and len(restored.state['cases'])==40

def test_unknown_timeout_not_latched_and_real_engine_restriction_persists(tmp_path):
    campaign=Campaign(tmp_path,state());campaign.service=service();provider=campaign.service.provider
    provider._failures({'unresponsive_engines':[['bing','timeout'],['duckduckgo videos','arbitrary']]})
    campaign.snapshot();assert campaign.state['restrictions']=={}
    provider.last_warnings=provider._failures({'unresponsive_engines':[['bing','CAPTCHA']]})
    campaign.snapshot()
    saved=json.loads((tmp_path/'checkpoint.json').read_text(encoding="utf-8"))
    assert saved['restrictions']['engine:bing']['evaluation_latched']
    assert saved['restrictions']['engine:bing']['warnings'][0]['reason_code']=='captcha'
    restored=Campaign(tmp_path,saved);restored.service=service();restored.restore()
    assert restored.service.provider.engine_pauses['bing']>0

def test_rate_limit_expiry_and_repeat_429_are_persisted(tmp_path):
    campaign=Campaign(tmp_path,state());campaign.service=service()
    campaign.service.provider.paused_until=time.monotonic()+120
    campaign.snapshot();record=campaign.state['restrictions']['search_service_pause']
    assert not record['evaluation_latched']
    resumed=Campaign(tmp_path,json.loads((tmp_path/'checkpoint.json').read_text(encoding='utf-8')))
    resumed.service=service();resumed.restore()
    assert 119<resumed.service.provider.paused_until-time.monotonic()<=120
    resumed.state['restrictions']['search_service_pause']['retry_after_expiry_utc']=datetime.fromtimestamp(time.time()-1,timezone.utc).isoformat()
    resumed.restore();assert resumed.service.provider.paused_until<=time.monotonic()
    resumed.service.provider.paused_until=time.monotonic()+240;resumed.snapshot()
    assert len(resumed.state['restrictions']['search_service_pause']['history'])==1
    assert datetime.fromisoformat(resumed.state['restrictions']['search_service_pause']['retry_after_expiry_utc']).timestamp()>time.time()+239

def test_engine_soft_limit_upgrades_to_permanent_denial_without_downgrade(tmp_path):
    campaign=Campaign(tmp_path,state());campaign.service=service();p=campaign.service.provider
    p.last_warnings=p._failures({'unresponsive_engines':[['bing','too many requests']]})
    campaign.snapshot();assert not campaign.state['restrictions']['engine:bing']['evaluation_latched']
    p.last_warnings=p._failures({'unresponsive_engines':[['bing','CAPTCHA']]})
    campaign.snapshot();assert campaign.state['restrictions']['engine:bing']['evaluation_latched']
    p.last_warnings=p._failures({'unresponsive_engines':[['bing','too many requests']]})
    campaign.snapshot();assert campaign.state['restrictions']['engine:bing']['evaluation_latched']
    assert campaign.state['restrictions']['engine:bing']['warnings'][0]['reason_code']=='captcha'

@pytest.mark.asyncio
async def test_budget_reserved_durably_before_delegate_and_not_refunded(tmp_path):
    campaign=Campaign(tmp_path,state());campaign.service=service()
    async def broken():
        saved=json.loads((tmp_path/'checkpoint.json').read_text(encoding="utf-8"))
        assert saved['counts']['search_http']==1 and saved['inflight']==1
        raise ValueError('fixture')
    with pytest.raises(ValueError):await campaign.transport('search_http',{},broken)
    assert campaign.state['counts']['search_http']==1
    assert campaign.state['requests'][0]['status']=='exception'
    assert campaign.state['inflight'] is None

