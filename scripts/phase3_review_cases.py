"""Independent, local-file-only preparation/validation of manual phase-3 reviews.

No application/ranking imports, HTTP, models, browser, subprocess or database.
The script collects raw evidence and checks human review completeness/anchors;
it never assigns semantic scores from keywords or turns a template into a pass.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = ROOT / "evidence/phase3-audit/unseen-review-plan.json"
MAX_JSON_BYTES = 32 * 1024 * 1024
SECTIONS = ("items", "partial_items", "review_items", "platform_items", "partial_platform_items", "review_platform_items")
DECISIONS = {"pending", "taught", "known_reuse", "integration_reuse", "missing", "rejected"}
CARD_DECISIONS = {"pending", "specific_teaching", "topical_partial", "prerequisite_only", "unverified_lead", "irrelevant", "misleading"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def local_json_path(value: str | Path) -> Path:
    path = Path(value)
    path = (ROOT / path).resolve() if not path.is_absolute() else path.resolve()
    if not path.is_relative_to(ROOT) or path.suffix.casefold() != ".json":
        raise ValueError("Only explicit workspace JSON files are supported")
    return path


def load_json(value: str | Path) -> tuple[Path, Any]:
    path = local_json_path(value)
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError("JSON exceeds reviewer size limit")
    return path, json.loads(path.read_text(encoding="utf-8"))


def write_new(value: str | Path, data: Any) -> Path:
    path = local_json_path(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    # No overwrite of raw input, old reviews, or a prior uncertain run.
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return path


def get_case(plan: dict, case_id: str) -> dict:
    matches = [case for case in plan["cases"] if case["case_id"] == case_id]
    if len(matches) != 1:
        raise ValueError("Case must be an exact unique preregistered case_id")
    return matches[0]


def analysis_from(data: dict) -> dict | None:
    if isinstance(data.get("version"), dict) and isinstance(data["version"].get("analysis"), dict):
        return data["version"]["analysis"]
    if isinstance(data.get("analysis"), dict):
        return data["analysis"]
    if isinstance(data.get("knowledge_points"), list) and "scope" in data:
        return data
    return None  # Never select one record from a multi-case/version container.


def input_from(data: dict) -> dict | None:
    if isinstance(data.get("version"), dict) and isinstance(data["version"].get("input"), dict):
        return data["version"]["input"]
    for field in ("input", "project_input", "project"):
        if isinstance(data.get(field), dict) and "requirements" in data[field]:
            return data[field]
    return None


def groups_from(data: dict) -> list[tuple[str, str, dict]]:
    groups = []
    if isinstance(data.get("points"), list):
        for index, point in enumerate(data["points"]):
            if isinstance(point, dict) and isinstance(point.get("result"), dict):
                groups.append((str(point.get("project_knowledge_point_id") or point.get("knowledge_point_id") or index), f"/points/{index}/result", point["result"]))
    elif isinstance(data.get("groups"), list):
        for index, group in enumerate(data["groups"]):
            if isinstance(group, dict):
                groups.append((str(group.get("knowledge_point_id") or index), f"/groups/{index}", group))
    return groups


def raw_candidates(data: dict) -> list[dict]:
    candidates: dict[tuple[str, str], dict] = {}
    for unit_id, pointer, group in groups_from(data):
        for section in SECTIONS:
            collection = group.get(section, [])
            buckets = collection.items() if isinstance(collection, dict) else [("all", collection)]
            for platform, items in buckets:
                if not isinstance(items, list):
                    continue
                for index, item in enumerate(items):
                    if not isinstance(item, dict) or not isinstance(item.get("resource"), dict):
                        continue
                    resource = item["resource"]
                    rid = resource.get("resource_id")
                    if not isinstance(rid, str) or not rid:
                        continue
                    key = unit_id, rid
                    occurrence = f"{pointer}/{section}/{platform}/{index}" if isinstance(collection, dict) else f"{pointer}/{section}/{index}"
                    if key in candidates:
                        candidates[key]["occurrences"].append(occurrence)
                        continue
                    evidence = item.get("evidence", [])
                    candidates[key] = {
                        "candidate_id": unit_id + "::" + rid, "unit_id": unit_id,
                        "resource_id": rid, "occurrences": [occurrence],
                        "raw_resource": resource, "raw_match": item.get("match", {}),
                        "own_observations_not_auto_verified": [row for row in evidence if isinstance(row, dict) and row.get("kind") in {"page", "catalog"}],
                        "search_observation_count_not_teaching": sum(isinstance(row, dict) and row.get("kind") == "search" for row in evidence),
                        "manual_scope_decision": "pending", "manual_student_fit": "pending",
                        "manual_reason": "", "limits_or_access_conditions": [],
                    }
    return list(candidates.values())


def prepare(plan_path: str | Path, case_id: str, result_path: str | Path, analysis_path: str | Path | None = None) -> dict:
    pp, plan = load_json(plan_path)
    case = get_case(plan, case_id)
    rp, raw = load_json(result_path)
    if not isinstance(raw, dict):
        raise ValueError("Result must be a JSON object")
    ap, analysis_raw = load_json(analysis_path) if analysis_path else (rp, raw)
    analysis = analysis_from(analysis_raw)
    if analysis is None:
        raise ValueError("Provide a single analysis object, analysis wrapper or project-results version.analysis")
    project_input = input_from(analysis_raw) or input_from(raw)
    units = analysis.get("knowledge_points")
    if not isinstance(units, list):
        raise ValueError("Analysis has no knowledge_points list")
    candidates = raw_candidates(raw)
    return {
        "review_schema": "phase3-independent-manual-review-v1",
        "case_id": case_id, "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "local_raw_evidence_template_no_quality_verdict",
        "effects": {"http_requests": 0, "model_calls": 0, "database_connections": 0, "source_edits": 0},
        "sources": {"plan": {"path": str(pp.relative_to(ROOT)), "sha256": digest(pp)},
                    "result": {"path": str(rp.relative_to(ROOT)), "sha256": digest(rp)},
                    "analysis": {"path": str(ap.relative_to(ROOT)), "sha256": digest(ap)}},
        "input_continuity": {"expected_input": case["input"], "actual_input": project_input,
                             "expected_sha256": case["input_sha256"],
                             "actual_sha256": json_digest(project_input) if project_input else None,
                             "exact_match": project_input == case["input"], "manual_difference_explanation": ""},
        "analysis_units": [{"unit_id": point.get("id"), "name": point.get("name"), "technology": point.get("technology"),
                            "learning_skills": point.get("learning_skills", []), "concepts": point.get("concepts", []),
                            "project_task": point.get("project_task"), "practice_check": point.get("practice_check"),
                            "prerequisite_ids": point.get("prerequisite_ids", []),
                            "manual_role": "pending", "manual_skill_fit_notes": ""} for point in units if isinstance(point, dict)],
        "skill_assessments": [{"required_skill_id": skill["id"], "required_skill": skill["skill"],
                               "method_semantics": skill["method_semantics"], "decision": "pending",
                               "generated_unit_ids": [], "source_assignments": [],
                               "reuse_skill_ids": [], "background_quote": "", "manual_reason": ""} for skill in case["skills"]],
        "candidate_reviews": candidates,
        "counts_not_quality": {"analysis_units": len(units), "unit_resource_pairs": len(candidates),
                               "unique_resource_ids": len({c["resource_id"] for c in candidates})},
        "source_assignment_shape": {"candidate_id": "copy exact candidate_id", "evidence_id": "copy actual own observation id",
                                    "quote_field": "text or title", "quote": "continuous exact original text",
                                    "teaches_this_skill": "human reason; no inference from search/title alone beyond actual scope",
                                    "evidence_tier": "own_title_topic / own_description_or_catalog / own_teaching_excerpt",
                                    "unknown_or_not_taught": []},
        "project_practice_review": {"all_constraints_preserved": None, "notes": "", "missing_or_changed_requirements": []},
        "hard_gates": {gate: None for gate in plan["hard_gates"]},
        "dimension_scores": {dimension["id"]: None for dimension in plan["scoring"]["dimensions"]},
        "dimension_reasons": {dimension["id"]: "" for dimension in plan["scoring"]["dimensions"]},
        "issues": [], "latency_and_cost": {"generation_seconds": None, "search_seconds": None, "first_useful_seconds": None,
            "generation_calls": None, "review_calls": None, "completion_tokens": None, "total_tokens": None,
            "source_reference": "", "unknown_values_remain_unknown": True},
        "overall": {"decision": "unreviewable", "weighted_score": None, "human_review_completed": False,
                    "reason": "Template only; every pending decision needs independent manual source/skill review."},
    }


def validate_review(review: dict, fresh: dict, plan: dict) -> dict:
    """Check raw anchors and completeness, never infer that a source teaches."""
    case = get_case(plan, review.get("case_id", ""))
    if review.get("sources") != fresh["sources"]:
        raise ValueError("Review source path/hash binding differs from the current explicit raw files")
    candidates = {candidate["candidate_id"]: candidate for candidate in fresh["candidate_reviews"]}
    card_reviews = review.get("candidate_reviews", [])
    cards = {row.get("candidate_id"): row for row in card_reviews if isinstance(row, dict)}
    if len(cards) != len(card_reviews) or set(cards) != set(candidates):
        raise ValueError("Every exact case candidate must be reviewed once")
    card_incomplete = []
    for cid, card in cards.items():
        if card.get("manual_scope_decision") not in CARD_DECISIONS:
            raise ValueError("Unknown candidate-scope decision")
        if (card.get("manual_scope_decision") == "pending" or card.get("manual_student_fit") in {None, "", "pending"}
                or not str(card.get("manual_reason", "")).strip()):
            card_incomplete.append(cid)
    expected = {skill["id"] for skill in case["skills"]}
    assessments = review.get("skill_assessments", [])
    by_id = {row.get("required_skill_id"): row for row in assessments if isinstance(row, dict)}
    if len(by_id) != len(assessments) or set(by_id) != expected:
        raise ValueError("Review must assess each exact preregistered skill once")
    unit_ids = {unit["unit_id"] for unit in fresh["analysis_units"]}
    incomplete = []
    for sid, assessment in by_id.items():
        decision = assessment.get("decision")
        if decision not in DECISIONS:
            raise ValueError("Unknown skill decision")
        if not set(assessment.get("generated_unit_ids", [])).issubset(unit_ids):
            raise ValueError("Unknown generated unit reference")
        if decision == "pending" or not assessment.get("manual_reason", "").strip():
            incomplete.append(sid)
        assignments = assessment.get("source_assignments", [])
        if decision == "taught" and not assignments:
            raise ValueError("A taught decision needs an exact own-source assignment")
        for assignment in assignments:
            candidate = candidates.get(assignment.get("candidate_id"))
            if candidate is None:
                raise ValueError("Teaching assignment uses a candidate absent from this case's result")
            if cards[candidate["candidate_id"]].get("manual_scope_decision") not in {"specific_teaching", "topical_partial"}:
                raise ValueError("A prerequisite, lead, irrelevant or unreviewed candidate cannot be counted as current teaching")
            observations = [row for row in candidate["own_observations_not_auto_verified"]
                            if row.get("evidence_id") == assignment.get("evidence_id")]
            field = assignment.get("quote_field")
            quote = assignment.get("quote")
            if field not in {"text", "title"} or not isinstance(quote, str) or not quote.strip():
                raise ValueError("Teaching assignment needs an exact nonempty original quote")
            if not any(isinstance(row.get(field), str) and quote in row[field] and row.get("source") not in {"search", "search_template"} for row in observations):
                raise ValueError("Quote is not an exact own page/catalog observation; search evidence cannot become teaching")
            if not str(assignment.get("teaches_this_skill", "")).strip():
                raise ValueError("Manual teaching-scope explanation is required")
        if decision == "known_reuse":
            quote = assessment.get("background_quote", "")
            background = case["student_fit"]["background_verbatim"]
            if not isinstance(quote, str) or not quote.strip() or quote not in background:
                raise ValueError("Known reuse needs an exact explicit-background quote")
        if decision == "integration_reuse":
            refs = assessment.get("reuse_skill_ids", [])
            if not refs or not set(refs).issubset(expected - {sid}):
                raise ValueError("Integration reuse needs other exact skill references")
    visiting, visited = set(), set()
    def visit(sid):
        if sid in visiting:
            raise ValueError("Integration reuse contains a cycle")
        if sid in visited:
            return
        visiting.add(sid)
        for ref in by_id[sid].get("reuse_skill_ids", []) if by_id[sid].get("decision") == "integration_reuse" else []:
            visit(ref)
        visiting.remove(sid); visited.add(sid)
    for sid in expected:
        visit(sid)
    gates = review.get("hard_gates", {})
    if set(gates) != set(plan["hard_gates"]) or any(value is not None and type(value) is not bool for value in gates.values()):
        raise ValueError("Every exact hard gate must be pending or a manual boolean")
    scores = review.get("dimension_scores", {})
    dimensions = plan["scoring"]["dimensions"]
    if set(scores) != {dimension["id"] for dimension in dimensions}:
        raise ValueError("Every exact scoring dimension is required")
    if any(value is not None and (type(value) is not int or not 0 <= value <= 4) for value in scores.values()):
        raise ValueError("Scores must be manual integer0..4 or pending")
    practice = review.get("project_practice_review", {})
    preserved = practice.get("all_constraints_preserved")
    if preserved is not None and type(preserved) is not bool:
        raise ValueError("Practice preservation must be a manual boolean or pending")
    if preserved and practice.get("missing_or_changed_requirements"):
        raise ValueError("Unresolved changed project requirements contradict full preservation")
    if gates.get("input_and_original_scope_preserved") and not fresh["input_continuity"]["exact_match"]:
        if not str(review.get("input_continuity", {}).get("manual_difference_explanation", "")).strip():
            raise ValueError("Input differences require an explicit manual comparison before a passing scope gate")
    complete = not incomplete and not card_incomplete and all(type(value) is bool for value in gates.values()) and all(type(value) is int for value in scores.values())
    complete = complete and preserved is not None and review.get("overall", {}).get("human_review_completed") is True
    complete = complete and all(str(review.get("dimension_reasons", {}).get(dimension["id"], "")).strip() for dimension in dimensions)
    weighted = round(sum(scores[dimension["id"]] / 4 * dimension["weight"] for dimension in dimensions), 2) if complete else None
    def covered(sid):
        row = by_id[sid]
        return row["decision"] in {"taught", "known_reuse"} or row["decision"] == "integration_reuse" and all(covered(ref) for ref in row["reuse_skill_ids"])
    missing = [sid for sid in expected if not covered(sid)]
    blocking = any(issue.get("severity") in {"high", "medium"} and not issue.get("resolved", False) for issue in review.get("issues", []) if isinstance(issue, dict))
    blocking = blocking or any(card.get("manual_scope_decision") in {"irrelevant", "misleading"} for card in cards.values())
    if not complete:
        decision = "unreviewable"
    elif not all(gates.values()) or blocking or not review["project_practice_review"]["all_constraints_preserved"]:
        decision = "failed"
    elif not missing and weighted >= 80:
        decision = "accepted_useful"
    else:
        decision = "partially_useful"
    return {"schema_and_quote_anchors_valid": True, "manual_review_complete": complete,
            "decision_consistent_with_manual_values": decision, "weighted_manual_score": weighted,
            "skills_still_missing_or_rejected": sorted(missing), "pending_skill_decisions": sorted(incomplete),
            "pending_candidate_decisions": sorted(card_incomplete),
            "automation_scope": "Only completeness, ID/hash/quote anchors and arithmetic; actual teaching, identity, fit and scope remain manual judgments.",
            "student_project_executed": False, "new_network_model_or_database_requests": 0}


def self_test() -> dict:
    """In-memory negative checks; no fake live result is written as evidence."""
    mini = {"cases": [{"case_id": "x", "skills": [{"id": "s1"}], "student_fit": {"background_verbatim": "会数组"}}],
            "hard_gates": ["scope"], "scoring": {"dimensions": [{"id": "fit", "weight": 100}]}}
    candidate = {"candidate_id": "k1::r1", "own_observations_not_auto_verified": [
        {"evidence_id": "e1", "kind": "page", "source": "own.notes", "text": "This lesson explains event-driven state updates."}]}
    fresh = {"sources": {}, "analysis_units": [{"unit_id": "k1"}], "candidate_reviews": [candidate], "input_continuity": {"exact_match": True}}
    review = {"case_id": "x", "sources": {}, "skill_assessments": [{"required_skill_id": "s1", "decision": "pending", "manual_reason": "", "source_assignments": []}],
              "hard_gates": {"scope": None}, "dimension_scores": {"fit": None}, "candidate_reviews": [{"candidate_id": "k1::r1", "manual_scope_decision": "pending"}]}
    assert validate_review(review, fresh, mini)["decision_consistent_with_manual_values"] == "unreviewable"
    review["skill_assessments"][0].update(decision="taught", manual_reason="Source explains the exact method", generated_unit_ids=["k1"],
        source_assignments=[{"candidate_id": "k1::r1", "evidence_id": "e1", "quote_field": "text", "quote": "explains event-driven state updates", "teaches_this_skill": "Explained method, not project identity"}])
    review.update(hard_gates={"scope": True}, dimension_scores={"fit": 4}, dimension_reasons={"fit": "Appropriate focused example"}, project_practice_review={"all_constraints_preserved": True},
                  candidate_reviews=[{"candidate_id": "k1::r1", "manual_scope_decision": "specific_teaching", "manual_student_fit": "appropriate", "manual_reason": "Source explains the specific method"}], overall={"human_review_completed": True})
    assert validate_review(review, fresh, mini)["decision_consistent_with_manual_values"] == "accepted_useful"
    for change in ("invented_quote", "other_candidate", "search_evidence"):
        copied = json.loads(json.dumps(review))
        assignment = copied["skill_assessments"][0]["source_assignments"][0]
        altered = json.loads(json.dumps(fresh))
        if change == "invented_quote": assignment["quote"] = "a fabricated lecture"
        elif change == "other_candidate": assignment["candidate_id"] = "foreign"
        else: altered["candidate_reviews"][0]["own_observations_not_auto_verified"][0]["source"] = "search"
        try: validate_review(copied, altered, mini)
        except ValueError: pass
        else: raise AssertionError("Invalid quote/source assignment was accepted")
    review["hard_gates"]["scope"] = False
    assert validate_review(review, fresh, mini)["decision_consistent_with_manual_values"] == "failed"
    review["hard_gates"]["scope"] = True
    review["skill_assessments"][0].update(decision="missing", source_assignments=[])
    assert validate_review(review, fresh, mini)["decision_consistent_with_manual_values"] == "partially_useful"
    raw = {"groups": [{"knowledge_point_id": "k1", "partial_items": [{"resource": {"resource_id": "r1"}, "evidence": []}],
                       "partial_platform_items": {"bilibili": [{"resource": {"resource_id": "r1"}, "evidence": []}]}}]}
    extracted = raw_candidates(raw)
    assert len(extracted) == 1 and len(extracted[0]["occurrences"]) == 2
    return {"in_memory_checks": 8, "passed": 8, "http_requests": 0, "model_calls": 0, "database_connections": 0,
            "live_or_semantic_quality_validation": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", default=str(DEFAULT_PLAN))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("plan")
    commands.add_parser("self-test")
    prep = commands.add_parser("prepare")
    prep.add_argument("--case", required=True); prep.add_argument("--result", required=True)
    prep.add_argument("--analysis"); prep.add_argument("--out", required=True)
    check = commands.add_parser("validate")
    check.add_argument("--review", required=True); check.add_argument("--out")
    args = parser.parse_args()
    if args.command == "self-test":
        print(json.dumps(self_test(), ensure_ascii=False)); return
    pp, plan = load_json(args.plan)
    if args.command == "plan":
        print(json.dumps({"plan_sha256": digest(pp), "cases": [{"case_id": case["case_id"], "cohort": case["cohort"], "skills": len(case["skills"])} for case in plan["cases"]], "quality_reviews_completed": 0}, ensure_ascii=False)); return
    if args.command == "prepare":
        report = prepare(pp, args.case, args.result, args.analysis)
        path = write_new(args.out, report)
        print(json.dumps({"prepared": str(path.relative_to(ROOT)), "sha256": digest(path), "quality_verdict": "unreviewable_template_only"}, ensure_ascii=False)); return
    rp, review = load_json(args.review)
    binding = review["sources"]
    fresh = prepare(pp, review["case_id"], binding["result"]["path"], binding["analysis"]["path"])
    report = validate_review(review, fresh, plan)
    report.update(review_file=str(rp.relative_to(ROOT)), review_sha256=digest(rp), plan_sha256=digest(pp))
    if args.out:
        path = write_new(args.out, report)
        print(json.dumps({"validation": str(path.relative_to(ROOT)), **report}, ensure_ascii=False))
    else:
        print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
