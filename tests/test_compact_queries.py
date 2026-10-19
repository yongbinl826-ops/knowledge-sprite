"""Offline query-recall tests; no course data or network results are supplied."""
import pytest

from backend.app.models import SearchRequest
from backend.app.queries import compact_search_phrase, fair_queries, generate_queries


def test_original_recall_is_first_with_compact_second_and_versions_preserved():
    topic = "TypeScript 接口属性的可选定义与只读约束"
    request = SearchRequest(knowledge_points=[topic], technical_version="TypeScript 5")
    queries = generate_queries("point", topic, request, ["TypeScript optional readonly properties"],
                               open_course_domains=("ocw.mit.edu", "open.edu"))
    assert len(queries) == 6
    assert topic in queries[0].query
    assert queries[1].query == "TypeScript optional readonly properties TypeScript 5 视频教程"
    assert sum(not query.domain_filters for query in queries) == 2
    assert all("TypeScript 5" in query.query for query in queries)
    assert all(topic in query.query for query in [queries[0], *queries[2:]])
    assert all(query.knowledge_point_id == "point" for query in queries)


@pytest.mark.parametrize("phrase", ["Rust", "Rusty lifetime", "Python lifetime", "Rust site:example.org",
    "Rust !youtube lifetime", "Rust https://example.org", "Rust -ownership", 'Rust "ownership"',
    "Rust (ownership)", "Rust " + "a" * 81])
def test_compact_recall_rejects_broad_wrong_technology_and_search_commands(phrase):
    assert compact_search_phrase("Rust ownership and borrowing", [phrase]) is None


def test_exact_fallback_and_fair_scheduling_remain_available_without_model():
    topics = ["Python 文件路径操作", "SQL 分组聚合"]
    request = SearchRequest(knowledge_points=topics)
    groups = [generate_queries(str(index), topic, request) for index, topic in enumerate(topics)]
    assert [query.knowledge_point_id for query in fair_queries(groups)[:4]] == ["0", "1", "0", "1"]
    assert all(topic in query.query for topic, group in zip(topics, groups) for query in group)


def test_compact_phrase_does_not_replace_original_match_identity():
    topic = "Python 文件路径操作"
    request = SearchRequest(knowledge_points=[topic])
    queries = generate_queries("unchanged-id", topic, request, ["Python pathlib 路径"])
    assert queries[0].query.startswith(topic)
    assert queries[1].query.startswith("Python pathlib 路径")
    assert request.knowledge_points == [topic]
    assert {query.knowledge_point_id for query in queries} == {"unchanged-id"}
