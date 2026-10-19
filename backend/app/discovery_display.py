"""Read-only video discovery cards, independent of teaching recommendations."""
from .ranking import has_type_evidence
from .url_utils import UnsafeURL, normalize_url


def discovered_video(point, resource, evidence):
    """Keep a source-bound search lead without asserting skill coverage."""
    if not has_type_evidence(resource, evidence):
        return None
    if resource.get("fetch_status") == "not_found":
        return None
    try:
        target = normalize_url(resource.get("canonical_url") or resource.get("url", ""))
    except (UnsafeURL, TypeError, ValueError):
        return None
    searches = []
    for row in evidence:
        if row.get("kind") != "search" or row.get("knowledge_point_id") != point["knowledge_point_id"]:
            continue
        try:
            if normalize_url(row.get("url", "")) == target and row.get("evidence_id") and row.get("title"):
                searches.append(row)
        except (UnsafeURL, TypeError, ValueError):
            continue
    if not searches:
        from .course_library import library_observations
        from .mooc_relevance import assess_mooc_relevance
        libraries = library_observations(point, resource, evidence)
        if not libraries or not assess_mooc_relevance(point, resource, evidence).get("display_eligible"):
            return None
        searches = libraries
    fields = ("resource_id", "title", "platform", "thumbnail_url", "fetch_status", "video_evidence_status", "resource_type")
    return {"resource": {**{key: resource.get(key) for key in fields}, "url": target, "canonical_url": target},
            "discovery_evidence": searches[:2]}


def display_discovered_videos(candidates):
    rows = sorted(candidates,
                  key=lambda row: (row["resource"].get("video_evidence_status") != "page_verified",
                                   row["resource"]["resource_id"]))
    return rows, {platform: [row for row in rows if row["resource"]["platform"] == platform]
                           for platform in sorted({row["resource"]["platform"] for row in rows})}
