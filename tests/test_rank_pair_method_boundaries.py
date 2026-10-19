"""Offline source-bound regressions; retained rows are not fresh model/playback passes."""
import asyncio
from copy import deepcopy
from pathlib import Path
import json
from unittest.mock import patch

import httpx
import pytest

from backend.app import teaching_match as match, teaching_review as review
from backend.app.learning_support import learning_skill_assessment
from backend.app.models import SearchRequest
from backend.app.ranking import rank_resource
from test_teaching_match import lesson, point, support, verdict, settings, envelope

FIXTURES = Path(__file__).parent / "fixtures/phase3_method_input"


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def skill_pair(skill="pandas 从内存对象读取 CSV", body="Reading CSV from a file-like object using pandas.", title="pandas input lesson"):
    p = point([skill], technology="pandas")
    r, e = lesson(body, title)
    pair = match.prepare_pair(p, r, e)
    assert pair is not None
    return p, r, e, pair


@pytest.mark.parametrize("index", [0, 1])
def test_retained_csv_title_does_not_declare_memory_input(index):
    retained = load("dashboard_memory_title_cards.json")
    item = retained["items"][index]
    p = retained["point"]
    pair = match.prepare_pair(p, item["resource"], item["evidence"], "intermediate")
    assert pair is not None
    old = item["match"]["teaching_support"][0]
    assert match.validate_decision(p, item["resource"], item["evidence"],
        {"fingerprint": pair["fingerprint"], "supports": [old]}, "intermediate") is None
    assert not match.literal_decision(pair)["supports"]
    # No old reviewed/hash-bound conclusion can bypass the revised method gate.
    sealed = review.sealed_decision({"fingerprint": pair["fingerprint"], "supports": [old]})
    assert review.validate_reviewed(p, item["resource"], item["evidence"], sealed, "intermediate") is None


@pytest.mark.parametrize("body", [
    "pandas 从内存对象读取 CSV，随后观察数据表类型。",
    "Reading CSV from a file-like object using pandas.",
    "Read CSV from a memory buffer using pandas.",
    "Read CSV in-memory using pandas.",
    "Reading CSV using StringIO as an in-memory stream.",
    "Reading CSV using BytesIO as a file-like object.",
    "Reading CSV from an uploaded file object using pandas.",
    "读取上传文件对象中的 CSV，而不是要求相同业务数据。",
    "无需磁盘临时文件，可从内存对象读取 CSV。",
])
def test_own_explicit_memory_equivalents_can_teach_another_project(body):
    p, r, e, pair = skill_pair(body=body)
    value = verdict(pair, [support(pair, body)])
    assert match.validate_decision(p, r, e, value) == value
    assert review.prepare_claims([pair], {pair["pair_id"]: value})[0]


@pytest.mark.parametrize("body,quote", [
    ("This lesson reads CSV files using pandas.", "This lesson reads CSV files using pandas."),
    ("Read CSV from disk using pandas.", "Read CSV from disk using pandas."),
    ("Writing CSV to a file-like object using pandas.", "Writing CSV to a file-like object using pandas."),
    ("This lesson does not teach reading CSV from memory.", "reading CSV from memory"),
    ("This lesson does not read CSV from memory.", "read CSV from memory"),
    ("Read CSV, not from memory.", "Read CSV"),
    ("Prerequisites: reading CSV from a file-like object.", "reading CSV from a file-like object"),
    ("Next lesson: reading CSV from a file-like object.", "reading CSV from a file-like object"),
    ("Read CSV files. See https://lessons.example/from-memory/file-like", "Read CSV files"),
    ("Read CSV files while observing memory usage.", "Read CSV files while observing memory usage."),
])
def test_medium_direction_and_own_quote_context_stay_necessary(body, quote):
    p, r, e, pair = skill_pair(body=body)
    assert match.validate_decision(p, r, e, verdict(pair, [support(pair, quote)])) is None


def test_generic_csv_reading_is_not_forced_to_use_a_memory_example():
    p, r, e, pair = skill_pair("pandas 读取 CSV", "This lesson teaches reading CSV files using pandas.")
    value = verdict(pair)
    assert match.validate_decision(p, r, e, value) == value


@pytest.mark.parametrize("skill,body,accepted", [
    ("pandas 从磁盘文件读取 CSV", "Read CSV from disk using pandas.", True),
    ("pandas 从磁盘文件读取 CSV", "Read CSV from a file-like object using pandas.", False),
    ("pandas 将 CSV 写入内存对象", "Writing CSV to a file-like object using pandas.", True),
    ("pandas 将 CSV 写入内存对象", "Reading CSV from a file-like object using pandas.", False),
])
def test_explicit_disk_and_output_direction_are_not_swapped(skill, body, accepted):
    p, r, e, pair = skill_pair(skill, body)
    value = match.validate_decision(p, r, e, verdict(pair))
    assert bool(value) is accepted


def test_memory_qualifier_does_not_invent_an_extra_requested_api_step():
    p, r, e, pair = skill_pair("pandas 从内存对象读取 CSV 并调用 validateColumns() 校验列")
    assert match.validate_decision(p, r, e, verdict(pair)) is None


def pairs(count=3):
    result=[]
    for i in range(count):
        r,e=lesson(url=f"https://lessons.example/own-{i}")
        r["resource_id"]=f"res-{i}"
        result.append(match.prepare_pair(point(knowledge_point_id=f"k-{i}"),r,e))
    assert all(result)
    return result


async def judged(pairs, output):
    calls=[]
    def handler(req):
        calls.append(req)
        return envelope(output)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result=await match.judge_batch(settings(),pairs,client)
    assert len(calls)==1
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize("damage", ["quote", "hash", "fingerprint", "basis"])
async def test_one_local_invalid_pair_does_not_discard_nine_good_pairs(damage):
    batch=pairs(10)
    values=[{"pair_id":p["pair_id"],**verdict(p)} for p in batch]
    bad=values[4]
    if damage=="quote":bad["supports"][0]["quote"]="Fabricated source sentence."
    elif damage=="hash":bad["supports"][0]["source_text_sha256"]="0"*64
    elif damage=="basis":bad["supports"][0]["basis"]="title"
    else:bad["fingerprint"]="0"*64
    result=await judged(batch,{"decisions":values})
    assert len(result)==9 and batch[4]["pair_id"] not in result
    assert all(result[p["pair_id"]]["supports"] for i,p in enumerate(batch) if i!=4)
    claims,mapping=review.prepare_claims(batch,result)
    assert len(claims)==9
    sealed=review.reviewed_decisions(batch,result,mapping,{c["claim_id"]:True for c in claims})
    assert len(sealed)==9 and batch[4]["pair_id"] not in sealed


@pytest.mark.asyncio
async def test_invalid_returned_pair_is_not_filled_as_valid_omission():
    batch=pairs(3)
    bad={"pair_id":batch[0]["pair_id"],**verdict(batch[0])}
    bad["supports"][0]["quote"]="Invented unrelated sentence."
    result=await judged(batch,{"decisions":[bad]})
    assert batch[0]["pair_id"] not in result
    assert result=={p["pair_id"]:{"fingerprint":p["fingerprint"],"supports":[]} for p in batch[1:]}


@pytest.mark.asyncio
@pytest.mark.parametrize("damage", ["pair-id", "duplicate-pair", "skill-id", "evidence-id", "duplicate-skill", "schema"])
async def test_global_schema_and_unknown_or_duplicate_ids_still_fail_whole_batch(damage):
    batch=pairs(3);values=[{"pair_id":p["pair_id"],**verdict(p)} for p in batch]
    if damage=="pair-id":values[0]["pair_id"]="pair_"+"0"*24
    elif damage=="duplicate-pair":values[1]=deepcopy(values[0])
    elif damage=="skill-id":values[0]["supports"][0]["skill_id"]="skill_6"
    elif damage=="evidence-id":values[0]["supports"][0]["evidence_id"]="unknown-own-id"
    elif damage=="duplicate-skill":values[0]["supports"]*=2
    else:values[0]["extra"]="unknown-global-field"
    assert await judged(batch,{"decisions":values})=={}


def test_retained_demo_score_fix_does_not_establish_unmentioned_skill_facets():
    retained=load("web_demo_title_card.json")
    p,r,e=deepcopy((retained["point"],retained["resource"],retained["evidence"]))
    request=SearchRequest.model_validate(retained["request"])
    pair=match.prepare_pair(p,r,e,request.student_level)
    # Controlled current-contract reseal of the retained exact claim only for
    # ranking isolation. It is not fresh semantic approval or a runtime write.
    core={"fingerprint":pair["fingerprint"],"supports":retained["decision"]["supports"]}
    p["_teaching_decision"]=review.sealed_decision(core)
    # This source only declares onclick binding in this exact quote; it does
    # not establish the actual complete button/click/callback skill. The
    # narrower own-method positive is tested in test_necessary_skill_components.
    assert match.validate_decision(p,r,e,core,request.student_level)["supports"]==[]
    assert learning_skill_assessment(p,r,e,request) is None
    assert rank_resource(p,r,e,request) is None
    old=deepcopy(p);old.pop("_teaching_decision");old.pop("learning_skills")
    assert rank_resource(old,r,e,request) is None
    # Historical review/version content cannot reactivate through the score fix.
    p["_teaching_decision"]=retained["decision"]
    assert rank_resource(p,r,e,request) is None


@pytest.mark.parametrize("damage", ["ads", "identity", "source"])
def test_score_change_does_not_remove_ad_identity_or_bound_source_gates(damage):
    r,e=lesson("This lesson teaches QuillFlow bounded queues.","QuillFlow bounded queues 招聘示例教程")
    p=point();request=SearchRequest(knowledge_points=[p["text"]],preferred_platforms=[])
    if damage=="ads":
        r["title"]+=" 招生 包就业"
        e[0]["text"]=r["title"]
    elif damage=="identity":r["video_evidence_status"]="search_discovered";r["field_provenance"].pop("video_evidence_status")
    else:e[0]["url"]="https://lessons.example/foreign"
    assert rank_resource(p,r,e,request) is None


def test_version_and_prompt_changes_invalidate_old_method_claims():
    assert match.VERSION=="source-skill-v4-necessary-components"
    assert review.VERSION=="teaching-claim-review-v3-necessary-components"
    for prompt in [match.SYSTEM_TEACHING_PROMPT,review.SYSTEM_REVIEW_PROMPT]:
        assert "medium" in prompt and "direction" in prompt
        assert "file-like" in prompt and "generic CSV" in prompt


def test_non_io_memory_topics_do_not_gain_an_unrequested_input_medium_gate():
    assert match._method_input_supported("QuillFlow memory allocation measurement", "This lesson measures memory allocations.")


def test_negated_disk_requirement_does_not_negate_the_necessary_memory_gate():
    body="无需磁盘临时文件，可从内存对象读取 CSV。"
    assert match._method_input_supported("pandas 从内存对象读取 CSV", body)
    p,r,e,pair=skill_pair(body=body)
    assert match.validate_decision(p,r,e,verdict(pair))["supports"]


def test_title_can_declare_the_memory_method_without_becoming_body_proof():
    title="pandas read CSV from a file-like object"
    p,r,e,pair=skill_pair(body="An overview of this focused lesson.",title=title)
    value=verdict(pair,[support(pair,title,basis="title")])
    assert match.validate_decision(p,r,e,value)==value
    assert value["supports"][0]["basis"]=="title"


def test_service_keeps_good_pair_for_mandatory_review_and_never_caches_bad_pair():
    from test_learning_support_service import setup
    service,job,resources,request=setup(count=2,resources_count=1)
    calls=[];reviews=[]
    async def fake_completion(config,system,payload,client=None,**kwargs):
        calls.append(payload)
        values=[]
        for index,p in enumerate(payload["pairs"]):
            source=next(row for row in p["observations"] if row["basis"]=="description")
            claim={"skill_id":p["skills"][0]["id"],"skill":p["skills"][0]["text"],
                "evidence_id":source["evidence_id"],"quote":source["segments"][0],"basis":source["basis"],
                "source_text_sha256":source["source_text_sha256"] if index else "0"*64}
            values.append({"pair_id":p["pair_id"],"fingerprint":p["fingerprint"],"supports":[claim]})
        return {"decisions":values}
    async def accept_review(config,claims):
        reviews.append(claims)
        return {row["claim_id"]:True for row in claims}
    with patch.object(match,"complete_json",fake_completion),patch.object(review,"review_batch",accept_review):
        asyncio.run(service._match_learning_skills(job,resources))
        assert len(calls)==1 and len(reviews)==1 and len(reviews[0])==1
        assert job["progress"]["teaching_match_calls"]==1
        assert job["progress"]["teaching_review_calls"]==1
        assert len(service.store.matches(job["job_id"]))==1
        assert service.store.connection.execute("SELECT COUNT(*) FROM cache").fetchone()[0]==1
        assert sum(bool(value.get("supports")) for perpoint in job["teaching_decisions"].values()
                   for value in perpoint.values())==1
        changes=service.store.connection.total_changes
        first=service.results(job["job_id"])
        assert service.results(job["job_id"])==first
        assert service.store.connection.total_changes==changes
        assert len(calls)==1 and len(reviews)==1


@pytest.mark.parametrize("body", [
    "无需内存对象读取 CSV，只介绍磁盘文件。",
    "不需要内存对象读取 CSV，演示磁盘读取 CSV。",
    "无需磁盘临时文件，不讲内存对象读取 CSV。",
    "无需磁盘临时文件，下一课演示内存对象读取 CSV。",
    "无需磁盘临时文件，先修要求为内存对象读取 CSV。",
    "Prerequisites:\n无需磁盘临时文件，可从内存对象读取 CSV。",
    "先修知识：\n无需磁盘临时文件，可从内存对象读取 CSV。",
    "本课不教内存对象读取 CSV，列校验，数据清洗。",
    "This lesson does not teach reading CSV from a file-like object, column checks, or data cleaning.",
    "无需安装教程，不讲内存对象读取 CSV，然后演示读取 CSV。",
])
def test_nonrequirement_exception_cannot_erase_target_negation_headers_or_lists(body):
    # Exercise actual quote + header + target-aware entry, not an assumed
    # lexical translation of the standalone veto's Chinese preposition.
    p=point(["pandas 从内存对象读取 CSV"],technology="pandas")
    r,e=lesson(body,"pandas input lesson")
    pair=match.prepare_pair(p,r,e)
    value=match.validate_decision(p,r,e,verdict(pair)) if pair else None
    assert value is None or not value["supports"]


@pytest.mark.parametrize("start", ["无需", "不需要", "无须", "不用"])
def test_only_unrelated_setup_nonrequirement_allows_explicit_own_positive(start):
    body=start+"磁盘临时文件，可从内存对象读取 CSV。"
    p,r,e,pair=skill_pair(body=body)
    assert match.validate_decision(p,r,e,verdict(pair))["supports"]


@pytest.mark.parametrize("clause", [
    "本课不教内存对象读取 CSV，列校验，数据清洗。",
    "无需磁盘临时文件，不讲内存对象读取 CSV。",
    "无需磁盘临时文件，下一课演示内存对象读取 CSV。",
    "无需内存对象读取 CSV，只介绍磁盘文件。",
])
def test_nonrequirement_projection_never_masks_explicit_target_or_strong_exclusion(clause):
    from backend.app.ranking import _unrelated_nonrequirement_scope,PARTIAL_SKILL_NONTEACHING
    assert _unrelated_nonrequirement_scope(clause,"内存对象读取 CSV",PARTIAL_SKILL_NONTEACHING)==clause


def test_nonrequirement_comma_list_without_explicit_positive_stays_whole():
    from backend.app.ranking import _unrelated_nonrequirement_scope,PARTIAL_SKILL_NONTEACHING
    clause="无需磁盘临时文件，内存对象读取 CSV，列校验。"
    assert _unrelated_nonrequirement_scope(clause,"内存对象读取 CSV",PARTIAL_SKILL_NONTEACHING)==clause
