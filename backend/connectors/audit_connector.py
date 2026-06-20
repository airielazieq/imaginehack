"""Simulated audit connector — writes immutable audit-trail entries.

The self-healing pipeline records an :class:`~backend.schemas.audit.AuditLog`
for every meaningful state transition (spec ``13_SAFETY_GOVERNANCE_AUDIT``).
This connector builds a validated ``AuditLog`` record and, when configured to
persist, writes it to the ``audit_logs`` table created in
``backend/core/database.py``.

Persistence is opt-in (``persist=True``) so the connector is trivially
importable and usable in tests without touching a database.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from backend.connectors.mcp_base import MCPConnector
from backend.schemas.audit import AuditLog


def _new_audit_id() -> str:
    return f"AUDIT-{uuid.uuid4().hex[:12].upper()}"


def build_audit_log(
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
) -> AuditLog:
    """Construct a validated :class:`AuditLog` record."""
    return AuditLog(
        audit_id=_new_audit_id(),
        event_type=event_type,
        actor=actor,
        workload_id=workload_id,
        issue_id=issue_id,
        recommendation_id=recommendation_id,
        remediation_id=remediation_id,
        timestamp=timestamp or datetime.now(timezone.utc),
        previous_status=previous_status,
        new_status=new_status,
        details=details or {},
        rollback_note=rollback_note,
    )


class AuditConnector(MCPConnector):
    """Simulated audit-log writer.

    Args:
        persist: When ``True``, write each audit entry to the ``audit_logs``
            table. When ``False`` (default), only the validated record is
            produced and returned.
        db_path: Optional database path override forwarded to the persistence
            layer (useful for tests using a temporary or ``:memory:`` DB).
    """

    category = "audit"

    def __init__(self, *, persist: bool = False, db_path: str | None = None) -> None:
        self.persist = persist
        self.db_path = db_path

    def _persist(self, log: AuditLog) -> None:
        """Insert an audit entry into the ``audit_logs`` table."""
        # Imported lazily so importing this module never requires a database.
        from backend.core.database import connection, init_db

        init_db(self.db_path)
        with connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO audit_logs (
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

    def _tool_write_audit_log(
        self,
        event_type: str = "audit_event",
        actor: str = "system",
        workload_id: str = "",
        issue_id: str | None = None,
        recommendation_id: str | None = None,
        remediation_id: str | None = None,
        previous_status: str | None = None,
        new_status: str | None = None,
        details: dict | None = None,
        rollback_note: str | None = None,
        **extra: Any,
    ) -> dict:
        merged_details = dict(details or {})
        if extra:
            merged_details.update(extra)

        log = build_audit_log(
            event_type=event_type,
            actor=actor,
            workload_id=workload_id,
            issue_id=issue_id,
            recommendation_id=recommendation_id,
            remediation_id=remediation_id,
            previous_status=previous_status,
            new_status=new_status,
            details=merged_details,
            rollback_note=rollback_note,
        )

        persisted = False
        if self.persist:
            self._persist(log)
            persisted = True

        return {
            "audit_id": log.audit_id,
            "event_type": log.event_type,
            "workload_id": log.workload_id,
            "persisted": persisted,
            "timestamp": log.timestamp.isoformat(),
            "audit_log": log.model_dump(mode="json"),
            "note": f"Audit entry {log.audit_id} recorded (simulated).",
        }
