"""Audit log persistence, query, and event-driven recording (task 15.1).

Centralizes the platform's **immutable** audit trail. Every meaningful state
transition in the pipeline (an Issue detected, a Recommendation generated, a
Remediation completed — including rollbacks) is recorded as an
:class:`~backend.schemas.audit.AuditLog` in the ``audit_logs`` table
(spec ``13_SAFETY_GOVERNANCE_AUDIT`` §6, Requirements 15.1-15.4).

Design:

- **Write-once / immutable.** Records are inserted with a plain ``INSERT`` so a
  duplicate ``audit_id`` is rejected at the database level. There is **no
  update path and no delete-by-id path** — an audit entry, once written, is
  never mutated or selectively removed. The only removal is bulk
  *retention enforcement* (:func:`purge_expired_logs`), which drops entries
  strictly older than the 90-day window (Requirement 15.2) and never touches a
  record that is still within retention.

- **Query helpers.** :func:`list_audit_logs` (optional ``workload_id`` /
  ``event_type`` / ``start_date`` / ``end_date`` filters), :func:`get_audit_log`
  (by id), and :func:`list_for_issue` (all entries referencing an issue). All
  list helpers return **most-recent-first**.

- **Event subscribers.** :func:`register_subscriptions` (idempotent) wires
  audit recording to the meaningful lifecycle events on the bus
  (``ISSUE_DETECTED``, ``RECOMMENDATION_GENERATED``, ``REMEDIATION_COMPLETED``),
  mirroring the pattern used by the detector / NBA pipeline / scorer. It is
  called from the application lifespan.

The actual ``INSERT`` shares the column layout defined in
``backend/core/database.py`` (and used by ``connectors/audit_connector.py``):
the full :class:`AuditLog` JSON is stored in the ``data`` column while the
frequently-filtered fields are promoted to dedicated indexed columns.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from backend.connectors.audit_connector import build_audit_log
from backend.core.database import connection
from backend.core.event_bus import Event, EventType, event_bus
from backend.schemas.audit import AuditLog

logger = logging.getLogger("clover.services.audit")

# Audit entries are retained for at least 90 days (Requirement 15.2).
RETENTION_DAYS = 90


# --------------------------------------------------------------------------- #
# Row reconstruction helpers
# --------------------------------------------------------------------------- #
def _row_to_audit_dict(row) -> dict:
    """Reconstruct an audit dict from a DB row (prefers the JSON document)."""
    data = row["data"]
    if data:
        return json.loads(data)
    return {
        "audit_id": row["audit_id"],
        "event_type": row["event_type"],
        "actor": row["actor"],
        "workload_id": row["workload_id"],
        "issue_id": row["issue_id"],
        "recommendation_id": row["recommendation_id"],
        "remediation_id": row["remediation_id"],
        "previous_status": row["previous_status"],
        "new_status": row["new_status"],
        "timestamp": row["timestamp"],
        "details": {},
    }


def _to_iso(value: datetime | str) -> str:
    """Normalize a datetime/ISO string to an ISO-8601 string for comparison."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    return str(value)


# --------------------------------------------------------------------------- #
# Write path (immutable / write-once)
# --------------------------------------------------------------------------- #
def record_audit(log: AuditLog, *, db_path: str | None = None) -> str:
    """Persist a fully-built :class:`AuditLog` (write-once).

    Uses a plain ``INSERT`` so re-recording the same ``audit_id`` raises a
    ``sqlite3.IntegrityError`` — the audit trail is append-only and immutable.
    Returns the ``audit_id``.
    """
    with connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO audit_logs (
                audit_id, event_type, actor, workload_id, issue_id,
                recommendation_id, remediation_id, previous_status,
                new_status, timestamp, data
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                log.audit_id,
                log.event_type,
                log.actor,
                log.workload_id,
                log.issue_id,
                log.recommendation_id,
                log.remediation_id,
                log.previous_status,
                log.new_status,
                log.timestamp.isoformat(),
                log.model_dump_json(),
            ),
        )
    logger.info(
        "Recorded audit %s (%s) for workload %s",
        log.audit_id,
        log.event_type,
        log.workload_id or "-",
    )
    return log.audit_id


def write_audit_log(
    *,
    event_type: str,
    actor: str = "system",
    workload_id: str = "",
    issue_id: str | None = None,
    recommendation_id: str | None = None,
    remediation_id: str | None = None,
    previous_status: str | None = None,
    new_status: str | None = None,
    details: dict | None = None,
    rollback_note: str | None = None,
    timestamp: datetime | None = None,
    db_path: str | None = None,
) -> AuditLog:
    """Build and persist an :class:`AuditLog`, returning the stored record.

    Convenience wrapper over :func:`build_audit_log` +
    :func:`record_audit` (reuses the connector's validated builder).
    """
    log = build_audit_log(
        event_type=event_type,
        actor=actor,
        workload_id=workload_id,
        issue_id=issue_id,
        recommendation_id=recommendation_id,
        remediation_id=remediation_id,
        previous_status=previous_status,
        new_status=new_status,
        details=details,
        rollback_note=rollback_note,
        timestamp=timestamp,
    )
    record_audit(log, db_path=db_path)
    return log


# --------------------------------------------------------------------------- #
# Query path
# --------------------------------------------------------------------------- #
def get_audit_log(audit_id: str, *, db_path: str | None = None) -> dict | None:
    """Return a single audit entry as a dict, or ``None`` if absent."""
    with connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM audit_logs WHERE audit_id = ?", (audit_id,)
        ).fetchone()
    return _row_to_audit_dict(row) if row is not None else None


def list_audit_logs(
    *,
    workload_id: str | None = None,
    event_type: str | None = None,
    start_date: datetime | str | None = None,
    end_date: datetime | str | None = None,
    db_path: str | None = None,
) -> list[dict]:
    """Return audit entries matching the optional filters, most-recent-first.

    Args:
        workload_id: Restrict to a single workload.
        event_type: Restrict to a single event type (e.g. ``"issue_detected"``).
        start_date: Inclusive lower bound on ``timestamp`` (datetime or ISO str).
        end_date: Inclusive upper bound on ``timestamp`` (datetime or ISO str).
    """
    clauses: list[str] = []
    params: list[object] = []

    if workload_id is not None:
        clauses.append("workload_id = ?")
        params.append(workload_id)
    if event_type is not None:
        clauses.append("event_type = ?")
        params.append(event_type)
    if start_date is not None:
        clauses.append("timestamp >= ?")
        params.append(_to_iso(start_date))
    if end_date is not None:
        clauses.append("timestamp <= ?")
        params.append(_to_iso(end_date))

    sql = "SELECT * FROM audit_logs"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY timestamp DESC, rowid DESC"

    with connection(db_path) as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [_row_to_audit_dict(row) for row in rows]


def list_for_issue(issue_id: str, *, db_path: str | None = None) -> list[dict]:
    """Return all audit entries referencing ``issue_id``, most-recent-first."""
    with connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM audit_logs WHERE issue_id = ? "
            "ORDER BY timestamp DESC, rowid DESC",
            (issue_id,),
        ).fetchall()
    return [_row_to_audit_dict(row) for row in rows]


def purge_expired_logs(
    *,
    retention_days: int = RETENTION_DAYS,
    now: datetime | None = None,
    db_path: str | None = None,
) -> int:
    """Delete audit entries older than the retention window (Requirement 15.2).

    This is the **only** removal path; it never mutates or removes a record
    still within the ``retention_days`` window. Returns the number of expired
    entries removed.
    """
    reference = now or datetime.now(timezone.utc)
    cutoff = (reference - timedelta(days=retention_days)).isoformat()
    with connection(db_path) as conn:
        cursor = conn.execute(
            "DELETE FROM audit_logs WHERE timestamp < ?", (cutoff,)
        )
        removed = cursor.rowcount
    if removed:
        logger.info("Purged %d audit entries older than %d days", removed, retention_days)
    return removed


# --------------------------------------------------------------------------- #
# Event handlers (immutable record per meaningful lifecycle event)
# --------------------------------------------------------------------------- #
async def _on_issue_detected(event: Event) -> None:
    """Record an audit entry when an Issue is detected (status -> its state)."""
    payload = event.payload or {}
    issue = payload.get("issue") or {}
    workload_id = payload.get("workload_id") or issue.get("workload_id")
    issue_id = payload.get("issue_id") or issue.get("issue_id")
    if not workload_id:
        return

    details = {
        "issue_type": issue.get("issue_type"),
        "issue_category": issue.get("issue_category"),
        "severity": issue.get("severity"),
        "confidence_score": issue.get("confidence_score"),
        "correlation_id": event.correlation_id,
    }
    try:
        write_audit_log(
            event_type=EventType.ISSUE_DETECTED.value,
            actor="system",
            workload_id=workload_id,
            issue_id=issue_id,
            previous_status=None,
            new_status=issue.get("status", "new"),
            details=details,
        )
    except Exception:  # noqa: BLE001 - isolate the subscriber from the bus
        logger.exception("Failed to record audit for ISSUE_DETECTED (%s)", issue_id)


async def _on_recommendation_generated(event: Event) -> None:
    """Record an audit entry when a Recommendation is generated for an Issue."""
    payload = event.payload or {}
    recommendation = payload.get("recommendation") or {}
    workload_id = payload.get("workload_id") or recommendation.get("workload_id")
    issue_id = payload.get("issue_id") or recommendation.get("issue_id")
    recommendation_id = payload.get("recommendation_id") or recommendation.get(
        "recommendation_id"
    )
    if not workload_id:
        return

    details = {
        "action_category": recommendation.get("action_category"),
        "recommendation_type": recommendation.get("recommendation_type"),
        "risk_level": recommendation.get("risk_level"),
        "required_execution_mode": recommendation.get("required_execution_mode"),
        "correlation_id": event.correlation_id,
    }
    try:
        write_audit_log(
            event_type=EventType.RECOMMENDATION_GENERATED.value,
            actor="system",
            workload_id=workload_id,
            issue_id=issue_id,
            recommendation_id=recommendation_id,
            previous_status="new",
            new_status="recommended",
            details=details,
        )
    except Exception:  # noqa: BLE001 - isolate the subscriber from the bus
        logger.exception(
            "Failed to record audit for RECOMMENDATION_GENERATED (%s)",
            recommendation_id,
        )


async def _on_remediation_completed(event: Event) -> None:
    """Record an audit entry when a Remediation completes (incl. rollbacks).

    The base entry captures the execution path / status transition. When the
    remediation triggered a rollback, an additional immutable entry is written
    with the original action context and the rollback outcome (Requirement
    15.4), enriched best-effort from the persisted RemediationResult.
    """
    payload = event.payload or {}
    workload_id = payload.get("workload_id")
    issue_id = payload.get("issue_id")
    recommendation_id = payload.get("recommendation_id")
    remediation_id = payload.get("remediation_id")
    execution_path = payload.get("execution_path")
    execution_status = payload.get("execution_status")
    if not workload_id:
        return

    # Best-effort enrichment from the stored RemediationResult (rollback,
    # verification, etc.). Never fatal if the record is not (yet) available.
    rollback_triggered = False
    verification_result = None
    actor = "auto_fix"
    try:
        from backend.services import remediation_service

        stored = remediation_service.get_remediation(remediation_id)
        if stored:
            rollback_triggered = bool(stored.get("rollback_triggered"))
            verification_result = stored.get("verification_result")
            if execution_path is None:
                execution_path = stored.get("execution_path")
            if execution_status is None:
                execution_status = stored.get("execution_status")
    except Exception:  # noqa: BLE001 - enrichment is non-fatal
        logger.debug("Could not enrich remediation audit for %s", remediation_id)

    if execution_path == "auto_fix":
        actor = "auto_fix"
    elif execution_path == "user_approved":
        actor = "user"
    elif execution_path == "human_escalation":
        actor = "system"

    base_details = {
        "execution_path": execution_path,
        "verification_result": verification_result,
        "rollback_triggered": rollback_triggered,
        "correlation_id": event.correlation_id,
    }
    try:
        write_audit_log(
            event_type=EventType.REMEDIATION_COMPLETED.value,
            actor=actor,
            workload_id=workload_id,
            issue_id=issue_id,
            recommendation_id=recommendation_id,
            remediation_id=remediation_id,
            previous_status="in_progress",
            new_status=execution_status or "completed",
            details=base_details,
        )
    except Exception:  # noqa: BLE001 - isolate the subscriber from the bus
        logger.exception(
            "Failed to record audit for REMEDIATION_COMPLETED (%s)", remediation_id
        )
        return

    # Requirement 15.4: a rollback gets its own immutable audit entry capturing
    # the original action details and the rollback outcome.
    if rollback_triggered:
        rollback_note = (
            f"Rollback triggered for remediation {remediation_id} after "
            f"verification_result={verification_result!r}; original execution "
            f"path was {execution_path!r}."
        )
        try:
            write_audit_log(
                event_type="rollback_triggered",
                actor=actor,
                workload_id=workload_id,
                issue_id=issue_id,
                recommendation_id=recommendation_id,
                remediation_id=remediation_id,
                previous_status=execution_status or "completed",
                new_status="rolled_back",
                details={
                    "original_execution_path": execution_path,
                    "verification_result": verification_result,
                    "correlation_id": event.correlation_id,
                },
                rollback_note=rollback_note,
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "Failed to record rollback audit for remediation %s", remediation_id
            )


# --------------------------------------------------------------------------- #
# Event subscription (idempotent)
# --------------------------------------------------------------------------- #
_HANDLERS: tuple[tuple[EventType, object], ...] = (
    (EventType.ISSUE_DETECTED, _on_issue_detected),
    (EventType.RECOMMENDATION_GENERATED, _on_recommendation_generated),
    (EventType.REMEDIATION_COMPLETED, _on_remediation_completed),
)

_subscribed = False


def register_subscriptions() -> None:
    """Subscribe the audit recorder to the meaningful lifecycle events.

    Idempotent: repeated calls (across test setups or re-imports) register the
    handlers at most once. Called from the application lifespan.
    """
    global _subscribed
    if _subscribed:
        return
    for event_type, handler in _HANDLERS:
        event_bus.subscribe(event_type, handler)  # type: ignore[arg-type]
    _subscribed = True
    logger.info(
        "Audit recorder subscribed to %s",
        ", ".join(e.value for e, _ in _HANDLERS),
    )
