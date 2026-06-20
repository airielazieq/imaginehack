"""Alert persistence and query service (task 16.1).

Centralizes read/write access to the ``alerts`` table for the Alert System
(``backend/modules/alerts/``). The full :class:`~backend.schemas.alert.Alert`
document is stored as JSON in the ``data`` column; the frequently
queried/filtered fields (``workload_id``, ``title``, ``severity``, ``status``,
``priority_score``, ``created_at``, ``resolved_at``, ``suppressed_until``) are
promoted to dedicated indexed columns (see ``backend/core/database.py``).

The alert engine (``modules/alerts/alert_engine.py``) uses this service to:
- persist newly generated alerts (:func:`create_alert`),
- look up the most recent active alert for a workload so later tasks can
  suppress / auto-resolve (:func:`get_active_alert`),
- update an alert in place when it is resolved or suppressed
  (:func:`update_alert`).

The ``GET /api/alerts`` endpoint (wired in task 16.2) uses :func:`list_alerts`
to return alerts filterable by workload, severity and status.
"""

from __future__ import annotations

import json
import logging

from backend.core.database import connection
from backend.schemas.alert import Alert

logger = logging.getLogger("clover.services.alert")

# Alert statuses considered "still open" (an active condition, not yet cleared).
ACTIVE_STATUSES: tuple[str, ...] = ("active", "delivery_failed")


def _row_to_alert_dict(row) -> dict:
    """Reconstruct an alert dict from a DB row (prefers the JSON document)."""
    data = row["data"]
    if data:
        return json.loads(data)
    return {
        "alert_id": row["alert_id"],
        "workload_id": row["workload_id"],
        "title": row["title"],
        "severity": row["severity"],
        "status": row["status"],
        "priority_score": row["priority_score"],
        "created_at": row["created_at"],
        "resolved_at": row["resolved_at"],
        "suppressed_until": row["suppressed_until"],
    }


def _persist(alert: Alert, *, insert: bool, db_path: str | None = None) -> str:
    """Insert or update an alert row, keeping promoted columns + JSON in sync."""
    payload = alert.model_dump(mode="json")
    promoted = (
        alert.workload_id,
        alert.title,
        alert.severity,
        alert.status,
        alert.priority_score,
        alert.created_at.isoformat(),
        alert.resolved_at.isoformat() if alert.resolved_at else None,
        alert.suppressed_until.isoformat() if alert.suppressed_until else None,
        json.dumps(payload),
    )
    with connection(db_path) as conn:
        if insert:
            conn.execute(
                """
                INSERT INTO alerts (
                    workload_id, title, severity, status, priority_score,
                    created_at, resolved_at, suppressed_until, data, alert_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (*promoted, alert.alert_id),
            )
        else:
            conn.execute(
                """
                UPDATE alerts SET
                    workload_id      = ?,
                    title            = ?,
                    severity         = ?,
                    status           = ?,
                    priority_score   = ?,
                    created_at       = ?,
                    resolved_at      = ?,
                    suppressed_until = ?,
                    data             = ?
                WHERE alert_id = ?
                """,
                (*promoted, alert.alert_id),
            )
    return alert.alert_id


def create_alert(alert: Alert, *, db_path: str | None = None) -> str:
    """Insert a new alert, returning its id."""
    _persist(alert, insert=True, db_path=db_path)
    logger.info(
        "Created alert %s (%s) for workload %s (score=%.1f)",
        alert.alert_id,
        alert.severity,
        alert.workload_id,
        alert.priority_score,
    )
    return alert.alert_id


def update_alert(alert: Alert, *, db_path: str | None = None) -> str:
    """Update an existing alert in place (used for resolution / suppression)."""
    _persist(alert, insert=False, db_path=db_path)
    logger.info("Updated alert %s (status=%s)", alert.alert_id, alert.status)
    return alert.alert_id


def get_alert(alert_id: str, *, db_path: str | None = None) -> dict | None:
    """Return a single alert as a dict, or ``None`` if absent."""
    with connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM alerts WHERE alert_id = ?", (alert_id,)
        ).fetchone()
    return _row_to_alert_dict(row) if row is not None else None


def list_alerts(
    *,
    workload_id: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    db_path: str | None = None,
) -> list[dict]:
    """Return alerts matching the optional filters, newest first.

    Backs the ``GET /api/alerts`` endpoint (filterable by workload, severity,
    status). Results are ordered most-recent-first by ``created_at``.
    """
    clauses: list[str] = []
    params: list[object] = []
    for column, value in (
        ("workload_id", workload_id),
        ("severity", severity),
        ("status", status),
    ):
        if value is not None:
            clauses.append(f"{column} = ?")
            params.append(value)

    sql = "SELECT * FROM alerts"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY created_at DESC, rowid DESC"

    with connection(db_path) as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [_row_to_alert_dict(row) for row in rows]


def get_active_alert(workload_id: str, *, db_path: str | None = None) -> dict | None:
    """Return the most recent still-open alert for a workload, or ``None``.

    Used by suppression / auto-resolve (task 16.2) to find an existing active
    alert for the same workload.
    """
    placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
    sql = (
        f"SELECT * FROM alerts WHERE workload_id = ? "
        f"AND status IN ({placeholders}) "
        f"ORDER BY created_at DESC, rowid DESC LIMIT 1"
    )
    with connection(db_path) as conn:
        row = conn.execute(sql, (workload_id, *ACTIVE_STATUSES)).fetchone()
    return _row_to_alert_dict(row) if row is not None else None
