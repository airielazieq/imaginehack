"""Recommendation persistence and query service (task 4.4).

Centralizes read/write access to the ``recommendations`` table for Module 2
(Next Best Action) and downstream consumers (Module 3 self-healing).

The full :class:`Recommendation` document is stored as JSON in the ``data``
column; the frequently queried/filtered fields (``issue_id``, ``workload_id``,
``recommendation_type``, ``action_category``, ``risk_level``,
``required_execution_mode``, ``created_at``) are promoted to dedicated columns.

Both the event-driven NBA pipeline (subscribed to ``ISSUE_DETECTED``) and the
generate-on-demand API (``POST /api/recommendations/generate/{issueId}``) use
this service to persist their output. The recommendations API
(``GET /api/recommendations/{id}``) reads single recommendations back.
"""

from __future__ import annotations

import json
import logging

from backend.core.database import connection
from backend.schemas.recommendation import Recommendation

logger = logging.getLogger("clover.services.recommendation")


def _row_to_recommendation_dict(row) -> dict:
    """Reconstruct a recommendation dict from a DB row (prefers JSON document)."""
    data = row["data"]
    if data:
        return json.loads(data)
    return {
        "recommendation_id": row["recommendation_id"],
        "issue_id": row["issue_id"],
        "workload_id": row["workload_id"],
        "recommendation_type": row["recommendation_type"],
        "action_category": row["action_category"],
        "risk_level": row["risk_level"],
        "required_execution_mode": row["required_execution_mode"],
        "created_at": row["created_at"],
    }


def create_recommendation(
    recommendation: Recommendation, *, db_path: str | None = None
) -> str:
    """Insert a recommendation, returning its id.

    The full document is stored as JSON in ``data``; the promoted columns are
    populated for indexed querying. Uses ``INSERT OR REPLACE`` keyed on the
    recommendation id so re-persisting the same id is idempotent.
    """
    payload = recommendation.model_dump(mode="json")
    with connection(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO recommendations (
                recommendation_id, issue_id, workload_id, recommendation_type,
                action_category, risk_level, required_execution_mode,
                created_at, data
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                recommendation.recommendation_id,
                recommendation.issue_id,
                recommendation.workload_id,
                recommendation.recommendation_type,
                recommendation.action_category,
                recommendation.risk_level,
                recommendation.required_execution_mode,
                recommendation.created_at.isoformat(),
                json.dumps(payload),
            ),
        )
    logger.info(
        "Persisted recommendation %s (%s/%s) for issue %s / workload %s",
        recommendation.recommendation_id,
        recommendation.recommendation_type,
        recommendation.risk_level,
        recommendation.issue_id,
        recommendation.workload_id,
    )
    return recommendation.recommendation_id


def get_recommendation(
    recommendation_id: str, *, db_path: str | None = None
) -> dict | None:
    """Return a single recommendation as a dict, or ``None`` if absent."""
    with connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM recommendations WHERE recommendation_id = ?",
            (recommendation_id,),
        ).fetchone()
    return _row_to_recommendation_dict(row) if row is not None else None


def list_recommendations(
    *,
    issue_id: str | None = None,
    workload_id: str | None = None,
    db_path: str | None = None,
) -> list[dict]:
    """Return recommendations matching the optional filters, newest first."""
    clauses: list[str] = []
    params: list[object] = []
    for column, value in (("issue_id", issue_id), ("workload_id", workload_id)):
        if value is not None:
            clauses.append(f"{column} = ?")
            params.append(value)

    sql = "SELECT * FROM recommendations"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY created_at DESC, rowid DESC"

    with connection(db_path) as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [_row_to_recommendation_dict(row) for row in rows]


def get_latest_for_issue(
    issue_id: str, *, db_path: str | None = None
) -> dict | None:
    """Return the most recent recommendation for an issue, or ``None``.

    Used by the event-driven pipeline to stay idempotent: a re-detection of the
    same (consolidated) issue does not create a duplicate recommendation.
    """
    recommendations = list_recommendations(issue_id=issue_id, db_path=db_path)
    return recommendations[0] if recommendations else None
