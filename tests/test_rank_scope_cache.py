
import pytest
from backend.app import ranking as module




def test_token_cache_returns_independent_mutable_sets_and_clears_after_rank(monkeypatch):
    states = []
    def run(*args, **kwargs):
        first = module.tokens("pygame keyboard")
        first.add("pollution")
        assert "pollution" not in module.tokens("pygame keyboard")
        assert "pandas" in module.tokens("pandas CSV")
        assert "pygame" not in module.tokens("pandas CSV")
        states.append(module._RANK_CACHE.get())
    monkeypatch.setattr(module, "_rank_resource_uncached", run)
    for _ in range(2):
        module.rank_resource({}, {}, [], None)
        assert module._RANK_CACHE.get() is None
    assert states[0] is not states[1]


def test_url_cache_only_success_exact_input_and_uncached_invalid_or_nonstrings(monkeypatch):
    original = module._normalize_url_uncached
    calls = []
    def counted(value):
        calls.append(value)
        return original(value)
    monkeypatch.setattr(module, "_normalize_url_uncached", counted)
    def run(*args, **kwargs):
        for value in ("https://example.com/a", "https://example.com/b"):
            assert module.normalize_url(value) == module.normalize_url(value)
        for _ in range(2):
            for value in (None, "http://127.0.0.1/"):
                with pytest.raises(module.UnsafeURL): module.normalize_url(value)
        assert len(module._RANK_CACHE.get()[0]) == 2
    monkeypatch.setattr(module, "_rank_resource_uncached", run)
    module.rank_resource({}, {}, [], None)
    assert calls.count("https://example.com/a") == 1 and calls.count("https://example.com/b") == 1
    assert calls.count(None) == 2 and calls.count("http://127.0.0.1/") == 2
    assert module._RANK_CACHE.get() is None


def test_exception_always_resets_scope(monkeypatch):
    def run(*args, **kwargs):
        module.tokens("private per-call input")
        module.normalize_url("https://example.com/one")
        raise RuntimeError("synthetic failure")
    monkeypatch.setattr(module, "_rank_resource_uncached", run)
    with pytest.raises(RuntimeError): module.rank_resource({}, {}, [], None)
    assert module._RANK_CACHE.get() is None


def test_nested_rank_reuses_only_outer_scope(monkeypatch):
    states = []
    def run(*args, **kwargs):
        states.append(module._RANK_CACHE.get())
        if len(states) == 1: module.rank_resource({}, {}, [], None)
        assert module._RANK_CACHE.get() is states[0]
    monkeypatch.setattr(module, "_rank_resource_uncached", run)
    module.rank_resource({}, {}, [], None)
    assert states[0] is states[1] and module._RANK_CACHE.get() is None


def test_each_dictionary_is_bounded_and_no_scope_uses_original_behavior(monkeypatch):
    assert module.tokens("pandas CSV") == module._tokens_uncached("pandas CSV")
    def run(*args, **kwargs):
        for i in range(module._RANK_CACHE_LIMIT + 5):
            module.tokens(f"word{i}")
            module.normalize_url(f"https://example.com/{i}")
        assert [len(c) for c in module._RANK_CACHE.get()] == [4096, 4096]
    monkeypatch.setattr(module, "_rank_resource_uncached", run)
    module.rank_resource({}, {}, [], None)
    assert module._RANK_CACHE.get() is None


def test_owned_short_fixture_different_targets_and_page_urls_do_not_borrow_support():
    from copy import deepcopy
    import json
    from pathlib import Path
    from backend.app.models import SearchRequest
    fixture = Path(__file__).parent / "fixtures" / "rank_cache" / "owned-video.json"
    source = json.loads(fixture.read_text(encoding="utf-8"))
    resource, evidence = source["resource"], source["evidence"]
    request = SearchRequest(knowledge_points=["pygame keyboard movement"])
    for target, expected in (("keyboard movement", "supported"), ("pygame.quantumTeleport", "unknown")):
        point = {"knowledge_point_id": "p", "text": "pygame keyboard movement", "learning_targets": [target]}
        before = module._rank_resource_uncached(point, resource, evidence, request)
        after = module.rank_resource(point, resource, evidence, request)
        assert after == before
        assert next(x for x in after["subtopic_coverage"] if x["id"] == "learning_target_1")["status"] == expected
    foreign = deepcopy(resource)
    foreign["url"] = foreign["canonical_url"] = "https://www.bilibili.com/video/BV1other56789/"
    point = {"knowledge_point_id": "p", "text": "pygame keyboard movement", "learning_targets": ["keyboard movement"]}
    after = module.rank_resource(point, foreign, evidence, request)
    assert after == module._rank_resource_uncached(point, foreign, evidence, request)
    assert not after or all(x["status"] == "unknown" for x in after["subtopic_coverage"] if x["id"].startswith("learning_target_"))
    assert module._RANK_CACHE.get() is None
