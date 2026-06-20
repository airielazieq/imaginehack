"""Issue persistence and query service (task 3.5).

Centralizes read/write access to the ``issues`` table for Module 1
(Detection & Insight) and downstream consumers. The full :class:`Issue`
document is stored as JSON in the ``data`` column; the frequently
queried/filtered fields (``issue_type``, ``issue_category``, ``severity``,
``status``, ``workload_id``, ``detected_at``) are promoted to dedicated indexed
columns.

The detector (``modules/detection_insight/detector.py``) uses this service to:
- persist newly detected issues (:func:`create_issue`),
- find a recent open issue for the same workload so detections within a
  5-minute window consolidate into a single issue (:func:`find_open_issue`),
- update a consolidated issue in place (:func:`update_issue`).

The detection API (``api/detection.py``) uses it to list/filter issues, fetch a
single issue, and transition an issue's status.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from backend.core.database import connection
from backend.schemas.issue import Issue

logger = logging.getLogger("clover.services.issue")

# Severity ordering used for consolidation (max-severity wins).
_SEVERITY_ORDER: list[str] = ["low", "medium", "high", "critical"]
_SEVERITY_INDEX: dict[str, int] = {s: i for i, s in enumerate(_SEVERITY_ORDER)}

# Issue statuses considered "open" (still actionable) for consolidation. An
# issue that has reached a terminal state is never consolidated into.
OPEN_STATUSES: tuple[str, ...] = (
    "new",
    "recommended",
    "pending_approval",
    "approved",
    "escalated",
)

# Default consolidation window per Requirement 3.3 / design Property 4.
CONSOLIDATION_WINDOW_SECONDS = 300


def severity_rank(severity: str) -> int:
    """Return the ordinal rank of a severity (low=0 .. critical=3)."""
    return _SEVERITY_INDEX.get(severity, 0)


def max_severity(a: str, b: str) -> str:
    """Return the higher of two severities."""
    return a if severity_rank(a) >= severity_rank(b) else b


def _row_to_issue_dict(row) -> dict:
    """Reconstruct an issue dict from a DB row (prefers the JSON document)."""
    data = row["data"]
    if data:
        return json.loads(data)
    return {
        "issue_id": row["issue_id"],
        "workload_id": row["workload_id"],
        "issue_type": row["issue_type"],
        "issue_category": row["issue_category"],
        "severity": row["severity"],
        "confidence_score": row["confidence_score"],
        "status": row["status"],
        "detected_at": row["detected_at"],
    }


def _parse_dt(value: str) -> datetime:
    """Parse an ISO timestamp into an aware UTC datetime (tolerant of 'Z')."""
    text = value.replace("Z", "+00:00") if value.endswith("Z") else value
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def create_issue(issue: Issue, *, db_path: str | None = None) -> str:
    """Insert a new issue, returning its id."""
    payload = issue.model_dump(mode="json")
    with connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO issues (
                issue_id, workload_id, issue_type, issue_category, severity,
                confidence_score, status, detected_at, data
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                issue.issue_id,
                issue.workload_id,
                issue.issue_type,
                issue.issue_category,
                issue.severity,
                issue.confidence_score,
                issue.status,
                issue.detected_at.isoformat(),
                json.dumps(payload),
            ),
        )
    logger.info(
        "Created issue %s (%s/%s) for workload %s",
        issue.issue_id,
        issue.issue_type,
        issue.severity,
        issue.workload_id,
    )
    return issue.issue_id


def update_issue(issue: Issue, *, db_path: str | None = None) -> str:
    """Update an existing issue in place (used for consolidation)."""
    payload = issue.model_dump(mode="json")
    with connection(db_path) as conn:
        conn.execute(
            """
            UPDATE issues SET
                workload_id      = ?,
                issue_type       = ?,
                issue_category   = ?,
                severity         = ?,
                confidence_score = ?,
                status           = ?,
                detected_at      = ?,
                data             = ?,
                updated_at       = datetime('now')
            WHERE issue_id = ?
            """,
            (
                issue.workload_id,
                issue.issue_type,
                issue.issue_category,
                issue.severity,
                issue.confidence_score,
                issue.status,
                issue.detected_at.isoformat(),
                json.dumps(payload),
                issue.issue_id,
            ),
        )
    logger.info("Updated issue %s (severity=%s)", issue.issue_id, issue.severity)
    return issue.issue_id


def get_issue(issue_id: str, *, db_path: str | None = None) -> dict | None:
    """Return a single issue as a dict, or ``None`` if absent."""
    with connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM issues WHERE issue_id = ?", (issue_id,)
        ).fetchone()
    return _row_to_issue_dict(row) if row is not None else None


def list_issues(
    *,
    issue_type: str | None = None,
    severity: str | None = None,
    issue_category: str | None = None,
    status: str | None = None,
    workload_id: str | None = None,
    db_path: str | None = None,
) -> list[dict]:
    """Return issues matching the optional filters, newest first."""
    clauses: list[str] = []
    params: list[object] = []
    for column, value in (
        ("issue_type", issue_type),
        ("severity", severity),
        ("issue_category", issue_category),
        ("status", status),
        ("workload_id", workload_id),
    ):
        if value is not None:
            clauses.append(f"{column} = ?")
            params.append(value)

    sql = "SELECT * FROM issues"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY detected_at DESC, rowid DESC"

    with connection(db_path) as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [_row_to_issue_dict(row) for row in rows]


def update_status(
    issue_id: str, new_status: str, *, db_path: str | None = None
) -> dict | None:
    """Transition an issue's status. Returns the updated issue, or ``None``.

    Keeps the promoted ``status`` column and the JSON document in sync.
    """
    with connection(db_path) as conn:
        row = conn.execute(
            "SELECT data FROM issues WHERE issue_id = ?", (issue_id,)
        ).fetchone()
        if row is None:
            return None
        doc = json.loads(row["data"]) if row["data"] else {}
        doc["status"] = new_status
        conn.execute(
            "UPDATE issues SET status = ?, data = ?, updated_at = datetime('now') "
            "WHERE issue_id = ?",
            (new_status, json.dumps(doc), issue_id),
        )
    logger.info("Issue %s status -> %s", issue_id, new_status)
    return doc


def find_open_issue(
    workload_id: str,
    *,
    within_seconds: int = CONSOLIDATION_WINDOW_SECONDS,
    now: datetime | None = None,
    db_path: str | None = None,
) -> dict | None:
    """Find the most recent OPEN issue for a workload within the time window.

    Used for 5-minute consolidation (Requirement 3.3): when an open issue for
    the same workload exists within ``within_seconds``, detection updates it
    instead of creating a duplicate. Returns the issue dict or ``None``.
    """
    reference = now or datetime.now(timezone.utc)
    cutoff = reference - timedelta(seconds=within_seconds)

    placeholders = ",".join("?" for _ in OPEN_STATUSES)
    sql = (
        f"SELECT * FROM issues WHERE workload_id = ? "
        f"AND status IN ({placeholders}) "
        f"ORDER BY detected_at DESC, rowid DESC"
    )
    with connection(db_path) as conn:
        rows = conn.execute(sql, (workload_id, *OPEN_STATUSES)).fetchall()

    for row in rows:
        try:
            detected_at = _parse_dt(row["detected_at"])
        except (ValueError, TypeError):
            continue
        if detected_at >= cutoff:
            return _row_to_issue_dict(row)
    return None
