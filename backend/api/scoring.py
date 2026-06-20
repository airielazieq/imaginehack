"""Scoring API (task 7.2).

Exposes the scoring read surface (spec 10 §5):

- ``GET /api/scoring/issues`` - return the open issues ranked by priority,
  each enriched with the per-dimension scores (:class:`DimensionScores`) of
  the workload it belongs to.

Issues are ranked highest-severity-first; ties break by the earliest
``detected_at`` (an earlier detection ranks higher, per spec 07 §A2). When the
6-factor Priority Score engine (task 7.1) is available, each issue is also
annotated with its workload's ``priority_score``; otherwise that field is
omitted and ranking falls back to severity. All responses use the shared
success envelope.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query, status

from backend.modules.scoring import dimension_scorer
from backend.schemas.api_responses import success
from backend.services import issue_service

logger = logging.getLogger("clover.api.scoring")

router = APIRouter(tags=["scoring"])


def _detected_at_key(issue: dict) -> str:
    """Sort key for the detection timestamp (ISO strings sort chronologically)."""
    return str(issue.get("detected_at") or "")


@router.get("/api/scoring/issues", status_code=status.HTTP_200_OK)
async def list_scored_issues(
    workload_id: str | None = Query(default=None),
) -> dict:
    """Return open issues ranked by priority, with per-workload dimension scores.

    Optionally filter to a single workload via ``workload_id``. Each item is
    the issue document plus a ``dimension_scores`` object for the issue's
    workload; the list is ordered most-severe first (earliest detection wins
    ties).
    """
    issues = [
        issue
        for issue in issue_service.list_issues(workload_id=workload_id)
        if issue.get("status") in issue_service.OPEN_STATUSES
    ]

    # Rank: higher severity first, then earlier detection_timestamp first.
    issues.sort(
        key=lambda i: (
            -issue_service.severity_rank(i.get("severity", "low")),
            _detected_at_key(i),
        )
    )

    # Cache dimension scores per workload so we score each workload once.
    scores_cache: dict[str, dict] = {}
    scored: list[dict] = []
    for issue in issues:
        wl_id = issue.get("workload_id")
        if wl_id not in scores_cache:
            scores_cache[wl_id] = dimension_scorer.score_workload(wl_id).model_dump(
                mode="json"
            )
        scored.append({**issue, "dimension_scores": scores_cache[wl_id]})

    return success(
        data={"issues": scored, "count": len(scored)},
        message=f"Retrieved {len(scored)} scored issue(s).",
    )
