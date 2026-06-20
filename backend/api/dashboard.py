"""Dashboard API (task 8.1).

Aggregates the cross-cutting read surface that powers the dashboard landing
page (spec 10 §6, Requirements 16.1, 16.2, 21.1):

- ``GET /api/dashboard/summary``            - stat cards: total workloads,
  active/critical issues, pending approvals and aggregate projected savings.
- ``GET /api/dashboard/heatmap/composite``  - one Priority_Score per workload
  (drives the continuous green->red composite grid).
- ``GET /api/dashboard/heatmap/matrix``     - per-workload DimensionScores
  (drives the Security/Energy/Carbon/Cost/Performance/Monitoring matrix).
- ``GET /api/dashboard/savings``            - projected cost/energy/carbon
  savings rollup across open recommendations.
- ``GET /api/dashboard/recent-actions``     - the most recent remediations.

All responses use the shared success envelope. The heatmap endpoints return
exactly one entry per workload so the frontend grid/matrix can render a fixed
cell per workload.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query, status

from backend.modules.scoring import dimension_scorer, priority_scorer
from backend.modules.self_healing.approval_queue import approval_queue
from backend.schemas.api_responses import success
from backend.services import (
    issue_service,
    recommendation_service,
    remediation_service,
    workload_service,
)

logger = logging.getLogger("clover.api.dashboard")

router = APIRouter(tags=["dashboard"])

# A remediation in one of these states has "consumed" its recommendation, so
# the recommendation's projected savings no longer count as still-open.
_RESOLVED_REMEDIATION_STATUSES = frozenset({"completed", "in_progress"})

# Zero-valued savings rollup used as the aggregation seed / empty result.
_EMPTY_SAVINGS = {"cost_30d": 0.0, "energy_30d_kwh": 0.0, "carbon_30d_kgco2e": 0.0}


def _resolved_recommendation_ids(*, db_path: str | None = None) -> set[str]:
    """Recommendation ids that already have a remediation in flight/completed."""
    resolved: set[str] = set()
    for remediation in remediation_service.list_remediations(db_path=db_path):
        if remediation.get("execution_status") in _RESOLVED_REMEDIATION_STATUSES:
            rec_id = remediation.get("recommendation_id")
            if rec_id:
                resolved.add(rec_id)
    return resolved


def _open_recommendations(*, db_path: str | None = None) -> list[dict]:
    """Recommendations that have not yet been remediated (still actionable)."""
    resolved = _resolved_recommendation_ids(db_path=db_path)
    return [
        rec
        for rec in recommendation_service.list_recommendations(db_path=db_path)
        if rec.get("recommendation_id") not in resolved
    ]


def _aggregate_projected_savings(recommendations: list[dict]) -> dict:
    """Sum ``projected_savings`` (cost/energy/carbon) across recommendations.

    Savings are clamped at zero per dimension (Requirement 6.4 keeps savings
    non-negative; this is a defensive guard for any partial/legacy document).
    """
    totals = dict(_EMPTY_SAVINGS)
    for rec in recommendations:
        forecast = rec.get("optimization_impact_forecast") or {}
        savings = forecast.get("projected_savings") or {}
        for key in totals:
            try:
                totals[key] += max(0.0, float(savings.get(key, 0.0) or 0.0))
            except (TypeError, ValueError):
                continue
    return {key: round(value, 2) for key, value in totals.items()}


def _open_issues(*, db_path: str | None = None) -> list[dict]:
    """All issues currently in an open/actionable status."""
    return [
        issue
        for issue in issue_service.list_issues(db_path=db_path)
        if issue.get("status") in issue_service.OPEN_STATUSES
    ]


# --------------------------------------------------------------------------- #
# Summary stat cards
# --------------------------------------------------------------------------- #
@router.get("/api/dashboard/summary", status_code=status.HTTP_200_OK)
async def dashboard_summary() -> dict:
    """Return the dashboard stat-card counts and aggregate projected savings."""
    workloads = workload_service.list_workloads()
    open_issues = _open_issues()
    critical_issues = [i for i in open_issues if i.get("severity") == "critical"]
    pending_approvals = approval_queue.list_items()
    open_recs = _open_recommendations()
    projected_savings = _aggregate_projected_savings(open_recs)

    return success(
        data={
            "total_workloads": len(workloads),
            "active_issues": len(open_issues),
            "critical_issues": len(critical_issues),
            "pending_approvals": len(pending_approvals),
            "open_recommendations": len(open_recs),
            "projected_savings": projected_savings,
        },
        message="Dashboard summary retrieved.",
    )


# --------------------------------------------------------------------------- #
# Composite heatmap (Priority_Score per workload)
# --------------------------------------------------------------------------- #
@router.get("/api/dashboard/heatmap/composite", status_code=status.HTTP_200_OK)
async def dashboard_heatmap_composite() -> dict:
    """Return the composite heatmap: one Priority_Score per workload.

    Each cell carries the workload identity/status plus the full
    :class:`PriorityScore` so the grid can colour on the 0-100 gradient and the
    tooltip can show the contributing factors.
    """
    weights = priority_scorer.load_weights()
    cells: list[dict] = []
    for workload in workload_service.list_workloads():
        workload_id = workload["workload_id"]
        score = priority_scorer.compute_for_workload(workload_id, weights=weights)
        cells.append(
            {
                "workload_id": workload_id,
                "workload_name": workload.get("workload_name"),
                "status": workload.get("status"),
                "construction_workflow": workload.get("construction_workflow"),
                "priority_score": score.score,
                "score_detail": score.model_dump(mode="json"),
            }
        )
    return success(
        data={"cells": cells, "count": len(cells)},
        message=f"Composite heatmap retrieved for {len(cells)} workload(s).",
    )


# --------------------------------------------------------------------------- #
# Matrix heatmap (DimensionScores per workload)
# --------------------------------------------------------------------------- #
@router.get("/api/dashboard/heatmap/matrix", status_code=status.HTTP_200_OK)
async def dashboard_heatmap_matrix() -> dict:
    """Return the matrix heatmap: per-workload DimensionScores (6 dimensions)."""
    rows: list[dict] = []
    for workload in workload_service.list_workloads():
        workload_id = workload["workload_id"]
        scores = dimension_scorer.score_workload(workload_id)
        rows.append(
            {
                "workload_id": workload_id,
                "workload_name": workload.get("workload_name"),
                "status": workload.get("status"),
                "dimension_scores": scores.model_dump(mode="json"),
            }
        )
    return success(
        data={"rows": rows, "count": len(rows)},
        message=f"Matrix heatmap retrieved for {len(rows)} workload(s).",
    )


# --------------------------------------------------------------------------- #
# Savings rollup
# --------------------------------------------------------------------------- #
@router.get("/api/dashboard/savings", status_code=status.HTTP_200_OK)
async def dashboard_savings() -> dict:
    """Return the projected cost/energy/carbon savings across open recommendations."""
    open_recs = _open_recommendations()
    projected_savings = _aggregate_projected_savings(open_recs)
    return success(
        data={
            "projected_savings": projected_savings,
            "recommendation_count": len(open_recs),
        },
        message="Projected savings rollup retrieved.",
    )


# --------------------------------------------------------------------------- #
# Recent actions
# --------------------------------------------------------------------------- #
@router.get("/api/dashboard/recent-actions", status_code=status.HTTP_200_OK)
async def dashboard_recent_actions(
    limit: int = Query(default=10, ge=1, le=100),
) -> dict:
    """Return the most recent remediations (newest first), capped by ``limit``."""
    remediations = remediation_service.list_remediations()[:limit]
    actions = [
        {
            "remediation_id": r.get("remediation_id"),
            "workload_id": r.get("workload_id"),
            "issue_id": r.get("issue_id"),
            "recommendation_id": r.get("recommendation_id"),
            "execution_path": r.get("execution_path"),
            "execution_status": r.get("execution_status"),
            "verification_result": r.get("verification_result"),
            "rollback_triggered": r.get("rollback_triggered"),
        }
        for r in remediations
    ]
    return success(
        data={"actions": actions, "count": len(actions)},
        message=f"Retrieved {len(actions)} recent action(s).",
    )
