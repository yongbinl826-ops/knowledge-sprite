"""UI-only projections and representation validators; full audit responses stay available."""
from __future__ import annotations

import hashlib
import json

from fastapi.responses import JSONResponse, Response


FAST_UI_FIELDS = frozenset({"policy", "status", "started_at", "finished_at", "elapsed_seconds",
                            "catalog_enrichment", "progress"})


def project_ui(value):
    """Remove bookkeeping duplicates, never resource provenance or recommendation evidence."""
    result = dict(value)
    # Wall-clock persistence timestamps are not UI state and would otherwise
    # invalidate the content revision on a diagnostics-only update.
    result.pop("updated_at", None)
    version = result.get("version")
    if isinstance(version, dict):
        version = dict(version)
        for field in ("analysis_attempts", "validated_concept_context", "updated_at"):
            version.pop(field, None)
        fast = version.get("fast_video_search")
        if isinstance(fast, dict):
            version["fast_video_search"] = {key: val for key, val in fast.items() if key in FAST_UI_FIELDS}
        result["version"] = version
    # Full diagnostic traces remain accessible via the default full projection.
    for field in ("search_attempts", "diagnostics"):
        result.pop(field, None)
    return result


def snapshot_payload(value, projection="full"):
    if value is None:
        return None
    result = project_ui(value) if projection == "ui" else dict(value)
    result.pop("snapshot_revision", None)
    content = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    result["snapshot_revision"] = hashlib.sha256(content.encode()).hexdigest()
    return result


def mobile_snapshot(value, projection="full"):
    result = dict(value)
    if isinstance(result.get("result"), dict):
        result["result"] = snapshot_payload(result["result"], projection)
    inner = (result.get("result") or {}).get("pipeline") or {}
    result["pipeline"] = {"terminal": result.get("status") not in {"queued", "running"},
                          "catalog_pending": inner.get("catalog_pending", False)}
    return snapshot_payload(result)


def conditional_snapshot(request, value, *, mobile=False):
    # Routes must perform normal access/expiry checks before comparing a token.
    tag = '"' + value["snapshot_revision"] + '"'
    headers = {"ETag": tag, "Cache-Control": "no-store" if mobile else "private, no-cache",
               "Vary": "Authorization" if mobile else "Accept"}
    candidates = request.headers.get("if-none-match", "").split(",")
    if any(part.strip().removeprefix("W/") in {tag, "*"} for part in candidates):
        return Response(status_code=304, headers=headers)
    return JSONResponse(value, headers=headers)
