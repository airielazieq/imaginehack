"""SQLite connection management and schema migrations.

Provides a lightweight persistence layer for the platform's core entities:
workloads, telemetry, issues, recommendations, remediations, audit_logs, and
alerts. Complex nested objects (XAI explanations, forecasts, MCP executions,
etc.) are stored as JSON ``TEXT`` columns; frequently-queried fields are
promoted to dedicated columns with indexes.

The module exposes:
- :func:`get_connection` - a configured ``sqlite3.Connection`` (row factory).
- :func:`connection` - a context manager that commits/rolls back.
- :func:`init_db` - idempotent schema creation (run on startup).
- :func:`execute_with_retry` - write helper with backoff for lock contention.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from backend.core.config import get_settings

logger = logging.getLogger("clover.database")

# Schema DDL. Executed via executescript; all statements are idempotent.
SCHEMA_STATEMENTS = """
CREATE TABLE IF NOT EXISTS workloads (
    workload_id           TEXT PRIMARY KEY,
    workload_name         TEXT NOT NULL,
    workload_type         TEXT NOT NULL,
    cloud_service_type    TEXT NOT NULL,
    environment           TEXT NOT NULL,
    region                TEXT,
    owner_team            TEXT,
    construction_workflow TEXT,
    workflow_criticality  TEXT NOT NULL,
    status                TEXT NOT NULL DEFAULT 'healthy',
    data                  TEXT,            -- full JSON document
    created_at            TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at            TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS telemetry (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    workload_id  TEXT NOT NULL,
    timestamp    TEXT NOT NULL,
    data         TEXT NOT NULL,            -- full TelemetrySnapshot JSON
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (workload_id) REFERENCES workloads(workload_id)
);
CREATE INDEX IF NOT EXISTS idx_telemetry_workload_ts
    ON telemetry(workload_id, timestamp);

CREATE TABLE IF NOT EXISTS issues (
    issue_id        TEXT PRIMARY KEY,
    workload_id     TEXT NOT NULL,
    issue_type      TEXT NOT NULL,
    issue_category  TEXT NOT NULL,
    severity        TEXT NOT NULL,
    confidence_score REAL,
    status          TEXT NOT NULL DEFAULT 'new',
    detected_at     TEXT NOT NULL,
    data            TEXT NOT NULL,         -- full Issue JSON
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (workload_id) REFERENCES workloads(workload_id)
);
CREATE INDEX IF NOT EXISTS idx_issues_workload ON issues(workload_id);
CREATE INDEX IF NOT EXISTS idx_issues_status ON issues(status);

CREATE TABLE IF NOT EXISTS recommendations (
    recommendation_id       TEXT PRIMARY KEY,
    issue_id                TEXT NOT NULL,
    workload_id             TEXT NOT NULL,
    recommendation_type     TEXT,
    action_category         TEXT,
    risk_level              TEXT,
    required_execution_mode TEXT,
    created_at              TEXT NOT NULL,
    data                    TEXT NOT NULL, -- full Recommendation JSON
    FOREIGN KEY (issue_id) REFERENCES issues(issue_id),
    FOREIGN KEY (workload_id) REFERENCES workloads(workload_id)
);
CREATE INDEX IF NOT EXISTS idx_recommendations_issue ON recommendations(issue_id);
CREATE INDEX IF NOT EXISTS idx_recommendations_workload ON recommendations(workload_id);

CREATE TABLE IF NOT EXISTS remediations (
    remediation_id      TEXT PRIMARY KEY,
    recommendation_id   TEXT NOT NULL,
    issue_id            TEXT NOT NULL,
    workload_id         TEXT NOT NULL,
    execution_path      TEXT,
    execution_status    TEXT NOT NULL DEFAULT 'not_started',
    verification_result TEXT,
    rollback_triggered  INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
    data                TEXT NOT NULL,     -- full RemediationResult JSON
    FOREIGN KEY (recommendation_id) REFERENCES recommendations(recommendation_id),
    FOREIGN KEY (issue_id) REFERENCES issues(issue_id),
    FOREIGN KEY (workload_id) REFERENCES workloads(workload_id)
);
CREATE INDEX IF NOT EXISTS idx_remediations_recommendation
    ON remediations(recommendation_id);
CREATE INDEX IF NOT EXISTS idx_remediations_workload ON remediations(workload_id);

CREATE TABLE IF NOT EXISTS audit_logs (
    audit_id          TEXT PRIMARY KEY,
    event_type        TEXT NOT NULL,
    actor             TEXT NOT NULL,
    workload_id       TEXT,
    issue_id          TEXT,
    recommendation_id TEXT,
    remediation_id    TEXT,
    previous_status   TEXT,
    new_status        TEXT,
    timestamp         TEXT NOT NULL,
    data              TEXT NOT NULL,       -- full AuditLog JSON
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_audit_workload ON audit_logs(workload_id);
CREATE INDEX IF NOT EXISTS idx_audit_event_type ON audit_logs(event_type);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_logs(timestamp);

CREATE TABLE IF NOT EXISTS alerts (
    alert_id        TEXT PRIMARY KEY,
    workload_id     TEXT NOT NULL,
    title           TEXT NOT NULL,
    severity        TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'active',
    priority_score  REAL,
    created_at      TEXT NOT NULL,
    resolved_at     TEXT,
    suppressed_until TEXT,
    data            TEXT NOT NULL,         -- full Alert JSON
    FOREIGN KEY (workload_id) REFERENCES workloads(workload_id)
);
CREATE INDEX IF NOT EXISTS idx_alerts_workload ON alerts(workload_id);
CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status);

CREATE TABLE IF NOT EXISTS mcp_log (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp         TEXT NOT NULL,
    workload_id       TEXT,
    category          TEXT NOT NULL,
    tool              TEXT NOT NULL,
    params            TEXT NOT NULL,       -- JSON: tool input params
    result            TEXT NOT NULL,       -- JSON: tool output
    status            TEXT,
    policy_compliance TEXT,
    remediation_id    TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_mcp_log_workload ON mcp_log(workload_id);
CREATE INDEX IF NOT EXISTS idx_mcp_log_timestamp ON mcp_log(timestamp);
"""


def get_connection(db_path: str | None = None) -> sqlite3.Connection:
    """Open a configured SQLite connection.

    Uses a dict-like row factory, enables foreign keys and WAL journaling for
    better concurrent read/write behavior.
    """
    path = db_path or get_settings().database_path
    # Ensure parent directory exists for file-based DBs (skip for :memory:).
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn


@contextmanager
def connection(db_path: str | None = None) -> Iterator[sqlite3.Connection]:
    """Context manager yielding a connection, committing on success.

    Rolls back and re-raises on exception; always closes the connection.
    """
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: str | None = None) -> None:
    """Create all tables and indexes if they do not already exist."""
    with connection(db_path) as conn:
        conn.executescript(SCHEMA_STATEMENTS)
    logger.info("Database schema initialized at %s", db_path or get_settings().database_path)


def execute_with_retry(
    sql: str,
    params: tuple = (),
    *,
    db_path: str | None = None,
    attempts: int = 3,
    backoff_seconds: float = 0.1,
) -> None:
    """Execute a write statement, retrying on SQLite lock contention.

    Retries up to ``attempts`` times with linear backoff. Raises the last
    ``sqlite3.OperationalError`` if all attempts are exhausted.
    """
    last_error: sqlite3.OperationalError | None = None
    for attempt in range(1, attempts + 1):
        try:
            with connection(db_path) as conn:
                conn.execute(sql, params)
            return
        except sqlite3.OperationalError as exc:  # database is locked, etc.
            last_error = exc
            if "locked" not in str(exc).lower() or attempt == attempts:
                raise
            logger.warning(
                "SQLite lock contention (attempt %d/%d): %s", attempt, attempts, exc
            )
            time.sleep(backoff_seconds * attempt)
    if last_error is not None:
        raise last_error
