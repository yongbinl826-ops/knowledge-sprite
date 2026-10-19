"""Offline scheduler behavior; lexical ordering never proves teaching coverage."""
from copy import deepcopy
from dataclasses import replace
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from backend.app import service as module, queries, teaching_match, teaching_review
from backend.app.models import SearchRequest
from test_learning_support_service import setup
from test_teaching_match import lesson


@pytest.fixture(autouse=True)
def offline_review(monkeypatch):
    async def accept(settings, claims):
        return {claim['claim_id']: True for claim in claims}
    monkeypatch.setattr(teaching_review, 'review_batch', accept)


async def search_schedule(service, job, *, public=True, primary_cost=1):
    service.settings = replace(service.settings, public_catalog_fallback=public, max_search_requests=30)
    service.public_catalog = SimpleNamespace(name="public_catalog") if public else None
    service.twt_catalog = SimpleNamespace(name="techwithtim_catalog", supports=lambda text: text.startswith("pygame ")) if public else None
    request = SearchRequest.model_validate(job["request"])
    lists = [queries.prioritize_video_entry_query(queries.generate_queries(p["knowledge_point_id"],p["text"],request)) for p in job["knowledge_points"]]
    schedule = queries.fair_queries(lists)
    original = [(q.knowledge_point_id,q.query,tuple(q.domain_filters)) for q in schedule]
    state = {"request":request,"points":job["knowledge_points"],"point_map":{p["knowledge_point_id"]:p for p in job["knowledge_points"]},
        "resources":{},"candidates":{},"candidate_groups":{p["knowledge_point_id"]:[] for p in job["knowledge_points"]},
        "ready":False,"search_finished":False,"changed":asyncio.Event(),"started":set(),"reserved":0,"cursor":0,"network_slots":asyncio.Semaphore(1)}
    called, cold = [], set()
    async def discover(query, request, original_point):
        service.provider.last_requests=[]
        public_source = module.JobService._public_provider(service, query)
        name = public_source.name if public_source else "primary"
        cost = primary_cost
        if public_source:
            cost = 0 if name in cold else 4 if name == "techwithtim_catalog" else 3
            cold.add(name)
        called.append((query.knowledge_point_id,query.query,tuple(query.domain_filters),name))
        for index in range(cost):
            await service.provider.request_hook()
            service.provider.last_requests.append({"status":"completed","http_status":200,"provider":"offline-counting"})
        return []
    service._discover=discover
    await service._search_queries(job,schedule,state)
    return original,called,state


def set_skills(job, counts, *, mixed=False):
    mapping={}
    for index,(point,count) in enumerate(zip(job["knowledge_points"],counts)):
        if mixed and index == 0:
            point.pop("learning_skills",None)
        else:
            point["learning_skills"]=[f"QuillFlow skill{i}" for i in range(1,count+1)]
            mapping[point["text"]]=point["learning_skills"]
    job["request"]["learning_skills"]=mapping


def test_full_public_frame_preserves_all_six_primary_skills_and_uses_actual_skill():
    service,job,_,_=setup(resources_count=0); set_skills(job,[6])
    original,called,state=asyncio.run(search_schedule(service,job))
    assert set(original) <= {row[:3] for row in called}
    public=[row for row in called if row[3]!="primary"]
    assert len(called)==7 and len(public)==1 and job["progress"]["queries_planned"]==7
    assert "skill" in public[0][1] and "项目阶段" not in public[0][1]


@pytest.mark.parametrize("mixed",[False,True])
def test_unequal_and_mixed_units_keep_primary_skill_queries_and_complete_public_frame(mixed):
    service,job,_,_=setup(count=2,resources_count=0); set_skills(job,[1,6],mixed=mixed)
    original,called,state=asyncio.run(search_schedule(service,job))
    new_pid=job["knowledge_points"][1]["knowledge_point_id"]
    assert {row for row in original if row[0]==new_pid} <= {row[:3] for row in called}
    public=[row for row in called if row[3]!="primary"]
    assert {row[0] for row in public}=={p["knowledge_point_id"] for p in job["knowledge_points"]}
    public_indices=[i for i,row in enumerate(called) if row[3]!="primary"]
    assert public_indices==list(range(min(public_indices),min(public_indices)+2))
    assert job["progress"]["queries_planned"]==len(original)+2


def test_reserve_distinct_shared_cold_sources_inside_thirty_requests_and_all_first_primaries():
    service,job,_,_=setup(count=5,resources_count=0); set_skills(job,[6]*5)
    # Use one actual category family per provider; its cold robot/index cost is
    # shared, rather than blindly multiplied by each point's count.
    p=job["knowledge_points"][4]; old=p["text"]; p["text"]="pygame test unit"
    job["request"]["knowledge_points"][4]=p["text"]
    job["request"]["learning_skills"][p["text"]]=job["request"]["learning_skills"].pop(old)
    original,called,state=asyncio.run(search_schedule(service,job,primary_cost=3))
    public=[row for row in called if row[3]!="primary"]
    assert len(public)==5 and {row[3] for row in public}=={"public_catalog","techwithtim_catalog"}
    assert len({row[3] for row in public[:2]}) == 2
    assert len({row[0] for row in called[:5]})==5
    assert job["progress"]["search_requests"]==30
    assert job.get("budget_limited") and any("预算" in w or "额度" in w for w in job["warnings"])


def test_pure_legacy_path_retains_existing_public_replacement_contract():
    service,job,_,_=setup(count=2,resources_count=0)
    job["request"]["learning_skills"]={}
    job["request"]["preferred_platforms"]=["bilibili"]
    for p in job["knowledge_points"]:p.pop("learning_skills",None)
    original,called,state=asyncio.run(search_schedule(service,job))
    assert len(called)==len(original)
    assert len([row for row in called if row[3]!="primary"])==2


@pytest.mark.parametrize("platforms", [["bilibili","icourse163","xuetangx"],["icourse163","bilibili","xuetangx"]])
@pytest.mark.parametrize("count",[3,4,6])
def test_bilibili_first_prefix_prioritizes_distinct_skills_before_repeated_channels(platforms,count):
    name="QuillFlow unit";skills=[f"QuillFlow skill{i}" for i in range(count)]
    request=SearchRequest(knowledge_points=[name],learning_skills={name:skills},preferred_platforms=platforms)
    rows=queries.prioritize_video_entry_query(queries.generate_queries("point",name,request))
    assert rows[0].domain_filters==["bilibili.com"]
    assert all(f"skill{i}" in rows[i].query for i in range(min(count,4)))
    if count==6:assert all(f"skill{i}" in row.query for i,row in enumerate(rows))


def test_without_bilibili_general_and_platform_assignment_unchanged():
    name="QuillFlow unit";skills=[f"QuillFlow skill{i}" for i in range(6)]
    request=SearchRequest(knowledge_points=[name],learning_skills={name:skills},preferred_platforms=["icourse163","xuetangx"])
    rows=queries.generate_queries("point",name,request)
    assert all(f"skill{i}" in row.query for i,row in enumerate(rows))


def test_four_inspection_slots_choose_distinct_skill_gain_not_four_duplicates():
    service,job,resources,_=setup(resources_count=0);set_skills(job,[6]);point=job["knowledge_points"][0]
    for index,skill in enumerate([point["learning_skills"][0]]*4+point["learning_skills"][1:]):
        rid=f"resource-{index}";r,e=lesson(f"This teaches {skill} with a worked example.",skill+" tutorial",url=f"https://lessons.example/{rid}")
        r.update(resource_id=rid,platform="other",language="en")
        for row in e:row["evidence_id"]+="-"+rid
        for origin in r["field_provenance"].values():origin["evidence_id"]+="-"+rid
        resources[rid]=r;service.store.save_resource(job["job_id"],r)
        for row in e:service.store.add_evidence(job["job_id"],rid,None,row)
    calls=[]
    async def judge(settings,pairs):
        calls.append(pairs)
        return {p["pair_id"]:teaching_match.literal_decision(p) for p in pairs}
    with patch.object(teaching_match,"judge_batch",judge):asyncio.run(service._match_learning_skills(job,resources))
    assert len(calls)==1 and len(calls[0])==4
    decisions=job["teaching_decisions"][point["knowledge_point_id"]]
    assert len({s["skill_id"] for d in decisions.values() for s in d["supports"]})==4
    assert len(set(decisions)&{f"resource-{i}" for i in range(4)})==1


def retained():
    return json.loads((Path(__file__).parent/"fixtures/phase3_prefetch/native-api-candidates.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("index",[0,1])
def test_actual_same_point_declared_native_api_can_enter_only_existing_metadata_probe(index):
    f=retained()[index];before=deepcopy(f)
    assert module.JobService._targeted_catalog_probe(f["point"],f["resource"],f["evidence"],{})
    state={"gap_probes_started":{f["point"]["knowledge_point_id"]:{"a","b","c","d"}}}
    assert not module.JobService._targeted_catalog_probe(f["point"],f["resource"],f["evidence"],state)
    assert f==before and f["resource"]["fetch_status"]=="not_fetched"


@pytest.mark.parametrize("mutation",["wrong-point","wrong-url","not-native","prefix","foreign-namespace","undeclared","public-directory"])
def test_api_prefetch_hint_cannot_borrow_other_scope_or_prefix(mutation):
    f=retained()[1];p,r,e=f["point"],f["resource"],f["evidence"]
    searches=[row for row in e if row.get("kind")=="search"]
    if mutation=="not-native":r["canonical_url"]=r["url"]="https://example.com/article"
    elif mutation=="undeclared":p["learning_skills"]=["QuillFlow queues"];p["learning_targets"]=[]
    for row in searches:
        if mutation=="wrong-point":row["knowledge_point_id"]="another-point"
        elif mutation=="wrong-url":row["url"]="https://www.bilibili.com/video/BV1C4411k7uw/"
        elif mutation=="prefix":row["title"]="localStorageWrapper tutorial"
        elif mutation=="foreign-namespace":row["title"]="Foreign.localStorage tutorial"
        elif mutation=="public-directory":row["source"]="public_catalog"
    assert not module.JobService._declared_api_probe(p,r,e)



@pytest.mark.parametrize("index",[0,1])
def test_native_api_prefetch_admission_does_not_create_teaching_support(index):
    f=retained()[index]; p,r,e=f["point"],f["resource"],f["evidence"]
    request=SearchRequest(knowledge_points=[p["text"]],learning_skills={p["text"]:p["learning_skills"]})
    before=module.rank_resource(p,r,e,request,require_type=False)
    assert module.JobService._targeted_catalog_probe(p,r,e,{})
    assert before is None and module.rank_resource(p,r,e,request,require_type=False) is None


@pytest.mark.parametrize("variant",["empty-query","ordinary-token","manual"])
def test_api_prefetch_does_not_generalize_plain_words_or_change_manual_probe(variant):
    f=retained()[1];p,r,e=f["point"],f["resource"],f["evidence"]
    if variant=="empty-query":
        for row in e:
            if row.get("kind")=="search":row["query"]=""
        assert not module.JobService._declared_api_probe(p,r,e)
    elif variant=="ordinary-token":
        p["learning_skills"]=["JavaScript Set 集合"];p["learning_targets"]=["Set"]
        for row in e:
            if row.get("kind")=="search":row["title"]="Swift Set 集合教程"
        assert not module.JobService._declared_api_probe(p,r,e)
    else:
        p.pop("learning_skills",None)
        assert not module.JobService._targeted_catalog_probe(p,r,e,{})
