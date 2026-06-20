"""MCP activity-log persistence and query (task 18.2).

Every simulated MCP tool invocation that flows through the
:class:`~backend.connectors.ConnectorRegistry` chokepoint can be recorded here
as an *activity-log* entry so operators can audit exactly which connector tools
(cloud, ticketing, notification, audit) ran, with what params, and what they
returned. The records back the dashboard MCP activity log surfaced by
``GET /api/mcp/log`` (frontend ``getMCPLog`` -> ``MCPLogEntry[]``).

Design:

- **Best-effort / non-fatal.** :func:`record_invocation` must never break tool
  execution. The registry wraps the call in ``try/except``; this module
  additionally lazy-imports the database layer so importing it never requires a
  DB, and initializes the schema on demand.
- **Append-only.** Each invocation is a fresh row; entries are never mutated.
- **Query helper.** :func:`list_mcp_log` returns entries **most-recent-first**,
  optionally filtered by ``workload_id``, shaped to match the frontend
  ``MCPLogEntry`` contract exactly (``timestamp``, ``workload_id``,
  ``category``, ``tool``, ``params``, ``result``, ``policy_compliance``,
  ``remediation_id``).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger("clover.services.mcp_log")

# Default compliance marker when a caller does not supply one.
_DEFAULT_POLICY_COMPLIANCE = "compliant"


def _to_iso(value: datetime | str | None) -> str:
    """Normalize a datetime/ISO string to an ISO-8601 string."""
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    return str(value)


def _coerce_json(value: object) -> str:
    """Serialize a params/result payload to JSON text (defensively)."""
    try:
        return json.dumps(value, default=str)
    except (TypeError, ValueError):
        return json.dumps({"value": str(value)})


def record_invocation(
    *,
    tool: str,
    category: str,
    params: dict | None = None,
    result: dict | None = None,
    status: str | None = None,
    workload_id: str | None = None,
    policy_compliance: str | None = None,
    remediation_id: str | None = None,
    timestamp: datetime | str | None = None,
    db_path: str | None = None,
) -> None:
    """Persist a single MCP tool invocation to the activity log.

    Best-effort: any persistence error is logged at debug level and swallowed so
    a logging failure never interferes with the tool execution that produced it.
    """
    try:
        # Imported lazily so importing this module never requires a database.
        from backend.core.database import connection, init_db

        init_db(db_path)
        with connection(db_path) as conn:
            conn.execute(
                """
                INSERT INTO mcp_log (
                    timestamp, workload_id, category, tool, params, result,
                    status, policy_compliance, remediation_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _to_iso(timestamp),
                    workload_id,
                    category,
                    tool,
                    _coerce_json(params or {}),
                    _coerce_json(result or {}),
                    status,
                    policy_compliance or _DEFAULT_POLICY_COMPLIANCE,
                    remediation_id,
                ),
            )
    except Exception:  # noqa: BLE001 - logging must never break tool execution
        logger.debug("Failed to record MCP invocation for tool %r", tool, exc_info=True)


def _row_to_entry(row) -> dict:
    """Reconstruct a frontend ``MCPLogEntry`` dict from a DB row."""

    def _load(text: str | None) -> dict:
        if not text:
            return {}
        try:
            loaded = json.loads(text)
        except (TypeError, ValueError):
            return {}
        return loaded if isinstance(loaded, dict) else {"value": loaded}

    return {
        "timestamp": row["timestamp"],
        "workload_id": row["workload_id"] or "",
        "category": row["category"],
        "tool": row["tool"],
        "params": _load(row["params"]),
        "result": _load(row["result"]),
        "policy_compliance": row["policy_compliance"] or _DEFAULT_POLICY_COMPLIANCE,
        "remediation_id": row["remediation_id"],
    }


def list_mcp_log(
    workload_id: str | None = None, *, db_path: str | None = None
) -> list[dict]:
    """Return MCP activity-log entries, most-recent-first.

    Args:
        workload_id: When provided, restrict to invocations recorded against
            that workload.

    Returns:
        A list of dicts matching the frontend ``MCPLogEntry`` contract. Returns
        an empty list if the table does not exist yet (best-effort read).
    """
    try:
        from backend.core.database import connection, init_db

        init_db(db_path)
        sql = "SELECT * FROM mcp_log"
        params: tuple = ()
        if workload_id is not None:
            sql += " WHERE workload_id = ?"
            params = (workload_id,)
        sql += " ORDER BY timestamp DESC, id DESC"

        with connection(db_path) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_entry(row) for row in rows]
    except Exception:  # noqa: BLE001 - a read failure must not break the endpoint
        logger.debug("Failed to list MCP activity log", exc_info=True)
        return []
