"""Confirmed API query recovery preserves targets and rejects engine injection."""
from copy import deepcopy
import pytest
from backend.app.models import SearchRequest
from backend.app import queries as candidate

def request(targets, name="pandas 日期时间处理"):
    return SearchRequest(knowledge_points=[name], learning_targets={name: targets}, preferred_platforms=[])

@pytest.mark.parametrize("target,phrase", [
    ("pd.to_datetime(errors)", "pd.to_datetime errors"),
    ("head() 预览", "head 预览"),
    ("end < start", "end start"),
    ("DataFrame.to_csv(index=False)", "DataFrame.to_csv index False"),
    ("drop_duplicates(subset, keep)", "drop_duplicates subset keep"),
    ("row[columns] 与 {'index': value}", "row columns 与 index value"),
    ("value != -1", "value 1"),
    ("start/end 与 folder\\name", "start end 与 folder name"),
    ("@decorator(arg)", "decorator arg"),
    ('func("column", x>=0)', "func column x 0"),
])
def test_only_exact_confirmed_api_or_comparison_becomes_bounded_recall(target, phrase):
    req = request([target])
    before = deepcopy(req.model_dump())
    rows = candidate.gap_query_candidates("unit1", req.knowledge_points[0], req, [target])
    assert rows[0].query == "pandas " + phrase + " 视频教程"
    assert all(row.knowledge_point_id == "unit1" for row in rows)
    assert all("<" not in row.query and "=" not in row.query and "(" not in row.query for row in rows)
    assert req.model_dump() == before
    assert req.learning_targets[req.knowledge_points[0]] == [target]
    assert not hasattr(rows[0], "supporting_evidence_ids")

@pytest.mark.parametrize("value", [
    "pd.to_datetime(errors)", "head() 预览", "end < start", "index=False", "array[index]",
    "dict{key}", "foo;bar", "foo/bar", "foo\\bar", "@decorator", "-exclude",
    "https://example.com/video", "site:example.com", "!google pandas",
])
def test_unknown_expansions_cannot_use_confirmed_syntax_exception(value):
    req = request(["完全不同的已确认目标"])
    assert candidate.gap_query_candidates("id", req.knowledge_points[0], req, [value]) == []

@pytest.mark.parametrize("value", [
    "https://example.com/video", "www.example.com/video", "ftp://example.com/path",
    "site:example.com pandas", "filetype:pdf pandas", "intitle:pandas", "!google pandas",
])
def test_even_confirmed_targets_cannot_launder_urls_or_engine_commands(value):
    req = request([value])
    assert candidate.gap_query_candidates("id", req.knowledge_points[0], req, [value]) == []

def test_canonical_exact_key_and_exact_target_text_are_required():
    req = request(["head() 预览"])
    assert not candidate.gap_query_candidates("id", "pandas  日期时间处理", req, ["head() 预览"])
    assert not candidate.gap_query_candidates("id", req.knowledge_points[0], req, ["head() 预览 "])
    assert not candidate.gap_query_candidates("id", req.knowledge_points[0], req, ["HEAD() 预览"])

def test_existing_length_limit_still_rejects_long_confirmed_targets():
    req = request(["method(" + "parameter" * 10 + ")"])
    assert not candidate.gap_query_candidates("id", req.knowledge_points[0], req, list(req.learning_targets.values())[0])

def test_query_count_and_version_boundaries_do_not_increase():
    targets = [f"method_{i}(value)" for i in range(8)]
    name = "pandas 日期时间处理"
    req = SearchRequest(knowledge_points=[name], learning_targets={name: targets}, technical_version="2.2",
                        preferred_platforms=["bilibili", "icourse163", "xuetangx"])
    rows = candidate.gap_query_candidates("id", name, req, targets,
                                           open_course_domains=("example.org",))
    assert len(rows) <= 6
    assert all(" 2.2 " in row.query and row.knowledge_point_id == "id" for row in rows)
    assert not any("method_4" in row.query for row in rows)  # Existing four-part selection bound.
