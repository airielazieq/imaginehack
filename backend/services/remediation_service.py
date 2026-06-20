"""Remediation persistence and query service (task 5.5).

Centralizes read/write access to the ``remediations`` table for Module 3
(Guardrailed Self-Healing). The full :class:`RemediationResult` document is
stored as JSON in the ``data`` column; the frequently queried/filtered fields
(``recommendation_id``, ``issue_id``, ``workload_id``, ``execution_path``,
``execution_status``, ``verification_result``, ``rollback_triggered``) are
promoted to dedicated columns so the dashboard and report endpoints can query
them directly.

The remediation API (``api/remediation.py``) uses this service to persist a
generated :class:`RemediationResult` (with its traceability links to the
originating Issue, Recommendation and Workload — Requirement 11.3) and to read a
single stored report back for ``GET /api/remediation/{id}/report``.
"""

from __future__ import annotations

import json
import logging

from backend.core.database import connection
from backend.schemas.remediation import RemediationResult

logger = logging.getLogger("clover.services.remediation")


def _row_to_remediation_dict(row) -> dict:
    """Reconstruct a remediation dict from a DB row (prefers the JSON document)."""
    data = row["data"]
    if data:
        return json.loads(data)
    return {
        "remediation_id": row["remediation_id"],
        "recommendation_id": row["recommendation_id"],
        "issue_id": row["issue_id"],
        "workload_id": row["workload_id"],
        "execution_path": row["execution_path"],
        "execution_status": row["execution_status"],
        "verification_result": row["verification_result"],
        "rollback_triggered": bool(row["rollback_triggered"]),
    }


def create_remediation(
    result: RemediationResult, *, db_path: str | None = None
) -> str:
    """Insert (or replace) a remediation result, returning its id.

    The full document is stored as JSON in ``data``; the promoted columns are
    populated for indexed querying. Keyed on ``remediation_id`` via
    ``INSERT OR REPLACE`` so re-persisting the same id is idempotent.
    """
    payload = result.model_dump(mode="json")
    with connection(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO remediations (
                remediation_id, recommendation_id, issue_id, workload_id,
                execution_path, execution_status, verification_result,
                rollback_triggered, data
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.remediation_id,
                result.recommendation_id,
                result.issue_id,
                result.workload_id,
                result.execution_path,
                result.execution_status,
                result.verification_result,
                1 if result.rollback_triggered else 0,
                json.dumps(payload),
            ),
        )
    logger.info(
        "Persisted remediation %s (%s/%s) for rec %s / issue %s / workload %s",
        result.remediation_id,
        result.execution_path,
        result.execution_status,
        result.recommendation_id,
        result.issue_id,
        result.workload_id,
    )
    return result.remediation_id


def get_remediation(
    remediation_id: str, *, db_path: str | None = None
) -> dict | None:
    """Return a single remediation result as a dict, or ``None`` if absent."""
    with connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM remediations WHERE remediation_id = ?",
            (remediation_id,),
        ).fetchone()
    return _row_to_remediation_dict(row) if row is not None else None


def list_remediations(
    *,
    workload_id: str | None = None,
    recommendation_id: str | None = None,
    issue_id: str | None = None,
    db_path: str | None = None,
) -> list[dict]:
    """Return remediations matching the optional filters, newest first."""
    clauses: list[str] = []
    params: list[object] = []
    for column, value in (
        ("workload_id", workload_id),
        ("recommendation_id", recommendation_id),
        ("issue_id", issue_id),
    ):
        if value is not None:
            clauses.append(f"{column} = ?")
            params.append(value)

    sql = "SELECT * FROM remediations"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY created_at DESC, rowid DESC"

    with connection(db_path) as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [_row_to_remediation_dict(row) for row in rows]
