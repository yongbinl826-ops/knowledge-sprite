"""The teaching axis is separate from the student's project practice checks."""
from __future__ import annotations

import hashlib

from .teaching_match import prepare_pair, literal_decision, validate_decision
from .teaching_review import validate_reviewed


def learning_skill_assessment(point: dict, resource: dict, evidence: list[dict], request) -> dict | None:
    """Pure rank/read path. Never calls a model or turns intent into evidence."""
    pair = prepare_pair(point, resource, evidence, request.student_level)
    if pair is None:
        return None
    saved = point.get("_teaching_decision")
    decision = validate_reviewed(point, resource, evidence, saved, request.student_level) if saved is not None else None
    if saved is not None and decision is None:
        return None  # Old/unreviewed/stale model claims cannot revive by fallback.
    if saved is None:
        decision = literal_decision(pair)
    supports = decision.get("supports", [])
    if not supports:
        return None
    rows = []
    for skill in pair["skills"]:
        claims = [row for row in supports if row["skill_id"] == skill["id"] and row["skill"] == skill["text"]]
        ids = list(dict.fromkeys(row["evidence_id"] for row in claims))
        rows.append({"id": skill["id"], "text": skill["text"], "status": "supported" if ids else "unknown",
            "evidence_ids": ids,
            "reason": ("本课明确列出这一技能主题；具体深度和步骤请到平台核对。" if claims and all(row["basis"] == "title" for row in claims)
                       else "本课自身的简介、目录或绑定教学笔记提供了这一技能的内容依据。" if claims
                       else "当前来源尚未证明讲授这一技能。")})
    identifiers = list(dict.fromkeys(row["evidence_id"] for row in supports))
    return {"topic_evidence_status": "partial", "supporting_evidence_ids": identifiers,
        "topic_evidence_reasons": [{"code": "transferable_learning_skill",
            "message": "此材料用于学习已列出的具体技能；项目中的数据、常量、参数选择与验收由学生迁移练习，不声称视频演示了同款项目。",
            "evidence_ids": identifiers}], "subtopic_coverage": rows,
        "teaching_support": supports, "teaching_fingerprint": pair["fingerprint"],
        "learning_support_mode": "transferable_skills"}


def summarize_learning_support(point: dict, items: list[dict]) -> dict:
    """Aggregate current displayed sources without any project-completion claim."""
    skills = [{"id": f"skill_{index+1}", "text": text, "content_resource_ids": [],
               "title_resource_ids": [], "evidence_ids": []}
              for index, text in enumerate(point.get("learning_skills") or [])]
    expected = {row["id"]: row for row in skills}
    for item in items:
        resource, match = item["resource"], item["match"]
        if (match.get("knowledge_point_id") != point["knowledge_point_id"]
                or match.get("resource_id") != resource.get("resource_id")
                or match.get("topic_evidence_status") == "needs_review"):
            continue
        source_map, duplicates = {}, set()
        for source in item.get("evidence") or []:
            identifier = source.get("evidence_id")
            if identifier in source_map:
                duplicates.add(identifier)
            source_map[identifier] = source
        for support in match.get("teaching_support") or []:
            row = expected.get(support.get("skill_id"))
            source = source_map.get(support.get("evidence_id"), {})
            raw = source.get("text")
            if (not row or row["text"] != support.get("skill") or source.get("evidence_id") in duplicates
                    or source.get("kind") not in {"page", "catalog"} or not isinstance(raw, str)
                    or not support.get("quote") or support["quote"] not in raw
                    or hashlib.sha256(raw.encode("utf-8")).hexdigest() != support.get("source_text_sha256")):
                continue
            field = "title_resource_ids" if support["basis"] == "title" else "content_resource_ids"
            if resource["resource_id"] not in row[field]:
                row[field].append(resource["resource_id"])
            if support["evidence_id"] not in row["evidence_ids"]:
                row["evidence_ids"].append(support["evidence_id"])
    return {"mode": "transferable_skills", "skills": skills,
        "disclaimer": "按当前展示材料的实际来源分别核对技能主题和内容依据；多个课程可互补。主题匹配不等于教学深度、学生掌握或项目实践完成。"}
