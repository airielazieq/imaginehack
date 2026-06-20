"""Telemetry persistence and query service.

Centralizes read/write access to the ``telemetry`` table so both the ingestion
API (``api/telemetry.py``) and the workloads API (``api/workloads.py``) share a
single implementation.

The full :class:`TelemetrySnapshot` is stored as JSON in the ``data`` column;
``workload_id`` and ``timestamp`` are promoted to dedicated indexed columns for
efficient per-workload, time-ordered queries.
"""

from __future__ import annotations

import json
import logging

from backend.core.database import connection
from backend.schemas.telemetry import TelemetrySnapshot

logger = logging.getLogger("clover.services.telemetry")


def persist_snapshot(snapshot: TelemetrySnapshot, *, db_path: str | None = None) -> int:
    """Persist a single telemetry snapshot, returning the new row id.

    The full snapshot is stored as JSON in the ``data`` column; ``workload_id``
    and ``timestamp`` are promoted to dedicated indexed columns.
    """
    with connection(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO telemetry (workload_id, timestamp, data) VALUES (?, ?, ?)",
            (
                snapshot.workload_id,
                snapshot.timestamp.isoformat(),
                snapshot.model_dump_json(),
            ),
        )
        return int(cursor.lastrowid)


def get_telemetry_history(
    workload_id: str,
    *,
    limit: int | None = None,
    db_path: str | None = None,
) -> list[dict]:
    """Return telemetry snapshots for a workload, most recent first.

    Each entry is the deserialized snapshot JSON. Ordering is by ``timestamp``
    descending (ties broken by insertion ``id`` descending). When ``limit`` is
    provided, at most that many rows are returned.
    """
    sql = (
        "SELECT data FROM telemetry WHERE workload_id = ? "
        "ORDER BY timestamp DESC, id DESC"
    )
    params: tuple = (workload_id,)
    if limit is not None:
        sql += " LIMIT ?"
        params = (workload_id, limit)

    with connection(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()

    return [json.loads(row["data"]) for row in rows]


def count_telemetry(workload_id: str, *, db_path: str | None = None) -> int:
    """Return the number of telemetry rows stored for a workload."""
    with connection(db_path) as conn:
        cur = conn.execute(
            "SELECT COUNT(*) AS n FROM telemetry WHERE workload_id = ?",
            (workload_id,),
        )
        return int(cur.fetchone()["n"])
