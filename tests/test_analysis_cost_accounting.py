"""Generation-only totals must not conceal the real semantic-review cost."""
import json

from scripts.phase2_acceptance import new_analysis_events, summarize


def finished(call_id, task, completion, total):
    return {"event_type": "model_call_finished", "call_id": call_id, "task": task,
            "usage": {"completion_tokens": completion, "total_tokens": total}}


def report(events):
    return summarize({"model_events_source": "sanitized-observer.jsonl", "records": [{
        "status": "analyzed", "case_id": "unseen-dashboard",
        "analysis_submission_attempted": True, "client_analysis_elapsed_seconds": 24.26,
        "model_events": events}]})


def test_generation_and_review_costs_are_included_but_search_is_separate(tmp_path):
    # Observed usage values from the unseen Streamlit dashboard acceptance.
    events = [{"event_type": "model_call_started", "call_id": "g", "task": "project_analysis"},
              finished("g", "project_analysis", 2420, 5828),
              {"event_type": "model_call_started", "call_id": "r", "task": "project_analysis_review"},
              finished("r", "project_analysis_review", 10, 4137),
              finished("q", "query_expansion", 99, 999)]
    path = tmp_path / "observer.jsonl"
    path.write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")
    result = report(new_analysis_events(path, 0))
    assert result["provider_finished_events"] == 2
    assert result["provider_completion_tokens"] == 2430
    assert result["provider_total_tokens"] == 9965
    assert result["provider_counts_are_complete"] is True
    assert result["provider_usage_is_complete"] is True


def test_an_unfinished_review_is_not_complete_accounting():
    result = report([
        {"event_type": "model_call_started", "call_id": "g", "task": "project_analysis"},
        finished("g", "project_analysis", 2420, 5828),
        {"event_type": "model_call_started", "call_id": "r", "task": "project_analysis_review"},
    ])
    assert result["provider_counts_are_complete"] is False
    assert result["provider_usage_is_complete"] is False


def test_a_finished_review_without_usage_does_not_mean_zero_cost():
    events = [
        {"event_type": "model_call_started", "call_id": "g", "task": "project_analysis"},
        finished("g", "project_analysis", 2420, 5828),
        {"event_type": "model_call_started", "call_id": "r", "task": "project_analysis_review"},
        {"event_type": "model_call_finished", "call_id": "r", "task": "project_analysis_review",
         "outcome": "error", "usage": None},
    ]
    result = report(events)
    assert result["provider_counts_are_complete"] is True
    assert result["provider_usage_is_complete"] is False
