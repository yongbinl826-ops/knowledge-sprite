"""Offline exact-name parser regression; no expanded learning-unit contract."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import pytest
from backend.app import ranking
from backend.app.models import SearchRequest

FIXTURE = Path(__file__).parent / "fixtures" / "professional_name_spacing.json"


def load_fixture():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload = json.dumps({"prior_own_lesson": data["prior_own_lesson"], "live": data["live"]},
                         ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(payload).hexdigest() == data["payload_canonical_sha256"]
    return data


@pytest.mark.parametrize("name", [
    "localStorage读写与JSON序列化", "localStorage 读写与JSON序列化",
    "localStorage 读写与 JSON序列化", "localStorage 读写与JSON 序列化",
    "localStorage 读写与 JSON 序列化",
])
def test_explicit_mixed_language_compound_ignores_optional_typographic_spaces(name):
    original = name
    plan = ranking.decompose_topic(name)
    assert plan["decomposition_status"] == "applied"
    assert plan["shared_context"] == ["localStorage"]
    assert ["".join(part["text"].split()) for part in plan["subtopics"]] == ["读写", "JSON序列化"]
    assert all(part["text"] in name for part in plan["subtopics"])
    assert name == original


@pytest.mark.parametrize("name,context,parts", [
    ("pandas列选择与DataFrame索引", ["pandas"], ["列选择", "DataFrame索引"]),
    ("Arduino按键检测与millis定时", ["Arduino"], ["按键检测", "millis定时"]),
    ("JavaScript事件处理与Promise并发", ["JavaScript"], ["事件处理", "Promise并发"]),
    ("Python文件读写与JSON序列化", ["Python"], ["文件读写", "JSON序列化"]),
])
def test_rule_is_grammar_not_one_project_or_owner(name, context, parts):
    plan = ranking.decompose_topic(name)
    assert plan["decomposition_status"] == "applied"
    assert plan["shared_context"] == context
    assert [p["text"] for p in plan["subtopics"]] == parts


@pytest.mark.parametrize("name", ["信号与门", "音乐和弦", "考试及格率", "JSON序列化", "输入输出"])
def test_lexical_words_and_single_topics_are_not_split(name):
    assert ranking._split_concepts(name) == [name]


@pytest.fixture(scope="module")
def prior_own_lesson():
    data = load_fixture()["prior_own_lesson"]
    return data["case"], data["row"]


@pytest.mark.parametrize("name", ["localStorage读写与JSON序列化", "localStorage 读写与JSON序列化", "localStorage 读写与 JSON 序列化"])
def test_actual_own_stringify_stays_partial_and_never_fills_readwrite(name, prior_own_lesson):
    case, row = prior_own_lesson
    point = {**case["product_results"]["groups"][0], "text": name}
    request = SearchRequest.model_validate({**case["request"], "knowledge_points": [name]})
    before = deepcopy((point, row))
    match = ranking.rank_resource(point, row["projected_resource"], row["all_evidence"], request,
                                  eligibility_evidence=row["all_evidence"])
    assert match and match["topic_evidence_status"] == "needs_review"
    # Topic evidence remains partial; the actual project's explicit native-web
    # requirement makes this Vue course a separate cross-stack reference.
    topic = ranking.assess_topic_evidence(point, row["projected_resource"], row["all_evidence"])
    assert topic and topic["topic_evidence_status"] == "partial"
    by_normalized = {"".join(part["text"].split()): part for part in topic["subtopic_coverage"]}
    assert by_normalized["读写"]["status"] == "unknown"
    assert by_normalized["JSON序列化"]["status"] == "supported"
    assert match["supporting_evidence_ids"] == topic["supporting_evidence_ids"]
    coverage = ranking.summarize_collection_coverage(name, [
        {"resource": row["projected_resource"], "match": match, "evidence": row["all_evidence"]}])
    assert coverage["status"] == "unknown"
    assert (point, row) == before


@pytest.mark.parametrize("heading", [
    "localStorage存储、JSON.parse", "localStorage存储、JSON介绍",
    "localStorage存储、JSON.stringify isn't covered",
    "localStorage存储、JSON.stringify will be covered next week",
    "localStorage存储、wrong.JSON.stringify",
])
def test_compact_target_does_not_relax_API_operation_or_scope(heading, prior_own_lesson):
    case, row = prior_own_lesson
    name = "localStorage 读写与JSON序列化"
    point = {**case["product_results"]["groups"][0], "text": name}
    resource, evidence = deepcopy(row["projected_resource"]), deepcopy(row["all_evidence"])
    chapter = deepcopy(resource["chapters"][0])
    chapter["title"] = heading
    resource["chapters"] = [chapter]
    observed = next(x for x in evidence if x.get("evidence_id") == chapter["evidence_id"])
    observed["text"] = heading
    match = ranking.rank_resource(point, resource, evidence,
        SearchRequest.model_validate({**case["request"], "knowledge_points": [name]}), eligibility_evidence=evidence)
    assert not match or not any("".join(p["text"].split()) == "JSON序列化" and p["status"] == "supported"
                                for p in match.get("subtopic_coverage", []))


def resource_evidence(pool, resource):
    targets = {ranking.normalize_url(resource[k]) for k in ("url", "canonical_url", "resolved_url") if resource.get(k)}
    ids = {v.get("evidence_id") for v in resource.get("field_provenance", {}).values() if isinstance(v, dict)}
    ids.update(ch.get("evidence_id") for ch in resource.get("chapters", []) if isinstance(ch, dict))
    def belongs(row):
        if row.get("evidence_id") in ids:
            return True
        try:
            return ranking.normalize_url(row.get("url", "")) in targets
        except Exception:
            return False
    return [row for row in pool["evidence"] if belongs(row)]


def live(name):
    data = load_fixture()["live"][name]
    return data["pool"], data["job"]


def test_new_live_JS_own_pages_stay_zero_no_IO_JSON_downgrade():
    pool, job = live("js-recovery-real-API")
    before = deepcopy((pool, job))
    fetched = [r for r in pool["resources"] if r.get("fetch_status") in {"fetched", "success"}]
    assert len(fetched) == 2
    for resource in fetched:
        evidence = resource_evidence(pool, resource)
        assert ranking.rank_resource(job["knowledge_points"][0], resource, evidence,
            SearchRequest.model_validate(job["request"]), eligibility_evidence=evidence) is None
    assert (pool, job) == before


def test_actual_pandas_catalog_positive_is_unchanged():
    pool, job = live("pandas-success-control-real")
    resource = next(r for r in pool["resources"] if r.get("fetch_status") == "fetched")
    evidence = resource_evidence(pool, resource)
    match = ranking.rank_resource(job["knowledge_points"][0], resource, evidence,
        SearchRequest.model_validate(job["request"]), eligibility_evidence=evidence)
    assert match and match["topic_evidence_status"] == "supported"
    # Existing course ranking may retain discovery IDs as well. Independently
    # require this positive to stand on its own page/catalog, not on search.
    own = [e for e in evidence if e.get("kind") in {"page", "catalog"}]
    own_assessment = ranking.assess_topic_evidence(job["knowledge_points"][0], resource, own)
    assert own_assessment and own_assessment["topic_evidence_status"] == "supported"
    assert all(next(e for e in own if e["evidence_id"] == i)["kind"] in {"page", "catalog"}
               for i in own_assessment["supporting_evidence_ids"])


def test_actual_Arduino_topic_support_does_not_gain_method_claims():
    pool, job = live("arduino-real")
    fetched = [r for r in pool["resources"] if r.get("fetch_status") == "fetched"]
    assert len(fetched) == 2
    for resource in fetched:
        evidence = resource_evidence(pool, resource)
        match = ranking.rank_resource(job["knowledge_points"][0], resource, evidence,
            SearchRequest.model_validate(job["request"]), eligibility_evidence=evidence)
        topic = ranking.assess_topic_evidence(job["knowledge_points"][0], resource, evidence)
        assert topic and topic["topic_evidence_status"] == "supported"
        expected = "needs_review" if "CubeMX" in resource.get("description", "") else "supported"
        assert match and match["topic_evidence_status"] == expected
        assert match["supporting_evidence_ids"] == topic["supporting_evidence_ids"]
        assert "nonblocking" not in match["recommendation_reason"].lower()
        assert "millis" not in match["recommendation_reason"]
        if expected == "needs_review":
            assert "project_stack_mismatch" in match["topic_match_rules"]
            coverage = ranking.summarize_collection_coverage(job["knowledge_points"][0]["text"], [
                {"resource": resource, "match": match, "evidence": evidence}])
            assert coverage["status"] == "unknown"
        else:
            assert "Uno" not in match["recommendation_reason"]
